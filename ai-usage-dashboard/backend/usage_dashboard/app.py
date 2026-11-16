import base64
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
from urllib.parse import parse_qsl, urlsplit
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .common import APIError, API_VERSION, MAX_INTEGER, PRODUCTS, canonical, ident, iso, now_ms, parse_time
from . import query as models
from .security import Auth
from .store import bump_revision, connect, insert, revision, transaction

SPEC = json.loads((Path(__file__).resolve().parents[2]/'contracts/openapi.json').read_text())
# Local app settings, outside the v0.2 data contract: see contracts/collector-settings.md.
LOCAL_OPERATIONS = {'/collector-settings':{'get':{'parameters':[]},'post':{'parameters':[]}}}


class Application:
    def __init__(self,db_path,port=49173,dev_origin=None,bearer=None,clock=now_ms):
        self.db_path,self.clock = db_path,clock
        self.auth = Auth('http://127.0.0.1:'+str(port),dev_origin,bearer,clock)
        self.cursor_key = secrets.token_bytes(32)
        self.collector = None  # collector_settings.CollectorService when serving from the CLI

    def meta(self,db=None,zone='Asia/Tokyo'):
        return {'api_version':API_VERSION,'data_mode':'live','as_of':iso(self.clock()),
            'data_revision':revision(db) if db else 0,'scenario_id':None,'timezone':zone,
            'stale_after_seconds':900,'warnings':[]}

    def handle(self,method,target,headers=None,body=b''):
        headers = {k.lower():v for k,v in (headers or {}).items()}
        authenticated = False
        try:
            self.auth.check_host_origin(headers)
            if len(target)>8192 or sum(len(k)+len(v) for k,v in headers.items())>16384:
                raise APIError(422,'invalid_query','Request too large')
            split = urlsplit(target)
            if split.scheme or split.netloc or split.fragment or not split.path.startswith('/api/v1/'):
                raise APIError(404,'not_found','Endpoint not found')
            path = split.path[len('/api/v1'):]
            route = '/labels/{id}' if re.fullmatch(r'/labels/[A-Za-z0-9_-]{1,128}',path) else path
            op = (LOCAL_OPERATIONS.get(route) or SPEC['paths'].get(route,{})).get(method.lower())
            if not op:
                raise APIError(404,'not_found','Endpoint not found')
            try:
                pairs = parse_qsl(split.query,keep_blank_values=True,strict_parsing=True,max_num_fields=20,encoding='utf-8',errors='strict') if split.query else []
            except (ValueError,UnicodeError):
                raise APIError(422,'invalid_query','Invalid query string')
            q = dict(pairs)
            allowed = {p['name'] for p in op['parameters'] if p['in']=='query'}
            if len(q)!=len(pairs) or set(q)-allowed or any(not v for v in q.values()):
                raise APIError(422,'invalid_query','Unknown, empty or repeated query parameters')
            if any(p.get('required') and p['name'] not in q for p in op['parameters'] if p['in']=='query'):
                raise APIError(422,'invalid_query','Required query parameter missing')
            zone = q.get('timezone','Asia/Tokyo')
            try:
                ZoneInfo(zone)
            except (ValueError,ZoneInfoNotFoundError):
                raise APIError(422,'invalid_query','Unknown IANA timezone','timezone')
            if len(body)>32768 or headers.get('transfer-encoding'):
                raise APIError(422,'invalid_body','Body too large or unsupported transfer encoding')
            payload = None
            if method in ('POST','PATCH'):
                if headers.get('content-type','').split(';')[0].strip().lower()!='application/json':
                    raise APIError(422,'invalid_body','application/json body required')
                def no_duplicates(pairs):
                    out = dict(pairs)
                    if len(out)!=len(pairs):
                        raise ValueError('duplicate JSON key')
                    return out
                def invalid_constant(value):
                    raise ValueError('nonfinite number')
                try:
                    payload = json.loads(body.decode('utf-8'),object_pairs_hook=no_duplicates,parse_constant=invalid_constant)
                except (ValueError,UnicodeError):
                    raise APIError(422,'invalid_body','Invalid JSON body')
            elif body:
                raise APIError(422,'invalid_body','Request body not allowed')
            with connect(self.db_path) as db:
                if path=='/auth/session' and method=='POST':
                    data,extra = self.auth.pair(db,headers,payload)
                    return 201,{'data':data,'meta':self.meta(db)},self.headers(extra)
                auth = self.auth.authenticate(db,headers,method,cookie_only=path=='/auth/session')
                authenticated = True
                if path=='/auth/session':
                    row,secret = auth
                    if method=='DELETE':
                        db.execute('UPDATE app_sessions SET revoked_ms=? WHERE id=?',(self.clock(),row['id']))
                        return 204,None,self.headers({'Set-Cookie':'aud_session=; HttpOnly; SameSite=Strict; Path=/api/v1; Max-Age=0'})
                    return 200,{'data':self.auth.session_data(secret,row['expires_ms']),'meta':self.meta(db)},self.headers()
                if path=='/collector-settings':
                    # Applies outside a request transaction: it stops/starts the collector thread.
                    data = self.collector_settings(method,payload)
                    return 200,{'data':data,'meta':self.meta(db)},self.headers()
                with transaction(db,write=method!='GET'):
                    if route in ('/labels','/labels/{id}') and method!='GET':
                        return self.write_label(db,method,path,headers,payload)
                    data,paged = self.read(db,path,q)
                    response = {'data':data,'meta':self.meta(db,zone)}
                    if paged:
                        response['data'],response['page'] = self.paginate(db,data,path,q)
                    return 200,response,self.headers()
        except APIError as error:
            try:
                with connect(self.db_path) as db:
                    meta = self.meta(db if authenticated else None)
            except Exception:
                meta = self.meta()
            return error.status,{'error':{'code':error.code,'message':error.message,'details':error.details},'meta':meta},self.headers(error.headers)
        except Exception:
            # No raw JSON, source content, SQL/path or exception text in HTTP logs.
            return 500,{'error':{'code':'internal_error','message':'Local backend could not complete request','details':[]},'meta':self.meta()},self.headers()

    def collector_settings(self,method,payload):
        if self.collector is None:
            if method=='POST':
                error = APIError(422,'invalid_body','Collector settings rejected')
                error.details = [{'field':'mode','reason':'collection_disabled_for_this_run'}]
                raise error
            return {'mode':'disabled','configured':False,'settings_error':None,'interval_seconds':60,'running':False,'sources':[]}
        return self.collector.status() if method=='GET' else self.collector.update(payload)

    @staticmethod
    def headers(extra=None):
        return {'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',**(extra or {})}

    def paginate(self,db,data,path,q):
        try:
            text = q.get('limit','100')
            if not re.fullmatch(r'[1-9][0-9]*',text):
                raise ValueError()
            limit = int(text)
            if limit>500:
                raise ValueError()
        except ValueError:
            raise APIError(422,'invalid_query','limit must be 1..500','limit')
        binding = {k:v for k,v in q.items() if k!='cursor'}
        binding['limit'] = str(limit)
        binding['timezone'] = binding.get('timezone','Asia/Tokyo')
        for k in ('from','to'):
            if k in binding:
                binding[k] = iso(parse_time(binding[k]))
        if 'products' in binding:
            binding['products'] = ','.join(sorted(set(binding['products'].split(','))))
        request_hash = hashlib.sha256(canonical([path,binding]).encode()).hexdigest()
        offset,rev = 0,revision(db)
        if q.get('cursor'):
            try:
                raw,tag = q['cursor'].split('.')
                if not hmac.compare_digest(hmac.new(self.cursor_key,raw.encode(),hashlib.sha256).hexdigest(),tag):
                    raise ValueError()
                payload = json.loads(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))
                if payload['binding']!=request_hash or payload['revision']!=rev:
                    raise APIError(409,'cursor_expired','Restart pagination from first page','cursor')
                offset = payload['offset']
                if type(offset) is not int or not 0<=offset<=len(data):
                    raise ValueError()
            except (ValueError,KeyError,TypeError):
                raise APIError(422,'invalid_query','Invalid cursor','cursor')
        next_ = offset+limit
        has_more = next_<len(data)
        cursor = None
        if has_more:
            raw = base64.urlsafe_b64encode(canonical({'binding':request_hash,'revision':rev,'offset':next_}).encode()).decode().rstrip('=')
            cursor = raw+'.'+hmac.new(self.cursor_key,raw.encode(),hashlib.sha256).hexdigest()
        return data[offset:next_],{'next_cursor':cursor,'has_more':has_more}

    def read(self,db,path,q):
        if path=='/health':
            return {'status':'ok','storage_schema_version':1,'backend_implemented':True},False
        if path=='/accounts':
            return [dict(r) for r in db.execute('SELECT id,provider,label,identity_status FROM accounts ORDER BY provider,id')],False
        provider,account = models.scope(db,q)
        if path=='/sources':
            return models.sources(db,provider,account),False
        if path=='/quota-pools':
            return models.pools(db,provider,account),False
        a,b,_ = models.bounds(q)
        if path.startswith('/quota-'):
            pid = models.pool(db,q,provider,account)
            if path=='/quota-windows':
                return models.quota_windows(db,pid,a,b,self.clock(),900),True
            window = q.get('window_id')
            if window and not db.execute('SELECT 1 FROM quota_windows WHERE id=? AND pool_id=?',(window,pid)).fetchone():
                raise APIError(404,'not_found','Window not found')
            sql = 'SELECT * FROM quota_snapshots WHERE pool_id=? AND effective_ms>=? AND effective_ms<?'
            args = [pid,a,b]
            if window:
                sql += ' AND window_id=?'
                args.append(window)
            rows = db.execute(sql+' ORDER BY effective_ms,id LIMIT 100001',args).fetchall()
            if len(rows)>100000:
                raise APIError(422,'invalid_query','Too many observations; choose a smaller range')
            if path=='/quota-snapshots':
                return [models.snapshot_dto(r) for r in rows],True
            groups = {}
            for row in rows:
                groups.setdefault(row['window_id'],[]).append(row)
            result = []
            for wid,points in groups.items():
                values = [r['used_percent'] for r in points if r['used_percent'] is not None]
                result.append({'window_id':wid,'pool_id':pid,'scope_from':iso(a),'scope_to':iso(b),
                    'max_observed_percent':max(values) if values else None,'sample_count':len(points),'known_value_count':len(values),
                    'first_sample_at':iso(points[0]['effective_ms']),'last_sample_at':iso(points[-1]['effective_ms']),
                    'label':'highest_observed_in_selected_range'})
            return sorted(result,key=lambda r:(r['first_sample_at'],r['window_id'])),True
        if path=='/usage-series':
            return models.series(db,q,provider,account,self.clock()),False
        products = models.selected_products(q,provider)
        rows = models.events(db,q,provider,account)
        labels = db.execute('SELECT * FROM labels WHERE account_id=? AND provider=? AND deleted_ms IS NULL ORDER BY created_ms,id',(account,provider)).fetchall()
        if path=='/usage-events':
            return [models.event_dto(db,row,labels) for row in rows],True
        if path=='/sessions':
            grouped = {}
            for row in rows:
                if row['session_id']:
                    grouped.setdefault(row['session_id'],[]).append(row)
            result = []
            for sid,selected in grouped.items():
                row = db.execute('SELECT * FROM sessions WHERE id=?',(sid,)).fetchone()
                known = [r['total_tokens'] for r in selected if r['total_tokens'] is not None]
                total = sum(known) if known else None
                if total is not None and total>MAX_INTEGER:
                    raise APIError(422,'invalid_query','Token total exceeds safe JSON integer range')
                result.append({**{k:row[k] for k in ('id','provider','account_id','product','source_id')},
                    'started_at':iso(row['started_ms']),'last_record_at':iso(row['last_record_ms']),
                    'range_from':iso(a),'range_to':iso(b),'event_count_in_range':len(selected),
                    'first_record_in_range_at':iso(selected[0]['occurred_ms']),'last_record_in_range_at':iso(selected[-1]['occurred_ms']),
                    'activity_bounds_basis':'record_timestamps','known_total_count':len(known),'unknown_total_count':len(selected)-len(known),
                    'total_tokens_in_range':total,'label_ids':sorted({label for event in selected for label in models.matching_labels(db,event,labels)})})
            return sorted(result,key=lambda r:(r['first_record_in_range_at'],r['id'])),True
        if path=='/labels':
            result = []
            for label in labels:
                if label['target_kind']=='session':
                    include = any(row['session_id']==label['session_id'] for row in rows)
                else:
                    target_products = [r[0] for r in db.execute('SELECT product FROM label_products WHERE label_id=?',(label['id'],))]
                    include = label['from_ms']<b and (label['to_ms'] is None or label['to_ms']>a) and bool(set(target_products)&set(products))
                if include:
                    result.append(models.label_dto(db,label))
            return result,True
        raise APIError(404,'not_found','Endpoint not found')

    def validate_target(self,db,target,provider,account):
        if not isinstance(target,dict):
            raise APIError(422,'invalid_body','Complete label target required','target')
        if target.get('kind')=='session' and set(target)=={'kind','session_id'}:
            sid = target['session_id']
            if not isinstance(sid,str) or not db.execute('SELECT 1 FROM sessions WHERE id=? AND provider=? AND account_id=?',(sid,provider,account)).fetchone():
                raise APIError(404,'not_found','Session not found')
            return {'kind':'session','session_id':sid}
        if target.get('kind')=='range' and set(target)=={'kind','from','to','products'}:
            try:
                a = parse_time(target['from'])
                b = parse_time(target['to']) if target['to'] is not None else None
                products = target['products']
                if (b is not None and b<=a) or not isinstance(products,list) or not products or any(type(p) is not str or p not in PRODUCTS[provider] for p in products) or len(products)!=len(set(products)):
                    raise ValueError()
            except (ValueError,TypeError,OverflowError):
                raise APIError(422,'invalid_body','Valid time range and products required','target')
            return {'kind':'range','from':iso(a),'to':iso(b),'products':sorted(products)}
        raise APIError(422,'invalid_body','Label target must be exclusively range or session','target')

    def write_label(self,db,method,path,headers,payload):
        if method=='POST':
            if not isinstance(payload,dict) or set(payload)!={'provider','account_id','client_request_id','name','target'}:
                raise APIError(422,'invalid_body','Invalid create-label fields')
            if not isinstance(payload['provider'],str) or payload['provider'] not in PRODUCTS or not isinstance(payload['account_id'],str):
                raise APIError(422,'invalid_body','Valid provider and account_id strings required')
            provider,account = models.scope(db,payload)
            try:
                request_id = str(uuid.UUID(payload['client_request_id']))
            except (ValueError,TypeError,AttributeError):
                raise APIError(422,'invalid_body','client_request_id must be UUID','client_request_id')
            target = self.validate_target(db,payload['target'],provider,account)
            name = self.label_name(payload['name'])
            request_hash = hashlib.sha256(canonical({**payload,'client_request_id':request_id,'name':name,'target':target}).encode()).hexdigest()
            old = db.execute('SELECT * FROM labels WHERE provider=? AND account_id=? AND client_request_id=?',(provider,account,request_id)).fetchone()
            if old:
                if old['create_request_hash']!=request_hash or old['deleted_ms'] is not None:
                    raise APIError(409,'idempotency_conflict','Create key already used for another or deleted label')
                return self.label_response(db,old,200)
            now = self.clock()
            row = {'id':'label_'+uuid.uuid4().hex,'account_id':account,'provider':provider,'client_request_id':request_id,
                'create_request_hash':request_hash,'name':name,'revision':1,'created_ms':now,'updated_ms':now,
                'target_kind':target['kind'],'session_id':target.get('session_id'),
                'from_ms':parse_time(target['from']) if target['kind']=='range' else None,
                'to_ms':parse_time(target['to']) if target['kind']=='range' and target['to'] else None}
            insert(db,'labels',row)
            self.label_products(db,row,target)
            bump_revision(db)
            return self.label_response(db,db.execute('SELECT * FROM labels WHERE id=?',(row['id'],)).fetchone(),201)
        lid = path.rsplit('/',1)[1]
        old = db.execute('SELECT * FROM labels WHERE id=? AND deleted_ms IS NULL',(lid,)).fetchone()
        if old is None:
            raise APIError(404,'not_found','Label not found')
        expected = headers.get('if-match')
        if expected is None:
            raise APIError(428,'precondition_required','If-Match required','If-Match')
        if expected!='"'+str(old['revision'])+'"':
            raise APIError(412,'revision_conflict','Label changed; reload before editing','If-Match')
        now = max(self.clock(),old['updated_ms'])
        if method=='DELETE':
            db.execute('UPDATE labels SET deleted_ms=?,updated_ms=?,revision=revision+1 WHERE id=?',(now,now,lid))
            bump_revision(db)
            return 204,None,self.headers()
        if not isinstance(payload,dict) or not payload or set(payload)-{'name','target'}:
            raise APIError(422,'invalid_body','Patch accepts name and/or complete target')
        target = self.validate_target(db,payload['target'],old['provider'],old['account_id']) if 'target' in payload else models.label_dto(db,old)['target']
        name = self.label_name(payload['name']) if 'name' in payload else old['name']
        db.execute('UPDATE labels SET name=?,target_kind=?,session_id=?,from_ms=?,to_ms=?,revision=revision+1,updated_ms=? WHERE id=?',
                   (name,target['kind'],target.get('session_id'),parse_time(target['from']) if target['kind']=='range' else None,
                    parse_time(target['to']) if target['kind']=='range' and target['to'] else None,now,lid))
        db.execute('DELETE FROM label_products WHERE label_id=?',(lid,))
        self.label_products(db,dict(old),target)
        bump_revision(db)
        return self.label_response(db,db.execute('SELECT * FROM labels WHERE id=?',(lid,)).fetchone(),200)

    @staticmethod
    def label_name(name):
        if not isinstance(name,str) or not name.strip() or len(name)>80:
            raise APIError(422,'invalid_body','Label name must be 1..80 nonblank characters','name')
        return name.strip()

    @staticmethod
    def label_products(db,row,target):
        if target['kind']=='range':
            for product in target['products']:
                insert(db,'label_products',{'label_id':row['id'],'account_id':row['account_id'],'provider':row['provider'],'product':product})

    def label_response(self,db,row,status):
        return status,{'data':models.label_dto(db,row),'meta':self.meta(db)},self.headers({'ETag':'"'+str(row['revision'])+'"'})
