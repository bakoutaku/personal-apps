"""Real-time check of app-managed collection: real CLI process, real 60 s schedule, restart and
disable. Synthetic logs in a temporary HOME, temporary data directory and a free port; the
user's real logs, settings, database and services are never touched. Takes about 5 minutes."""
import http.client
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / 'tests'))
from test_backend import raw_usage, claude_row  # noqa: E402

LOG = []


def note(text):
    LOG.append(text)
    print(text, flush=True)


def line(row):
    return json.dumps(row, separators=(',', ':')) + '\n'


def response(rid, stamp, thread):
    return {'type': 'token_usage_record', 'timestamp': stamp,
            'payload': {'thread_id': thread, 'response_id': rid, 'usage': raw_usage()}}


def meta(thread):
    return {'type': 'session_meta', 'timestamp': '2026-10-01T00:00:00.000Z', 'payload': {'id': thread, 'base_instructions': 'DO_NOT_STORE_PRIVATE'}}


def message(mid, stamp):
    row = claude_row()
    row.update(timestamp=stamp, requestId='req_' + mid)
    row['message']['id'] = mid
    return row


def now_stamp(offset=0):
    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(time.time() + offset))


def append(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f:
        f.write(''.join(line(r) for r in rows))


class Server:
    def __init__(self, home, data, port, token_file):
        env = {**os.environ, 'HOME': str(home), 'PYTHONDONTWRITEBYTECODE': '1'}
        self.port, self.token = port, token_file.read_text().strip()
        # The fixed port may still be in TIME_WAIT right after a normal stop; the CLI then
        # reports "尚未释放" and exits. Retry like a user would, for up to two minutes.
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            self.process = subprocess.Popen(
                [sys.executable, '-B', '-m', 'usage_dashboard', '--data-dir', str(data), 'serve', '--port', str(port),
                 '--client-token-file', str(token_file)],
                cwd=str(BACKEND), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            while self.process.poll() is None:
                try:
                    self.call('GET', '/health')
                    return
                except OSError:
                    time.sleep(.2)
            output = self.process.stdout.read()
            if '尚未释放' not in output:
                raise AssertionError('server did not start')
            self.retried = getattr(self, 'retried', 0) + 1
            time.sleep(5)
        raise AssertionError('port not released in time')

    def call(self, method, path, body=None):
        client = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        headers = {'Authorization': 'Bearer ' + self.token, 'Host': '127.0.0.1:' + str(self.port)}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        client.request(method, '/api/v1' + path, body=data, headers=headers)
        result = client.getresponse()
        payload = json.loads(result.read() or b'null')
        client.close()
        if result.status != 200:
            raise AssertionError('HTTP %s %s -> %s %s' % (method, path, result.status, payload))
        return payload['data']

    def stop(self):
        self.process.send_signal(signal.SIGINT)
        output, _ = self.process.communicate(timeout=30)
        return output


def counts(db_path):
    with sqlite3.connect(str(db_path)) as db:
        return {p: db.execute('SELECT COUNT(*) FROM usage_events WHERE provider=?', (p,)).fetchone()[0] for p in ('gpt', 'claude')}


def wait_for(predicate, seconds, what):
    start = time.monotonic()
    while time.monotonic() - start < seconds:
        if predicate():
            return time.monotonic() - start
        time.sleep(1)
    raise AssertionError('timed out waiting for ' + what)


def main():
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder).resolve()
        home, data = base / 'home', base / 'data'
        codex, claude = home / '.codex/sessions', home / '.claude/projects'
        old_codex, old_claude = codex / '2026/10/01/rollout-old.jsonl', claude / 'proj/old.jsonl'
        append(old_codex, [meta('old_thread')] + [response('hist_%d' % i, '2026-10-01T01:%02d:00.000Z' % i, 'old_thread') for i in range(5)])
        append(old_claude, [message('hist_m%d' % i, '2026-10-01T02:%02d:00.000Z' % i) for i in range(3)])
        data.mkdir()
        token_file = base / 'client-token'
        token_file.write_text('aud_' + secrets.token_urlsafe(32))
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        db_path = data / 'usage.sqlite3'

        server = Server(home, data, port, token_file)
        status = server.call('GET', '/collector-settings')
        assert status['configured'] is False and not any(s['enabled'] for s in status['sources'])
        time.sleep(3)
        assert counts(db_path) == {'gpt': 0, 'claude': 0}
        with sqlite3.connect(str(db_path)) as db:
            assert db.execute('SELECT COUNT(*) FROM sources').fetchone()[0] == 0
        note('1. not set up: no sources, no records, nothing read')

        server.call('POST', '/collector-settings', {'provider': 'gpt', 'enabled': True, 'location': 'standard',
                    'history': 'from_enable', 'confirm_scope': '~/.codex/sessions'})
        server.call('POST', '/collector-settings', {'provider': 'claude', 'enabled': True, 'location': 'standard',
                    'history': 'import_history', 'confirm_scope': '~/.claude/projects'})
        wait_for(lambda: all(s['last_success_at'] for s in server.call('GET', '/collector-settings')['sources']), 20, 'first round')
        status = server.call('GET', '/collector-settings')
        assert [s['boundary_status'] for s in status['sources']] == ['ready', 'not_applicable']
        assert counts(db_path) == {'gpt': 0, 'claude': 3}, counts(db_path)
        note('2. enabled: GPT from_enable imported 0 of 5 history records; Claude import_history imported 3')

        append(old_codex, [response('after_1', now_stamp(), 'old_thread')])
        append(codex / '2026/10/29/rollout-new.jsonl', [meta('new_thread'), response('after_2', now_stamp(), 'new_thread')])
        append(claude / 'proj/new-chat.jsonl', [message('new_m1', now_stamp())])
        took = wait_for(lambda: counts(db_path) == {'gpt': 2, 'claude': 4}, 75, 'scheduled pick-up of append + new chat files')
        note('3. append to existing file + new chat files picked up by the schedule after %.0f s' % took)
        gpt = server.call('GET', '/collector-settings')['sources'][0]
        assert gpt['retry_mode'] == 'automatic' and gpt['next_attempt_at'] and gpt['last_record_at']

        output = server.stop()
        assert str(home) not in output and 'DO_NOT_STORE' not in output
        with sqlite3.connect(str(db_path)) as db:
            assert db.execute("SELECT COUNT(*) FROM sources WHERE retry_mode='automatic' OR next_attempt_ms IS NOT NULL").fetchone()[0] == 0
        note('4. normal stop: schedule cleared, data kept %s' % counts(db_path))

        server = Server(home, data, port, token_file)
        if getattr(server, 'retried', 0):
            note('   (restart waited for the port to be released: %d retries)' % server.retried)
        status = server.call('GET', '/collector-settings')
        assert status['running'] and [s['enabled'] for s in status['sources']] == [True, True]
        before = time.time()
        wait_for(lambda: all(s['last_success_at'] and s['last_success_at'] >= now_stamp(before - time.time() - 1)[:19]
                             for s in server.call('GET', '/collector-settings')['sources']), 20, 'first round after restart')
        assert counts(db_path) == {'gpt': 2, 'claude': 4}, counts(db_path)
        append(old_codex, [response('after_3', now_stamp(), 'old_thread')])
        took = wait_for(lambda: counts(db_path)['gpt'] == 3, 75, 'append after restart')
        assert counts(db_path) == {'gpt': 3, 'claude': 4}
        note('5. restart restored settings, no history or duplicates added; next append after %.0f s' % took)

        server.call('POST', '/collector-settings', {'provider': 'gpt', 'enabled': False})
        append(old_codex, [response('after_disable', now_stamp(), 'old_thread')])
        append(claude / 'proj/new-chat.jsonl', [message('new_m2', now_stamp())])
        wait_for(lambda: counts(db_path)['claude'] == 5, 75, 'claude still collecting')
        time.sleep(5)
        assert counts(db_path)['gpt'] == 3
        gpt = server.call('GET', '/collector-settings')['sources'][0]
        assert gpt['enabled'] is False and gpt['retry_mode'] == 'manual' and gpt['next_attempt_at'] is None
        note('6. GPT disabled: its new record ignored, data kept; Claude kept collecting')

        settings = server.call('GET', '/collector-settings')
        assert str(home) not in json.dumps(settings)
        server.stop()
        raw = db_path.read_bytes()
        assert str(home).encode() not in raw and b'DO_NOT_STORE_PRIVATE' not in raw
        assert (data / 'collector-settings.json').stat().st_mode & 0o777 == 0o600
        note('7. no source paths or content in SQLite/API; settings file private (0600)')
    print(json.dumps({'synthetic_data': True, 'interval_seconds': 60, 'elapsed_seconds': round(time.monotonic() - started, 1),
                      'steps_passed': len(LOG)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
