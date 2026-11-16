"""Versioned, whitelist-only JSONL readers. No credentials, prompts or tool text retained."""
from collections import defaultdict
import json
import math
import os
import stat as stat_types
from pathlib import Path
import sys
import uuid

from .common import COMPONENTS, canonical, ident, iso, now_ms, parse_time, token_int
from .store import bump_revision, connect, insert, transaction, upsert_event

ADAPTER_VERSION = 'local-jsonl-v1'
RAW_FIELDS = ('input_tokens','cached_input_tokens','cache_write_input_tokens','output_tokens','reasoning_output_tokens','total_tokens')


class CollectionCancelled(Exception):
    pass


class CollectionError(ValueError):
    # waiting: the source simply has nothing to read yet (missing directory, no JSONL).
    # notice: optional user-facing limitation text for terminal states.
    def __init__(self,code,message,terminal=False,waiting=False,notice=None):
        super().__init__(message)
        self.code,self.terminal,self.waiting,self.notice=code,terminal,waiting,notice


def cancellation_point(cancel):
    if cancel is not None and cancel.is_set():
        raise CollectionCancelled()


def source_files(path,cancel=None):
    cancellation_point(cancel)
    path=Path(path).expanduser()
    if path.is_symlink():
        raise CollectionError('source_unreadable','Select a real source directory/file, not a symlink',True)
    try:
        metadata=path.stat()
    except FileNotFoundError:
        raise CollectionError('source_missing','Source path is missing',waiting=True) from None
    if stat_types.S_ISREG(metadata.st_mode):
        if path.suffix.lower()!='.jsonl':
            raise CollectionError('unsupported_format','Select JSONL transcript files only',True)
        return [path]
    if not stat_types.S_ISDIR(metadata.st_mode):
        raise CollectionError('source_unreadable','Source must be a directory or regular file',True)
    files=[]
    def failed(error):
        raise error
    for folder,dirs,names in os.walk(str(path),followlinks=False,onerror=failed):
        cancellation_point(cancel)
        dirs[:]=sorted(d for d in dirs if not (Path(folder)/d).is_symlink())
        for name in sorted(names):
            cancellation_point(cancel)
            file=Path(folder)/name
            if not name.lower().endswith('.jsonl') or file.is_symlink():
                continue
            try:
                metadata=file.stat()
            except FileNotFoundError:
                continue  # Rotation between directory listing and stat is normal.
            if not stat_types.S_ISREG(metadata.st_mode):
                raise CollectionError('source_unreadable','Source entry is not a regular file',True)
            files.append(file)
    if not files:
        raise CollectionError('unsupported_format','No JSONL files found; source cannot be confirmed empty',waiting=True)
    return sorted(files)


def ensure_source(db,provider,namespace):
    if provider not in ('gpt','claude'):
        raise ValueError('provider must be gpt or claude')
    product='codex' if provider=='gpt' else 'code'
    account_id=ident('acct',provider,namespace)
    insert(db,'accounts',{'id':account_id,'provider':provider,'label':'本机来源（账户归属未验证）','identity_status':'local_unverified'},True)
    device=db.execute('SELECT id FROM devices LIMIT 1').fetchone()
    device_id=device[0] if device else 'device_'+uuid.uuid4().hex
    if device is None:
        platform='windows' if sys.platform=='win32' else 'macos' if sys.platform=='darwin' else None
        if platform is None:
            raise ValueError('Supported platforms are macOS and Windows')
        insert(db,'devices',{'id':device_id,'label':'此数据库所在设备','platform':platform})
    source_id=ident('src',account_id,device_id,product)
    insert(db,'sources',{'id':source_id,'account_id':account_id,'provider':provider,'product':product,'device_id':device_id,
           'kind':'local_log','connection_status':'not_configured','adapter_version':ADAPTER_VERSION},True)
    for other in ('chat','work') if provider=='gpt' else ('chat','cowork'):
        insert(db,'sources',{'id':ident('src',account_id,other),'account_id':account_id,'provider':provider,
               'product':other,'kind':'official_client','connection_status':'not_configured'},True)
    return account_id,source_id


