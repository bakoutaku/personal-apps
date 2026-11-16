"""通用服务：时间、取记录、乐观锁、审计日志。"""

from datetime import UTC, date, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from ..errors import ApiError, not_found
from ..models import ChangeLog


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    return date.today().isoformat()


def actor_of(request: Request) -> str:
    return getattr(request.state, "actor", "anonymous")


def get_or_404[T](session: Session, model: type[T], ident: int, *, include_deleted: bool = False) -> T:
    obj = session.get(model, ident)
    if obj is None or (not include_deleted and getattr(obj, "deleted_at", None) is not None):
        raise not_found(model.__tablename__, ident)
    return obj


def require_version(obj: Any, body_version: int | None, if_match: str | None = None) -> None:
    """R6：修改核心实体必须带当前 version（body 或 If-Match）。"""
    version = body_version
    if version is None and if_match:
        try:
            version = int(if_match.strip().strip('"').removeprefix("W/").strip('"'))
        except ValueError as exc:
            raise ApiError(422, "VALIDATION_ERROR", "If-Match 必须是整数版本号") from exc
    if version is None:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "缺少 version",
            [{"loc": ["version"], "code": "missing", "message": "修改已有记录必须提供当前 version 或 If-Match 头"}],
        )
    if version != obj.version:
        raise ApiError(
            409,
            "VERSION_CONFLICT",
            f"版本冲突：提交的 version={version}，当前为 {obj.version}",
            [{"loc": ["version"], "current_version": obj.version}],
        )


def touch(obj: Any, *, bump: bool = True) -> None:
    obj.updated_at = now_iso()
    if bump and hasattr(obj, "version"):
        obj.version = obj.version + 1


def snapshot(obj: Any, fields: list[str] | None = None) -> dict[str, Any]:
    cols = fields or [c.key for c in inspect(obj).mapper.column_attrs]
    return {f: getattr(obj, f) for f in cols}


def diff_fields(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict, dict]:
    keys = [k for k in after if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after[k] for k in keys}


def commit(session: Session) -> None:
    """API 写操作的提交点。

    导入执行与接受修改提议时，会把多个 API 写操作放进同一个事务：此时 session.info["defer_commit"]
    为真，这里只 flush，由外层统一提交或回滚。这样导入和提议走的是与 API 完全相同的校验与审计逻辑。
    """
    if session.info.get("defer_commit"):
        session.flush()
    else:
        session.commit()


def log_change(
    session: Session,
    *,
    actor: str,
    entity: str,
    entity_id: int,
    op: str,
    before: dict | None = None,
    after: dict | None = None,
    version_after: int | None = None,
) -> None:
    """写审计日志。当前处于导入批次或接受提议时，自动记录 import_job_id / proposal_id。"""
    session.add(
        ChangeLog(
            occurred_at=now_iso(),
            actor=actor,
            entity=entity,
            entity_id=entity_id,
            op=op,
            before=before,
            after=after,
            version_after=version_after,
            import_job_id=session.info.get("import_job_id"),
            proposal_id=session.info.get("proposal_id"),
        )
    )


def apply_fields(obj: Any, values: dict[str, Any]) -> tuple[dict, dict]:
    """把 values 写到 obj 上，返回 (before, after) 中真正变化的字段。"""
    before = {k: getattr(obj, k) for k in values}
    for k, v in values.items():
        setattr(obj, k, v)
    return diff_fields(before, values)
