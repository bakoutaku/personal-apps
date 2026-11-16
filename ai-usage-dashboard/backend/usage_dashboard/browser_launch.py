"""Opt-in browser handoff; pairing secret is only carried in a short-lived fragment."""
from html.parser import HTMLParser
from pathlib import Path
import sys
import threading
from urllib.parse import quote
import webbrowser


class _CapabilityParser(HTMLParser):
    supported = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta' and values.get('name') == 'usage-dashboard-launch-pairing' and values.get('content') == 'fragment-v1':
            self.supported = True


def supports_launch_pairing(frontend):
    if not frontend:
        return False
    try:
        path = Path(frontend)/'index.html'
        if path.stat().st_size > 1024*1024:
            return False
        parser = _CapabilityParser()
        parser.feed(path.read_text(encoding='utf-8'))
        return parser.supported
    except (OSError, UnicodeError):
        return False


class BrowserLaunch:
    def __init__(self, server):
        self._url = ('http://127.0.0.1:'+str(server.server_port)+
                     '/#launch_pairing='+quote(server.app.auth.pairing_code, safe=''))
        self._cancel = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._open, name='local-dashboard-browser', daemon=True)
        self._thread.start()

    def _open(self):
        # The socket is already bound/listening. Let the main thread enter serve_forever.
        if self._cancel.wait(0.2):
            return
        try:
            opened = webbrowser.open(self._url, new=2, autoraise=True)
        except Exception:
            opened = False
        if not opened and not self._cancel.is_set():
            print('无法自动打开浏览器；请保持服务窗口，关闭后重试启动，或改用普通启动方式手动连接。', file=sys.stderr)

    def stop(self):
        self._cancel.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