def retry_at(at,interval,failures):
    delay=min(max(interval,900),interval*2**min(max(0,failures-1),10)) if failures else interval
    return at+delay*1000


def normalized(usage, product, basis='reported'):
    u = {k:token_int(v) for k,v in usage.items() if isinstance(k,str)}
    if product == 'code':
        c = dict(zip(COMPONENTS, [u.get('input_tokens'),u.get('cache_read_input_tokens'),
                                  u.get('cache_creation_input_tokens'),u.get('output_tokens')]))
        total = sum(c.values()) if all(v is not None for v in c.values()) else None
        if total is not None and token_int(total) is None:
            total = None
        reasoning = None
    else:
        total = u.get('total_tokens')
        input_, cached, write, output = [u.get(k) for k in RAW_FIELDS[:4]]
        # Cache-write inclusion has not been established for nonzero values.
        safe = all(v is not None for v in (input_,cached,write,output,total)) and write == 0 and cached<=input_ and total==input_+output
        c = dict(zip(COMPONENTS,[input_-cached if safe else None,cached,write,output]))
        reasoning = u.get('reasoning_output_tokens')
        if reasoning is not None and output is not None and reasoning>output:
            reasoning = None
    complete = total is not None and all(v is not None for v in c.values()) and sum(c.values())==total
    return {**c,'total_tokens':total,'total_basis':basis if total is not None else 'unknown',
            'components_complete':complete,'reasoning_output_tokens':reasoning}


def read_records(path, warnings, cancel=None, limit=None):
    # Bound a single record; transcripts may contain huge attachments, but the
    # collector must not allocate unbounded lines. Unterminated tails are retried.
    # limit: read only the first N bytes (content present at a history boundary);
    # a record crossing the limit counts as not yet written.
    remaining = limit
    def readline():
        nonlocal remaining
        size = 4*1024*1024+1 if remaining is None else min(4*1024*1024+1,remaining)
        if size<=0:
            return b''
        line = f.readline(size)
        if remaining is not None:
            remaining -= len(line)
        return line
    with Path(path).open('rb') as f:
        while True:
            cancellation_point(cancel)
            line = readline()
            if not line:
                return
            if len(line)>4*1024*1024:
                warnings.add('oversized_line')
                while line and not line.endswith(b'\n'):
                    cancellation_point(cancel)
                    line = readline()
                continue
            if not line.endswith(b'\n'):
                warnings.add('incomplete_tail')
                return
            try:
                row = json.loads(line)
                if isinstance(row,dict):
                    yield row
                else:
                    warnings.add('invalid_record')
            except (ValueError,UnicodeError):
                warnings.add('invalid_json')


def quota_key(recorded, rate):
    # Identity of one raw quota record, used only to exclude pre-boundary history.
    raw = json.dumps([recorded,rate],sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str)
    return ident('quota',raw)


