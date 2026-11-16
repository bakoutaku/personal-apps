import os
from pathlib import Path
import sqlite3
from contextlib import contextmanager

from .common import now_ms

SCHEMA = Path(__file__).resolve().parents[1] / 'sql/001_initial.sql'


def initialize(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError('Database path must not be a symbolic link')
    # Restrictive mode before SQLite first opens the file, not after writing data.
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    with connect(path) as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version == 0:
            if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                raise ValueError('Refusing to initialize an unrelated nonempty database')
            db.executescript(SCHEMA.read_text())
        elif version != 1:
            raise ValueError('Unsupported database schema version')
        else:
            # A matching version number alone does not identify our schema.
            # Reject unrelated/older draft databases before changing their contents.
            with sqlite3.connect(':memory:') as expected:
                expected.executescript(SCHEMA.read_text())
                for name, sql in expected.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"):
                    actual = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
                    if actual is None or ' '.join(actual[0].split()) != ' '.join(sql.split()):
                        raise ValueError('Database schema does not match this backend; explicit migration required')
        if os.name != 'nt':
            path.chmod(0o600)
        # Runtime bookkeeping is separate from supplier data and never stores paths/content.
        db.executescript('''
          CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          INSERT OR IGNORE INTO app_state VALUES ('data_revision','0');
          CREATE TABLE IF NOT EXISTS session_accounting_modes (
            session_id TEXT PRIMARY KEY REFERENCES sessions(id),
            mode TEXT NOT NULL CHECK(mode IN ('codex_response','codex_legacy','claude_message'))
          );
          CREATE TABLE IF NOT EXISTS account_source_bindings (
            account_id TEXT PRIMARY KEY REFERENCES accounts(id),
            source_identity_hash TEXT NOT NULL
          );
          -- App-managed automatic collection (collector_settings.py). Files are identified
          -- only by keyed hashes; source paths and contents never enter SQLite.
          CREATE TABLE IF NOT EXISTS collector_boundaries (
            source_id TEXT PRIMARY KEY REFERENCES sources(id),
            boundary_id TEXT NOT NULL,
            boundary_ms INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','ready')),
            ready_ms INTEGER
          );
          CREATE TABLE IF NOT EXISTS collector_boundary_files (
            source_id TEXT NOT NULL REFERENCES sources(id),
            file_key TEXT NOT NULL,
            signature TEXT NOT NULL,
            size INTEGER NOT NULL,
            PRIMARY KEY (source_id, file_key)
          );
          CREATE TABLE IF NOT EXISTS collector_history_exclusions (
            source_id TEXT NOT NULL REFERENCES sources(id),
            key_hash TEXT NOT NULL,
            PRIMARY KEY (source_id, key_hash)
          ) WITHOUT ROWID;
          CREATE TABLE IF NOT EXISTS collector_file_checkpoints (
            source_id TEXT NOT NULL REFERENCES sources(id),
            file_key TEXT NOT NULL,
            signature TEXT NOT NULL,
            PRIMARY KEY (source_id, file_key)
          );
        ''')


@contextmanager
def connect(path):
    db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=10000')
    try:
        yield db
    finally:
        db.close()


@contextmanager
def transaction(db, write=False):
    db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise


def insert(db, table, values, ignore=False):
    # Identifiers are internal constants. Values are always bound parameters.
    db.execute('INSERT ' + ('OR IGNORE ' if ignore else '') + 'INTO ' + table +
               ' (' + ','.join(values) + ') VALUES (' + ','.join('?' for _ in values) + ')', list(values.values()))


def revision(db):
    return int(db.execute("SELECT value FROM app_state WHERE key='data_revision'").fetchone()[0])


def bump_revision(db):
    db.execute("UPDATE app_state SET value=CAST(value AS INTEGER)+1 WHERE key='data_revision'")


def upsert_event(db, event, mode):
    current_mode = db.execute('SELECT mode FROM session_accounting_modes WHERE session_id=?', (event['session_id'],)).fetchone()
    if current_mode and current_mode[0] == 'codex_response' and mode == 'codex_legacy':
        return False
    if current_mode and current_mode[0] == 'codex_legacy' and mode == 'codex_response':
        # Replace the legacy estimate for this session, never add both streams.
        db.execute('DELETE FROM usage_events WHERE session_id=?', (event['session_id'],))
        db.execute('UPDATE session_accounting_modes SET mode=? WHERE session_id=?', (mode,event['session_id']))
    insert(db, 'session_accounting_modes', {'session_id': event['session_id'], 'mode': mode}, True)
    old = db.execute('SELECT * FROM usage_events WHERE source_id=? AND external_event_key=?',
                     (event['source_id'], event['external_event_key'])).fetchone()
    if old is None:
        insert(db, 'usage_events', event)
        return True
    db.execute('UPDATE usage_events SET recorded_ms=MAX(COALESCE(recorded_ms,occurred_ms),?) WHERE id=?',
               (event['recorded_ms'] if event['recorded_ms'] is not None else event['occurred_ms'],old['id']))
    # Stable provider response IDs can occur in copied/forked files. Do not move
    # the original event to another session or count it a second time.
    fields = ('total_tokens','total_basis','uncached_input_tokens','cache_read_input_tokens',
              'cache_write_input_tokens','output_tokens','reasoning_output_tokens','components_complete')
    if all(old[k] == event[k] for k in fields):
        return False
    if old['total_tokens'] is None and old['source_revision']>1 and all(old[k] is None for k in ('uncached_input_tokens','cache_read_input_tokens','cache_write_input_tokens','output_tokens')):
        return False  # Explicit conflicts remain unknown until a deliberate rebuild.
    if mode in ('claude_message','codex_response') and old['total_tokens'] is not None and event['total_tokens'] is not None:
        components = ('uncached_input_tokens','cache_read_input_tokens','cache_write_input_tokens','output_tokens')
        if all(old[k] is not None and event[k] is not None and old[k]>=event[k] for k in components):
            return False  # A copied earlier streaming fragment cannot undo a later revision.
        if not all(old[k] is not None and event[k] is not None and event[k]>=old[k] for k in components):
            event = dict(event, total_tokens=None, total_basis='unknown', components_complete=False,
                         uncached_input_tokens=None,cache_read_input_tokens=None,cache_write_input_tokens=None,
                         output_tokens=None,reasoning_output_tokens=None)
            insert(db,'source_limitations',{'source_id':event['source_id'],'code':'conflicting_response_usage',
                'description':'同一响应存在不一致用量，合计暂标为未知'},True)
    changes = {k:event[k] for k in fields}
    changes['source_revision'] = old['source_revision']+1
    changes['ingested_ms'] = event['ingested_ms']
    db.execute('UPDATE usage_events SET '+','.join(k+'=?' for k in changes)+' WHERE id=?', list(changes.values())+[old['id']])
    return True
