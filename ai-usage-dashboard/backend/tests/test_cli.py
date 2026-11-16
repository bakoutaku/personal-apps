import contextlib
import errno
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from usage_dashboard.__main__ import main


class StartupErrorTests(unittest.TestCase):
    def invoke(self,folder,port=49173,config=None):
        error=io.StringIO()
        args=['usage_dashboard','--data-dir',str(folder),'serve','--port',str(port)]
        if config:
            args+=['--collector-config',str(config)]
        with patch.object(sys,'argv',args), contextlib.redirect_stderr(error):
            result=main()
        return result,error.getvalue()

    def test_address_in_use_has_specific_safe_message(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('usage_dashboard.__main__.make_server',side_effect=OSError(errno.EADDRINUSE,'PRIVATE_FILE_OR_SECRET')):
                result,message=self.invoke(folder)
        self.assertEqual(result,1)
        self.assertIn('127.0.0.1:49173',message)
        self.assertIn('已被占用或尚未释放',message)
        self.assertNotIn('PRIVATE_FILE_OR_SECRET',message)

    def test_windows_address_in_use_codes_are_recognized(self):
        cases=[OSError(10048,'PRIVATE_FILE_OR_SECRET'),OSError(errno.EINVAL,'PRIVATE_FILE_OR_SECRET')]
        cases[1].winerror=10048
        for error in cases:
            with self.subTest(error_code=error.errno), tempfile.TemporaryDirectory() as folder:
                with patch('usage_dashboard.__main__.make_server',side_effect=error):
                    result,message=self.invoke(folder)
                self.assertEqual(result,1)
                self.assertIn('已被占用或尚未释放',message)
                self.assertNotIn('PRIVATE_FILE_OR_SECRET',message)

    def test_permission_failure_is_not_mislabeled_as_port_in_use(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('usage_dashboard.__main__.make_server',side_effect=PermissionError(errno.EACCES,'PRIVATE_FILE_OR_SECRET')):
                result,message=self.invoke(folder)
        self.assertEqual(result,1)
        self.assertNotIn('已被占用',message)
        self.assertNotIn('PRIVATE_FILE_OR_SECRET',message)

    def test_real_occupied_loopback_port_reports_without_disrupting_listener(self):
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
            try:
                listener.bind(('127.0.0.1',0))
                listener.listen(1)
            except PermissionError:
                self.skipTest('Loopback socket permission required')
            port=listener.getsockname()[1]
            with tempfile.TemporaryDirectory() as folder:
                result,message=self.invoke(folder,port)
            self.assertEqual(result,1)
            self.assertIn('127.0.0.1:'+str(port),message)
            self.assertIn('已被占用或尚未释放',message)
            self.assertEqual(listener.getsockname()[1],port)
            self.assertGreaterEqual(listener.fileno(),0)

    def test_configured_collector_starts_and_stops_with_cli_service(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=Path(folder)/'collector.json'
            cfg.write_text(json.dumps({'version':1,'interval_seconds':60,'sources':[
                {'enabled':True,'provider':'gpt','path':str(Path(folder).resolve())}]}))
            order=Mock()
            order.serve.side_effect=KeyboardInterrupt
            server=SimpleNamespace(server_port=49173,serve_forever=order.serve,server_close=order.close)
            with patch('usage_dashboard.__main__.make_server',return_value=server), patch('usage_dashboard.__main__.AutoCollector',return_value=order.collector), contextlib.redirect_stdout(io.StringIO()):
                result,_=self.invoke(folder,config=cfg)
            self.assertEqual(result,0)
            self.assertEqual([call[0] for call in order.mock_calls],['collector.start','serve','collector.stop','close'])

    def test_failed_bind_never_starts_configured_collector(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=Path(folder)/'collector.json'
            cfg.write_text(json.dumps({'version':1,'interval_seconds':60,'sources':[
                {'enabled':True,'provider':'gpt','path':str(Path(folder).resolve())}]}))
            with patch('usage_dashboard.__main__.make_server',side_effect=OSError(errno.EADDRINUSE,'private')), patch('usage_dashboard.__main__.AutoCollector') as collector:
                result,_=self.invoke(folder,config=cfg)
                self.assertEqual(result,1)
                collector.assert_not_called()
