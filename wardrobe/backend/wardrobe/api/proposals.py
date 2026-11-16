"""修改提议的查看、接受与拒绝（只允许 web-ui / cli 决定）。

接受 = 以接受者身份、按记录当前 version 重放原来的写操作（同一个 API 函数），
因此接受时会重新执行全部校验（容量、依赖、唯一性、默认色等）。
"""

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from ..errors import ApiError, not_found
from ..models import ChangeProposal, Product, PurchaseLine, WardrobeItem
from ..schemas import ColorsPut, IdentifierAdd, ItemPatch, LinePatch, MaterialsPut, ProductPatch, SizesPut, TagsPut
from ..services import products as product_svc
from ..services.common import commit, now_iso
from ..services.proposals import FIELD_GROUPS, ai_context_stale_reason, current_value, proposal_out
from ..services.protection import guard_privileged
from ..services.tag_category_suggestions import missing_tags, rule_context_stale_reason
from . import items as items_api
from . import products as products_api
from . import purchases as purchases_api
from .deps import ActorDep, PagingDep, SessionDep, page

router = APIRouter(prefix="/proposals", tags=["proposals"])

MODELS = {"product": Product, "purchase_line": PurchaseLine, "wardrobe_item": WardrobeItem}
COLLECTIONS = ("identifiers", "colors", "sizes", "materials")


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(None, description="可选的处理说明")


class BulkDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[int] = Field(min_length=1, max_length=200)
    decision: Literal["accept", "reject"]


def _target(session, p: ChangeProposal):
    obj = session.get(MODELS[p.entity], p.entity_id)
    if obj is None or getattr(obj, "deleted_at", None) is not None:
        raise ApiError(409, "PROPOSAL_STALE", f"提议 {p.id} 的目标记录已不存在或已删除")
    return obj


def _current(p: ChangeProposal, obj):
    if p.entity == "product" and p.field in COLLECTIONS:
        return product_svc.collection_snapshot(obj, p.field)
    return current_value(p.entity, obj, p.field)


def _apply(session, p: ChangeProposal, obj, actor: str) -> None:
    """以接受者身份重放写操作。所有 API 函数在 defer_commit 下只 flush，由本请求统一提交。"""
    value = p.proposed_value
    if p.entity == "product":
        pid = obj.id
        if p.field == "colors":
            products_api.put_colors(pid, ColorsPut(version=obj.version, colors=value), session, actor)
        elif p.field == "sizes":
            products_api.put_sizes(pid, SizesPut(version=obj.version, sizes=value), session, actor)
        elif p.field == "materials":
            products_api.put_materials(pid, MaterialsPut(version=obj.version, materials=value), session, actor)
        elif p.field == "identifiers":
            existing = {(i["scheme"], i["value"]) for i in product_svc.collection_snapshot(obj, "identifiers")}
            for ident in value:
                if (ident["scheme"], ident["value"]) not in existing:
                    products_api.add_identifier(pid, IdentifierAdd(version=obj.version, **ident), session, actor)
        else:
            products_api.patch_product(pid, ProductPatch(version=obj.version, **{p.field: value}), session, actor)
        return

    if p.entity == "wardrobe_item" and p.field == "tags_add":
        # 只追加仍缺少的标签；全部已存在时不写入（不提升 version）
        add = missing_tags(obj, value)
        if add:
            items_api.put_tags(
                obj.id, TagsPut(version=obj.version, tags=[t.name for t in obj.tags] + add), session, actor
            )
        return

    fields = value if p.field in FIELD_GROUPS[p.entity] else {p.field: value}
    if p.entity == "purchase_line":
        fields = dict(fields)
        if fields.get("product_id") is None:
            fields.pop("product_match", None)  # 解除匹配时由服务层设为 unmatched
        purchases_api.patch_line(obj.id, LinePatch(version=obj.version, **fields), session, actor)
    else:
        items_api.patch_item(obj.id, ItemPatch(version=obj.version, **fields), session, actor)


