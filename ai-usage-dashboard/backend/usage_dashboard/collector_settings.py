"""App-managed automatic collection settings (the 数据来源 page).

The settings file lives next to the database in the private application data directory, so
it survives re-extracting or updating the program. It is the only place that holds source
paths; SQLite, the HTTP API and logs only see display forms (``~/...``) and keyed hashes.
Nothing is read from a source until the user has enabled it and confirmed its scope.
"""
import json
import os
from pathlib import Path
import secrets
import threading
import time
import uuid

from .auto_collect import AutoCollector, CollectorConfig, SourceConfig, capture_boundary, clear_boundary, file_keyer
from .collect import CollectionError, ensure_source
from .common import APIError, ident, iso, now_ms
from .store import bump_revision, connect, transaction

SETTINGS_FILE = 'collector-settings.json'
INTERVAL_SECONDS = 60
PROVIDERS = ('gpt', 'claude')
PRODUCT = {'gpt': 'codex', 'claude': 'code'}
STANDARD = {'gpt': ('.codex', 'sessions'), 'claude': ('.claude', 'projects')}
HISTORY = ('from_enable', 'import_history')
ENTRY_KEYS = {'enabled', 'location', 'path', 'history', 'boundary_id', 'enabled_ms'}


class SettingsError(ValueError):
    pass


def standard_root(provider, home=None):
    return Path(home or Path.home()).joinpath(*STANDARD[provider])


def display_path(path, home=None):
    """Home-relative form for the page; never the absolute user directory."""
    home = Path(home or Path.home())
    path = Path(path)
    try:
        rel = path.relative_to(home)
    except ValueError:
        return str(path)
    return '~' if not rel.parts else '~/' + rel.as_posix()


def _resolved(path):
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


def too_broad(path, home, data_dir):
    """A source must be a specific log directory: not a volume/top-level folder, not the
    home directory or any of its ancestors, and not containing or inside the app data."""
    path, home, data = Path(path), _resolved(home), _resolved(data_dir)
    if len(path.parts) <= 2:
        return True
    return home.is_relative_to(path) or data.is_relative_to(path) or path.is_relative_to(data)


def default_entry(provider):
    return {'enabled': False, 'location': 'standard', 'path': None, 'history': 'from_enable', 'boundary_id': None, 'enabled_ms': None}


def load_settings(folder, home=None):
    """Return (settings or None when never set up, error code or None). Never guesses."""
    path = Path(folder) / SETTINGS_FILE
    if not path.exists() and not path.is_symlink():
        return None, None
    try:
        if path.is_symlink() or not path.is_file():
            raise SettingsError()
        with path.open('rb') as f:
            raw = f.read(65537)
        if len(raw) > 65536:
            raise SettingsError()

        def unique(pairs):
            obj = dict(pairs)
            if len(obj) != len(pairs):
                raise SettingsError()
            return obj

        def invalid(value):
            raise SettingsError()
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=invalid)
        if not isinstance(data, dict) or set(data) != {'version', 'interval_seconds', 'file_key_secret', 'sources'}:
            raise SettingsError()
        if type(data['version']) is not int or data['version'] != 1:
            raise SettingsError()
        if type(data['interval_seconds']) is not int or not 30 <= data['interval_seconds'] <= 3600:
            raise SettingsError()
        secret = data['file_key_secret']
        if not isinstance(secret, str) or len(secret) != 64 or set(secret) - set('0123456789abcdef'):
            raise SettingsError()
        if not isinstance(data['sources'], dict) or set(data['sources']) - set(PROVIDERS):
            raise SettingsError()
        sources = {}
        for provider in PROVIDERS:
            entry = data['sources'].get(provider, default_entry(provider))
            if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
                raise SettingsError()
            if type(entry['enabled']) is not bool or entry['location'] not in ('standard', 'custom') or entry['history'] not in HISTORY:
                raise SettingsError()
            if entry['location'] == 'custom':
                if not isinstance(entry['path'], str) or not entry['path'] or '\0' in entry['path'] or not Path(entry['path']).is_absolute():
                    raise SettingsError()
                if too_broad(Path(entry['path']), home or Path.home(), folder):
                    raise SettingsError()
            elif entry['path'] is not None:
                raise SettingsError()
            boundary = entry['boundary_id']
            if boundary is not None and (not isinstance(boundary, str) or not 1 <= len(boundary) <= 80):
                raise SettingsError()
            if entry['enabled'] and entry['history'] == 'from_enable' and boundary is None:
                raise SettingsError()
            if entry['enabled_ms'] is not None and type(entry['enabled_ms']) is not int:
                raise SettingsError()
            sources[provider] = dict(entry)
        return {'version': 1, 'interval_seconds': data['interval_seconds'], 'file_key_secret': secret, 'sources': sources}, None
    except (SettingsError, ValueError, TypeError, UnicodeError, OSError, RecursionError):
        return None, 'invalid_settings_file'


