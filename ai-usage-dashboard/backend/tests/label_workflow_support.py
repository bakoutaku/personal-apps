"""Execute documented writes against either the app or a real HTTP transport."""
import copy
import json
from pathlib import Path
from urllib.parse import urlencode

from test_contract import SCHEMAS, check

ROOT=Path(__file__).resolve().parents[2]
WORKFLOW=json.loads((ROOT/'contracts/mocks/label-workflow/workflow.json').read_text())


def exercise_labels(transport, browser_headers, csrf_token):
    cases=WORKFLOW['cases']
    query={'provider':'gpt','account_id':'acct_demo_gpt','from':'2026-10-21T15:00:00.000Z',
           'to':'2026-10-22T15:00:00.000Z','timezone':'Asia/Tokyo'}
    checked=0

    def read(path,schema):
        nonlocal checked
        target='/api/v1'+path+('?' +urlencode(query) if path!='/health' else '')
        status,body,_=transport('GET',target,browser_headers,None)
        if status!=200:
            raise AssertionError('Workflow read failed: '+path)
        check(body,SCHEMAS[schema])
        checked+=1
        return body

    def without_tags(events):
        return [{k:v for k,v in e.items() if k!='label_ids'} for e in events]

    before=read('/usage-events','EventsResponse')['data']
    revision=read('/health','HealthResponse')['meta']['data_revision']
    label_id=None
    current=None
    for case in cases:
        request,expected=case['request'],case['expected']
        headers=dict(browser_headers)
        if request['auth']=='none':
            headers.pop('Cookie',None)
        headers.update({k:csrf_token if v=='$memory_csrf' else v for k,v in request['headers'].items()})
        path=request['path'].replace('{id}',label_id or 'unset')
        status,response,received=transport(request['method'],path,headers,request['body'])
        if status!=expected['status']:
            raise AssertionError(case['id']+': unexpected status '+str(status))
        if expected['schema']:
            check(response,SCHEMAS[expected['schema']])
            checked+=1
            if expected['error_code'] and response['error']['code']!=expected['error_code']:
                raise AssertionError(case['id']+': unexpected error code')
        elif response is not None:
            raise AssertionError('204 must not contain JSON')
        if status in (200,201):
            if label_id is None:
                label_id=response['data']['id']
            sample=json.loads((ROOT/'contracts/mocks'/expected['response_file']).read_text())['data']
            sample['id']=label_id
            if response['data']!=sample:
                raise AssertionError(case['id']+': documented label fields differ from runtime')
            if received.get('ETag')!=expected['headers']['ETag']:
                raise AssertionError(case['id']+': ETag differs from revision')
            current=copy.deepcopy(response['data'])
        elif status==204:
            current=None
        after=read('/health','HealthResponse')['meta']['data_revision']
        if after-revision!=expected['data_revision_delta']:
            raise AssertionError(case['id']+': unexpected data revision change')
        revision=after
        labels=read('/labels','LabelsResponse')['data']
        found=[label for label in labels if label['id']==label_id]
        if found!=([current] if current else []):
            raise AssertionError(case['id']+': active label list differs')
        events=read('/usage-events','EventsResponse')['data']
        if without_tags(events)!=without_tags(before):
            raise AssertionError(case['id']+': write changed original usage')
        for e in events:
            match=False
            if current:
                target=current['target']
                match=e['session_id']==target['session_id'] if target['kind']=='session' else (
                    e['product'] in target['products'] and e['occurred_at']>=target['from'] and
                    (target['to'] is None or e['occurred_at']<target['to']))
            if (label_id in e['label_ids'])!=match:
                raise AssertionError(case['id']+': event label association differs')
    return {'workflow_steps':len(cases),'schema_checked_responses':checked,'all_writes_verified':True}
