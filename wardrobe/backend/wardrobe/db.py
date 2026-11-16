"""数据库引擎、会话与迁移。

事务约定：
* 每个请求一个 Session；写请求在第一次访问数据库时以 BEGIN IMMEDIATE 开始事务，
  使并发写入串行化，版本检查（读 → 比较 → 写）不会出现竞态。
* 写处理函数显式 commit；抛出异常时 Session 关闭即回滚，整个请求不部分生效。
"""

import functools
import tempfile
from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
IMMEDIATE = "wardrobe_immediate"


def make_engine(db_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False, "timeout": 10})

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):
        # 交给 SQLAlchemy 的 begin 事件自己发 BEGIN，才能选择 IMMEDIATE
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")
        cur.execute("PRAGMA busy_timeout = 10000")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        immediate = conn.get_execution_options().get(IMMEDIATE, False)
        conn.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")

    return engine


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False, autoflush=True)


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def known_revisions() -> set[str]:
    return {rev.revision for rev in ScriptDirectory.from_config(alembic_config()).walk_revisions()}


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def run_migrations(engine: Engine, target: str = "head") -> None:
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, target)


def table_columns(conn) -> dict[str, frozenset[str]]:
    """数据库中每张表（含 FTS 内部表，不含 sqlite_ 系统表）的列名集合。conn 为 DB-API 连接。"""
    names = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
    ]
    return {n: frozenset(r[1] for r in conn.execute(f'PRAGMA table_info("{n}")')) for n in names}


@functools.cache
def expected_schema(revision: str) -> dict[str, frozenset[str]]:
    """把迁移执行到 revision 得到的表与列。用于校验备份结构，随迁移自动更新，不需要手工维护清单。"""
    with tempfile.TemporaryDirectory() as tmp:
        engine = make_engine(Path(tmp) / "expected.db")
        try:
            run_migrations(engine, revision)
            raw = engine.raw_connection()
            try:
                return table_columns(raw.driver_connection)
            finally:
                raw.close()
        finally:
            engine.dispose()


def session_dependency(request: Request) -> Iterator[Session]:
    """GET 用普通事务，其余方法用 BEGIN IMMEDIATE。"""
    factory: sessionmaker[Session] = request.app.state.sessionmaker
    session = factory()
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        session.connection(execution_options={IMMEDIATE: True})
    try:
        yield session
    finally:
        session.close()
