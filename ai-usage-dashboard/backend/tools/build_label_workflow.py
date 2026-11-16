"""Ordered, synthetic label write examples. No executable credentials."""
from copy import deepcopy


def generate_label_workflow(fixture, envelope, save, output, now, version):
    original = {'provider':'gpt','account_id':'acct_demo_gpt',
                'client_request_id':'a53cf049-8f5c-4e31-a8ed-0f1b2c3d4e5f','name':'  标签写入示例  ',
                'target':{'kind':'range','from':'2026-10-21T15:00:00.000Z','to':now,'products':['codex','chat']}}
    state = {'id':'label_workflow_demo','provider':'gpt','account_id':'acct_demo_gpt','name':'标签写入示例',
             'target':{**original['target'],'products':['chat','codex']},'revision':1,'created_at':now,'updated_at':now}
    cases = []

    def add(key, method, body, status, code=None, headers=None, auth='cookie_csrf', label=None, delta=0):
        request_headers={'Content-Type':'application/json'} if body is not None else {}
        request_headers.update(headers or {})
        if auth=='cookie_csrf':
            request_headers['X-CSRF-Token']='$memory_csrf'
        schema='LabelResponse' if status in (200,201) else None if status==204 else 'ErrorResponse'
        file='label-workflow/'+key+'.json' if schema else None
        if status in (200,201):
            data=envelope(deepcopy(label or state),'label-write-'+key)
        elif schema:
            data={'error':{'code':code,'message':'Synthetic label workflow example; frontend uses error.code, not this message.',
                           'details':[]},'meta':envelope(None,'label-write-'+key)['meta']}
        path='/labels' if method=='POST' else '/labels/{id}'
        if schema:
            fixture(file,schema,data,path,method=method,status=status,
                    note='Ordered write example only; see label-workflow/workflow.json. Does not mutate other static fixtures.')
        cases.append({'id':key,'request':{'method':method,'path':'/api/v1'+path,'headers':request_headers,
                      'auth':auth,'body':deepcopy(body),'schema':'LabelCreate' if method=='POST' else 'LabelPatch' if method=='PATCH' else None},
                      'expected':{'status':status,'schema':schema,'response_file':file,'error_code':code,
                                  'headers':{'ETag':'"'+str((label or state)['revision'])+'"'} if status in (200,201) else {},
                                  'data_revision_delta':delta}})

    add('unauthenticated','POST',original,401,'unauthorized',auth='none')
    add('range-created','POST',original,201,delta=1)
    add('create-retried','POST',original,200)
    equivalent=deepcopy(original)
    equivalent.update({'client_request_id':original['client_request_id'].upper(),'name':'标签写入示例'})
    equivalent['target']={'kind':'range','from':'2026-10-22T00:00:00.000+09:00','to':'2026-10-22T13:01:00.000+09:00','products':['chat','codex']}
    add('create-normalized-retry','POST',equivalent,200)
    add('create-key-conflict','POST',{**original,'name':'不同内容'},409,'idempotency_conflict')
    add('patch-without-version','PATCH',{'name':'整理标签示例'},428,'precondition_required')
    add('patch-stale-version','PATCH',{'name':'整理标签示例'},412,'revision_conflict',headers={'If-Match':'"99"'})
    add('patch-invalid-name','PATCH',{'name':'   '},422,'invalid_body',headers={'If-Match':'"1"'})
    state.update({'name':'整理标签示例','revision':2})
    add('label-renamed','PATCH',{'name':'整理标签示例'},200,headers={'If-Match':'"1"'},delta=1)
    add('create-retry-after-edit','POST',original,200)
    state.update({'target':{'kind':'session','session_id':'ses_history_gpt_3'},'revision':3})
    add('target-session','PATCH',{'target':state['target']},200,headers={'If-Match':'"2"'},delta=1)
    add('delete-stale-version','DELETE',None,412,'revision_conflict',headers={'If-Match':'"2"'})
    add('patch-without-csrf','PATCH',{'name':'不能写入'},403,'csrf_invalid',headers={'If-Match':'"3"'},auth='cookie_only')
    add('patch-owner-forbidden','PATCH',{'provider':'claude'},422,'invalid_body',headers={'If-Match':'"3"'})
    add('patch-foreign-session','PATCH',{'target':{'kind':'session','session_id':'ses_history_claude_3'}},404,'not_found',headers={'If-Match':'"3"'})
    state.update({'target':{'kind':'range','from':original['target']['from'],'to':None,'products':['codex']},'revision':4})
    add('target-ongoing-range','PATCH',{'target':state['target']},200,headers={'If-Match':'"3"'},delta=1)
    add('patch-incomplete-target','PATCH',{'target':{'kind':'range','from':original['target']['from']}},422,'invalid_body',headers={'If-Match':'"4"'})
    add('label-deleted','DELETE',None,204,headers={'If-Match':'"4"'},delta=1)
    add('create-retry-after-delete','POST',original,409,'idempotency_conflict')
    add('delete-repeated','DELETE',None,404,'not_found',headers={'If-Match':'"4"'})
    save(output/'mocks/label-workflow/workflow.json',{'api_version':version,'data_mode':'mock','base_scenario':'gpt-history',
        'label_id_placeholder':'{id}','csrf_placeholder':'$memory_csrf','cases':cases,
        'notes':['Static ordered examples, not a mutable mock backend. Never send the placeholder CSRF value.',
                 'Successful POST IDs are generated; replace {id} with the actual returned ID.',
                 'Each response fixture is an isolated state, not a screen dataset to merge.']})
