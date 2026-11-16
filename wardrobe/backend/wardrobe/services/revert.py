"""导入撤销（DATA_MODEL 5.1，BUG-003）。

整批、单事务、全有或全无：
1. 冲突检查（任何修改之前）：
   * 该批次触及的记录在提交后又被别的操作修改过（审计日志中有批次之外的非 system 记录；
     接受本批次提议产生的修改除外——那是人的决定，保留）；
   * 该批次新建的记录被批次之外的记录引用（明细、衣物、穿搭）。
2. 按审计日志逆序执行逆操作：
   * 批次新建的穿搭 / 衣物 / 购买明细 / 购买记录 / 商品：物理删除（新建时的完整快照保留在审计日志中）；
   * 批次修改的已有记录：恢复修改前的值（标量、子集合、标签、图片关联、穿搭条目），version + 1；
   * 批次隐式新建的标签：已无引用则删除，仍被批次外记录使用则保留；
   * 本批次的待处理提议改为 withdrawn；已接受 / 已拒绝的提议保持不变（人的决定）。
3. 重算受影响衣物的有效颜色/尺寸与搜索索引，写 op=revert 审计日志。
"""

from collections import defaultdict

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import (
    ChangeLog,
    ChangeProposal,
    ItemImage,
    ItemTag,
    MaterialComponent,
    Outfit,
    OutfitImage,
    OutfitItem,
    OutfitTag,
    Product,
    ProductIdentifier,
    ProductImage,
    Purchase,
    PurchaseLine,
    Tag,
    WardrobeItem,
)
from ..schemas import ColorIn, SizeIn
from .common import log_change, now_iso, touch
from .items import validate_item_links
from .products import build_colors, build_sizes, get_or_create_tags, replace_collection
from .resolve import items_of_product, refresh_items
from .text import normalize_identifier

MODELS = {
    "product": Product,
    "purchase": Purchase,
    "purchase_line": PurchaseLine,
    "wardrobe_item": WardrobeItem,
    "outfit": Outfit,
    "tag": Tag,
}
PRODUCT_COLLECTIONS = ("identifiers", "colors", "sizes", "materials", "images")


def _job_logs(session: Session, job_id: int) -> list[ChangeLog]:
    return list(
        session.scalars(
            select(ChangeLog).where(ChangeLog.import_job_id == job_id, ChangeLog.op != "revert").order_by(ChangeLog.id)
        )
    )


def _created(logs: list[ChangeLog]) -> dict[str, set[int]]:
    out: dict[str, set[int]] = defaultdict(set)
    for log in logs:
        if log.op == "create":
            out[log.entity].add(log.entity_id)
        if log.entity == "purchase" and log.after and "lines_added" in log.after:
            out["purchase_line"].update(log.after["lines_added"])
    return out


