"""Verify documented label writes via Cookie/CSRF on a temporary synthetic DB."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_calendar_history import seed_calendar, NOW
from label_workflow_support import exercise_labels
from test_contract import SCHEMAS, check
from usage_dashboard.server import make_server


def main():
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'label-write-synthetic.sqlite3'
        seed_calendar(path)
        server=make_server(path,0,clock=lambda:NOW)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        origin='http://127.0.0.1:'+str(server.server_port)
        requests=0
        def transport(method,target,headers,body):
            nonlocal requests
            client.request(method,target,json.dumps(body) if body is not None else None,headers)
            response=client.getresponse()
            raw=response.read()
            if response.getheader('Cache-Control')!='no-store':
                raise AssertionError('Missing no-store')
            requests+=1
            return response.status,json.loads(raw) if raw else None,dict(response.getheaders())
        try:
            h={'Host':'127.0.0.1:'+str(server.server_port),'Origin':origin,'Content-Type':'application/json','X-Dashboard-Pairing':'1'}
            status,paired,headers=transport('POST','/api/v1/auth/session',h,{'pairing_code':server.app.auth.pairing_code})
            if status!=201:
                raise AssertionError('Synthetic browser pairing failed')
            check(paired,SCHEMAS['BrowserSessionResponse'])
            browser={k:h[k] for k in ('Host','Origin')}
            browser['Cookie']=headers['Set-Cookie'].split(';')[0]
            result=exercise_labels(transport,browser,paired['data']['csrf_token'])
            status,body,_=transport('DELETE','/api/v1/auth/session',{**browser,'X-CSRF-Token':paired['data']['csrf_token']},None)
            if status!=204 or body is not None:
                raise AssertionError('Logout must return empty 204')
            status,body,_=transport('GET','/api/v1/auth/session',browser,None)
            check(body,SCHEMAS['ErrorResponse'])
            if status!=401:
                raise AssertionError('Revoked synthetic session still active')
            result.update({'http_requests':requests,'synthetic_data':True,'cookie_csrf_verified':True,
                           'schema_checked_responses':result['schema_checked_responses']+2})
        finally:
            client.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        result['temporary_server_stopped']=True
        print(json.dumps(result))


if __name__=='__main__':
    main()