def parse_file(path, product, cancel=None, limit=None):
    warnings, usage_rows, quotas = set(), [], []
    metadata, structured, legacy, claude = {}, [], [], defaultdict(list)
    recognized = False
    for r in read_records(path,warnings,cancel,limit):
        kind = r.get('type')
        p = r.get('payload')
        p = p if isinstance(p,dict) else {}
        if kind == 'session_meta':
            metadata = {k:p.get(k) for k in ('id','session_id','forked_from_id','parent_thread_id','cli_version','creator_account_id')}
            recognized = isinstance(metadata.get('id') or metadata.get('session_id'),str)
        if product=='code' and kind in ('user','assistant') and isinstance(r.get('sessionId'),str) and isinstance(r.get('message'),dict):
            recognized = True
        try:
            at = parse_time(r.get('timestamp'))
        except (TypeError,ValueError,OverflowError):
            if kind in ('assistant','token_usage_record') or p.get('type')=='token_count':
                warnings.add('missing_or_invalid_time')
            continue
        if product == 'codex':
            if kind=='token_usage_record' and isinstance(p.get('usage'),dict):
                recognized = True
                sid = p.get('thread_id') or metadata.get('id') or metadata.get('session_id')
                rid = p.get('response_id')
                if isinstance(sid,str) and isinstance(rid,str) and sid and rid:
                    structured.append((sid,'response:'+rid,at,normalized(p['usage'],product)))
                else:
                    warnings.add('missing_response_identity')
            elif kind=='event_msg' and p.get('type')=='token_count':
                info = p.get('info') or {}
                if isinstance(info,dict) and isinstance(info.get('total_token_usage'),dict):
                    legacy.append((at,info))
                rate = p.get('rate_limits')
                if isinstance(rate,dict):
                    quotas.append((at,rate))
        elif kind=='assistant':
            m = r.get('message')
            if not isinstance(m,dict) or not isinstance(m.get('usage'),dict):
                continue
            sid, mid, req = r.get('sessionId'),m.get('id'),r.get('requestId')
            if not isinstance(sid,str) or not sid or not isinstance(mid,str) or not mid:
                warnings.add('missing_message_identity')
                continue
            # Message IDs are provider-generated and stable across transcript copies.
            key = 'message:'+canonical([req if isinstance(req,str) else None,mid])
            claude[key].append((sid,key,at,normalized(m['usage'],product)))
    if product=='code':
        for variants in claude.values():
            cancellation_point(cancel)
            # Pick an ACTUALLY REPORTED vector dominating all revisions. Never
            # manufacture a per-field maximum that did not exist in the source.
            valid = [x for x in variants if x[3]['components_complete']]
            candidates = [x for x in valid if all(all(y[3][k] is None or x[3][k]>=y[3][k] for k in COMPONENTS) for y in variants)]
            if candidates:
                chosen = max(candidates,key=lambda x:(x[3]['total_tokens'],x[2]))
            elif valid:
                warnings.add('conflicting_message_usage')
                chosen = variants[0][:3]+({'total_tokens':None,'total_basis':'unknown','components_complete':False,
                        **dict.fromkeys(COMPONENTS),'reasoning_output_tokens':None},)
            else:
                chosen = variants[-1]
            # An event represents the response first observed, not continuous activity.
            usage_rows.append((chosen[0],chosen[1],min(v[2] for v in variants),
                               {**chosen[3],'recorded_ms':max(v[2] for v in variants)}))
        mode = 'claude_message'
    elif structured:
        mode, usage_rows = 'codex_response', structured
        warnings.add('structured_response_records_preferred')
    else:
        mode = 'codex_legacy'
        sid = metadata.get('id') or metadata.get('session_id')
        if not isinstance(sid,str) or not sid:
            if legacy:
                warnings.add('missing_session_identity')
            legacy = []
        if metadata.get('forked_from_id') or metadata.get('parent_thread_id'):
            warnings.add('legacy_fork_not_counted')
            legacy = []
        prev = None
        seen = set()
        for at,info in legacy:
            cancellation_point(cancel)
            total = {k:token_int(info['total_token_usage'].get(k)) for k in RAW_FIELDS}
            fingerprint = canonical(total)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            last = info.get('last_token_usage') or {}
            last = last if isinstance(last,dict) else {}
            if prev is None:
                good = total['total_tokens'] is not None and total['total_tokens']==token_int(last.get('total_tokens'))
                delta, basis = (total if good else {}),'reported'
                if not good:
                    warnings.add('initial_cumulative_baseline_unknown')
            else:
                good = all(total[k] is not None and prev[k] is not None and total[k]>=prev[k] for k in ('total_tokens','input_tokens','output_tokens'))
                delta = {k: total[k]-prev[k] if total[k] is not None and prev[k] is not None and total[k]>=prev[k] else None for k in RAW_FIELDS} if good else {}
                basis = 'derived'
                if not good:
                    warnings.add('cumulative_counter_regressed')
            usage_rows.append((sid,'legacy:'+fingerprint,at,normalized(delta,product,basis)))
            prev = total
    if not recognized:
        warnings.add('unrecognized_log_format')
    raw_account = metadata.get('creator_account_id')
    account_fingerprint = ident('scope',raw_account) if isinstance(raw_account,str) and raw_account else None
    return usage_rows,quotas,mode,warnings,account_fingerprint


