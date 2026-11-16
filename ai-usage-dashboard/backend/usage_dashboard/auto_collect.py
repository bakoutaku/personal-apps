"""Opt-in local polling. Paths stay outside SQLite; app-managed sources keep only keyed file hashes there."""
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import stat as stat_types
from pathlib import Path
import sys
import threading
import time
import uuid

from .collect import collect, parse_file, quota_key, source_files, ensure_source, retry_at, CollectionCancelled, CollectionError
from .common import canonical, now_ms, ident
from .store import connect, transaction, bump_revision, insert

# A file that did not exist at the boundary (new chat, rotation, replacement) was
# written after enabling; only copied history inside it can carry much older times.
NEW_FILE_GRACE_MS = 15*60*1000
BOUNDARY_NOTICE = '仅统计启用后新增的记录；启用前已有的本机历史未导入'


@dataclass(frozen=True)
class SourceConfig:
    provider: str
    path: Path
    namespace: str = 'local'
    # App-managed settings only: from_enable sources carry the confirmed boundary id.
    boundary_id: object = None


@dataclass(frozen=True)
class CollectorConfig:
    interval_seconds: int
    sources: tuple
    # App-managed settings only: key for hashing file paths into SQLite checkpoints.
    # None keeps the explicit --collector-config behaviour (in-memory manifest).
    file_secret: object = None


def file_keyer(secret,provider):
    def key(path):
        return hmac.new(secret,(provider+'\0'+str(path)).encode('utf-8','surrogateescape'),hashlib.sha256).hexdigest()[:40]
    return key


def file_signature(stat):
    return (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)


def capture_boundary(db,source_id,root,keyer,boundary_id,at,cancel=None):
    """Record which bytes already exist at the moment the user confirms "only after enabling".

    Only file sizes/identities are stored (keyed hashes, no paths). Content is read later by
    the collector, up to these sizes, to learn which records are history.
    """
    try:
        files=source_files(root,cancel)
    except CollectionError as error:
        if not error.waiting:
            raise
        files=[]
    rows=[]
    for path in files:
        try:
            stat=path.stat()
        except FileNotFoundError:
            continue
        rows.append((source_id,keyer(path),canonical(list(file_signature(stat))),stat.st_size))
    for table in ('collector_boundary_files','collector_history_exclusions','collector_file_checkpoints'):
        db.execute('DELETE FROM '+table+' WHERE source_id=?',(source_id,))
    db.executemany('INSERT INTO collector_boundary_files VALUES (?,?,?,?)',rows)
    db.execute('INSERT INTO collector_boundaries VALUES (?,?,?,?,NULL) ON CONFLICT(source_id) DO UPDATE SET boundary_id=excluded.boundary_id,boundary_ms=excluded.boundary_ms,status=excluded.status,ready_ms=NULL',
               (source_id,boundary_id,at,'pending'))
    return len(rows)


def clear_boundary(db,source_id):
    """Import-history mode: forget any boundary so the next scan reads complete files."""
    for table in ('collector_boundary_files','collector_history_exclusions','collector_file_checkpoints','collector_boundaries'):
        db.execute('DELETE FROM '+table+' WHERE source_id=?',(source_id,))
    db.execute("DELETE FROM source_limitations WHERE source_id=? AND code='history_before_enable_excluded'",(source_id,))


class HistoryBoundary:
    """Counts a record only if it was not already present when collection was enabled.

    Records present up to the boundary size of each file are excluded by their stable
    record identity (not by time), so delayed writes after enabling are still counted
    and streaming revisions of an already-present message are not. Files that did not
    exist at the boundary additionally drop records far older than it (resumed/copied
    history).
    """
    def __init__(self,source_id,boundary_ms,keyer):
        self.source_id,self.boundary_ms,self.keyer=source_id,boundary_ms,keyer

    def new_file(self,db,path):
        row=db.execute('SELECT signature,size FROM collector_boundary_files WHERE source_id=? AND file_key=?',(self.source_id,self.keyer(path))).fetchone()
        if row is None:
            return True
        stat=path.stat()
        return json.loads(row['signature'])[1]!=stat.st_ino or stat.st_size<row['size']

    def allow(self,db,key_hash,at,new_file):
        if db.execute('SELECT 1 FROM collector_history_exclusions WHERE source_id=? AND key_hash=?',(self.source_id,key_hash)).fetchone():
            return False
        return not new_file or at>=self.boundary_ms-NEW_FILE_GRACE_MS


