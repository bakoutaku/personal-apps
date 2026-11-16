"""Mac preview entry point. Collects only sources the user enabled on the 数据来源 page."""
import argparse
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description='AI Usage Dashboard · Mac 本机预览版')
    parser.add_argument('--data-dir', type=Path, help='可选独立数据目录；默认使用用户 Library 中的应用目录')
    parser.add_argument('--collector-config', type=Path, help='高级：本次改用显式本机配置（页面设置只读）')
    parser.add_argument('--no-collection', action='store_true', help='本次启动不采集，即使页面里已启用来源')
    args = parser.parse_args()
    if sys.platform != 'darwin' or sys.version_info < (3, 9):
        print('此预览包需要 macOS 和 Python 3.9 或更新版本。', file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parent
    required = ('web/index.html', 'backend/usage_dashboard/__main__.py',
                'backend/sql/001_initial.sql', 'contracts/openapi.json')
    if not all((root/name).is_file() for name in required):
        print('预览包不完整，请重新完整解压，保留 web、backend、contracts 与启动文件。', file=sys.stderr)
        return 1
    sys.path.insert(0, str(root/'backend'))
    from usage_dashboard.__main__ import main as backend_main
    from usage_dashboard.browser_launch import supports_launch_pairing
    argv = ['usage_dashboard']
    if args.data_dir is not None:
        argv.extend(['--data-dir', str(args.data_dir)])
    argv.extend(['serve', '--frontend-dist', str(root/'web')])
    automatic = supports_launch_pairing(root/'web')
    if automatic:
        argv.append('--open-browser')
    if args.collector_config is not None:
        argv.extend(['--collector-config', str(args.collector_config)])
    if args.no_collection:
        argv.append('--no-collection')
    sys.argv = argv
    print('AI Usage Dashboard · Mac 本机预览版', flush=True)
    print('服务将自动打开浏览器并连接本机面板。' if automatic else
          '当前页面构建尚未支持自动连接；服务启动后打开 http://127.0.0.1:49173 并输入下方一次性配对码。', flush=True)
    print('自动采集按页面“数据来源”中的设置运行；未设置时不读取任何日志。', flush=True)
    print('保持这个终端窗口开启；按 Ctrl+C 正常停止（采集随之停止，数据保留）。此包不会开机自启。', flush=True)
    return backend_main()


if __name__ == '__main__':
    raise SystemExit(main())