def save_settings(folder, settings):
    """Atomic private write: a crash leaves either the old or the new complete file."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / SETTINGS_FILE
    temp = folder / ('.' + SETTINGS_FILE + '.' + uuid.uuid4().hex + '.tmp')
    data = (json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(temp), str(target))
    except BaseException:
        try:
            temp.unlink()
        except OSError:
            pass
        raise
    if os.name != 'nt':
        try:
            dir_fd = os.open(str(folder), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass


def entry_root(provider, entry, home=None):
    return Path(entry['path']) if entry['location'] == 'custom' else standard_root(provider, home)


def _invalid(field, reason):
    # Reasons are short codes for the page to translate; never echo paths or input.
    error = APIError(422, 'invalid_body', 'Collector settings rejected')
    error.details = [{'field': field, 'reason': reason}]
    return error


class CollectorService:
    """Owns the running collector and applies settings changes without a restart."""

    def __init__(self, db_path, folder, startup_config=None, disabled=False, factory=AutoCollector,
                 clock=now_ms, monotonic=time.monotonic, home=None):
        self.db_path, self.folder, self.factory = Path(db_path), Path(folder), factory
        self.clock, self.monotonic, self.home = clock, monotonic, Path(home) if home else None
        self.startup_config = startup_config
        self.mode = 'startup_config' if startup_config is not None else 'disabled' if disabled else 'settings'
        self.lock = threading.Lock()
        self.collector = None
        self.settings, self.settings_error = (None, None)
        if self.mode == 'settings':
            self.settings, self.settings_error = load_settings(self.folder, self.home)

    # -- lifecycle -------------------------------------------------------
    def config(self):
        if self.mode == 'startup_config':
            return self.startup_config
        if self.mode != 'settings' or self.settings is None:
            return None
        sources = []
        for provider in PROVIDERS:
            entry = self.settings['sources'][provider]
            if entry['enabled']:
                sources.append(SourceConfig(provider, entry_root(provider, entry, self.home), 'local',
                    entry['boundary_id'] if entry['history'] == 'from_enable' else None))
        return CollectorConfig(self.settings['interval_seconds'], tuple(sources), bytes.fromhex(self.settings['file_key_secret']))

    def enabled_count(self):
        config = self.config()
        return len(config.sources) if config else 0

    def start(self):
        with self.lock:
            self._start()

    def _start(self):
        config = self.config()
        if config is not None and config.sources:
            collector = self.factory(self.db_path, config, clock=self.clock, monotonic=self.monotonic)
            collector.start()
            self.collector = collector

    def _stop(self):
        if self.collector is not None:
            collector, self.collector = self.collector, None
            collector.stop()

    def stop(self):
        with self.lock:
            self._stop()

    # -- HTTP ------------------------------------------------------------
    def status(self):
        with self.lock:
            return self._status()

    def _status(self):
        running = self.collector is not None and getattr(self.collector, 'thread', None) is not None and self.collector.thread.is_alive()
        sources = []
        with connect(self.db_path) as db:
            for provider in PROVIDERS:
                if self.mode == 'startup_config':
                    match = [s for s in self.startup_config.sources if s.provider == provider]
                    entry = {'enabled': bool(match), 'location': 'startup_config', 'history': 'import_history', 'enabled_ms': None}
                    root, namespace = (match[0].path, match[0].namespace) if match else (None, 'local')
                else:
                    entry = (self.settings or {}).get('sources', {}).get(provider) or default_entry(provider)
                    root, namespace = entry_root(provider, entry, self.home), 'local'
                row = db.execute("SELECT * FROM sources WHERE provider=? AND product=? AND kind='local_log' AND account_id=?",
                                 (provider, PRODUCT[provider], ident('acct', provider, namespace))).fetchone()
                boundary = db.execute('SELECT status FROM collector_boundaries WHERE source_id=?', (row['id'],)).fetchone() if row else None
                if entry['history'] != 'from_enable' or not entry['enabled']:
                    boundary_status = 'not_applicable'
                elif boundary is None:
                    boundary_status = 'missing'
                else:
                    boundary_status = boundary['status']
                item = {
                    'provider': provider, 'product': PRODUCT[provider], 'enabled': entry['enabled'],
                    'location': entry['location'], 'display_path': display_path(root, self.home) if root else None,
                    'standard_display_path': display_path(standard_root(provider, self.home), self.home),
                    'history': entry['history'], 'enabled_at': iso(entry.get('enabled_ms')),
                    'boundary_status': boundary_status, 'source_id': row['id'] if row else None,
                }
                for key in ('connection_status', 'error_code', 'consecutive_failure_count', 'retry_mode'):
                    item[key] = row[key] if row else None
                for out, col in (('last_attempt_at', 'last_attempt_ms'), ('last_success_at', 'last_success_ms'),
                                 ('last_record_at', 'last_record_ms'), ('next_attempt_at', 'next_attempt_ms')):
                    item[out] = iso(row[col]) if row else None
                sources.append(item)
        return {'mode': self.mode, 'configured': self.settings is not None, 'settings_error': self.settings_error,
                'interval_seconds': self.settings['interval_seconds'] if self.settings else INTERVAL_SECONDS,
                'running': running, 'sources': sources}

    def update(self, payload):
        if self.mode == 'startup_config':
            raise _invalid('mode', 'locked_by_startup_config')
        if self.mode != 'settings':
            raise _invalid('mode', 'collection_disabled_for_this_run')
        if not isinstance(payload, dict) or not isinstance(payload.get('provider'), str) or payload['provider'] not in PROVIDERS:
            raise _invalid('provider', 'invalid')
        provider = payload['provider']
        if type(payload.get('enabled')) is not bool:
            raise _invalid('enabled', 'invalid')
        allowed = {'provider', 'enabled'} | ({'location', 'custom_path', 'history', 'confirm_scope'} if payload['enabled'] else set())
        if set(payload) - allowed:
            raise _invalid('body', 'unknown_field')
        with self.lock:
            settings = self.settings or {'version': 1, 'interval_seconds': INTERVAL_SECONDS,
                                         'file_key_secret': secrets.token_hex(32),
                                         'sources': {p: default_entry(p) for p in PROVIDERS}}
            current = settings['sources'][provider]
            entry = dict(current)
            if not payload['enabled']:
                entry['enabled'] = False
                self._apply(settings, provider, entry, None)
                return self._status()
            location = payload.get('location')
            if location not in ('standard', 'custom'):
                raise _invalid('location', 'invalid')
            history = payload.get('history')
            if history not in HISTORY:
                raise _invalid('history', 'invalid')
            home = self.home or Path.home()
            if location == 'custom':
                root = self._custom_root(payload.get('custom_path'), home)
            else:
                if 'custom_path' in payload:
                    raise _invalid('custom_path', 'not_allowed')
                root = standard_root(provider, home)
                if root.is_symlink():
                    raise _invalid('location', 'path_symlink')
                if root.exists() and not root.is_dir():
                    raise _invalid('location', 'path_not_directory')
            # The page must echo back exactly the scope it showed: the standard folder's display
            # form, or for a custom folder either the text the user entered or its display form.
            shown = {display_path(root, home)}
            if location == 'custom':
                shown.add(payload['custom_path'].strip())
            if not isinstance(payload.get('confirm_scope'), str) or payload['confirm_scope'] not in shown:
                raise _invalid('confirm_scope', 'scope_not_confirmed')
            same_root = current['enabled'] and current['location'] == location and entry_root(provider, current, self.home) == root
            if current['enabled']:
                if same_root and current['history'] == history:
                    return self._status()  # Already enabled exactly like this; keep the boundary.
                if not (same_root and current['history'] == 'from_enable' and history == 'import_history'):
                    raise _invalid('enabled', 'disable_first')
            entry.update({'enabled': True, 'location': location, 'path': str(root) if location == 'custom' else None,
                          'history': history, 'enabled_ms': self.clock(),
                          'boundary_id': 'boundary_' + uuid.uuid4().hex if history == 'from_enable' else None})
            self._apply(settings, provider, entry, root)
            return self._status()

    def _custom_root(self, text, home):
        if not isinstance(text, str) or not text.strip() or len(text) > 1024 or '\0' in text or '\n' in text:
            raise _invalid('custom_path', 'invalid')
        path = Path(text.strip()).expanduser()
        if not path.is_absolute():
            raise _invalid('custom_path', 'not_absolute')
        if path.is_symlink():
            raise _invalid('custom_path', 'path_symlink')
        if not path.is_dir():
            raise _invalid('custom_path', 'path_not_directory')
        try:
            path = path.resolve(strict=True)
        except OSError:
            raise _invalid('custom_path', 'path_unreadable') from None
        if too_broad(path, home, self.folder):
            raise _invalid('custom_path', 'path_too_broad')
        return path

    def _apply(self, settings, provider, entry, root):
        """Stop collection, record the boundary in SQLite, then persist settings, then restart."""
        self._stop()
        try:
            if entry['enabled']:
                keyer = file_keyer(bytes.fromhex(settings['file_key_secret']), provider)
                try:
                    with connect(self.db_path) as db, transaction(db, True):
                        _, source_id = ensure_source(db, provider, 'local')
                        if entry['history'] == 'from_enable':
                            capture_boundary(db, source_id, root, keyer, entry['boundary_id'], entry['enabled_ms'])
                        else:
                            clear_boundary(db, source_id)
                        bump_revision(db)
                except CollectionError:
                    raise _invalid('location' if entry['location'] == 'standard' else 'custom_path', 'path_unreadable') from None
                except OSError:
                    raise _invalid('location' if entry['location'] == 'standard' else 'custom_path', 'path_unreadable') from None
            updated = {**settings, 'sources': {**settings['sources'], provider: entry}}
            if self.settings_error:
                # Keep the unreadable file for inspection instead of silently discarding it.
                broken = self.folder / SETTINGS_FILE
                if broken.exists() and not broken.is_symlink():
                    os.replace(str(broken), str(self.folder / ('collector-settings.invalid-' + str(self.clock()) + '.json')))
            save_settings(self.folder, updated)
            self.settings, self.settings_error = updated, None
        finally:
            self._start()


def describe(service):
    """One line for the terminal; counts only, never paths."""
    if service.mode == 'startup_config':
        return 'Automatic collection: ' + str(service.enabled_count()) + ' source(s) from --collector-config (settings page is read-only).'
    if service.mode == 'disabled':
        return 'Automatic collection disabled for this run (--no-collection).'
    if service.settings_error:
        return '自动采集设置文件无效，本次不采集；请在“数据来源”页重新设置。'
    if service.settings is None:
        return 'Automatic collection not set up yet; enable sources on the 数据来源 page.'
    count = service.enabled_count()
    return ('Automatic collection: ' + str(count) + ' source(s) enabled in app settings, checked every ' +
            str(service.settings['interval_seconds']) + 's.') if count else 'Automatic collection: all sources disabled in app settings.'