def find_conflicts(session: Session, job_id: int) -> list[dict]:
    logs = _job_logs(session, job_id)
    if not logs:
        return []
    max_id = logs[-1].id
    proposal_ids = list(session.scalars(select(ChangeProposal.id).where(ChangeProposal.import_job_id == job_id)))
    created = _created(logs)
    created["purchase_line"].update(
        session.scalars(select(PurchaseLine.id).where(PurchaseLine.purchase_id.in_(created["purchase"] or {-1})))
    )
    conflicts: list[dict] = []

    touched = {(log.entity, log.entity_id) for log in logs if log.entity in MODELS and log.entity != "tag"}
    for entity, entity_id in sorted(touched):
        later = list(
            session.scalars(
                select(ChangeLog.id).where(
                    ChangeLog.entity == entity,
                    ChangeLog.entity_id == entity_id,
                    ChangeLog.id > max_id,
                    ChangeLog.actor != "system",
                    or_(ChangeLog.import_job_id.is_(None), ChangeLog.import_job_id != job_id),
                    or_(ChangeLog.proposal_id.is_(None), ChangeLog.proposal_id.not_in(proposal_ids or [-1])),
                )
            )
        )
        if later:
            conflicts.append(
                {"entity": entity, "entity_id": entity_id, "reason": "modified_after_import", "change_ids": later}
            )

    def external(entity: str, rows, reason: str):
        for rid, ref in rows:
            conflicts.append({"entity": entity, "entity_id": ref, "reason": reason, "referenced_by": rid})

    if created["product"]:
        external(
            "product",
            session.execute(
                select(PurchaseLine.id, PurchaseLine.product_id).where(
                    PurchaseLine.product_id.in_(created["product"]),
                    PurchaseLine.id.not_in(created["purchase_line"] or {-1}),
                )
            ),
            "used_by_purchase_line_outside_import",
        )
        external(
            "product",
            session.execute(
                select(WardrobeItem.id, WardrobeItem.product_id).where(
                    WardrobeItem.product_id.in_(created["product"]),
                    WardrobeItem.id.not_in(created["wardrobe_item"] or {-1}),
                )
            ),
            "used_by_item_outside_import",
        )
    if created["purchase_line"]:
        external(
            "purchase_line",
            session.execute(
                select(WardrobeItem.id, WardrobeItem.purchase_line_id).where(
                    WardrobeItem.purchase_line_id.in_(created["purchase_line"]),
                    WardrobeItem.id.not_in(created["wardrobe_item"] or {-1}),
                )
            ),
            "used_by_item_outside_import",
        )
    if created["wardrobe_item"]:
        external(
            "wardrobe_item",
            session.execute(
                select(OutfitItem.outfit_id, OutfitItem.item_id).where(
                    OutfitItem.item_id.in_(created["wardrobe_item"]),
                    OutfitItem.outfit_id.not_in(created["outfit"] or {-1}),
                )
            ),
            "used_by_outfit_outside_import",
        )
    return conflicts


# ───────────── 逆操作 ─────────────


def _restore_product_collection(session: Session, product: Product, name: str, rows: list[dict]) -> None:
    now = now_iso()
    if name == "identifiers":
        new = [
            ProductIdentifier(scheme=r["scheme"], value=r["value"], value_norm=normalize_identifier(r["value"]),
                              source=r.get("source"), created_at=now)
            for r in rows
        ]  # fmt: skip
    elif name == "colors":
        new = build_colors([ColorIn(**r) for r in rows])
    elif name == "sizes":
        new = build_sizes([SizeIn(**r) for r in rows])
    elif name == "materials":
        new = [MaterialComponent(**r, sort_order=i) for i, r in enumerate(rows)]
    else:  # images
        new = [ProductImage(**r) for r in rows]
    replace_collection(session, product, name, new)


def _undo_update(session: Session, log: ChangeLog, actor: str, affected_items: set[int]) -> None:
    obj = session.get(MODELS[log.entity], log.entity_id)
    before = dict(log.before or {})
    after = log.after or {}
    restored: dict = {}

    if log.entity == "product":
        for name in PRODUCT_COLLECTIONS:
            if name in before:
                _restore_product_collection(session, obj, name, before.pop(name))
                restored[name] = "restored"
        affected_items.update(i.id for i in items_of_product(session, obj.id))
    elif log.entity == "purchase":
        for line_id in after.get("lines_added", []):
            line = session.get(PurchaseLine, line_id)
            if line is not None:
                obj.lines.remove(line)
                restored.setdefault("lines_removed", []).append(line_id)
    elif log.entity == "purchase_line":
        affected_items.update(session.scalars(select(WardrobeItem.id).where(WardrobeItem.purchase_line_id == obj.id)))
    elif log.entity == "wardrobe_item":
        affected_items.add(obj.id)
        if "tags" in before:
            obj.tags = get_or_create_tags(session, before.pop("tags"))
            restored["tags"] = [t.name for t in obj.tags]
        for image_id in after.get("images_added", []):
            link = session.get(ItemImage, (obj.id, image_id))
            if link is not None:
                obj.images.remove(link)
                restored.setdefault("images_removed", []).append(image_id)
    elif log.entity == "outfit":
        if "items" in before:
            obj.items.clear()
            session.flush()
            obj.items = [OutfitItem(item_id=x["item_id"], slot=x["slot"], sort_order=i)
                         for i, x in enumerate(before.pop("items"))]  # fmt: skip
            restored["items"] = "restored"
        if "tags" in before:
            obj.tags = get_or_create_tags(session, before.pop("tags"))
            restored["tags"] = [t.name for t in obj.tags]
        for image_id in after.get("images_added", []):
            link = session.get(OutfitImage, (obj.id, image_id))
            if link is not None:
                obj.images.remove(link)
                restored.setdefault("images_removed", []).append(image_id)

    for k, v in before.items():  # 剩下的都是标量字段
        restored[k] = v
        setattr(obj, k, v)
    touch(obj)
    session.flush()
    if log.entity == "wardrobe_item" and {"product_id", "purchase_line_id"} & set(restored):
        # 恢复原来的商品 / 明细关联前重新校验：原明细可能已被批次外的衣物占满（BUG-014 相关）
        session.refresh(obj, ["product", "purchase_line"])
        try:
            validate_item_links(session, obj.product, obj.purchase_line, exclude_item_id=obj.id)
        except ApiError as exc:
            raise ApiError(
                409, "REVERT_CONFLICT", f"无法恢复衣物 {obj.id} 原来的关联：{exc.message}，未做任何撤销",
                [{"entity": "wardrobe_item", "entity_id": obj.id, "reason": "link_no_longer_valid",
                  "cause": exc.code}],
            ) from exc  # fmt: skip
    log_change(session, actor=actor, entity=log.entity, entity_id=obj.id, op="revert",
               before=None, after={"undo_change": log.id, **restored}, version_after=obj.version)  # fmt: skip


