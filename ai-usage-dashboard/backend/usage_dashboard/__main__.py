import argparse
import errno
import os
from pathlib import Path
import secrets
import sqlite3
import sys

from .collect import collect
from .common import canonical
from .server import make_server
from .store import initialize
from .auto_collect import AutoCollector, load_config
from .collector_settings import CollectorService, describe
from .browser_launch import BrowserLaunch, supports_launch_pairing


def default_directory():
    if sys.platform=='darwin':
        return Path.home()/'Library/Application Support/AI Usage Dashboard'
    if sys.platform=='win32':
        return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'AIUsageDashboard'
    raise ValueError('Supported platforms are macOS and Windows')


def main():
    parser = argparse.ArgumentParser(description='Local AI usage backend; no supplier credentials required')
    parser.add_argument('--data-dir',type=Path)
    commands = parser.add_subparsers(dest='command',required=True)
    commands.add_parser('init',help='Initialize private local SQLite storage')
    read = commands.add_parser('collect',help='Explicit one-shot JSONL import; safe to repeat')
    read.add_argument('--provider',choices=['gpt','claude'],required=True)
    read.add_argument('--path',type=Path,required=True)
    read.add_argument('--account-namespace',default='local',help='Separate local namespace when changing supplier account')
    commands.add_parser('create-local-token',help='Create a dedicated client token in the data directory (never overwrite)')
    serve = commands.add_parser('serve',help='Serve on 127.0.0.1; collects only sources enabled on the 数据来源 page (or an explicit --collector-config)')
    serve.add_argument('--port',type=int,default=49173)
    serve.add_argument('--dev-origin',help='Exact frontend proxy origin, e.g. http://127.0.0.1:5174')
    serve.add_argument('--frontend-dist',type=Path)
    serve.add_argument('--client-token-file',type=Path,help='Optional explicitly generated aud_ local client token file')
    serve.add_argument('--collector-config',type=Path,help='Explicit local JSON configuration; overrides app settings for this run, no auto-discovery')
    serve.add_argument('--no-collection',action='store_true',help='Do not collect during this run, even if sources are enabled in app settings')
    serve.add_argument('--open-browser',action='store_true',help='Open a compatible built frontend and hand off one-time local pairing without manual entry')
    args = parser.parse_args()
    try:
        folder = args.data_dir.expanduser() if args.data_dir else default_directory()
        db_path = folder/'usage.sqlite3'
        initialize(db_path)
        if args.command=='init':
            print('Local storage initialized; no collection started.')
        elif args.command=='collect':
            print(canonical(collect(db_path,args.provider,args.path,args.account_namespace)))
        elif args.command=='create-local-token':
            path = folder/'client-token'
            descriptor = os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,'w') as f:
                f.write('aud_'+secrets.token_urlsafe(32)+'\n')
            print('Dedicated local client token saved in data directory. Value not printed.')
        else:
            if not 1024<=args.port<=65535:
                raise ValueError('Choose a fixed port in 1024..65535')
            token = args.client_token_file.read_text().strip() if args.client_token_file else None
            if args.collector_config and args.no_collection:
                raise ValueError('--collector-config 与 --no-collection 不能同时使用')
            config=load_config(args.collector_config) if args.collector_config else None
            if args.open_browser and not supports_launch_pairing(args.frontend_dist):
                raise ValueError('自动打开需要支持 fragment-v1 本机连接的前端构建；请先更新前端或使用普通启动方式')
            service=CollectorService(db_path,folder,startup_config=config,disabled=args.no_collection,factory=AutoCollector)
            try:
                server = make_server(db_path,args.port,args.dev_origin,token,args.frontend_dist,collector=service)
            except OSError as error:
                if error.errno in (errno.EADDRINUSE,10048) or getattr(error,'winerror',None)==10048:
                    raise ValueError('本机端口 127.0.0.1:'+str(args.port)+
                        ' 已被占用或尚未释放。请确认旧服务已关闭，稍后再试；若持续出现，请检查是否有其他程序使用该端口。') from None
                raise
            scheduler=service
            browser=BrowserLaunch(server) if args.open_browser else None
            try:
                if scheduler:
                    scheduler.start()
                print('Local server: http://127.0.0.1:'+str(server.server_port),flush=True)
                if browser:
                    browser.start()
                    print('正在自动打开本机面板并连接，无需复制地址或输入配对码。',flush=True)
                elif sys.stdout.isatty():
                    print('One-time app pairing code (5 minutes): '+server.app.auth.pairing_code,flush=True)
                else:
                    print('Pairing code hidden outside an interactive terminal; run serve interactively to pair a browser.',flush=True)
                print(describe(service)+' Ctrl+C stops the server and collector.',flush=True)
                server.serve_forever(poll_interval=0.25)
            except KeyboardInterrupt:
                pass
            finally:
                try:
                    try:
                        if browser:
                            browser.stop()
                    finally:
                        if scheduler:
                            scheduler.stop()
                finally:
                    server.server_close()
    except (OSError,ValueError,sqlite3.Error) as error:
        # Never print OSError filenames, selected transcript paths or credential values.
        print('Operation failed: '+(str(error) if isinstance(error,ValueError) else 'Local file/network operation was not permitted or failed'),file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
