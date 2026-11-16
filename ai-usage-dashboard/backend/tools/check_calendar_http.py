"""Check all synthetic calendar fixture responses over a temporary HTTP server."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import urlencode

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_calendar_history import NOW, TOKEN, seed_calendar, unordered
from test_contract import CATALOG, SCHEMAS, check, load
from usage_dashboard.server import make_server


def main():
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'synthetic-calendar.sqlite3'
        seed_calendar(path)
        server=make_server(path,0,bearer=TOKEN,clock=lambda:NOW)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        checked=0
        try:
            for entry in CATALOG['fixtures']:
                if entry['scenario_id'] not in ('gpt-history','claude-history'):
                    continue
                client.request('GET',entry['path']+'?'+urlencode(entry['query']),headers={'Authorization':'Bearer '+TOKEN})
                response=client.getresponse()
                body=json.loads(response.read())
                if response.status!=200:
                    raise AssertionError('Unexpected HTTP status for '+entry['file'])
                check(body,SCHEMAS[entry['schema']])
                if body['meta']['data_mode']!='live' or unordered(body['data'])!=unordered(load(entry['file'])['data']):
                    raise AssertionError('Runtime/fixture data mismatch for '+entry['file'])
                if response.getheader('Cache-Control')!='no-store':
                    raise AssertionError('Missing no-store')
                checked+=1
        finally:
            client.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        print(json.dumps({'synthetic_data':True,'schema_checked_http_responses':checked,
                          'fixture_data_matches':True,'temporary_server_stopped':True}))


if __name__=='__main__':
    main()
