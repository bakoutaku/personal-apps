from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from urllib.parse import urlencode

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_calendar_history import seed_calendar, NOW, TOKEN
from label_workflow_support import WORKFLOW, exercise_labels, ROOT
from test_contract import check, SCHEMAS
from usage_dashboard.app import Application
from usage_dashboard.common import canonical
from usage_dashboard.store import connect


class LabelWriteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'synthetic.sqlite3'
        seed_calendar(self.path)
        self.app=Application(self.path,bearer=TOKEN,clock=lambda:NOW)
        self.h={'Host':'127.0.0.1:49173','Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'}

    def tearDown(self):
        self.temp.cleanup()

    def call(self,method,path,headers,body):
        return self.app.handle(method,path,headers,b'' if body is None else canonical(body).encode())

    def body(self):
        body=json.loads(json.dumps(WORKFLOW['cases'][1]['request']['body']))
        body['client_request_id']=str(uuid.uuid4())
        return body

    def test_documented_cookie_write_workflow_and_immutable_usage(self):
        h={'Host':'127.0.0.1:49173','Origin':'http://127.0.0.1:49173','Content-Type':'application/json','X-Dashboard-Pairing':'1'}
        status,body,headers=self.call('POST','/api/v1/auth/session',h,{'pairing_code':self.app.auth.pairing_code})
        self.assertEqual(status,201)
        cookie_headers={k:h[k] for k in ('Host','Origin')}
        cookie_headers['Cookie']=headers['Set-Cookie'].split(';')[0]
        result=exercise_labels(self.call,cookie_headers,body['data']['csrf_token'])
        self.assertEqual(result['workflow_steps'],20)
        with connect(self.path) as db:
            label=db.execute('SELECT * FROM labels WHERE client_request_id=?',(WORKFLOW['cases'][1]['request']['body']['client_request_id'],)).fetchone()
            self.assertIsNotNone(label['deleted_ms'])
            self.assertEqual(label['revision'],5)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM usage_events').fetchone()[0],20)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM quota_snapshots').fetchone()[0],9)

    def test_simultaneous_same_create_is_one_label(self):
        body=self.body()
        barrier=threading.Barrier(2)
        def create(_):
            barrier.wait(timeout=5)
            return self.call('POST','/api/v1/labels',self.h,body)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(create,range(2)))
        self.assertEqual(sorted(r[0] for r in results),[200,201])
        self.assertEqual(results[0][1]['data']['id'],results[1][1]['data']['id'])
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM labels WHERE client_request_id=?',(body['client_request_id'],)).fetchone()[0],1)

    def test_simultaneous_edit_one_wins_other_conflicts(self):
        status,response,_=self.call('POST','/api/v1/labels',self.h,self.body())
        self.assertEqual(status,201)
        path='/api/v1/labels/'+response['data']['id']
        barrier=threading.Barrier(2)
        def edit(name):
            barrier.wait(timeout=5)
            return self.call('PATCH',path,{**self.h,'If-Match':'"1"'},{'name':name})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(edit,['first editor','second editor']))
        self.assertEqual(sorted(r[0] for r in results),[200,412])
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT revision FROM labels WHERE id=?',(response['data']['id'],)).fetchone()[0],2)

    def test_write_example_shapes_match_operation_contracts(self):
        valid_errors={'patch-invalid-name','patch-owner-forbidden','patch-incomplete-target'}
        for case in WORKFLOW['cases']:
            request,expected=case['request'],case['expected']
            with self.subTest(step=case['id']):
                if request['schema'] and case['id'] not in valid_errors:
                    check(request['body'],SCHEMAS[request['schema']])
                if expected['response_file']:
                    check(json.loads((ROOT/'contracts/mocks'/expected['response_file']).read_text()),SCHEMAS[expected['schema']])
                else:
                    self.assertEqual(expected['status'],204)

    def test_emoji_names_and_invalid_target_are_atomic(self):
        body=self.body()
        body['name']='🍵'*80
        status,response,_=self.call('POST','/api/v1/labels',self.h,body)
        self.assertEqual(status,201)
        self.assertEqual(len(response['data']['name']),80)
        path='/api/v1/labels/'+response['data']['id']
        status,_,_=self.call('PATCH',path,{**self.h,'If-Match':'"1"'},
            {'name':'must not commit','target':{'kind':'session','session_id':'ses_history_claude_3'}})
        self.assertEqual(status,404)
        with connect(self.path) as db:
            row=db.execute('SELECT name,revision FROM labels WHERE id=?',(response['data']['id'],)).fetchone()
            self.assertEqual((row['name'],row['revision']),('🍵'*80,1))

    def test_claude_session_label_is_account_scoped_without_quota(self):
        original=self.body()
        status,gpt,_=self.call('POST','/api/v1/labels',self.h,original)
        self.assertEqual(status,201)
        body={**original,'provider':'claude','account_id':'acct_demo_claude',
              'target':{'kind':'session','session_id':'ses_history_claude_3'}}
        status,claude,_=self.call('POST','/api/v1/labels',self.h,body)
        self.assertEqual(status,201)
        self.assertNotEqual(gpt['data']['id'],claude['data']['id'])
        for provider,expected in [('gpt',0),('claude',3)]:
            q={'provider':provider,'account_id':'acct_demo_'+provider,'from':'2026-10-21T15:00:00.000Z','to':'2026-10-22T15:00:00.000Z'}
            status,events,_=self.call('GET','/api/v1/usage-events?'+urlencode(q),self.h,None)
            self.assertEqual(status,200)
            self.assertEqual(sum(claude['data']['id'] in e['label_ids'] for e in events['data']),expected)
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM quota_pools WHERE provider='claude'").fetchone()[0],0)
