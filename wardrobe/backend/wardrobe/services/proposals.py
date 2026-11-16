"""修改提议（DATA_MODEL R4，Phase 2）。

受限请求方（非 web-ui / cli）或导入批次修改「已核实记录的受保护字段」时，不直接写入，而是生成
change_proposal，由人在 UI / CLI 中接受或拒绝。不受保护的字段照常生效。

R1 规定颜色、尺寸按「组」整体取值，因此同组字段合成一条提议（例如 color = code/name/hex），
接受时整组写入，避免出现半组新值、半组旧值。
"""

from typing import Any

from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AISuggestionContext, ChangeProposal, Image, ItemImage
from ..security import is_privileged
from .common import now_iso
from .protection import PROTECTED

FIELD_GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    "product": {},
    "purchase_line": {
        "color": ("color_code", "color_name", "color_hex"),
        "size": ("size_label", "size_system"),
        "match": ("product_id", "product_match"),
    },
    "wardrobe_item": {
        "color": ("color_code", "color_name", "color_hex"),
        "size": ("size_label", "size_system"),
        "status": ("status", "retired_on", "refund_amount"),
    },
}


def blocked_fields(actor: str, entity: str, obj: Any, touched: set[str]) -> set[str]:
    """需要转为提议的字段：记录已核实、请求方受限、字段受保护。"""
    if obj.verification != "verified" or is_privileged(actor):
        return set()
    return touched & PROTECTED[entity]


def group_of(entity: str, field: str) -> tuple[str, tuple[str, ...]] | None:
    for name, fields in FIELD_GROUPS[entity].items():
        if field in fields:
            return name, fields
    return None


def current_value(entity: str, obj: Any, field: str, snapshot=None) -> Any:
    """提议字段的当前值：组字段为 dict，子集合为快照列表，其他为标量。"""
    groups = FIELD_GROUPS[entity]
    if field in groups:
        return {k: getattr(obj, k) for k in groups[field]}
    if snapshot is not None:
        return snapshot(obj, field)
    return getattr(obj, field)


def create_proposal(
    session: Session,
    *,
    actor: str,
    entity: str,
    entity_id: int,
    field: str,
    current: Any,
    proposed: Any,
    reason: str | None = None,
) -> ChangeProposal:
    """新建提议；同一记录同一字段尚未处理的旧提议标记为 superseded。"""
    for old in session.scalars(
        select(ChangeProposal).where(
            ChangeProposal.entity == entity,
            ChangeProposal.entity_id == entity_id,
            ChangeProposal.field == field,
            ChangeProposal.status == "pending",
        )
    ):
        old.status = "superseded"
        old.decided_at = now_iso()
    p = ChangeProposal(
        entity=entity,
        entity_id=entity_id,
        field=field,
        current_value=current,
        proposed_value=proposed,
        reason=reason,
        actor=actor,
        import_job_id=session.info.get("import_job_id"),
        status="pending",
        created_at=now_iso(),
    )
    session.add(p)
    session.flush()
    session.info.setdefault("proposals_created", []).append(p.id)
    return p


def propose_blocked(
    session: Session, actor: str, entity: str, obj: Any, values: dict, touched: set[str]
) -> list[ChangeProposal]:
    """把 values / touched 中被保护的部分转为提议，并从两者中移除；返回生成的提议。"""
    blocked = blocked_fields(actor, entity, obj, touched)
    proposals = []
    handled: set[str] = set()
    for f in sorted(blocked):
        if f in handled:
            continue
        grp = group_of(entity, f)
        if grp:
            name, fields = grp
            current = {k: getattr(obj, k) for k in fields}
            proposed = {k: values.get(k, current[k]) for k in fields}
            keys = set(fields)
        else:
            name, current, proposed, keys = f, getattr(obj, f), values[f], {f}
        proposals.append(
            create_proposal(
                session, actor=actor, entity=entity, entity_id=obj.id, field=name, current=current, proposed=proposed
            )
        )
        handled |= keys
    for k in handled:
        values.pop(k, None)
        touched.discard(k)
    return proposals


def proposal_out(p: ChangeProposal) -> dict:
    return {
        "proposal_id": p.id,
        "entity": p.entity,
        "entity_id": p.entity_id,
        "field": p.field,
        "current_value": p.current_value,
        "proposed_value": p.proposed_value,
        "reason": p.reason,
        "actor": p.actor,
        "import_job_id": p.import_job_id,
        "status": p.status,
        "created_at": p.created_at,
        "decided_at": p.decided_at,
        # Phase 5A：主动生成的 AI 建议附带来源；历史提议为 null（新增字段，向后兼容）
        "ai_context": ai_context_out(p.ai_context),
        # Phase 5C：标签 / 分类规则建议的依据；其他提议为 null
        "rule_context": rule_context_out(p.rule_context),
    }


def rule_context_out(ctx) -> dict | None:
    if ctx is None:
        return None
    return {
        "kind": ctx.kind,
        "source": "rule_based",
        "algorithm": ctx.algorithm,
        "target_version": ctx.target_version,
        "evidence": ctx.evidence,
        "created_at": ctx.created_at,
    }


def ai_context_out(ctx: AISuggestionContext | None) -> dict | None:
    if ctx is None:
        return None
    return {
        "kind": ctx.kind,
        "source": "local_image_analysis",
        "target_version": ctx.target_version,
        "image_id": ctx.image_id,
        "image_sha256": ctx.image_sha256,
        "region": ctx.region,
        "algorithm": ctx.algorithm,
        "parameters": ctx.parameters,
        "candidate": ctx.candidate,
        "candidates": ctx.candidates,
        "created_at": ctx.created_at,
    }


def ai_context_stale_reason(session: Session, p: ChangeProposal, obj: Any) -> str | None:
    """带 AI 来源的提议在接受前的保守核对（只用于新 AI 建议，不改变普通提议的规则）。

    目标 version 自生成后有任何变化、来源图片已删除或内容不同、图片已不再关联到这件衣物，都视为过期。
    """
    ctx = p.ai_context
    if ctx is None:
        return None
    if obj.version != ctx.target_version:
        return f"衣物 version 已从 {ctx.target_version} 变为 {obj.version}"
    if ctx.image_id is None:
        return "来源图片已被删除"
    img = session.get(Image, ctx.image_id)
    if img is None or img.sha256 != ctx.image_sha256:
        return "来源图片已被删除或内容不同"
    if session.get(ItemImage, (obj.id, ctx.image_id)) is None:
        return "来源图片已不再关联到这件衣物"
    return None


def accepted_response(record: dict, applied: set[str] | list[str], proposals: list[ChangeProposal]) -> JSONResponse:
    """202：受保护字段已转为提议，其余字段（applied）已生效。"""
    return JSONResponse(
        status_code=202,
        content={
            "applied": sorted(applied),
            "proposed": [proposal_out(p) for p in proposals],
            "message": "记录已核实，受保护字段已转为待确认提议",
            "record": record,
        },
    )