def collect(db_path, provider, path, namespace='local', clock=now_ms, *, selected_files=None, automatic_interval=None, cancel=None,
            history=None, on_commit=None):
    # history: optional boundary filter (auto_collect.HistoryBoundary) for "only after enabling".
    # on_commit(db,status,warnings): scheduler checkpoint written in this same transaction.
    if provider not in ('gpt','claude'):
        raise ValueError('provider must be gpt or claude')
    product = 'codex' if provider=='gpt' else 'code'
    path = Path(path).expanduser()
    if selected_files is None:
        files=source_files(path,cancel)
    else:
        # Only the local scheduler can supply this internal changed-file list.
        if path.is_symlink():
            raise CollectionError('source_unreadable','Source became a symlink',True)
        if not path.exists():
            raise CollectionError('source_missing','Source path is missing')
        files=list(selected_files)
        root=path.resolve()
        if not files or any(f.is_symlink() or not (f.resolve()==root or f.resolve().is_relative_to(root)) for f in files):
            raise CollectionError('source_unreadable','Changed files must remain inside the configured source',True)
    account_id = ident('acct',provider,namespace)
    at, changed, warnings = clock(),0,set()
    with connect(db_path) as db, transaction(db,True):
        account_id,source_id=ensure_source(db,provider,namespace)
        run_id = 'run_'+uuid.uuid4().hex
        insert(db,'collection_runs',{'id':run_id,'source_id':source_id,'started_ms':at,'status':'running'})
        count, latest, recognized_files, excluded = 0,None,0,0
        for file in files:
            cancellation_point(cancel)
            try:
                records,quotas,mode,issues,fingerprint = parse_file(file,product,cancel)
                new_file = history.new_file(db,file) if history is not None else False
            except OSError:
                warnings.add('source_unreadable')
                continue
            warnings |= issues
            if 'unrecognized_log_format' not in issues:
                recognized_files += 1
            if fingerprint:
                binding = db.execute('SELECT source_identity_hash FROM account_source_bindings WHERE account_id=?',(account_id,)).fetchone()
                if binding and binding[0]!=fingerprint:
                    raise CollectionError('unknown_error','Source account differs; import into a separate account namespace',True)
                insert(db,'account_source_bindings',{'account_id':account_id,'source_identity_hash':fingerprint},True)
            for raw_sid,key,occurred,usage in records:
                cancellation_point(cancel)
                if occurred>at+120000:
                    warnings.add('source_time_in_future')
                    continue
                if history is not None and not history.allow(db,ident('external',key),occurred,new_file):
                    excluded += 1
                    continue
                session_id = ident('ses',source_id,raw_sid)
                insert(db,'sessions',{'id':session_id,'source_id':source_id,'account_id':account_id,'provider':provider,
                       'product':product,'external_session_key':ident('external',raw_sid),
                       'started_ms':occurred,'last_record_ms':occurred},True)
                db.execute('UPDATE sessions SET started_ms=MIN(started_ms,?),last_record_ms=MAX(last_record_ms,?) WHERE id=?', (occurred,occurred,session_id))
                event = {'id':ident('evt',source_id,key),'source_id':source_id,'account_id':account_id,'provider':provider,
                         'product':product,'session_id':session_id,'external_event_key':ident('external',key),
                         'occurred_ms':occurred,'recorded_ms':occurred,'ingested_ms':at,**usage}
                changed += upsert_event(db,event,mode)
                count += 1
            for recorded,rate in quotas:
                cancellation_point(cancel)
                if recorded>at+120000:
                    warnings.add('source_time_in_future')
                    continue
                if history is not None and not history.allow(db,quota_key(recorded,rate),recorded,new_file):
                    excluded += 1
                    continue
                changed += ingest_quota(db,source_id,account_id,provider,rate,recorded,at,warnings)
        stored = db.execute('SELECT MAX(t) FROM (SELECT MAX(COALESCE(recorded_ms,occurred_ms)) t FROM usage_events WHERE source_id=? UNION ALL SELECT MAX(effective_ms) t FROM quota_snapshots WHERE source_id=?)',(source_id,source_id)).fetchone()[0]
        previous = db.execute('SELECT last_record_ms FROM sources WHERE id=?',(source_id,)).fetchone()[0]
        latest = max((v for v in (latest,stored,previous) if v is not None), default=None)
        informational = {'structured_response_records_preferred'}
        incomplete = bool(warnings-informational)
        status = 'error' if 'source_unreadable' in warnings else 'available'
        # A scheduler subset may contain only a not-yet-recognizable new file; earlier
        # records still prove the source format. Pre-boundary history may carry warnings
        # without any counted record, which does not make the bounded source unusable.
        no_format = recognized_files==0 and not (selected_files is not None and latest is not None)
        error = 'source_unreadable' if status=='error' else ('unsupported_format' if no_format or (incomplete and latest is None and history is None) else None)
        if error:
            status = 'error'
        history = 'has_records' if latest is not None else ('unknown' if incomplete else 'empty')
        old = db.execute('SELECT consecutive_failure_count FROM sources WHERE id=?',(source_id,)).fetchone()[0]
        failures=(old or 0)+1 if error else 0
        db.execute('UPDATE sources SET connection_status=?,last_attempt_ms=?,last_success_ms=CASE WHEN ? IS NULL THEN ? ELSE last_success_ms END,last_record_ms=?,error_code=?,history_status=?,consecutive_failure_count=?,retry_mode=?,next_attempt_ms=? WHERE id=?',
                   (status,at,error,at,latest,error,history,failures,'automatic' if automatic_interval else 'manual',
                    retry_at(clock(),automatic_interval,failures) if automatic_interval else None,source_id))
        if not error:
            db.execute("DELETE FROM source_limitations WHERE source_id=? AND code='automatic_collection_problem'",(source_id,))
        for capability in ['token_events','session_ids']+(['quota_snapshots'] if provider=='gpt' and db.execute('SELECT 1 FROM quota_snapshots WHERE source_id=? LIMIT 1',(source_id,)).fetchone() else []):
            insert(db,'source_capabilities',{'source_id':source_id,'capability':capability},True)
        descriptions = {
            'oversized_line':'部分记录过大，已跳过，历史可能不完整',
            'incomplete_tail':'末条记录尚未写完，下次导入时重试',
            'invalid_record':'部分记录格式无效，历史可能不完整',
            'invalid_json':'部分记录无法解析，仅显示可验证的内容',
            'missing_or_invalid_time':'部分记录缺少有效时间，未计入时间序列',
            'missing_response_identity':'部分用量缺少响应标识，未计数',
            'missing_message_identity':'部分消息缺少唯一标识，未计数',
            'conflicting_message_usage':'同一消息出现冲突用量，合计暂标为未知',
            'missing_session_identity':'旧记录缺少会话标识，未计数',
            'legacy_fork_not_counted':'旧格式的分叉记录暂不计数，避免重复统计',
            'initial_cumulative_baseline_unknown':'部分旧记录缺少累计基线，不能还原完整消耗',
            'cumulative_counter_regressed':'累计计数出现回退，对应片段的用量标为未知',
            'unrecognized_log_format':'未识别日志格式，不能确认历史为空',
            'source_unreadable':'部分来源无法读取，已保留之前的有效历史',
            'source_time_in_future':'部分来源时间明显超前，暂未纳入统计',
            'quota_bucket_unknown':'部分额度记录缺少额度池标识，未归入已知池'}
        limitations = {'local_device_only':'仅本机日志；不保证捕获全部请求，其他设备未覆盖',
                      **{k:descriptions.get(k,'部分记录存在不确定性，历史可能不完整') for k in warnings-informational}}
        for key,description in limitations.items():
            db.execute('INSERT INTO source_limitations VALUES (?,?,?) ON CONFLICT(source_id,code) DO UPDATE SET description=excluded.description',(source_id,key,description))
        if latest is not None:
            first = db.execute('SELECT MIN(t) FROM (SELECT MIN(occurred_ms) t FROM usage_events WHERE source_id=? UNION ALL SELECT MIN(effective_ms) t FROM quota_snapshots WHERE source_id=?)',(source_id,source_id)).fetchone()[0]
            if first is not None and first<latest:
                db.execute('DELETE FROM coverage_intervals WHERE source_id=?',(source_id,))
                insert(db,'coverage_intervals',{'id':ident('cov',source_id),'source_id':source_id,'from_ms':first,
                       'to_ms':latest+1,'status':'partial','scope':'local_device','reason':'local_device_only',
                       'evidence':'valid_local_log_records; adapter='+ADAPTER_VERSION})
        db.execute('UPDATE collection_runs SET ended_ms=?,status=?,records_seen=?,error_code=? WHERE id=?',
                   (max(at,clock()),'failed' if error else 'succeeded',count,error,run_id))
        if on_commit is not None:
            on_commit(db,source_id,status,warnings)
        bump_revision(db)  # Synchronization state itself is part of a data revision.
    return {'account_id':account_id,'source_id':source_id,'files_scanned':len(files),
            'candidate_records':count,'changed_events_or_snapshots':changed,'excluded_history_records':excluded,'warnings':sorted(warnings),
            'history_status':history,'connection_status':status}


