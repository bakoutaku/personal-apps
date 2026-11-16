"""Synthetic calendar scenarios; never reads local logs or credentials."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def generate_history(fixture, envelope, make_event, now):
    zone = ZoneInfo('Asia/Tokyo')
    parse = lambda s: datetime.fromisoformat(s.replace('Z', '+00:00'))
    fmt = lambda d: d.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    instant = parse(now)
    today = instant.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today-timedelta(days=today.weekday())
    month = today.replace(day=1)
    next_month = month.replace(year=month.year+(month.month==12), month=month.month%12+1)
    periods = {'day':(today,today+timedelta(days=1),'hour'),
               'week':(monday,monday+timedelta(days=7),'day'),
               'month':(month,next_month,'day'),
               'selection':(parse('2026-10-22T03:00:00.000Z'),parse('2026-10-22T04:00:00.000Z'),'hour')}
    times = ['2026-09-30T14:55:00.000Z', '2026-09-30T15:00:00.000Z',
             '2026-10-18T14:55:00.000Z', '2026-10-18T15:00:00.000Z',
             '2026-10-20T03:00:00.000Z', '2026-10-21T14:55:00.000Z',
             '2026-10-21T15:00:00.000Z', '2026-10-22T03:05:00.000Z',
             '2026-10-22T03:20:00.000Z', '2026-10-22T03:59:00.000Z']
    component_names = ('uncached_input_tokens','cache_read_input_tokens','cache_write_input_tokens','output_tokens')
    contexts = {}
    for provider, product, missing in [('gpt','codex',('chat','work')),('claude','code',('chat','cowork'))]:
        scenario = provider+'-history'
        source_id, account = 'src_demo_'+provider, 'acct_demo_'+provider
        scope = {'provider':provider,'account_id':account}
        pid = 'pool_history_gpt' if provider=='gpt' else None
        source = {'id':source_id,**scope,'product':product,'kind':'local_log','device_id':'device_demo',
                  'device_label':'演示设备（虚构）','connection_status':'available','last_attempt_at':now,
                  'last_success_at':now,'last_record_at':times[-1],'error_code':None,'history_status':'has_records',
                  'consecutive_failure_count':0,'retry_mode':'manual','next_attempt_at':None,
                  'capabilities':['token_events','session_ids']+(['quota_snapshots'] if pid else []),
                  'coverage':[{'from':times[0],'to':times[-1],'status':'partial','scope':'local_device',
                               'reason':'synthetic_local_history','evidence':'synthetic_selected_records_only'}],
                  'limitations':['仅虚构本机抽样；无记录不等于没有使用；其他设备未覆盖']}
        disconnected = [{**source,'id':'src_unconfigured_'+provider+'_'+p,'product':p,'device_id':None,'device_label':None,
                         'kind':'official_client','connection_status':'not_configured','last_attempt_at':None,
                         'last_success_at':None,'last_record_at':None,'history_status':'unknown',
                         'consecutive_failure_count':None,'retry_mode':'disabled','capabilities':[],'coverage':[],
                         'limitations':['该产品的自动采集入口尚未验证']} for p in missing]
        fixture(scenario+'/sources.json','SourcesResponse',envelope([source]+disconnected,scenario),'/sources',scope)
        pools = [{'id':pid,**scope,'label':'历史场景 Codex 虚构额度池','provider_bucket_key':'codex',
                  'products':[product],'product_membership_complete':False,'membership_evidence':'仅虚构 Codex 桶，其他产品关联未知',
                  'source_ids':[source_id]}] if pid else []
        fixture(scenario+'/quota-pools.json','PoolsResponse',envelope(pools,scenario),'/quota-pools',scope)
        labels = [{'id':'label_history_'+provider+'_range',**scope,'name':'历史学习示例',
                   'target':{'kind':'range','from':fmt(monday),'to':fmt(today+timedelta(days=1)),'products':[product]},
                   'revision':1,'created_at':fmt(monday),'updated_at':fmt(monday)},
                  {'id':'label_history_'+provider+'_session',**scope,'name':'当日开发示例',
                   'target':{'kind':'session','session_id':'ses_history_'+provider+'_3'},
                   'revision':1,'created_at':times[7],'updated_at':times[7]}]
        events = []
        for i, at in enumerate(times):
            group = 0 if i<2 else 1 if i<4 else 2 if i<7 else 3
            # Include both incomplete known components and unknown totals.
            e = make_event(provider,product,2 if i==8 else 1 if i==4 else 0,None if i==8 else 2000 if i==4 else 1000)
            e.update({'id':'evt_history_'+provider+'_'+str(i),'session_id':'ses_history_'+provider+'_'+str(group),
                      'occurred_at':at,'recorded_at':at,'label_ids':[]})
            if parse(at)>=monday:
                e['label_ids'].append(labels[0]['id'])
            if group==3:
                e['label_ids'].append(labels[1]['id'])
            events.append(e)
        fixture(scenario+'/events-reference.json','EventsResponse',envelope(events,scenario,True),'/usage-events',
                {**scope,'products':product,'from':'2026-09-29T15:00:00.000Z','to':fmt(next_month),'timezone':'Asia/Tokyo'},
                note='One reference dataset for all calendar views, including records outside the current month/week/day.')

        def selected_labels(rows, a, b, selected_products):
            return [label for label in labels if
                    (label['target']['kind']=='range' and product in selected_products and
                     parse(label['target']['from'])<b and parse(label['target']['to'])>a) or
                    (label['target']['kind']=='session' and any(e['session_id']==label['target']['session_id'] for e in rows))]

        def sessions(rows, a, b):
            result = []
            for sid in sorted({e['session_id'] for e in rows}):
                lifetime = [e for e in events if e['session_id']==sid]
                selected = [e for e in rows if e['session_id']==sid]
                known = [e['total_tokens'] for e in selected if e['total_tokens'] is not None]
                result.append({'id':sid,**scope,'product':product,'source_id':source_id,
                    'started_at':lifetime[0]['occurred_at'],'last_record_at':lifetime[-1]['occurred_at'],
                    'range_from':fmt(a),'range_to':fmt(b),'first_record_in_range_at':selected[0]['occurred_at'],
                    'last_record_in_range_at':selected[-1]['occurred_at'],'activity_bounds_basis':'record_timestamps',
                    'event_count_in_range':len(selected),'known_total_count':len(known),
                    'unknown_total_count':len(selected)-len(known),'total_tokens_in_range':sum(known) if known else None,
                    'label_ids':sorted({label for e in selected for label in e['label_ids']})})
            return result

        windows, snapshots = [], []
        if pid:
            definitions = [
                ('old','primary','2026-09-30T15:00:00.000Z',18000,[('2026-09-30T15:10:00.000Z',20)]),
                ('midnight','primary','2026-10-21T11:00:00.000Z',18000,
                 [('2026-10-21T14:55:00.000Z',30),('2026-10-21T15:10:00.000Z',55)]),
                ('today','primary','2026-10-22T00:58:00.000Z',18000,
                 [('2026-10-22T03:05:00.000Z',42),('2026-10-22T03:20:00.000Z',50),('2026-10-22T03:59:00.000Z',62)]),
                ('previous_week','secondary','2026-10-11T15:00:00.000Z',604800,[('2026-10-18T14:55:00.000Z',81)]),
                ('this_week','secondary','2026-10-18T15:00:00.000Z',604800,
                 [('2026-10-19T00:00:00.000Z',12),('2026-10-22T03:59:00.000Z',52)])]
            for key, slot, start, duration, points in definitions:
                wid = 'win_history_'+key
                own = [{'id':'snap_history_'+key+'_'+str(i),'pool_id':pid,'window_id':wid,'source_id':source_id,
                        'observed_at':None,'recorded_at':at,'ingested_at':now,'effective_at':at,'time_basis':'recorded_at',
                        'used_percent':value,'value_basis':'reported'} for i,(at,value) in enumerate(points)]
                end = fmt(parse(start)+timedelta(seconds=duration))
                w = {'id':wid,'pool_id':pid,'slot':slot,'duration_seconds':duration,'starts_at':start,'ends_at':end,
                     'start_source':'derived','end_source':'reported','semantics':'unknown',
                     'status':'expired' if parse(end)<=instant else 'current','freshness':'stale' if (instant-parse(points[-1][0])).total_seconds()>900 else 'fresh',
                     'latest_snapshot':own[-1],'previous_window_id':None,'next_window_id':None}
                windows.append(w)
                snapshots += own
            for slot in ('primary','secondary'):
                ordered = sorted((w for w in windows if w['slot']==slot),key=lambda w:w['ends_at'])
                for i,w in enumerate(ordered):
                    w['previous_window_id']=ordered[i-1]['id'] if i else None
                    w['next_window_id']=ordered[i+1]['id'] if i+1<len(ordered) else None

        for view,(a,b,bucket_kind) in periods.items():
            for selected, suffix in [([product],product), (['chat','work','codex'] if provider=='gpt' else ['chat','code','cowork'],'all')]+[([p],p) for p in missing]:
                rows = [e for e in events if e['product'] in selected and a<=parse(e['occurred_at'])<b]
                q = {**scope,'from':fmt(a),'to':fmt(b),'timezone':'Asia/Tokyo'}
                if suffix!='all':
                    q['products']=suffix
                buckets, cursor = [], a
                while cursor<b:
                    end = min(cursor+timedelta(hours=1) if bucket_kind=='hour' else cursor+timedelta(days=1),b)
                    cuts = [cursor,instant,end] if cursor<instant<end else [cursor,end]
                    for lo,hi in zip(cuts,cuts[1:]):
                        future = lo>=instant
                        own = [e for e in rows if lo<=parse(e['occurred_at'])<hi] if not future else []
                        known = [e['total_tokens'] for e in own if e['total_tokens'] is not None]
                        complete = bool(own) and all(e['components_complete'] for e in own)
                        overlap = product in selected and parse(times[0])<hi and parse(times[-1])>lo
                        reasons = ['not_yet_elapsed'] if future else ['synthetic_local_history' if overlap else 'no_records_not_proof_of_zero']
                        if not future and any(p in selected for p in missing):
                            reasons.append('selected_products_not_configured')
                        buckets.append({'from':fmt(lo),'to':fmt(hi),'is_partial_bucket':lo!=cursor or hi!=end,
                            'record_state':'future' if future else 'observed' if own else 'no_records',
                            'coverage_status':'partial' if own else 'unknown','coverage_reasons':reasons,
                            'source_ids':[] if future else sorted(s['id'] for s in [source]+disconnected if s['product'] in selected),
                            'event_count':len(own),'known_total_count':len(known),'unknown_total_count':len(own)-len(known),
                            'total_tokens':sum(known) if known else None,
                            'total_status':('known' if len(known)==len(own) else 'partial') if known else 'unknown',
                            'components_complete':complete,'components':{k:sum(e['components'][k] for e in own) for k in component_names} if complete else dict.fromkeys(component_names)})
                    cursor=end
                prefix = scenario+'/'+view+'/'+suffix+'-'
                data = {**scope,'products':selected,'from':fmt(a),'to':fmt(b),'bucket':bucket_kind,'buckets':buckets}
                fixture(prefix+'usage-series.json','SeriesResponse',envelope(data,scenario),'/usage-series',{**q,'bucket':bucket_kind})
                fixture(prefix+'usage-events.json','EventsResponse',envelope(rows,scenario,True),'/usage-events',q)
                fixture(prefix+'sessions.json','SessionsResponse',envelope(sessions(rows,a,b),scenario,True),'/sessions',q)
                fixture(prefix+'labels.json','LabelsResponse',envelope(selected_labels(rows,a,b,selected),scenario,True),'/labels',q)
            if pid:
                q = {**scope,'pool_id':pid,'from':fmt(a),'to':fmt(b),'timezone':'Asia/Tokyo'}
                chosen = [s for s in snapshots if a<=parse(s['effective_at'])<b]
                summaries=[]
                for wid in sorted({s['window_id'] for s in chosen}):
                    own=sorted((s for s in chosen if s['window_id']==wid),key=lambda s:s['effective_at'])
                    summaries.append({'window_id':wid,'pool_id':pid,'scope_from':fmt(a),'scope_to':fmt(b),
                        'max_observed_percent':max(s['used_percent'] for s in own),'sample_count':len(own),
                        'known_value_count':len(own),'first_sample_at':own[0]['effective_at'],'last_sample_at':own[-1]['effective_at'],
                        'label':'highest_observed_in_selected_range'})
                matching=[w for w in windows if parse(w['starts_at'])<b and parse(w['ends_at'])>a]
                fixture(scenario+'/'+view+'/quota-windows.json','WindowsResponse',envelope(matching,scenario,True),'/quota-windows',q)
                fixture(scenario+'/'+view+'/quota-snapshots.json','SnapshotsResponse',envelope(sorted(chosen,key=lambda s:(s['effective_at'],s['id'])),scenario,True),'/quota-snapshots',q)
                fixture(scenario+'/'+view+'/quota-window-summaries.json','WindowSummariesResponse',envelope(summaries,scenario,True),'/quota-window-summaries',q)
        contexts[scenario]={'initial_view':'day',**scope,'products':[product],'pool_id':pid,'window_id':None,
                            'from':fmt(today),'to':fmt(today+timedelta(days=1)),'bucket':'hour','timezone':'Asia/Tokyo',
                            'history_views':{v:{'from':fmt(a),'to':fmt(b),'bucket':kind} for v,(a,b,kind) in periods.items() if v!='selection'},
                            'example_selection':{'from':fmt(periods['selection'][0]),'to':fmt(periods['selection'][1])}}
    return contexts
