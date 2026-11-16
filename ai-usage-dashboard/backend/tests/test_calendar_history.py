"""Calendar scenarios checked against independent SQLite/API aggregation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_contract import CATALOG, SCHEMAS, check, load
from usage_dashboard.app import Application
from usage_dashboard.common import parse_time, canonical
from usage_dashboard.query import intervals
from usage_dashboard.store import initialize, connect, insert

NOW = parse_time(CATALOG['as_of'])
TOKEN = 'aud_'+'synthetic_calendar_test_only_0123456789'


def unordered(value):
    if isinstance(value,dict):
        return {k:unordered(v) for k,v in value.items()}
    if isinstance(value,list):
        return sorted((unordered(v) for v in value),key=canonical)
    return value


def seed_calendar(path):
    initialize(path)
    with connect(path) as db:
        insert(db,'devices',{'id':'device_demo','label':'演示设备（虚构）','platform':'macos'})
        for provider,product in [('gpt','codex'),('claude','code')]:
            scenario=provider+'-history'
            account='acct_demo_'+provider
            insert(db,'accounts',{'id':account,'provider':provider,'label':'synthetic','identity_status':'local_unverified'})
            for s in load(scenario+'/sources.json')['data']:
                values={k:s[k] for k in ('id','account_id','provider','product','device_id','kind','connection_status','error_code','history_status','consecutive_failure_count','retry_mode')}
                values.update({target:parse_time(s[source]) if s[source] else None for source,target in
                    [('last_attempt_at','last_attempt_ms'),('last_success_at','last_success_ms'),('last_record_at','last_record_ms'),('next_attempt_at','next_attempt_ms')]})
                insert(db,'sources',values)
                for capability in s['capabilities']:
                    insert(db,'source_capabilities',{'source_id':s['id'],'capability':capability})
                for i,text in enumerate(s['limitations']):
                    insert(db,'source_limitations',{'source_id':s['id'],'code':'synthetic_'+str(i),'description':text})
                for i,c in enumerate(s['coverage']):
                    insert(db,'coverage_intervals',{'id':s['id']+'_coverage_'+str(i),'source_id':s['id'],
                        'from_ms':parse_time(c['from']),'to_ms':parse_time(c['to']),**{k:c[k] for k in ('status','scope','reason','evidence')}})
            events=load(scenario+'/events-reference.json')['data']
            for sid in sorted({e['session_id'] for e in events}):
                rows=[e for e in events if e['session_id']==sid]
                insert(db,'sessions',{'id':sid,'source_id':'src_demo_'+provider,'account_id':account,'provider':provider,'product':product,
                    'external_session_key':sid,'started_ms':parse_time(rows[0]['occurred_at']),'last_record_ms':parse_time(rows[-1]['occurred_at'])})
            for e in events:
                values={k:e[k] for k in ('id','source_id','account_id','provider','product','session_id','total_tokens','total_basis','components_complete','reasoning_output_tokens')}
                values.update(e['components'])
                values.update({'external_event_key':e['id'],'occurred_ms':parse_time(e['occurred_at']),
                    'recorded_ms':parse_time(e['recorded_at']),'ingested_ms':parse_time(e['ingested_at'])})
                insert(db,'usage_events',values)
            for label in load(scenario+'/week/'+product+'-labels.json')['data']:
                target=label['target']
                values={k:label[k] for k in ('id','account_id','provider','name','revision')}
                values.update({'client_request_id':label['id'],'create_request_hash':'synthetic','target_kind':target['kind'],
                    'created_ms':parse_time(label['created_at']),'updated_ms':parse_time(label['updated_at'])})
                if target['kind']=='range':
                    values.update({'from_ms':parse_time(target['from']),'to_ms':parse_time(target['to'])})
                else:
                    values['session_id']=target['session_id']
                insert(db,'labels',values)
                for p in target.get('products',[]):
                    insert(db,'label_products',{'label_id':label['id'],'account_id':account,'provider':provider,'product':p})
            for pool in load(scenario+'/quota-pools.json')['data']:
                values={k:pool[k] for k in ('id','account_id','provider','label','provider_bucket_key','product_membership_complete','membership_evidence')}
                insert(db,'quota_pools',{**values,'product_membership_known':1})
                insert(db,'quota_pool_sources',{'pool_id':pool['id'],'source_id':'src_demo_'+provider,'account_id':account,'provider':provider})
                insert(db,'quota_pool_products',{'pool_id':pool['id'],'account_id':account,'provider':provider,'product':product,'evidence':'synthetic'})
                for w in load(scenario+'/month/quota-windows.json')['data']:
                    insert(db,'quota_windows',{**{k:w[k] for k in ('id','pool_id','slot','duration_seconds','start_source','end_source','semantics')},
                        'external_window_key':w['id'],'starts_ms':parse_time(w['starts_at']),'ends_ms':parse_time(w['ends_at'])})
                for s in load(scenario+'/month/quota-snapshots.json')['data']:
                    insert(db,'quota_snapshots',{**{k:s[k] for k in ('id','pool_id','window_id','source_id','time_basis','used_percent','value_basis')},
                        'external_snapshot_key':s['id'],'observed_ms':None,'recorded_ms':parse_time(s['recorded_at']),
                        'effective_ms':parse_time(s['effective_at']),'ingested_ms':parse_time(s['ingested_at'])})


class CalendarHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'calendar.sqlite3'
        seed_calendar(self.path)
        self.app=Application(self.path,bearer=TOKEN,clock=lambda:NOW)
        self.headers={'Host':'127.0.0.1:49173','Authorization':'Bearer '+TOKEN}

    def tearDown(self):
        self.temp.cleanup()

    def test_all_complete_history_responses_equal_runtime_queries(self):
        entries=[f for f in CATALOG['fixtures'] if f['scenario_id'] in ('gpt-history','claude-history')]
        self.assertEqual(len(entries),146)
        for entry in entries:
            with self.subTest(file=entry['file']):
                status,response,_=self.app.handle('GET',entry['path']+'?'+urlencode(entry['query']),self.headers)
                self.assertEqual(status,200,response)
                check(response,SCHEMAS[entry['schema']])
                self.assertEqual(unordered(response['data']),unordered(load(entry['file'])['data']))

    def test_calendar_boundaries_unknowns_future_and_session_tracks(self):
        for provider,product in [('gpt','codex'),('claude','code')]:
            for view,count,total,buckets_count in [('day',4,3000,25),('week',7,7000,8),('month',9,9000,32)]:
                base=provider+'-history/'+view+'/'+product+'-'
                series=load(base+'usage-series.json')['data']
                events=load(base+'usage-events.json')['data']
                sessions=load(base+'sessions.json')['data']
                self.assertEqual(len(events),count)
                self.assertEqual(sum(e['total_tokens'] or 0 for e in events),total)
                self.assertEqual(len(series['buckets']),buckets_count)
                previous=series['from']
                for b in series['buckets']:
                    self.assertEqual(b['from'],previous)
                    previous=b['to']
                    if b['record_state']=='future':
                        self.assertGreaterEqual(b['from'],CATALOG['as_of'])
                        self.assertIsNone(b['total_tokens'])
                        self.assertEqual(b['event_count'],0)
                self.assertEqual(previous,series['to'])
                self.assertEqual(sum(b['event_count'] for b in series['buckets']),count)
                self.assertEqual(sum(b['unknown_total_count'] for b in series['buckets']),1)
                self.assertEqual(sum(s['event_count_in_range'] for s in sessions),count)
                self.assertEqual(sum(s['total_tokens_in_range'] or 0 for s in sessions),total)
            # Exact local midnight / Monday / month boundary, half-open filtering.
            day=load(provider+'-history/day/'+product+'-usage-events.json')['data']
            self.assertTrue(day[0]['id'].endswith('_6'))
            week=load(provider+'-history/week/'+product+'-usage-events.json')['data']
            self.assertTrue(week[0]['id'].endswith('_3'))
            month=load(provider+'-history/month/'+product+'-usage-events.json')['data']
            self.assertTrue(month[0]['id'].endswith('_1'))
            overnight=load(provider+'-history/day/'+product+'-sessions.json')['data'][0]
            self.assertLess(overnight['started_at'],overnight['range_from'])
            self.assertEqual(overnight['first_record_in_range_at'],overnight['last_record_in_range_at'])

    def test_selected_detail_range_and_quota_summary_use_requested_range(self):
        query={'provider':'gpt','account_id':'acct_demo_gpt','from':'2026-10-22T03:00:00.000Z',
               'to':'2026-10-22T04:00:00.000Z','timezone':'Asia/Tokyo'}
        def get(path,extra=None):
            status,data,_=self.app.handle('GET','/api/v1'+path+'?'+urlencode({**query,**(extra or {})}),self.headers)
            self.assertEqual(status,200,data)
            return data['data']
        rows=get('/usage-events')
        self.assertEqual(len(rows),3)
        self.assertEqual(sum(e['total_tokens'] or 0 for e in rows),2000)
        self.assertEqual(unordered(rows),unordered(load('gpt-history/selection/codex-usage-events.json')['data']))
        self.assertEqual(get('/sessions')[0]['event_count_in_range'],3)
        summaries=get('/quota-window-summaries',{'pool_id':'pool_history_gpt'})
        self.assertEqual({s['window_id'] for s in summaries},{'win_history_today','win_history_this_week'})
        for s in summaries:
            self.assertEqual((s['scope_from'],s['scope_to']),(query['from'],query['to']))
        self.assertEqual(next(s['sample_count'] for s in summaries if s['window_id']=='win_history_this_week'),1)

    def test_calendar_year_and_leap_month_boundaries(self):
        for a,b,kind in [('2026-12-27T15:00:00.000Z','2027-01-03T15:00:00.000Z','week'),
                         ('2026-11-30T15:00:00.000Z','2026-12-31T15:00:00.000Z','month'),
                         ('2028-01-31T15:00:00.000Z','2028-02-29T15:00:00.000Z','month')]:
            rows=list(intervals(parse_time(a),parse_time(b),kind,ZoneInfo('Asia/Tokyo'),parse_time(b)))
            self.assertEqual(rows,[(parse_time(a),parse_time(b),False)])