def ingest_quota(db,source_id,account_id,provider,rate,recorded,ingested,warnings):
    bucket = rate.get('limit_id')
    if not isinstance(bucket,str) or not bucket:
        warnings.add('quota_bucket_unknown')
        return 0
    pool_id = ident('pool',account_id,bucket)
    insert(db,'quota_pools',{'id':pool_id,'account_id':account_id,'provider':provider,'label':bucket,
        'provider_bucket_key':bucket,'product_membership_known':1 if bucket=='codex' else 0,
        'product_membership_complete':0,'membership_evidence':'local log limit_id; other product membership unknown'},True)
    insert(db,'quota_pool_sources',{'pool_id':pool_id,'source_id':source_id,'account_id':account_id,'provider':provider},True)
    if bucket=='codex':
        insert(db,'quota_pool_products',{'pool_id':pool_id,'account_id':account_id,'provider':provider,'product':'codex','evidence':'log bucket identifier'},True)
    changed = 0
    for slot in ('primary','secondary'):
        w = rate.get(slot)
        if not isinstance(w,dict):
            continue
        percent,mins,reset = w.get('used_percent'),w.get('window_minutes'),w.get('resets_at')
        percent = percent if type(percent) in (int,float) and math.isfinite(percent) and percent>=0 else None
        duration = mins*60 if type(mins) is int and 0<mins<=525600 else None
        end = reset*1000 if type(reset) is int and 0<reset<253402300800 else None
        start = end-duration*1000 if end is not None and duration is not None else None
        window_key = canonical([slot,end,duration])
        window_id = ident('win',pool_id,window_key)
        insert(db,'quota_windows',{'id':window_id,'pool_id':pool_id,'slot':slot,'external_window_key':window_key,
            'starts_ms':start,'ends_ms':end,'duration_seconds':duration,'start_source':'derived' if start is not None else 'unknown',
            'end_source':'reported' if end is not None else 'unknown','semantics':'unknown'},True)
        key = ident('external',window_id,recorded,percent)
        before = db.total_changes
        insert(db,'quota_snapshots',{'id':ident('snap',source_id,key),'pool_id':pool_id,'window_id':window_id,'source_id':source_id,
            'external_snapshot_key':key,'observed_ms':None,'recorded_ms':recorded,'ingested_ms':ingested,
            'effective_ms':recorded,'time_basis':'recorded_at','used_percent':percent,'value_basis':'reported' if percent is not None else 'unknown'},True)
        changed += db.total_changes-before
    return changed
