"""Read models and calendar buckets; all time intervals are half open."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .common import APIError, COMPONENTS, MAX_INTEGER, PRODUCTS, iso, parse_time


def limitation_text(code, description):
    # Early local databases persisted the internal code as its display text.
    # Adapt these rows on read; never require reimport or mutate a user's data.
    if description == code:
        return {'structured_response_records_preferred':
                '优先按响应标识统计结构化用量；同一会话的旧累计记录不重复相加'}.get(
                    code, '存在尚未识别的来源说明，其具体影响暂不明确')
    return description


def scope(db, query):
    provider, account = query.get('provider'),query.get('account_id')
    if not isinstance(provider,str) or provider not in PRODUCTS or not isinstance(account,str) or not account:
        raise APIError(422,'invalid_query','provider and account_id are required')
    if not db.execute('SELECT 1 FROM accounts WHERE id=? AND provider=?',(account,provider)).fetchone():
        raise APIError(404,'not_found','Account not found')
    return provider,account


def bounds(query):
    try:
        a,b = parse_time(query['from']),parse_time(query['to'])
        zone = ZoneInfo(query.get('timezone','Asia/Tokyo'))
        days = (datetime.fromtimestamp(b/1000,zone).date()-datetime.fromtimestamp(a/1000,zone).date()).days
        if a>=b or days>366 or b-a>367*86400000:
            raise ValueError()
    except (KeyError,ValueError,OverflowError,ZoneInfoNotFoundError):
        raise APIError(422,'invalid_query','Valid from < to, IANA timezone and at most 366 local days are required')
    return a,b,zone


def selected_products(query,provider):
    if 'products' not in query:
        return list(PRODUCTS[provider])
    values = query['products'].split(',')
    if not values or any(v not in PRODUCTS[provider] for v in values):
        raise APIError(422,'invalid_query','Invalid products for provider','products')
    return sorted(set(values))


def pool(db,query,provider,account):
    pid = query.get('pool_id')
    if not pid:
        raise APIError(422,'invalid_query','pool_id is required','pool_id')
    if not db.execute('SELECT 1 FROM quota_pools WHERE id=? AND account_id=? AND provider=?',(pid,account,provider)).fetchone():
        raise APIError(404,'not_found','Quota pool not found')
    return pid


def label_dto(db,row):
    target = {'kind':'session','session_id':row['session_id']} if row['target_kind']=='session' else {
        'kind':'range','from':iso(row['from_ms']),'to':iso(row['to_ms']),
        'products':[r[0] for r in db.execute('SELECT product FROM label_products WHERE label_id=? ORDER BY product',(row['id'],))]}
    return {'id':row['id'],'provider':row['provider'],'account_id':row['account_id'],'name':row['name'],
            'target':target,'revision':row['revision'],'created_at':iso(row['created_ms']),'updated_at':iso(row['updated_ms'])}


def matching_labels(db,event,labels=None):
    if labels is None:
        labels = db.execute('SELECT * FROM labels WHERE account_id=? AND provider=? AND deleted_ms IS NULL',
                             (event['account_id'],event['provider'])).fetchall()
    ids = []
    for label in labels:
        if label['target_kind']=='session':
            match = label['session_id']==event['session_id']
        else:
            match = label['from_ms']<=event['occurred_ms'] and (label['to_ms'] is None or event['occurred_ms']<label['to_ms'])
            if match:
                match = db.execute('SELECT 1 FROM label_products WHERE label_id=? AND product=?',(label['id'],event['product'])).fetchone() is not None
        if match:
            ids.append(label['id'])
    return sorted(ids)


def events(db,query,provider,account):
    a,b,_ = bounds(query)
    products = selected_products(query,provider)
    where = 'account_id=? AND provider=? AND occurred_ms>=? AND occurred_ms<? AND product IN ('+','.join('?' for _ in products)+')'
    args = [account,provider,a,b]+products
    if query.get('session_id'):
        if not db.execute('SELECT 1 FROM sessions WHERE id=? AND account_id=? AND provider=?',(query['session_id'],account,provider)).fetchone():
            raise APIError(404,'not_found','Session not found')
        where += ' AND session_id=?'
        args.append(query['session_id'])
    rows = db.execute('SELECT * FROM usage_events WHERE '+where+' ORDER BY occurred_ms,id LIMIT 100001',args).fetchall()
    if len(rows)>100000:
        raise APIError(422,'invalid_query','Too many records; choose a smaller time range')
    if query.get('label_id'):
        label = db.execute('SELECT * FROM labels WHERE id=? AND account_id=? AND provider=? AND deleted_ms IS NULL',(query['label_id'],account,provider)).fetchone()
        if not label:
            raise APIError(404,'not_found','Label not found')
        rows = [r for r in rows if matching_labels(db,r,[label])]
    return rows


def event_dto(db,row,labels):
    return {**{k:row[k] for k in ('id','provider','account_id','product','source_id','session_id','total_tokens','total_basis','reasoning_output_tokens')},
        'occurred_at':iso(row['occurred_ms']),'recorded_at':iso(row['recorded_ms']),'ingested_at':iso(row['ingested_ms']),
        'components':{k:row[k] for k in COMPONENTS},'components_complete':bool(row['components_complete']),
        'label_ids':matching_labels(db,row,labels)}


def snapshot_dto(row):
    return {**{k:row[k] for k in ('id','pool_id','window_id','source_id','time_basis','used_percent','value_basis')},
            **{out:iso(row[col]) for out,col in [('observed_at','observed_ms'),('recorded_at','recorded_ms'),
                ('ingested_at','ingested_ms'),('effective_at','effective_ms')]}}


def sources(db,provider,account):
    result = []
    for row in db.execute('SELECT s.*,d.label device_label FROM sources s LEFT JOIN devices d ON d.id=s.device_id WHERE s.account_id=? AND s.provider=? ORDER BY s.id',(account,provider)):
        data = {k:row[k] for k in ('id','provider','account_id','product','kind','device_id','device_label','connection_status','error_code','history_status','consecutive_failure_count','retry_mode')}
        data.update({out:iso(row[col]) for out,col in [('last_attempt_at','last_attempt_ms'),('last_success_at','last_success_ms'),('last_record_at','last_record_ms'),('next_attempt_at','next_attempt_ms')]})
        data['capabilities'] = [r[0] for r in db.execute('SELECT capability FROM source_capabilities WHERE source_id=? ORDER BY capability',(row['id'],))]
        data['limitations'] = [limitation_text(r['code'], r['description']) for r in db.execute('SELECT code,description FROM source_limitations WHERE source_id=? ORDER BY code',(row['id'],))]
        data['coverage'] = [{'from':iso(r['from_ms']),'to':iso(r['to_ms']),**{k:r[k] for k in ('status','scope','reason','evidence')}} for r in db.execute('SELECT * FROM coverage_intervals WHERE source_id=? ORDER BY from_ms,id',(row['id'],))]
        result.append(data)
    return result


def pools(db,provider,account):
    result = []
    for row in db.execute('SELECT * FROM quota_pools WHERE account_id=? AND provider=? ORDER BY id',(account,provider)):
        result.append({**{k:row[k] for k in ('id','provider','account_id','label','provider_bucket_key','membership_evidence')},
            'product_membership_complete':bool(row['product_membership_complete']),
            'products':[r[0] for r in db.execute('SELECT product FROM quota_pool_products WHERE pool_id=? ORDER BY product',(row['id'],))] if row['product_membership_known'] else None,
            'source_ids':[r[0] for r in db.execute('SELECT source_id FROM quota_pool_sources WHERE pool_id=? ORDER BY source_id',(row['id'],))]})
    return result


def quota_windows(db,pid,a,b,now,stale_seconds):
    result = []
    all_rows = db.execute('SELECT * FROM quota_windows WHERE pool_id=? ORDER BY COALESCE(ends_ms,9223372036854775807),id',(pid,)).fetchall()
    for row in all_rows:
        known = row['starts_ms'] is not None and row['ends_ms'] is not None
        intersects = row['starts_ms']<b and row['ends_ms']>a if known else db.execute('SELECT 1 FROM quota_snapshots WHERE window_id=? AND effective_ms>=? AND effective_ms<? LIMIT 1',(row['id'],a,b)).fetchone() is not None
        if not intersects:
            continue
        latest = db.execute('SELECT * FROM quota_snapshots WHERE window_id=? AND effective_ms<=? ORDER BY effective_ms DESC,id DESC LIMIT 1',(row['id'],now)).fetchone()
        navigable = [r for r in all_rows if r['slot']==row['slot'] and r['starts_ms'] is not None and r['ends_ms'] is not None]
        idx = next((i for i,r in enumerate(navigable) if r['id']==row['id']),None)
        status = 'expired' if row['ends_ms'] is not None and row['ends_ms']<=now else 'current' if known and row['starts_ms']<=now<row['ends_ms'] and latest else 'unknown'
        result.append({**{k:row[k] for k in ('id','pool_id','slot','duration_seconds','start_source','end_source','semantics')},
            'starts_at':iso(row['starts_ms']),'ends_at':iso(row['ends_ms']),'status':status,
            'freshness':'unknown' if not latest else 'stale' if now-latest['effective_ms']>stale_seconds*1000 else 'fresh',
            'latest_snapshot':snapshot_dto(latest) if latest else None,
            'previous_window_id':navigable[idx-1]['id'] if idx is not None and idx>0 else None,
            'next_window_id':navigable[idx+1]['id'] if idx is not None and idx+1<len(navigable) else None})
    return result


def intervals(a,b,kind,zone,now):
    if kind not in ('15m','hour','day','week','month'):
        raise APIError(422,'invalid_query','Invalid bucket','bucket')
    fixed = {'15m':900000,'hour':3600000}.get(kind)
    current = a if fixed else datetime.fromtimestamp(a/1000,zone).replace(hour=0,minute=0,second=0,microsecond=0)
    if not fixed and kind=='week':
        current -= timedelta(days=current.weekday())
    if not fixed and kind=='month':
        current = current.replace(day=1)
    count = 0
    while True:
        if fixed:
            start,end = current,current+fixed
            next_ = end
        else:
            next_ = current.replace(year=current.year+(current.month==12),month=current.month%12+1,day=1) if kind=='month' else current+timedelta(days=7 if kind=='week' else 1)
            start,end = int(current.timestamp()*1000),int(next_.timestamp()*1000)
        if start>=b:
            return
        lo,hi = max(a,start),min(b,end)
        if lo>=hi:  # Some IANA calendars contain a skipped local date.
            current = next_
            continue
        cuts = [lo,now,hi] if lo<now<hi else [lo,hi]
        for x,y in zip(cuts,cuts[1:]):
            count += 1
            if count>2000:
                raise APIError(422,'invalid_query','Too many buckets; choose a coarser bucket')
            yield x,y,(x!=start or y!=end)
        current = next_


def series(db,query,provider,account,now):
    a,b,zone = bounds(query)
    products = selected_products(query,provider)
    rows = events(db,query,provider,account)
    selected_sources = db.execute('SELECT id,connection_status FROM sources WHERE provider=? AND account_id=? AND product IN ('+','.join('?' for _ in products)+')',(provider,account,*products)).fetchall()
    source_ids = [r['id'] for r in selected_sources]
    unconfigured = any(r['connection_status']=='not_configured' for r in selected_sources)
    cover = db.execute('SELECT c.* FROM coverage_intervals c JOIN sources s ON s.id=c.source_id WHERE s.provider=? AND s.account_id=? AND s.product IN ('+','.join('?' for _ in products)+') AND c.from_ms<? AND c.to_ms>?',(provider,account,*products,b,a)).fetchall()
    buckets = []
    pos = 0
    for lo,hi,partial in intervals(a,b,query.get('bucket'),zone,now):
        selected = []
        while pos<len(rows) and rows[pos]['occurred_ms']<hi:
            if lo<=rows[pos]['occurred_ms'] and lo<now:
                selected.append(rows[pos])
            pos += 1
        future = lo>=now
        known = [r['total_tokens'] for r in selected if r['total_tokens'] is not None]
        total = sum(known) if known else None
        if total is not None and total>MAX_INTEGER:
            raise APIError(422,'invalid_query','Token total exceeds safe JSON integer range')
        complete = bool(selected) and all(r['components_complete'] for r in selected)
        overlap = [c for c in cover if c['from_ms']<hi and c['to_ms']>lo]
        # No assertion of account-wide complete coverage from a local log.
        coverage = 'gap' if any(c['status']=='gap' for c in overlap) else 'partial' if selected else 'unknown'
        reasons = ['not_yet_elapsed'] if future else sorted({c['reason'] for c in overlap}) or ['local_device_only' if selected else 'no_records_not_proof_of_zero']
        if not future and unconfigured:
            reasons.append('selected_products_not_configured')
        buckets.append({'from':iso(lo),'to':iso(hi),'is_partial_bucket':partial,
            'record_state':'future' if future else 'observed' if selected else 'no_records',
            'coverage_status':'unknown' if future else coverage,
            'coverage_reasons':reasons,
            'source_ids':[] if future else sorted(set(source_ids)), 'event_count':len(selected),
            'known_total_count':len(known),'unknown_total_count':len(selected)-len(known),'total_tokens':total,
            'total_status':'known' if known and len(known)==len(selected) else 'partial' if known else 'unknown',
            'components':{k:sum(r[k] for r in selected) for k in COMPONENTS} if complete else dict.fromkeys(COMPONENTS),
            'components_complete':complete})
    return {'provider':provider,'account_id':account,'products':products,'from':iso(a),'to':iso(b),'bucket':query['bucket'],'buckets':buckets}