def load_config(path):
    path=Path(path).expanduser()
    if path.is_symlink():
        raise ValueError('自动采集配置不能是符号链接')
    if not path.is_file():
        raise ValueError('自动采集配置必须是可读取的普通 JSON 文件')
    def unique(pairs):
        obj=dict(pairs)
        if len(obj)!=len(pairs):
            raise ValueError()
        return obj
    def invalid(value):
        raise ValueError()
    try:
        with path.open('rb') as f:
            raw=f.read(65537)
        if len(raw)>65536:
            raise ValueError()
        data=json.loads(raw.decode('utf-8'),object_pairs_hook=unique,parse_constant=invalid)
        if not isinstance(data,dict) or set(data)!={'version','interval_seconds','sources'}:
            raise ValueError()
        if type(data['version']) is not int or data['version']!=1:
            raise ValueError()
        interval=data['interval_seconds']
        if type(interval) is not int or not 30<=interval<=3600:
            raise ValueError()
        if not isinstance(data['sources'],list) or len(data['sources'])>8:
            raise ValueError()
        selected,seen=[],set()
        for item in data['sources']:
            if not isinstance(item,dict) or set(item)-{'enabled','provider','path','account_namespace'} or not {'enabled','provider','path'}<=set(item):
                raise ValueError()
            if type(item['enabled']) is not bool or item['provider'] not in ('gpt','claude'):
                raise ValueError()
            ns=item.get('account_namespace','local')
            if not isinstance(ns,str) or not ns.strip() or len(ns)>80 or not isinstance(item['path'],str) or not item['path'] or '\0' in item['path']:
                raise ValueError()
            root=Path(item['path']).expanduser()
            if not root.is_absolute():
                raise ValueError()
            if item['enabled']:
                key=(item['provider'],ns.strip())
                if key in seen:
                    raise ValueError()
                seen.add(key)
                selected.append(SourceConfig(item['provider'],root,ns.strip()))
        return CollectorConfig(interval,tuple(selected))
    except (ValueError,TypeError,UnicodeError,RuntimeError):
        raise ValueError('自动采集配置无效：请检查版本、字段、30–3600 秒间隔及绝对路径/用户主目录路径') from None


@dataclass
class Job:
    config: SourceConfig
    manifest: object = None
    source_id: object = None
    due_ms: object = None
    due_monotonic: float = 0
    paused: bool = False
    history: object = None
    keyer: object = None


