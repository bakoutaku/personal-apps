import copy
import http.client
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlencode
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from usage_dashboard.app import Application
from usage_dashboard.collect import collect, parse_file
from usage_dashboard.common import canonical, iso, parse_time
from usage_dashboard.query import intervals
from usage_dashboard.security import csrf
from usage_dashboard.server import make_server
from usage_dashboard.store import connect, initialize
from test_contract import SCHEMAS, check
from zoneinfo import ZoneInfo

NOW = parse_time('2026-10-22T04:01:00.000Z')
BEARER = 'aud_'+'test_local_only_not_a_real_credential_0123456789'


def raw_usage(input_=100,cached=60,output=20):
    return {'input_tokens':input_,'cached_input_tokens':cached,'cache_write_input_tokens':0,
            'output_tokens':output,'reasoning_output_tokens':5,'total_tokens':input_+output}


def codex_rows(modern=True):
    one,two = raw_usage(),raw_usage(200,120,40)
    total = {k:one[k]+two[k] for k in one}
    rows = [{'type':'session_meta','timestamp':'2026-10-22T03:00:00.000Z',
             'payload':{'id':'synthetic_thread','cli_version':'synthetic-version','base_instructions':'DO_NOT_STORE_PRIVATE'}}]
    for i,(usage,cumulative) in enumerate([(one,one),(two,total)]):
        at = '2026-10-22T03:%02d:00.000Z' % (5+i*15)
        if modern:
            rows.append({'type':'token_usage_record','timestamp':at,'payload':{
                'thread_id':'synthetic_thread','response_id':'response_'+str(i),'usage':usage,'thread_token_usage':cumulative}})
        rows.append({'type':'event_msg','timestamp':at,'payload':{'type':'token_count',
            'info':{'total_token_usage':cumulative,'last_token_usage':usage}}})
    rows.append({'type':'event_msg','timestamp':'2026-10-22T03:59:00.000Z','payload':{'type':'token_count','info':None,
        'rate_limits':{'limit_id':'codex','primary':{'used_percent':62,'window_minutes':300,'resets_at':parse_time('2026-10-22T05:58:00.000Z')//1000},
                       'secondary':{'used_percent':31,'window_minutes':10080,'resets_at':parse_time('2026-10-27T00:00:00.000Z')//1000}}}})
    return rows


def claude_row(output=4,minute=5,**usage_changes):
    return {'type':'assistant','timestamp':'2026-10-22T03:%02d:00.000Z'%minute,'sessionId':'claude_synthetic_session',
            'requestId':'synthetic_request','message':{'id':'synthetic_message','content':'DO_NOT_STORE_PRIVATE',
                'usage':{'input_tokens':2,'cache_creation_input_tokens':10,'cache_read_input_tokens':30,'output_tokens':output,**usage_changes}}}


class BackendCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root/'private/usage.sqlite3'
        initialize(self.db)
        self.file = self.root/'log.jsonl'

    def tearDown(self):
        self.temp.cleanup()

    def write(self,rows):
        self.file.write_text(''.join(canonical(row)+'\n' for row in rows))

    def import_rows(self,rows=None,provider='gpt'):
        if rows is not None:
            self.write(rows)
        return collect(self.db,provider,self.file,clock=lambda:NOW)

    def rows(self,sql):
        with connect(self.db) as db:
            return [dict(r) for r in db.execute(sql)]


class StorageTests(BackendCase):
    def test_unrelated_version_one_database_is_not_modified(self):
        other = self.root/'unrelated.sqlite3'
        with sqlite3.connect(other) as db:
            db.execute('CREATE TABLE personal_notes (text TEXT)')
            db.execute("INSERT INTO personal_notes VALUES ('keep')")
            db.execute('PRAGMA user_version=1')
        before = other.read_bytes()
        with self.assertRaisesRegex(ValueError, 'schema does not match'):
            initialize(other)
        self.assertEqual(other.read_bytes(), before)

    def test_current_schema_can_be_reopened(self):
        initialize(self.db)
        self.assertEqual(self.rows('PRAGMA user_version')[0]['user_version'],1)


class CollectorTests(BackendCase):
    def test_modern_and_legacy_streams_not_added_together(self):
        report = self.import_rows(codex_rows())
        events = self.rows('SELECT * FROM usage_events')
        self.assertEqual(len(events),2)
        self.assertEqual(sum(r['total_tokens'] for r in events),360)
        self.assertEqual(report['connection_status'],'available')

    def test_rescan_and_copied_file_are_idempotent(self):
        self.import_rows(codex_rows())
        report = self.import_rows()
        self.assertEqual(report['changed_events_or_snapshots'],0)
        copy_file = self.root/'copy.jsonl'
        copy_file.write_bytes(self.file.read_bytes())
        collect(self.db,'gpt',self.root,clock=lambda:NOW)
        self.assertEqual(len(self.rows('SELECT id FROM usage_events')),2)
        self.assertEqual(len(self.rows('SELECT id FROM quota_snapshots')),2)

    def test_cumulative_legacy_deltas_not_cumulative_sums(self):
        self.import_rows(codex_rows(False))
        events = self.rows('SELECT * FROM usage_events ORDER BY occurred_ms')
        self.assertEqual([r['total_tokens'] for r in events],[120,240])
        self.assertEqual(events[1]['total_basis'],'derived')
        self.assertEqual(events[0]['uncached_input_tokens'],40)

    def test_structured_upgrade_replaces_legacy_counts(self):
        self.import_rows(codex_rows(False))
        self.import_rows(codex_rows(True))
        events = self.rows('SELECT * FROM usage_events')
        self.assertEqual(len(events),2)
        self.assertEqual(sum(r['total_tokens'] for r in events),360)
        self.import_rows(codex_rows(False))
        self.assertEqual(len(self.rows('SELECT id FROM usage_events')),2)

    def test_unknown_initial_baseline_not_counted_as_lifetime_usage(self):
        rows = codex_rows(False)
        del rows[1]
        report = self.import_rows(rows)
        self.assertIn('initial_cumulative_baseline_unknown',report['warnings'])
        self.assertIsNone(self.rows('SELECT total_tokens FROM usage_events')[0]['total_tokens'])

    def test_counter_regression_never_creates_negative_or_fake_delta(self):
        rows = codex_rows(False)
        u = raw_usage(10,0,1)
        rows.insert(-1,{'type':'event_msg','timestamp':'2026-10-22T03:30:00.000Z','payload':{'type':'token_count',
            'info':{'total_token_usage':u,'last_token_usage':u}}})
        report = self.import_rows(rows)
        self.assertIn('cumulative_counter_regressed',report['warnings'])
        totals = [r['total_tokens'] for r in self.rows('SELECT total_tokens FROM usage_events')]
        self.assertIn(None,totals)
        self.assertEqual(sum(v or 0 for v in totals),360)

    def test_legacy_fork_unsupported_is_explicit(self):
        rows = codex_rows(False)
        rows[0]['payload']['forked_from_id'] = 'synthetic_parent'
        report = self.import_rows(rows)
        self.assertIn('legacy_fork_not_counted',report['warnings'])
        self.assertEqual(self.rows('SELECT id FROM usage_events'),[])

    def test_claude_duplicates_and_streaming_revision_use_one_message(self):
        self.import_rows([claude_row(),claude_row(),claude_row(8,6)],'claude')
        rows = self.rows('SELECT * FROM usage_events')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['total_tokens'],50)
        self.assertEqual(rows[0]['occurred_ms'],parse_time('2026-10-22T03:05:00.000Z'))
        self.import_rows([claude_row()],'claude')
        self.assertEqual(self.rows('SELECT total_tokens FROM usage_events')[0]['total_tokens'],50)

    def test_claude_incomparable_revisions_do_not_create_per_field_maximum(self):
        report = self.import_rows([claude_row(8),claude_row(7,6,input_tokens=3,cache_read_input_tokens=29)],'claude')
        self.assertIn('conflicting_message_usage',report['warnings'])
        self.assertIsNone(self.rows('SELECT total_tokens FROM usage_events')[0]['total_tokens'])

    def test_partial_last_line_retried_without_false_empty(self):
        self.write([claude_row()])
        with self.file.open('a') as f:
            f.write('{"type":"assistant"')
        report = self.import_rows(provider='claude')
        self.assertIn('incomplete_tail',report['warnings'])
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),1)

    def test_unknown_format_is_not_reported_as_empty(self):
        report = self.import_rows([{'type':'unrecognized','timestamp':'2026-10-22T03:00:00.000Z','body':'DO_NOT_STORE_PRIVATE'}])
        self.assertEqual(report['history_status'],'unknown')
        self.assertEqual(report['connection_status'],'error')

    def test_confirmed_metadata_only_transcript_can_be_empty(self):
        report = self.import_rows(codex_rows()[:1])
        self.assertEqual(report['history_status'],'empty')
        self.assertEqual(report['connection_status'],'available')

    def test_failed_new_scan_keeps_history_but_marks_source_error(self):
        self.import_rows(codex_rows())
        report = self.import_rows([{'type':'unrecognized','timestamp':'2026-10-22T03:00:00.000Z'}])
        self.assertEqual(report['connection_status'],'error')
        self.assertEqual(report['history_status'],'has_records')
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),2)

    def test_partial_claude_metrics_cannot_override_larger_known_components(self):
        partial = claude_row(10,6)
        del partial['message']['usage']['cache_creation_input_tokens']
        report = self.import_rows([claude_row(4),partial],'claude')
        self.assertIn('conflicting_message_usage',report['warnings'])
        self.assertIsNone(self.rows('SELECT total_tokens FROM usage_events')[0]['total_tokens'])

    def test_source_account_change_does_not_merge_namespaces(self):
        first = codex_rows()
        first[0]['payload']['creator_account_id'] = 'synthetic_account_A'
        self.import_rows(first)
        second = codex_rows()
        second[0]['payload']['creator_account_id'] = 'synthetic_account_B'
        with self.assertRaises(ValueError):
            self.import_rows(second)
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),2)
        collect(self.db,'gpt',self.file,namespace='second-account',clock=lambda:NOW)
        self.assertEqual(len(self.rows('SELECT * FROM accounts')),2)

    def test_conflicting_persisted_response_stays_unknown_on_reimport(self):
        self.import_rows([claude_row(8)],'claude')
        self.import_rows([claude_row(7,6,input_tokens=3,cache_read_input_tokens=29)],'claude')
        self.assertIsNone(self.rows('SELECT total_tokens FROM usage_events')[0]['total_tokens'])
        self.import_rows([claude_row(8)],'claude')
        self.assertIsNone(self.rows('SELECT total_tokens FROM usage_events')[0]['total_tokens'])

    def test_stream_revision_records_last_record_time_separately(self):
        self.import_rows([claude_row(4),claude_row(8,6)],'claude')
        event = self.rows('SELECT * FROM usage_events')[0]
        self.assertEqual(event['occurred_ms'],parse_time('2026-10-22T03:05:00.000Z'))
        self.assertEqual(event['recorded_ms'],parse_time('2026-10-22T03:06:00.000Z'))

    def test_no_content_path_or_supplier_credentials_saved(self):
        self.import_rows(codex_rows())
        data = self.db.read_bytes()
        self.assertNotIn(b'DO_NOT_STORE_PRIVATE',data)
        self.assertNotIn(str(self.file).encode(),data)
        self.assertNotIn(b'synthetic_thread',data)

    def test_quota_uses_source_record_time_not_import_time(self):
        self.import_rows(codex_rows())
        for row in self.rows('SELECT * FROM quota_snapshots'):
            self.assertIsNone(row['observed_ms'])
            self.assertEqual(row['effective_ms'],parse_time('2026-10-22T03:59:00.000Z'))
            self.assertEqual(row['time_basis'],'recorded_at')


