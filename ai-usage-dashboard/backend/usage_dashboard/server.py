from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import threading
from urllib.parse import unquote, urlsplit

from .app import Application
from .common import APIError


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self,*args,**kwargs):
        self.capacity = threading.BoundedSemaphore(16)
        super().__init__(*args,**kwargs)

    def process_request(self,request,address):
        if not self.capacity.acquire(False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request,address)
        except BaseException:
            self.capacity.release()
            raise

    def process_request_thread(self,*args):
        try:
            super().process_request_thread(*args)
        finally:
            self.capacity.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    server_version = 'AIUsageLocal'
    sys_version = ''

    def setup(self):
        self.request.settimeout(5)
        super().setup()

    def log_message(self,*args):
        pass  # Request URLs/headers may contain secrets; no automatic access logs.

    def run_request(self):
        headers = {k.lower():v for k,v in self.headers.items()}
        app = self.server.app
        try:
            app.auth.check_host_origin(headers)
            protected = ('host','origin','authorization','cookie','content-length','content-type','transfer-encoding','x-csrf-token','if-match','x-dashboard-pairing')
            if any(len(self.headers.get_all(k,[]))>1 for k in protected):
                raise APIError(422,'invalid_body','Repeated security/framing header')
            if headers.get('transfer-encoding') or headers.get('expect'):
                raise APIError(422,'invalid_body','Chunked/Expect requests are unsupported')
            length = headers.get('content-length','0')
            if not length.isascii() or not length.isdigit() or len(length)>8 or int(length)>32768:
                raise APIError(422,'invalid_body','Invalid or oversized Content-Length')
            body = self.rfile.read(int(length)) if int(length) else b''
            if len(body)!=int(length):
                raise APIError(422,'invalid_body','Incomplete request body')
            if self.path.startswith('/api/v1/'):
                status,data,extra = app.handle(self.command,self.path,headers,body)
                encoded = b'' if data is None else json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
                self.respond(status,encoded,'application/json; charset=utf-8',extra)
                return
            if self.command not in ('GET','HEAD') or body:
                raise APIError(404,'not_found','Endpoint not found')
            root = self.server.frontend
            if root is None:
                raise APIError(404,'not_found','No frontend build configured; API service is running')
            raw = unquote(urlsplit(self.path).path,errors='strict')
            relative = 'index.html' if raw=='/' else raw.lstrip('/')
            parts = Path(relative).parts
            target = (root/relative).resolve()
            if any(x.startswith('.') for x in parts) or not target.is_relative_to(root) or not target.is_file() or target.stat().st_size>20*1024*1024:
                raise APIError(404,'not_found','Static resource not found')
            allowed = {'.html','.js','.css','.svg','.png','.jpg','.jpeg','.webp','.ico','.woff','.woff2','.json'}
            if target.suffix.lower() not in allowed:
                raise APIError(404,'not_found','Static resource not found')
            csp = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            self.respond(200,target.read_bytes(),mimetypes.guess_type(str(target))[0] or 'application/octet-stream',
                         {'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':csp})
        except (APIError,TimeoutError,OSError,UnicodeError,ValueError) as error:
            if not isinstance(error,APIError):
                error = APIError(422,'invalid_body','Invalid or incomplete request')
            data = {'error':{'code':error.code,'message':error.message,'details':error.details},'meta':app.meta()}
            self.respond(error.status,json.dumps(data,ensure_ascii=False).encode(),'application/json; charset=utf-8',app.headers(error.headers))

    def respond(self,status,body,content_type,extra):
        try:
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            for k,v in extra.items():
                self.send_header(k,v)
            self.end_headers()
            if self.command!='HEAD' and body:
                self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError,TimeoutError):
            pass

    do_GET = do_POST = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = run_request


def make_server(db_path,port=49173,dev_origin=None,bearer=None,frontend=None,clock=None,collector=None):
    root = Path(frontend).resolve() if frontend else None
    if root is not None and (not root.is_dir() or not (root/'index.html').is_file()):
        raise ValueError('Frontend must be an explicit built directory containing index.html')
    server = LocalServer(('127.0.0.1',port),Handler)
    try:
        options = {} if clock is None else {'clock':clock}
        server.app = Application(db_path,server.server_port,dev_origin,bearer,**options)
        server.frontend = root
        server.app.collector = collector
        return server
    except BaseException:
        server.server_close()
        raise
