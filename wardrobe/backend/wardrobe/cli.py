"""命令行入口：./wardrobe start|stop|status|dev|backup|restore|migrate|gc-images|dump-schema"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser
from pathlib import Path

import typer

from .config import REPO_ROOT, Settings, load_settings

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Wardrobe 本地衣橱管理")
BACKEND_DIR = REPO_ROOT / "backend"


def _settings() -> Settings:
    return load_settings()


def _url(s: Settings) -> str:
    return f"http://{s.host}:{s.port}"


def _healthy(s: Settings, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{_url(s)}/api/v1/health", timeout=timeout) as r:
            return json.loads(r.read()).get("status") == "ok"
    except OSError:
        return False


def _read_pid(s: Settings) -> int | None:
    try:
        pid = int(s.pid_file.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        s.pid_file.unlink(missing_ok=True)  # 残留的 PID 文件
        return None
    except PermissionError:
        return None
    return pid


@app.command()
def serve():
    """前台运行（start 在后台调用它；一般不需要直接使用）。"""
    import uvicorn

    from .main import create_app

    s = _settings()
    uvicorn.run(create_app(s), host=s.host, port=s.port, log_level="info")


@app.command()
def start(no_open: bool = typer.Option(False, "--no-open", help="启动后不自动打开浏览器")):
    """后台启动服务。"""
    s = _settings()
    s.ensure_dirs()
    if _read_pid(s) and _healthy(s):
        typer.echo(f"已在运行：{_url(s)}")
        return
    if _healthy(s):
        typer.echo(f"端口 {s.port} 已被其他 Wardrobe 进程占用（没有 PID 文件）。请先关闭它。", err=True)
        raise typer.Exit(1)
    _build_ui()  # 首次启动时构建网页界面；失败不影响 API

    env = {**os.environ, "PYTHONPATH": str(BACKEND_DIR), "WARDROBE_DATA_DIR": str(s.data_dir),
           "WARDROBE_PORT": str(s.port)}  # fmt: skip
    with s.log_file.open("ab") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "wardrobe.cli", "serve"],
            cwd=BACKEND_DIR, env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )  # fmt: skip
    s.pid_file.write_text(str(proc.pid))

    for _ in range(60):
        if proc.poll() is not None:
            s.pid_file.unlink(missing_ok=True)
            typer.echo(f"启动失败，请查看日志：{s.log_file}", err=True)
            raise typer.Exit(1)
        if _healthy(s):
            break
        time.sleep(0.25)
    else:
        typer.echo(f"等待服务就绪超时，请查看日志：{s.log_file}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Wardrobe 已启动：{_url(s)}  （API 文档：{_url(s)}/api/docs）")
    typer.echo(f"数据目录：{s.data_dir}")
    if not no_open:
        webbrowser.open(_url(s))


FRONTEND_DIR = REPO_ROOT / "frontend"


def _build_ui(force: bool = False) -> bool:
    """构建网页界面（npm ci + npm run build）。缺少 npm 或构建失败时返回 False。"""
    import shutil

    if not (FRONTEND_DIR / "package.json").exists():
        return False
    if not force and (FRONTEND_DIR / "dist" / "index.html").exists():
        return True
    npm = shutil.which("npm")
    if npm is None:
        typer.echo("未找到 npm，无法构建网页界面（API 仍可使用）。安装 Node.js 后执行 ./wardrobe build-ui", err=True)
        return False
    typer.echo("正在构建网页界面……")
    for args in ([npm, "ci", "--no-audit", "--no-fund"], [npm, "run", "build"]):
        if subprocess.run(args, cwd=FRONTEND_DIR).returncode != 0:
            typer.echo(f"构建失败：{' '.join(args[1:])}（API 仍可使用）", err=True)
            return False
    return True


@app.command("build-ui")
def build_ui():
    """重新构建网页界面（修改前端代码后执行）。"""
    if not _build_ui(force=True):
        raise typer.Exit(1)
    typer.echo(f"已构建：{FRONTEND_DIR / 'dist'}")


@app.command("seed-demo")
def seed_demo_cmd():
    """向正在运行的空数据库写入虚构的演示数据（含示意图），方便查看界面。"""
    from .demo import seed_demo

    s = _settings()
    if not _healthy(s):
        typer.echo("服务未运行，请先执行 ./wardrobe start", err=True)
        raise typer.Exit(1)
    try:
        result = seed_demo(_url(s))
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"已写入演示数据：导入批次 {result['job_id']}，{result['images']} 张示意图，{result['summary']}")
    typer.echo(f"不需要时可以整批撤销：POST /api/v1/imports/{result['job_id']}/revert")


@app.command()
def stop():
    """停止后台服务。"""
    s = _settings()
    pid = _read_pid(s)
    if pid is None:
        typer.echo("没有在运行。")
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.25)
    else:
        os.kill(pid, signal.SIGKILL)
    s.pid_file.unlink(missing_ok=True)
    typer.echo("已停止。")


@app.command()
def status():
    """运行状态、地址、数据目录、schema 版本。"""
    from .db import current_revision, head_revision, make_engine

    s = _settings()
    pid = _read_pid(s)
    running = pid is not None and _healthy(s)
    revision = current_revision(make_engine(s.db_path)) if s.db_path.exists() else None
    typer.echo(f"状态      ：{'运行中 (pid ' + str(pid) + ')' if running else '未运行'}")
    typer.echo(f"地址      ：{_url(s)}")
    typer.echo(f"数据目录  ：{s.data_dir}")
    typer.echo(f"schema    ：{revision or '（尚未创建）'}  / 程序最新 {head_revision()}")


@app.command()
def dev():
    """前台运行并在代码变化时自动重载（开发用）。"""
    import uvicorn

    s = _settings()
    os.environ.setdefault("WARDROBE_DATA_DIR", str(s.data_dir))
    uvicorn.run(
        "wardrobe.main:create_app", factory=True, host=s.host, port=s.port, reload=True,
        reload_dirs=[str(BACKEND_DIR / "wardrobe")],
    )  # fmt: skip


@app.command()
def backup():
    """立即备份数据库与图片（服务运行中也可以执行）。"""
    from .storage.backup import BackupError, create_backup

    try:
        path = create_backup(_settings(), "manual")
    except BackupError as exc:
        typer.echo(f"备份失败：{exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"已备份：{path}")


@app.command()
def restore(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="备份 zip 文件"),
    yes: bool = typer.Option(False, "--yes", "-y", help="不再确认"),
):
    """从备份恢复（需先 stop）。恢复前会自动备份当前数据。"""
    from .storage.backup import BackupError, restore_backup

    s = _settings()
    if _read_pid(s) is not None or _healthy(s):
        typer.echo("服务正在运行，请先执行 ./wardrobe stop", err=True)
        raise typer.Exit(1)
    if not yes:
        typer.confirm(
            f"将用 {file.name} 覆盖 {s.data_dir} 中的数据库和图片（当前数据会先自动备份），继续？", abort=True
        )
    try:
        result = restore_backup(s, file.resolve())
    except BackupError as exc:
        typer.echo(f"恢复失败（现有数据未改动）：{exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"已恢复：{result['restored_from']}（schema {result['schema_revision']}）")
    if result["pre_restore_backup"]:
        typer.echo(f"恢复前的数据已备份为：{result['pre_restore_backup']}")
    typer.echo("下次 start 时会自动执行需要的迁移。")


@app.command()
def migrate():
    """执行数据库迁移（start 时也会自动执行；有数据时先自动备份）。"""
    from .db import current_revision
    from .main import prepare_database

    engine, _ = prepare_database(_settings())
    typer.echo(f"数据库已是最新：{current_revision(engine)}")


@app.command("gc-images")
def gc_images():
    """删除没有被任何图片记录引用的文件。"""
    from .db import make_engine, make_sessionmaker
    from .storage.images import gc_orphans

    s = _settings()
    typer.echo(f"已删除 {gc_orphans(s, make_sessionmaker(make_engine(s.db_path)))} 个孤儿文件")


@app.command("dump-schema")
def dump_schema(out: Path = typer.Option(REPO_ROOT / "docs" / "schema.sql", help="输出文件")):
    """用最新迁移建一个临时库，导出完整 DDL 到 docs/schema.sql。"""
    import sqlite3

    from .db import head_revision, make_engine, run_migrations

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "schema.db"
        engine = make_engine(db)
        run_migrations(engine)
        engine.dispose()
        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'search_index_%' "
            "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' ORDER BY rowid"
        ).fetchall()
        conn.close()
    header = (
        f"-- 由 `./wardrobe dump-schema` 生成，请勿手工编辑。\n"
        f"-- 来源：backend/wardrobe/migrations（head = {head_revision()}）\n\n"
    )
    out.write_text(header + "\n\n".join(r[0] + ";" for r in rows) + "\n", encoding="utf-8")
    typer.echo(f"已写入 {out}")


if __name__ == "__main__":
    app()