def _delete_created(session: Session, log: ChangeLog, actor: str, summary: dict) -> None:
    obj = session.get(MODELS[log.entity], log.entity_id)
    if obj is None:
        return
    if log.entity == "tag":
        in_use = session.scalar(select(ItemTag.item_id).where(ItemTag.tag_id == obj.id).limit(1)) or session.scalar(
            select(OutfitTag.outfit_id).where(OutfitTag.tag_id == obj.id).limit(1)
        )
        if in_use:
            summary["tags_kept"].append(obj.name)
            return
    if log.entity == "wardrobe_item":
        session.execute(text("DELETE FROM search_index WHERE rowid = :id"), {"id": obj.id})
    session.delete(obj)
    session.flush()
    summary["deleted"][log.entity] = summary["deleted"].get(log.entity, 0) + 1
    log_change(session, actor=actor, entity=log.entity, entity_id=log.entity_id, op="revert",
               before=None, after={"undo_change": log.id, "deleted": True})  # fmt: skip


def revert_import(session: Session, job_id: int, actor: str) -> dict:
    conflicts = find_conflicts(session, job_id)
    if conflicts:
        raise ApiError(409, "REVERT_CONFLICT", f"有 {len(conflicts)} 处在导入之后被修改或引用，未做任何撤销", conflicts)
    logs = _job_logs(session, job_id)
    created = _created(logs)
    summary: dict = {"deleted": {}, "restored": 0, "tags_kept": [], "proposals_withdrawn": 0, "proposals_kept": []}
    affected_items: set[int] = set()
    tag_logs = []

    for log in reversed(logs):
        if log.actor == "system" and log.entity != "tag":
            continue  # 缓存重算，最后统一重算
        if log.entity == "tag" and log.op == "create":
            tag_logs.append(log)  # 标签放到最后：先删掉引用它的批次记录
            continue
        if log.op == "create":
            _delete_created(session, log, actor, summary)
        elif log.op == "update":
            if log.entity_id in created.get(log.entity, set()):
                continue  # 记录会被整体删除，中间修改不需要单独撤销
            _undo_update(session, log, actor, affected_items)
            summary["restored"] += 1
    for log in tag_logs:
        _delete_created(session, log, actor, summary)

    for p in session.scalars(select(ChangeProposal).where(ChangeProposal.import_job_id == job_id)):
        if p.status == "pending":
            p.status = "withdrawn"
            p.decided_at = now_iso()
            summary["proposals_withdrawn"] += 1
        else:
            summary["proposals_kept"].append({"proposal_id": p.id, "status": p.status})

    items = [i for i in (session.get(WardrobeItem, x) for x in affected_items) if i is not None]
    refresh_items(session, items, upstream_actor=actor)
    return summary
