"""批量导入（API §10）：预览 → 提交 → 撤销。

* POST /imports：校验格式与引用 → 在保存点内完整执行一遍并回滚 → 保存逐行结果（status=previewed）。数据不变。
* POST /imports/{id}/commit：自动备份 → 重新执行 → 与预览逐行比对，不一致则 409 PREVIEW_STALE（整体回滚）。
* POST /imports/{id}/revert：冲突检查后整批撤销；重复撤销返回上次结果。
"""

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Body
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import delete, func, select

from ..errors import ApiError, not_found
from ..import_schema import FORMAT, ImportPayload, check_refs
from ..models import ImportJob, ImportRow
from ..services.common import commit, now_iso
from ..services.revert import revert_import
from ..storage.backup import BackupError, create_backup
from .deps import ActorDep, PagingDep, SessionDep, SettingsDep, page
from .import_executor import ImportExecutor, Row, summarize

router = APIRouter(prefix="/imports", tags=["imports"])


class CommitOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow_partial: bool | None = None


def _parse(raw: Any) -> ImportPayload:
    try:
        payload = ImportPayload.model_validate(raw)
    except ValidationError as exc:
        details = [{"loc": list(e["loc"]), "code": e["type"], "message": e["msg"]} for e in exc.errors()]
        raise ApiError(422, "VALIDATION_ERROR", f"{len(details)} 个字段校验失败", details) from exc
    check_refs(payload)
    return payload


def _execute(session, payload: ImportPayload, job: ImportJob) -> list[Row]:
    session.info.update({"defer_commit": True, "import_job_id": job.id, "proposals_created": []})
    try:
        return ImportExecutor(session, payload, actor=job.actor).run()
    finally:
        session.info.update({"defer_commit": False, "import_job_id": None})


def _save_rows(session, job: ImportJob, rows: list[Row]) -> None:
    session.execute(delete(ImportRow).where(ImportRow.job_id == job.id))
    for r in rows:
        session.add(
            ImportRow(
                job_id=job.id, row_index=r.index, entity=r.entity, ref=r.ref, action=r.action, target_id=r.target_id,
                match_reason=r.match_reason, normalized=r.normalized, diff=r.diff or None, errors=r.errors,
                warnings=r.warnings,
            )
        )  # fmt: skip


def _row_out(r: ImportRow) -> dict:
    return {
        "row_index": r.row_index,
        "entity": r.entity,
        "ref": r.ref,
        "action": r.action,
        "target_id": r.target_id,
        "match_reason": r.match_reason,
        "diff": r.diff or {},
        "errors": r.errors,
        "warnings": r.warnings,
    }


def _job_out(session, job: ImportJob, *, with_rows: bool = False) -> dict:
    out = {
        "job_id": job.id,
        "status": job.status,
        "actor": job.actor,
        "source_label": job.source_label,
        "options": job.options,
        "summary": job.summary,
        "can_commit": job.status == "previewed" and _can_commit(job.summary, job.options),
        "created_at": job.created_at,
        "committed_at": job.committed_at,
        "reverted_at": job.reverted_at,
        "backup_file": job.backup_file,
        "payload_sha256": job.payload_sha256,
    }
    if with_rows:
        rows = session.scalars(select(ImportRow).where(ImportRow.job_id == job.id).order_by(ImportRow.row_index))
        out["rows"] = [_row_out(r) for r in rows]
    return out


def _can_commit(summary: dict, options: dict) -> bool:
    return summary.get("error", 0) == 0 or bool(options.get("allow_partial"))


def _get_job(session, job_id: int) -> ImportJob:
    job = session.get(ImportJob, job_id)
    if job is None:
        raise not_found("import_job", job_id)
    return job


@router.get("/schema")
def import_schema():
    """导入格式的 JSON Schema。AI 生成导入数据前可先读取。"""
    return {"format": FORMAT, "schema": ImportPayload.model_json_schema()}


@router.post("", status_code=201)
def preview_import(
    session: SessionDep,
    actor: ActorDep,
    raw: dict = Body(..., description="wardrobe.import/v1 JSON，见 GET /api/v1/imports/schema"),
):
    payload = _parse(raw)
    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(canonical.encode()).hexdigest()
    job = ImportJob(
        status="previewed", actor=actor, source_label=payload.source_label, payload_sha256=sha, payload=canonical,
        options=payload.options.model_dump(), summary={}, created_at=now_iso(),
    )  # fmt: skip
    session.add(job)
    session.flush()

    nested = session.begin_nested()
    try:
        rows = _execute(session, payload, job)
    finally:
        nested.rollback()  # 预览不改变任何数据
    session.info["proposals_created"] = []

    summary = summarize(rows)
    job_warnings = []
    earlier = session.scalar(
        select(ImportJob.id).where(
            ImportJob.payload_sha256 == sha, ImportJob.status == "committed", ImportJob.id != job.id
        )
    )
    if earlier:
        job_warnings.append({"code": "duplicate_payload", "message": f"相同内容已在导入批次 {earlier} 中提交过"})
    summary["job_warnings"] = job_warnings
    job.summary = summary
    for r in rows:
        if r.action == "create":
            r.target_id = None  # 预览中新建记录的 id 没有意义
    _save_rows(session, job, rows)
    commit(session)
    return _job_out(session, job, with_rows=True)