def _decide(session, proposal_id: int, decision: str, actor: str) -> ChangeProposal:
    p = session.get(ChangeProposal, proposal_id)
    if p is None:
        raise not_found("proposal", proposal_id)
    if p.status != "pending":
        raise ApiError(409, "PROPOSAL_NOT_PENDING", f"提议 {p.id} 的状态是 {p.status}，不能再处理")
    if decision == "accept":
        obj = _target(session, p)
        # 追加标签是幂等的「只追加」操作：其他标签变化不影响它，因此不比较当前值
        if p.field != "tags_add" and _current(p, obj) != p.current_value:
            raise ApiError(
                409,
                "PROPOSAL_STALE",
                f"提议 {p.id} 生成后记录已被修改，请重新确认",
                [{"proposal_current_value": p.current_value, "record_current_value": _current(p, obj)}],
            )
        stale = ai_context_stale_reason(session, p, obj) or rule_context_stale_reason(p, obj)
        if stale:
            raise ApiError(409, "PROPOSAL_STALE", f"提议 {p.id} 的来源已变化（{stale}），请重新分析后再生成建议")
        previous = session.info.get("proposal_id")
        session.info["proposal_id"] = p.id
        try:
            _apply(session, p, obj, actor)
        finally:
            session.info["proposal_id"] = previous
    p.status = "accepted" if decision == "accept" else "rejected"
    p.decided_at = now_iso()
    session.flush()
    return p


@router.get("")
def list_proposals(
    session: SessionDep,
    paging: PagingDep,
    status: str | None = "pending",
    entity: str | None = None,
    entity_id: int | None = None,
    import_job_id: int | None = None,
):
    limit, offset = paging
    q = select(ChangeProposal)
    if status and status != "all":
        q = q.where(ChangeProposal.status == status)
    if entity:
        q = q.where(ChangeProposal.entity == entity)
    if entity_id is not None:
        q = q.where(ChangeProposal.entity_id == entity_id)
    if import_job_id is not None:
        q = q.where(ChangeProposal.import_job_id == import_job_id)
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rows = session.scalars(q.order_by(ChangeProposal.id.desc()).limit(limit).offset(offset))
    return page([proposal_out(p) for p in rows], total, limit, offset)


@router.get("/{proposal_id}")
def get_proposal(proposal_id: int, session: SessionDep):
    p = session.get(ChangeProposal, proposal_id)
    if p is None:
        raise not_found("proposal", proposal_id)
    return proposal_out(p)


def _single(session, proposal_id: int, decision: str, actor: str):
    guard_privileged(actor, "接受/拒绝修改提议")
    session.info["defer_commit"] = True
    p = _decide(session, proposal_id, decision, actor)
    session.info["defer_commit"] = False
    commit(session)
    return proposal_out(p)


@router.post("/{proposal_id}/accept")
def accept_proposal(proposal_id: int, session: SessionDep, actor: ActorDep, body: Decision | None = None):
    return _single(session, proposal_id, "accept", actor)


@router.post("/{proposal_id}/reject")
def reject_proposal(proposal_id: int, session: SessionDep, actor: ActorDep, body: Decision | None = None):
    return _single(session, proposal_id, "reject", actor)


@router.post("/bulk")
def bulk_decide(body: BulkDecision, session: SessionDep, actor: ActorDep):
    """逐条处理；每条在自己的保存点内，失败的条目不影响其他条目，结果逐条返回。"""
    guard_privileged(actor, "接受/拒绝修改提议")
    session.info["defer_commit"] = True
    results = []
    for pid in body.ids:
        try:
            with session.begin_nested():
                p = _decide(session, pid, body.decision, actor)
            results.append({"proposal_id": pid, "ok": True, "status": p.status})
        except ApiError as exc:
            results.append({"proposal_id": pid, "ok": False, "error": {"code": exc.code, "message": exc.message}})
    session.info["defer_commit"] = False
    commit(session)
    ok_count = sum(r["ok"] for r in results)
    return JSONResponse({"results": results, "succeeded": ok_count, "failed": len(results) - ok_count})