class AutoCollector:
    def __init__(self,db_path,config,clock=now_ms,monotonic=time.monotonic):
        self.db_path,self.config,self.clock,self.monotonic=db_path,config,clock,monotonic
        self.jobs=[Job(source,keyer=file_keyer(config.file_secret,source.provider) if config.file_secret is not None else None) for source in config.sources]
        self.cancel=threading.Event()
        self._run_lock=threading.Lock()
        self.thread=None
        self._started=False
        self._stopped=False

    def start(self):
        if self._started or self.cancel.is_set():
            raise ValueError('Automatic collector cannot be started twice')
        self._started=True
        if self.jobs:
            self.thread=threading.Thread(target=self._loop,name='local-usage-collector',daemon=True)
            self.thread.start()

    def _loop(self):
        while not self.cancel.is_set():
            self.run_due()
            self.cancel.wait(1)

    def _set_due(self,job,when):
        job.due_ms=when
        job.due_monotonic=self.monotonic()+max(0,when-self.clock())/1000 if when is not None else float('inf')

    def _snapshot(self,job):
        snapshot={}
        for path in source_files(job.config.path,self.cancel):
            if self.cancel.is_set():
                raise CollectionCancelled()
            if not stat_types.S_ISREG(path.stat().st_mode):
                raise CollectionError('source_unreadable','Source entry is not a regular file',True)
            with path.open('rb') as f:
                stat=os.fstat(f.fileno())
                # Opening checks readability. No raw contents are cached here.
                snapshot[path]=(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
        return snapshot

    def _source_state(self,job):
        with connect(self.db_path) as db:
            if job.source_id is None:
                row=db.execute("SELECT * FROM sources WHERE account_id=? AND product=? AND kind='local_log' ORDER BY id LIMIT 1",
                    (ident('acct',job.config.provider,job.config.namespace),'codex' if job.config.provider=='gpt' else 'code')).fetchone()
                if row:
                    job.source_id=row['id']
                return row
            return db.execute('SELECT * FROM sources WHERE id=?',(job.source_id,)).fetchone()

    def _manifest(self,job,snapshot):
        if job.keyer is None:
            return job.manifest
        if job.source_id is None:
            return {}
        with connect(self.db_path) as db:
            stored={r['file_key']:r['signature'] for r in db.execute('SELECT file_key,signature FROM collector_file_checkpoints WHERE source_id=?',(job.source_id,))}
        return {path:sig for path,sig in snapshot.items() if stored.get(job.keyer(path))==canonical(list(sig))}

    def _checkpoint(self,job,snapshot,selected):
        def write(db,source_id,status,warnings):
            # Same transaction as the imported records: a crash or rollback re-reads the file.
            if status!='available' or 'source_time_in_future' in warnings:
                return
            current={job.keyer(path) for path in snapshot}
            stale=[r[0] for r in db.execute('SELECT file_key FROM collector_file_checkpoints WHERE source_id=?',(source_id,)) if r[0] not in current]
            db.executemany('DELETE FROM collector_file_checkpoints WHERE source_id=? AND file_key=?',[(source_id,k) for k in stale])
            db.executemany('INSERT INTO collector_file_checkpoints VALUES (?,?,?) ON CONFLICT(source_id,file_key) DO UPDATE SET signature=excluded.signature',
                [(source_id,job.keyer(path),canonical(list(snapshot[path]))) for path in selected])
        return write

    def _prepare_boundary(self,job):
        """Resolve a from_enable boundary; on first use learn which records were history."""
        missing=CollectionError('unknown_error','History boundary missing',True,
            notice='“仅从启用后开始”的历史边界记录缺失，为避免补入旧历史已停止采集；请在数据来源页停用后重新启用')
        state=self._source_state(job)
        if state is None:
            raise missing
        with connect(self.db_path) as db:
            row=db.execute('SELECT * FROM collector_boundaries WHERE source_id=?',(job.source_id,)).fetchone()
            if row is None or row['boundary_id']!=job.config.boundary_id:
                raise missing
            if row['status']=='ready':
                job.history=HistoryBoundary(job.source_id,row['boundary_ms'],job.keyer)
                return
            sizes={r['file_key']:(r['size'],r['signature']) for r in db.execute('SELECT file_key,size,signature FROM collector_boundary_files WHERE source_id=?',(job.source_id,))}
        product='codex' if job.config.provider=='gpt' else 'code'
        keys,seeds=set(),[]
        try:
            files=source_files(job.config.path,self.cancel) if sizes else []
        except CollectionError as error:
            if not error.waiting:
                raise
            files=[]
        for path in files:
            entry=sizes.get(job.keyer(path))
            if entry is None:
                continue
            size,signature=entry
            if json.loads(signature)[1]!=path.stat().st_ino:
                continue  # Replaced since the boundary; treated as a new file instead.
            records,quotas,_,_,_=parse_file(path,product,self.cancel,limit=size)
            keys.update(ident('external',key) for _,key,_,_ in records)
            keys.update(quota_key(recorded,rate) for recorded,rate in quotas)
            seeds.append((job.source_id,job.keyer(path),signature))
        with connect(self.db_path) as db,transaction(db,True):
            current=db.execute('SELECT boundary_id,boundary_ms FROM collector_boundaries WHERE source_id=?',(job.source_id,)).fetchone()
            if current is None or current['boundary_id']!=job.config.boundary_id:
                raise missing
            db.execute('DELETE FROM collector_history_exclusions WHERE source_id=?',(job.source_id,))
            db.executemany('INSERT OR IGNORE INTO collector_history_exclusions VALUES (?,?)',[(job.source_id,k) for k in keys])
            # Bytes up to the boundary are accounted for; unchanged files need no re-read.
            db.execute('DELETE FROM collector_file_checkpoints WHERE source_id=?',(job.source_id,))
            db.executemany('INSERT INTO collector_file_checkpoints VALUES (?,?,?)',seeds)
            db.execute("UPDATE collector_boundaries SET status='ready',ready_ms=? WHERE source_id=?",(self.clock(),job.source_id))
            db.execute('INSERT INTO source_limitations VALUES (?,?,?) ON CONFLICT(source_id,code) DO UPDATE SET description=excluded.description',
                (job.source_id,'history_before_enable_excluded',BOUNDARY_NOTICE))
            bump_revision(db)
        job.history=HistoryBoundary(job.source_id,current['boundary_ms'],job.keyer)

    def _unchanged(self,job):
        at=self.clock()
        when=retry_at(at,self.config.interval_seconds,0)
        with connect(self.db_path) as db,transaction(db,True):
            db.execute("UPDATE sources SET last_attempt_ms=?,last_success_ms=?,consecutive_failure_count=0,retry_mode='automatic',next_attempt_ms=? WHERE id=?",(at,at,when,job.source_id))
            bump_revision(db)
        self._set_due(job,when)

    def _failure(self,job,error):
        terminal=isinstance(error,CollectionError) and error.terminal
        code=error.code if isinstance(error,CollectionError) else 'permission_denied' if isinstance(error,PermissionError) else 'source_missing' if isinstance(error,FileNotFoundError) else 'source_unreadable' if isinstance(error,OSError) else 'collector_internal_error'
        at=self.clock()
        with connect(self.db_path) as db,transaction(db,True):
            _,sid=ensure_source(db,job.config.provider,job.config.namespace)
            job.source_id=sid
            row=db.execute('SELECT * FROM sources WHERE id=?',(sid,)).fetchone()
            failures=(row['consecutive_failure_count'] or 0)+1
            # App-managed sources keep checking every interval while there is simply nothing
            # to read yet (e.g. Claude Code not used on this Mac so far).
            waiting=job.keyer is not None and getattr(error,'waiting',False)
            when=None if terminal else retry_at(at,self.config.interval_seconds,0 if waiting else failures)
            db.execute('UPDATE sources SET connection_status=\'error\',last_attempt_ms=?,error_code=?,history_status=?,consecutive_failure_count=?,retry_mode=?,next_attempt_ms=? WHERE id=?',
                (at,code,'has_records' if row['last_record_ms'] is not None else 'unknown',failures,'disabled' if terminal else 'automatic',when,sid))
            text='自动采集遇到读取或格式问题，已保留之前的记录；将按计划重试'
            if terminal:
                text='此来源自动采集已停止，请检查来源和配置后重启服务'
                if code=='unknown_error':
                    text='来源账户归属发生变化，自动采集已停止；请为新账户另设命名空间'
                if getattr(error,'notice',None):
                    text=error.notice
            db.execute('INSERT INTO source_limitations VALUES (?,?,?) ON CONFLICT(source_id,code) DO UPDATE SET description=excluded.description',
                (sid,'automatic_collection_problem',text))
            insert(db,'collection_runs',{'id':'run_auto_'+uuid.uuid4().hex,'source_id':sid,'started_ms':at,
                'ended_ms':at,'status':'failed','records_seen':0,'error_code':code})
            bump_revision(db)
        job.manifest=None
        job.paused=terminal
        self._set_due(job,when)

    def run_due(self):
        results=[]
        with self._run_lock:
            for job in self.jobs:
                if self.cancel.is_set():
                    break
                if job.paused or (job.due_ms is not None and self.clock()<job.due_ms and self.monotonic()<job.due_monotonic):
                    continue
                try:
                    if job.config.boundary_id is not None and job.history is None:
                        self._prepare_boundary(job)
                    snapshot=self._snapshot(job)
                    state=self._source_state(job)
                    manifest=self._manifest(job,snapshot)
                    changed=[p for p,signature in snapshot.items() if manifest is None or manifest.get(p)!=signature]
                    if not changed and state is not None and state['connection_status']=='available':
                        self._unchanged(job)
                        job.manifest=snapshot
                        results.append({'result':'unchanged','files_processed':0})
                        continue
                    selected=changed or list(snapshot)
                    report=collect(self.db_path,job.config.provider,job.config.path,job.config.namespace,clock=self.clock,
                        selected_files=selected,automatic_interval=self.config.interval_seconds,cancel=self.cancel,
                        history=job.history,on_commit=self._checkpoint(job,snapshot,selected) if job.keyer is not None else None)
                    job.source_id=report['source_id']
                    # Future timestamps may become eligible even without a file change.
                    job.manifest=snapshot if report['connection_status']=='available' and 'source_time_in_future' not in report['warnings'] else None
                    state=self._source_state(job)
                    self._set_due(job,state['next_attempt_ms'])
                    results.append({'result':report['connection_status'],'files_processed':report['files_scanned']})
                except CollectionCancelled:
                    break
                except Exception as error:
                    try:
                        self._failure(job,error)
                    except Exception:
                        self._set_due(job,self.clock()+self.config.interval_seconds*1000)
                        print('自动采集无法更新本机数据库，将稍后重试。',file=sys.stderr)
                    results.append({'result':'error','files_processed':0})
        return results

    def stop(self):
        if self._stopped:
            return
        self.cancel.set()
        if self.thread is not None:
            self.thread.join()
        with self._run_lock:
            for job in self.jobs:
                self._source_state(job)
            ids=[job.source_id for job in self.jobs if job.source_id is not None]
            if ids:
                with connect(self.db_path) as db,transaction(db,True):
                    changed=0
                    for sid in ids:
                        changed+=db.execute("UPDATE sources SET retry_mode='manual',next_attempt_ms=NULL WHERE id=? AND retry_mode='automatic'",(sid,)).rowcount
                    if changed:
                        bump_revision(db)
            self._stopped=True