@router.get("")
def list_imports(session: SessionDep, paging: PagingDep, status: str | None = None):
    limit, offset = paging
    q = select(ImportJob)
    if status:
        q = q.where(ImportJob.status == status)
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rows = session.scalars(q.order_by(ImportJob.id.desc()).limit(limit).offset(offset))
    return page([_job_out(session, j) for j in rows], total, limit, offset)


@router.get("/{job_id}")
def get_import(job_id: int, session: SessionDep):
    return _job_out(session, _get_job(session, job_id))


@router.get("/{job_id}/rows")
def get_import_rows(job_id: int, session: SessionDep, action: str | None = None, entity: str | None = None):
    _get_job(session, job_id)
    q = select(ImportRow).where(ImportRow.job_id == job_id)
    if action:
        q = q.where(ImportRow.action == action)
    if entity:
        q = q.where(ImportRow.entity == entity)
    return {"items": [_row_out(r) for r in session.scalars(q.order_by(ImportRow.row_index))]}


@router.post("/{job_id}/commit")
def commit_import(job_id: int, session: SessionDep, settings: SettingsDep, body: CommitOptions | None = None):
    job = _get_job(session, job_id)
    if job.status != "previewed":
        raise ApiError(409, "IMPORT_NOT_PREVIEWED", f"导入批次 {job.id} 的状态是 {job.status}，不能提交")
    options = dict(job.options)
    if body is not None and body.allow_partial is not None:
        options["allow_partial"] = body.allow_partial
    payload = _parse(json.loads(job.payload))
    payload.options.allow_partial = options["allow_partial"]
    preview_rows = list(
        session.scalars(select(ImportRow).where(ImportRow.job_id == job.id).order_by(ImportRow.row_index))
    )

    try:
        backup = create_backup(settings, f"pre-import-{job.id}")
    except BackupError as exc:
        raise ApiError(500, "BACKUP_FAILED", f"提交前自动备份失败，未导入：{exc}") from exc

    rows = _execute(session, payload, job)
    expected = [
        (r.entity, r.ref, r.action, r.match_reason, None if r.action == "create" else r.target_id,
         (r.diff or {}).get("basis_version") if r.action in ("update", "propose") else None)
        for r in preview_rows
    ]  # fmt: skip
    actual = [r.plan_key() for r in rows]
    if expected != actual:
        changed = [i for i, (a, b) in enumerate(zip(expected, actual, strict=False)) if a != b]
        raise ApiError(
            409, "PREVIEW_STALE", "预览之后数据已经变化，提交结果会与预览不同；请重新预览",
            [{"changed_rows": changed or list(range(min(len(expected), len(actual)), max(len(expected), len(actual))))}],
        )  # fmt: skip
    summary = summarize(rows)
    if summary["error"] and not options["allow_partial"]:
        raise ApiError(
            409, "IMPORT_HAS_ERRORS", f"有 {summary['error']} 行出错；修正后重新预览，或以 allow_partial 提交"
        )

    summary["job_warnings"] = job.summary.get("job_warnings", [])
    job.summary = summary
    job.options = options
    job.status = "committed"
    job.committed_at = now_iso()
    job.backup_file = backup.name
    _save_rows(session, job, rows)
    commit(session)
    return _job_out(session, job, with_rows=True)


@router.post("/{job_id}/revert")
def revert_import_route(job_id: int, session: SessionDep, settings: SettingsDep, actor: ActorDep):
    job = _get_job(session, job_id)
    if job.status == "reverted":
        return {**_job_out(session, job), "revert": job.summary.get("revert"), "already_reverted": True}
    if job.status != "committed":
        raise ApiError(409, "IMPORT_NOT_COMMITTED", f"导入批次 {job.id} 的状态是 {job.status}，没有可撤销的内容")
    session.info["import_job_id"] = job.id
    try:
        result = revert_import(session, job.id, actor)  # 冲突时抛 409，此前不做任何修改
    finally:
        session.info["import_job_id"] = None
    # 备份通过独立连接读取已提交的数据，因此得到的是撤销之前的状态（本事务尚未提交）
    try:
        backup = create_backup(settings, f"pre-revert-{job.id}")
    except BackupError as exc:
        raise ApiError(500, "BACKUP_FAILED", f"撤销前自动备份失败，未撤销：{exc}") from exc
    result["backup_file"] = backup.name
    job.summary = {**job.summary, "revert": result}
    job.status = "reverted"
    job.reverted_at = now_iso()
    commit(session)
    return {**_job_out(session, job), "revert": result, "already_reverted": False}


@router.delete("/{job_id}")
def discard_import(job_id: int, session: SessionDep):
    job = _get_job(session, job_id)
    if job.status != "previewed":
        raise ApiError(409, "IMPORT_NOT_PREVIEWED", f"只能丢弃未提交的预览，当前状态 {job.status}")
    job.status = "discarded"
    commit(session)
    return _job_out(session, job)
