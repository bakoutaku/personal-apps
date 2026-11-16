import contextlib
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from usage_dashboard.browser_launch import BrowserLaunch, supports_launch_pairing
from usage_dashboard.__main__ import main
from usage_dashboard.server import make_server
from usage_dashboard.store import initialize


class BrowserLaunchTests(unittest.TestCase):
    def test_only_explicit_frontend_capability_enables_handoff(self):
        with tempfile.TemporaryDirectory() as folder:
            page=Path(folder)/'index.html'
            self.assertFalse(supports_launch_pairing(folder))
            page.write_text('<meta name="usage-dashboard-launch-pairing" content="fragment-v0">')
            self.assertFalse(supports_launch_pairing(folder))
            page.write_text("<meta content='fragment-v1' name='usage-dashboard-launch-pairing'>")
            self.assertTrue(supports_launch_pairing(folder))
            page.write_bytes(b'\xff')
            self.assertFalse(supports_launch_pairing(folder))

    def test_stop_before_launch_does_not_open_a_closed_service(self):
        server=SimpleNamespace(server_port=49173,app=SimpleNamespace(auth=SimpleNamespace(pairing_code='synthetic_test_only_code')))
        handoff=BrowserLaunch(server)
        with patch('usage_dashboard.browser_launch.webbrowser.open') as opened:
            handoff.start()
            handoff.stop()
        opened.assert_not_called()
        self.assertFalse(handoff._thread.is_alive())

    def test_failed_browser_launch_never_prints_secret_or_exception(self):
        code='synthetic_pairing_secret_0123456789'
        server=SimpleNamespace(server_port=49173,app=SimpleNamespace(auth=SimpleNamespace(pairing_code=code)))
        handoff=BrowserLaunch(server)
        errors=io.StringIO()
        with patch.object(handoff._cancel,'wait',return_value=False), patch('usage_dashboard.browser_launch.webbrowser.open',side_effect=RuntimeError(code)), contextlib.redirect_stderr(errors):
            handoff._open()
        self.assertIn('无法自动打开',errors.getvalue())
        self.assertNotIn(code,errors.getvalue())
        self.assertNotIn('launch_pairing',errors.getvalue())

    def test_fragment_is_not_sent_on_http_get_and_pairing_is_single_use(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'index.html').write_text('<meta name="usage-dashboard-launch-pairing" content="fragment-v1">')
            db=root/'private/usage.sqlite3'
            initialize(db)
            try:
                server=make_server(db,0,frontend=root)
            except PermissionError:
                self.skipTest('Loopback socket permission required')
            worker=threading.Thread(target=server.serve_forever,daemon=True)
            worker.start()
            finished=threading.Event()
            results={}
            def pretend_browser(url,**options):
                try:
                    parsed=urlsplit(url)
                    code=parse_qs(parsed.fragment)['launch_pairing'][0]
                    results['no_http_query']=not parsed.query
                    origin=parsed.scheme+'://'+parsed.netloc
                    def request(method,path,body=None,headers=None):
                        conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                        try:
                            conn.request(method,path,body,headers or {})
                            response=conn.getresponse()
                            response.read()
                            return response.status,dict(response.getheaders())
                        finally:
                            conn.close()
                    results['root_status']=request('GET',parsed.path)[0]
                    body=json.dumps({'pairing_code':code})
                    headers={'Origin':origin,'Content-Type':'application/json','X-Dashboard-Pairing':'1'}
                    results['pair_status'],extra=request('POST','/api/v1/auth/session',body,headers)
                    results['single_use_status']=request('POST','/api/v1/auth/session',body,headers)[0]
                    cookie=extra['Set-Cookie'].split(';',1)[0]
                    results['restore_status']=request('GET','/api/v1/auth/session',headers={'Origin':origin,'Cookie':cookie})[0]
                    return True
                finally:
                    finished.set()
            handoff=BrowserLaunch(server)
            try:
                with patch('usage_dashboard.browser_launch.webbrowser.open',side_effect=pretend_browser):
                    handoff.start()
                    self.assertTrue(finished.wait(5))
                    handoff.stop()
                self.assertEqual(results,{'no_http_query':True,'root_status':200,'pair_status':201,'single_use_status':401,'restore_status':200})
            finally:
                handoff.stop()
                server.shutdown();worker.join();server.server_close()

    def test_cli_rejects_legacy_frontend_before_binding_or_opening(self):
        with tempfile.TemporaryDirectory() as folder:
            args=['usage_dashboard','--data-dir',folder,'serve','--open-browser']
            with patch.object(sys,'argv',args), patch('usage_dashboard.__main__.make_server') as bind, patch('usage_dashboard.__main__.BrowserLaunch') as browser, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(),1)
                bind.assert_not_called();browser.assert_not_called()

    def test_cli_auto_mode_hides_pairing_code_even_in_terminal_and_cleans_up(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        order=Mock()
        order.serve.side_effect=KeyboardInterrupt
        code='synthetic_pairing_secret_0123456789'
        server=SimpleNamespace(server_port=49173,app=SimpleNamespace(auth=SimpleNamespace(pairing_code=code)),serve_forever=order.serve,server_close=order.close)
        output=Terminal()
        with tempfile.TemporaryDirectory() as folder:
            args=['usage_dashboard','--data-dir',folder,'serve','--open-browser','--frontend-dist',folder]
            with patch.object(sys,'argv',args), patch('usage_dashboard.__main__.supports_launch_pairing',return_value=True), patch('usage_dashboard.__main__.make_server',return_value=server), patch('usage_dashboard.__main__.BrowserLaunch',return_value=order.browser), contextlib.redirect_stdout(output):
                self.assertEqual(main(),0)
        self.assertEqual([c[0] for c in order.mock_calls],['browser.start','serve','browser.stop','close'])
        self.assertNotIn(code,output.getvalue())
        self.assertNotIn('launch_pairing',output.getvalue())


if __name__=='__main__':
    unittest.main()