class APIBackendTests(BackendCase):
    def setUp(self):
        super().setUp()
        self.report = self.import_rows(codex_rows())
        self.app = Application(self.db,bearer=BEARER,clock=lambda:NOW)
        self.h = {'Host':'127.0.0.1:49173','Authorization':'Bearer '+BEARER}
        self.q = {'provider':'gpt','account_id':self.report['account_id'],'products':'codex',
                  'from':'2026-10-22T00:58:00.000Z','to':'2026-10-22T05:58:00.000Z','timezone':'Asia/Tokyo'}

    def get(self,path,q=None,headers=None):
        return self.app.handle('GET','/api/v1'+path+('?' +urlencode(q) if q else ''),headers or self.h)

    def label_body(self):
        return {'provider':'gpt','account_id':self.report['account_id'],'client_request_id':str(uuid.uuid4()),
                'name':'测试任务','target':{'kind':'range','from':self.q['from'],'to':self.q['to'],'products':['codex']}}

    def write_api(self,method,path,body=None,headers=None):
        h = {**self.h,'Content-Type':'application/json',**(headers or {})}
        return self.app.handle(method,'/api/v1'+path,h,b'' if body is None else canonical(body).encode())

    def test_read_endpoints_match_contract_schemas(self):
        for path,schema,q in [('/health','HealthResponse',None),('/accounts','AccountsResponse',None),
                ('/sources','SourcesResponse',{k:self.q[k] for k in ('provider','account_id')}),
                ('/quota-pools','PoolsResponse',{k:self.q[k] for k in ('provider','account_id')}),
                ('/usage-events','EventsResponse',self.q),('/sessions','SessionsResponse',self.q),
                ('/labels','LabelsResponse',self.q),('/usage-series','SeriesResponse',{**self.q,'bucket':'15m'})]:
            with self.subTest(path=path):
                status,data,_ = self.get(path,q)
                self.assertEqual(status,200,data)
                check(data,SCHEMAS[schema])
                self.assertEqual(data['meta']['data_mode'],'live')
        pools = self.get('/quota-pools',{k:self.q[k] for k in ('provider','account_id')})[1]['data']
        pq = {k:v for k,v in self.q.items() if k!='products'}
        pq['pool_id'] = pools[0]['id']
        for path,schema in [('/quota-windows','WindowsResponse'),('/quota-snapshots','SnapshotsResponse'),('/quota-window-summaries','WindowSummariesResponse')]:
            status,data,_ = self.get(path,pq)
            self.assertEqual(status,200,data)
            check(data,SCHEMAS[schema])

    def test_auth_host_origin_required_and_ambiguous_auth_rejected(self):
        self.assertEqual(self.get('/health',headers={'Host':'127.0.0.1:49173'})[0],401)
        self.assertEqual(self.get('/health',headers={**self.h,'Host':'evil.invalid'})[0],403)
        self.assertEqual(self.get('/health',headers={**self.h,'Origin':'http://evil.invalid'})[0],403)
        self.assertEqual(self.get('/health',headers={**self.h,'Cookie':'aud_session=anything'})[0],401)

    def test_legacy_limitation_codes_are_display_text_without_database_mutation(self):
        code = 'structured_response_records_preferred'
        with connect(self.db) as db:
            source = db.execute("SELECT id FROM sources WHERE product='codex'").fetchone()[0]
            db.execute('INSERT INTO source_limitations VALUES (?,?,?)', (source,code,code))
            db.execute('INSERT INTO source_limitations VALUES (?,?,?)', (source,'future_internal_code','future_internal_code'))
            db.execute('INSERT INTO source_limitations VALUES (?,?,?)', (source,'custom_note','自定义可读说明'))
        scope = {k:self.q[k] for k in ('provider','account_id')}
        status, response, _ = self.get('/sources',scope)
        self.assertEqual(status,200)
        check(response,SCHEMAS['SourcesResponse'])
        texts = next(s['limitations'] for s in response['data'] if s['id']==source)
        self.assertNotIn(code,texts)
        self.assertNotIn('future_internal_code',texts)
        self.assertIn('优先按响应标识统计结构化用量；同一会话的旧累计记录不重复相加',texts)
        self.assertIn('自定义可读说明',texts)
        with connect(self.db) as db:
            self.assertEqual(db.execute('SELECT description FROM source_limitations WHERE source_id=? AND code=?',(source,code)).fetchone()[0],code)

    def test_unknown_duplicate_and_cross_product_queries_rejected(self):
        self.assertEqual(self.get('/usage-events',{**self.q,'products':'code'})[0],422)
        self.assertEqual(self.get('/usage-events',{**self.q,'unexpected':'1'})[0],422)
        self.assertEqual(self.app.handle('GET','/api/v1/health?a=1&a=2',self.h)[0],422)
        self.assertEqual(self.get('/usage-events',{**self.q,'account_id':'not_my_account'})[0],404)
        self.assertEqual(self.get('/usage-series',{**self.q,'bucket':'second'})[0],422)

    def test_whole_five_hours_future_unknown_and_totals(self):
        status,data,_ = self.get('/usage-series',{**self.q,'bucket':'15m'})
        self.assertEqual(status,200,data)
        buckets = data['data']['buckets']
        self.assertEqual(len(buckets),21)
        self.assertEqual(sum(r['total_tokens'] or 0 for r in buckets),360)
        for r in buckets:
            if r['record_state'] in ('future','no_records'):
                self.assertIsNone(r['total_tokens'])
        self.assertEqual(sum(r['event_count'] for r in buckets),2)

    def test_claude_recent_activity_without_any_quota_pool(self):
        first=claude_row()
        second=claude_row(minute=20)
        second['requestId']='second_request'
        second['message']['id']='second_message'
        report=self.import_rows([first,second],provider='claude')
        scope={'provider':'claude','account_id':report['account_id']}
        self.assertEqual(self.get('/quota-pools',scope)[1]['data'],[])
        query={**scope,'from':iso(NOW-18000000),'to':iso(NOW),'timezone':'Asia/Tokyo'}
        status,response,_=self.get('/usage-series',{**query,'bucket':'15m'})
        self.assertEqual(status,200)
        check(response,SCHEMAS['SeriesResponse'])
        self.assertEqual(len(response['data']['buckets']),20)
        self.assertEqual(set(response['data']['products']),{'chat','code','cowork'})
        self.assertEqual(sum(b['event_count'] for b in response['data']['buckets']),2)
        self.assertEqual(sum(b['total_tokens'] or 0 for b in response['data']['buckets']),92)
        events=self.get('/usage-events',query)[1]['data']
        sessions=self.get('/sessions',query)[1]['data']
        self.assertEqual(len(events),2)
        self.assertEqual(sum(s['event_count_in_range'] for s in sessions),2)
        empty=self.get('/usage-series',{**query,'products':'chat','bucket':'15m'})[1]['data']
        self.assertTrue(all(b['total_tokens'] is None and b['event_count']==0 for b in empty['buckets']))

    def test_session_bounds_selected_records_not_clipped_lifetime(self):
        q = {**self.q,'from':'2026-10-22T03:15:00.000Z','to':'2026-10-22T03:30:00.000Z'}
        data = self.get('/sessions',q)[1]['data'][0]
        self.assertEqual(data['event_count_in_range'],1)
        self.assertEqual(data['first_record_in_range_at'],data['last_record_in_range_at'])
        self.assertNotEqual(data['started_at'],data['first_record_in_range_at'])

    def test_cursor_cannot_be_reused_after_data_revision_or_query_change(self):
        status,data,_ = self.get('/usage-events',{**self.q,'limit':'1'})
        self.assertEqual(status,200)
        cursor = data['page']['next_cursor']
        self.assertIsNotNone(cursor)
        self.assertEqual(self.get('/usage-events',{**self.q,'limit':'1','cursor':cursor})[0],200)
        self.assertEqual(self.get('/usage-events',{**self.q,'limit':'2','cursor':cursor})[0],409)
        self.import_rows()
        self.assertEqual(self.get('/usage-events',{**self.q,'limit':'1','cursor':cursor})[0],409)

    def test_label_crud_idempotency_cas_and_overlap(self):
        body = self.label_body()
        status,data,h = self.write_api('POST','/labels',body)
        self.assertEqual(status,201,data)
        check(data,SCHEMAS['LabelResponse'])
        lid = data['data']['id']
        self.assertEqual(self.write_api('POST','/labels',body)[0],200)
        self.assertEqual(self.write_api('POST','/labels',{**body,'name':'changed'})[0],409)
        self.assertEqual(self.write_api('PATCH','/labels/'+lid,{'name':'new'})[0],428)
        self.assertEqual(self.write_api('PATCH','/labels/'+lid,{'name':'new'},headers={'If-Match':'"1"'})[0],200)
        self.assertEqual(self.write_api('PATCH','/labels/'+lid,{'name':'old'},headers={'If-Match':'"1"'})[0],412)
        self.write_api('POST','/labels',self.label_body())
        status,events,_ = self.get('/usage-events',self.q)
        self.assertEqual(len(events['data']),2)
        self.assertTrue(all(len(r['label_ids'])==2 for r in events['data']))
        self.assertEqual(self.write_api('DELETE','/labels/'+lid,headers={'If-Match':'"2"'})[0],204)
        self.assertEqual(self.write_api('POST','/labels',body)[0],409)
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),2)

    def test_bad_json_unknown_label_keys_and_cross_account_session(self):
        self.assertEqual(self.write_api('POST','/labels',{**self.label_body(),'prompt':'not allowed'})[0],422)
        self.assertEqual(self.write_api('POST','/labels',{**self.label_body(),'target':{'kind':'session','session_id':'unknown'}})[0],404)
        h = {**self.h,'Content-Type':'application/json'}
        self.assertEqual(self.app.handle('POST','/api/v1/labels',h,b'{"name":1,"name":2}')[0],422)
        self.assertEqual(self.write_api('POST','/labels',{**self.label_body(),'provider':{}})[0],422)
        self.assertEqual(self.write_api('POST','/labels',{**self.label_body(),'account_id':[]})[0],422)

    def test_cookie_pair_refresh_csrf_logout_and_restart(self):
        h = {'Host':'127.0.0.1:49173','Origin':'http://127.0.0.1:49173','Content-Type':'application/json','X-Dashboard-Pairing':'1'}
        status,data,extra = self.app.handle('POST','/api/v1/auth/session',h,canonical({'pairing_code':self.app.auth.pairing_code}).encode())
        self.assertEqual(status,201,data)
        check(data,SCHEMAS['BrowserSessionResponse'])
        cookie = extra['Set-Cookie'].split(';')[0]
        csrf_value = data['data']['csrf_token']
        ch = {'Host':h['Host'],'Origin':h['Origin'],'Cookie':cookie,'Content-Type':'application/json'}
        self.assertEqual(self.app.handle('GET','/api/v1/auth/session',ch)[0],200)
        restarted = Application(self.db,clock=lambda:NOW)
        self.assertEqual(restarted.handle('GET','/api/v1/auth/session',ch)[0],200)
        self.assertEqual(self.app.handle('POST','/api/v1/labels',ch,canonical(self.label_body()).encode())[0],403)
        self.assertEqual(self.app.handle('POST','/api/v1/labels',{**ch,'X-CSRF-Token':'错误值'},canonical(self.label_body()).encode())[0],403)
        self.assertEqual(self.app.handle('POST','/api/v1/labels',{**ch,'X-CSRF-Token':csrf_value},canonical(self.label_body()).encode())[0],201)
        self.assertEqual(self.app.handle('DELETE','/api/v1/auth/session',{**ch,'X-CSRF-Token':csrf_value})[0],204)
        self.assertEqual(restarted.handle('GET','/api/v1/auth/session',ch)[0],401)
        self.assertNotIn(cookie.split('=')[1].encode(),self.db.read_bytes())

    def test_pairing_one_use_expiry_and_rate_limit(self):
        h = {'Host':'127.0.0.1:49173','Origin':'http://127.0.0.1:49173','Content-Type':'application/json','X-Dashboard-Pairing':'1'}
        for _ in range(5):
            self.assertEqual(self.app.handle('POST','/api/v1/auth/session',h,canonical({'pairing_code':'wrong_'+'x'*30}).encode())[0],401)
        status,_,headers = self.app.handle('POST','/api/v1/auth/session',h,canonical({'pairing_code':self.app.auth.pairing_code}).encode())
        self.assertEqual(status,429)
        self.assertIn('Retry-After',headers)
        app = Application(self.db,clock=lambda:NOW)
        app.auth.pairing_created -= 300000
        self.assertEqual(app.handle('POST','/api/v1/auth/session',h,canonical({'pairing_code':app.auth.pairing_code}).encode())[0],401)

    def test_browser_requires_origin_context_and_idle_session_expires(self):
        h = {'Host':'127.0.0.1:49173','Origin':'http://127.0.0.1:49173','Content-Type':'application/json','X-Dashboard-Pairing':'1'}
        status,data,extra = self.app.handle('POST','/api/v1/auth/session',h,canonical({'pairing_code':self.app.auth.pairing_code}).encode())
        self.assertEqual(status,201)
        cookie = extra['Set-Cookie'].split(';')[0]
        ch = {'Host':h['Host'],'Cookie':cookie}
        self.assertEqual(self.app.handle('GET','/api/v1/auth/session',ch)[0],403)
        self.assertEqual(self.app.handle('GET','/api/v1/auth/session',{**ch,'Sec-Fetch-Site':'same-origin'})[0],200)
        old_revision = self.get('/health')[1]['meta']['data_revision']
        self.assertEqual(self.app.handle('GET','/api/v1/auth/session',{**ch,'Origin':h['Origin']})[1]['meta']['data_revision'],old_revision)
        app = Application(self.db,clock=lambda:NOW+86400000)
        self.assertEqual(app.handle('GET','/api/v1/auth/session',{**ch,'Origin':h['Origin']})[0],401)

    def test_time_roundtrip_preserves_exact_milliseconds(self):
        for value in ('2026-10-22T03:05:00.001Z','2026-10-22T03:05:00.999Z','1969-12-31T23:59:59.999Z'):
            self.assertEqual(iso(parse_time(value)),value.replace('Z','+00:00').replace('+00:00','Z'))

    def test_calendar_dst_and_month_boundaries(self):
        for zone,a,b,expected_hours in [
            ('America/New_York','2026-03-08T05:00:00.000Z','2026-03-09T04:00:00.000Z',23),
            ('America/New_York','2026-11-01T04:00:00.000Z','2026-11-02T05:00:00.000Z',25)]:
            rows = list(intervals(parse_time(a),parse_time(b),'day',ZoneInfo(zone),parse_time(b)))
            self.assertEqual(len(rows),1)
            self.assertEqual((rows[0][1]-rows[0][0])/3600000,expected_hours)
        rows = list(intervals(parse_time('2026-10-01T15:00:00.000Z'),parse_time('2026-11-01T15:00:00.000Z'),'month',ZoneInfo('Asia/Tokyo'),NOW+10**10))
        self.assertEqual(iso(rows[0][1]),'2026-10-31T15:00:00.000Z')


class HTTPBackendTests(BackendCase):
    def test_real_http_reads_auth_and_static_directory_boundary(self):
        self.import_rows(codex_rows())
        static = self.root/'build'
        static.mkdir()
        (static/'index.html').write_text('<!doctype html><title>synthetic build</title>')
        try:
            server = make_server(self.db,0,bearer=BEARER,frontend=static,clock=lambda:NOW)
        except PermissionError:
            self.skipTest('Loopback socket permission is required for HTTP integration test')
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        client = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        try:
            client.request('GET','/api/v1/health',headers={'Authorization':'Bearer '+BEARER})
            r = client.getresponse()
            self.assertEqual(r.status,200)
            check(json.loads(r.read()),SCHEMAS['HealthResponse'])
            client.request('GET','/api/v1/accounts')
            r = client.getresponse()
            self.assertEqual(r.status,401)
            r.read()
            client.request('GET','/')
            r = client.getresponse()
            self.assertEqual(r.status,200)
            self.assertIn(b'synthetic build',r.read())
            client.request('GET','/../private/usage.sqlite3')
            r = client.getresponse()
            self.assertEqual(r.status,404)
            r.read()
        finally:
            client.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__=='__main__':
    unittest.main()
