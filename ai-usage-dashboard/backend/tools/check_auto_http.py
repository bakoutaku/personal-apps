"""Thirty-second polling smoke check with synthetic logs only; no user sources."""
import http.client
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_backend import codex_rows, claude_row, raw_usage, NOW
from test_contract import check, SCHEMAS
from usage_dashboard.auto_collect import AutoCollector, load_config
from usage_dashboard.common import canonical, iso
from usage_dashboard.server import make_server
from usage_dashboard.store import initialize, connect


def main():
    start=time.monotonic()
    checked=0
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder).resolve()
        db_path=root/'private/usage.sqlite3'
        initialize(db_path)
        gpt_file,claude_file=root/'gpt.jsonl',root/'claude.jsonl'
        gpt_file.write_text(''.join(canonical(r)+'\n' for r in codex_rows()))
        claude_file.write_text(canonical(claude_row())+'\n')
        cfg_file=root/'collector.json'
        cfg_file.write_text(canonical({'version':1,'interval_seconds':30,'sources':[
            {'enabled':True,'provider':'gpt','path':str(gpt_file),'account_namespace':'synthetic'},
            {'enabled':True,'provider':'claude','path':str(claude_file),'account_namespace':'synthetic'}]}))
        token='aud_'+secrets.token_urlsafe(32)
        server=make_server(db_path,0,bearer=token)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        collector=AutoCollector(db_path,load_config(cfg_file))
        thread.start()
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        def get(path,query,schema):
            nonlocal checked
            client.request('GET','/api/v1'+path+('?' +urlencode(query) if query else ''),headers={'Authorization':'Bearer '+token})
            response=client.getresponse()
            body=json.loads(response.read())
            if response.status!=200:
                raise AssertionError('Synthetic auto check: API read failed')
            check(body,SCHEMAS[schema])
            checked+=1
            return body['data']
        def counts():
            accounts=get('/accounts',{},'AccountsResponse')
            result={}
            for account in accounts:
                q={'provider':account['provider'],'account_id':account['id'],'from':iso(NOW-18000000),'to':iso(NOW+1)}
                result[account['provider']]=len(get('/usage-events',q,'EventsResponse'))
            return result
        def await_counts(expected,seconds):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                if counts()==expected:
                    return
                time.sleep(.25 if seconds<=5 else 1)
            raise AssertionError('Synthetic auto check: scheduled data did not appear in time')
        try:
            collector.start()
            await_counts({'gpt':2,'claude':1},5)
            gpt={'type':'token_usage_record','timestamp':'2026-10-22T03:45:00.000Z',
                 'payload':{'thread_id':'synthetic_thread','response_id':'automatic_new_response','usage':raw_usage()}}
            claude=claude_row(minute=40)
            claude['requestId']='automatic_new_request'
            claude['message']['id']='automatic_new_message'
            with gpt_file.open('a') as f:
                f.write(canonical(gpt)+'\n')
            with claude_file.open('a') as f:
                f.write(canonical(claude)+'\n')
            await_counts({'gpt':3,'claude':2},40)
            for account in get('/accounts',{},'AccountsResponse'):
                rows=get('/sources',{'provider':account['provider'],'account_id':account['id']},'SourcesResponse')
                active=next(r for r in rows if r['kind']=='local_log')
                if active['retry_mode']!='automatic' or active['next_attempt_at'] is None:
                    raise AssertionError('Synthetic auto check: missing next schedule')
        finally:
            collector.stop()
            client.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        with connect(db_path) as db:
            if db.execute("SELECT COUNT(*) FROM sources WHERE retry_mode='automatic' OR next_attempt_ms IS NOT NULL").fetchone()[0]:
                raise AssertionError('Synthetic auto check: schedule remains after shutdown')
        raw=db_path.read_bytes()
        if str(root).encode() in raw or b'DO_NOT_STORE_PRIVATE' in raw:
            raise AssertionError('Synthetic auto check: private source contents were persisted')
    print(json.dumps({'synthetic_data':True,'interval_seconds':30,'elapsed_seconds':round(time.monotonic()-start,1),
                      'events_after_append':{'gpt':3,'claude':2},'schema_checked_http_responses':checked,
                      'worker_and_server_stopped':True,'private_paths_and_content_not_persisted':True}))


if __name__=='__main__':
    main()
