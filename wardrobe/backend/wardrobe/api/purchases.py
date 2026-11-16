"""购买 Purchase / PurchaseLine。购买记录是事实，退货不修改它（R5）。"""

from datetime import date
from difflib import SequenceMatcher

from fastapi import APIRouter, Response
from sqlalchemy import func, or_, select

from ..errors import ApiError, validation
from ..models import Product, ProductIdentifier, Purchase, PurchaseLine, WardrobeItem
from ..schemas import LineAdd, LineIn, LinePatch, MatchIn, PurchaseCreate, PurchasePatch, Versioned
from ..services.common import commit, get_or_404, log_change, now_iso, require_version, touch
from ..services.items import create_item
from ..services.proposals import accepted_response, propose_blocked
from ..services.protection import DELETE, changed_fields, guard, guard_privileged
from ..services.resolve import items_of_line, refresh_items
from ..services.text import normalize_identifier, normalize_text
from .deps import ActorDep, IfMatch, PagingDep, SessionDep, page
from .serializers import line_out, product_summary, purchase_out

router = APIRouter(tags=["purchases"])

LINE_FIELDS = (
    "product_id", "product_match", "item_code_raw", "name_raw", "color_code", "color_name", "color_hex",
    "size_label", "size_system", "quantity", "unit_price", "discount_amount", "notes", "attributes",
)  # fmt: skip


def _product_or_422(session, product_id: int, loc: list) -> Product:
    product = session.get(Product, product_id)
    if product is None or product.deleted_at is not None:
        raise validation(loc, "not_found", f"商品 {product_id} 不存在")
    return product


def _active_items(session, line_id: int) -> list[WardrobeItem]:
    return [i for i in items_of_line(session, line_id) if i.deleted_at is None]


def _build_line(session, body: LineIn, loc: list) -> PurchaseLine:
    if body.product_match is not None and body.product_id is None:
        raise validation([*loc, "product_match"], "requires_product", "设置 product_match 时必须同时给出 product_id")
    if body.product_id is not None:
        _product_or_422(session, body.product_id, [*loc, "product_id"])
    now = now_iso()
    values = body.model_dump(include=set(LINE_FIELDS))
    values["product_match"] = (body.product_match or "confirmed") if body.product_id else "unmatched"
    values["attributes"] = body.attributes or {}
    return PurchaseLine(**values, created_at=now, updated_at=now, version=1)


def _create_line_items(session, actor: str, line: PurchaseLine, loc: list) -> None:
    if line.product_id is None:
        raise validation(
            [*loc, "product_id"], "required", "create_items=true 时每行都需要 product_id（衣物必须属于一个商品）"
        )
    for _ in range(line.quantity):
        create_item(session, actor=actor, product=line.product, line=line)


def _check_duplicate_order(session, store_name, order_no, exclude_id: int | None = None) -> None:
    if not order_no:
        return
    q = select(Purchase.id).where(
        Purchase.order_no == order_no,
        Purchase.deleted_at.is_(None),
        Purchase.store_name.is_(None) if store_name is None else Purchase.store_name == store_name,
    )
    if exclude_id is not None:
        q = q.where(Purchase.id != exclude_id)
    existing = session.scalar(q)
    if existing:
        raise ApiError(409, "DUPLICATE", f"已存在相同店铺与订单号的购买记录 {existing}", [{"existing_id": existing}])


@router.get("/purchases")
def list_purchases(
    session: SessionDep,
    paging: PagingDep,
    date_from: date | None = None,
    date_to: date | None = None,
    channel: str | None = None,
    store: str | None = None,
    q: str | None = None,
):
    limit, offset = paging
    query = select(Purchase).where(Purchase.deleted_at.is_(None))
    if date_from:
        query = query.where(Purchase.purchased_on >= date_from.isoformat())
    if date_to:
        query = query.where(Purchase.purchased_on <= date_to.isoformat())
    if channel:
        query = query.where(Purchase.channel == channel)
    if store:
        query = query.where(Purchase.store_name.like(f"%{store}%"))
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                Purchase.order_no.like(like),
                Purchase.notes.like(like),
                Purchase.id.in_(
                    select(PurchaseLine.purchase_id).where(
                        or_(PurchaseLine.name_raw.like(like), PurchaseLine.item_code_raw.like(like))
                    )
                ),
            )
        )
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.scalars(query.order_by(Purchase.purchased_on.desc(), Purchase.id.desc()).limit(limit).offset(offset))
    return page([purchase_out(session, p) for p in rows], total, limit, offset)


@router.post("/purchases", status_code=201)
def create_purchase(body: PurchaseCreate, session: SessionDep, actor: ActorDep):
    _check_duplicate_order(session, body.store_name, body.order_no)
    now = now_iso()
    purchase = Purchase(
        **body.model_dump(exclude={"lines", "create_items", "purchased_on"}),
        purchased_on=body.purchased_on.isoformat(), created_at=now, updated_at=now, version=1,
    )  # fmt: skip
    session.add(purchase)
    for i, ln in enumerate(body.lines):
        purchase.lines.append(_build_line(session, ln, ["lines", i]))
    session.flush()
    log_change(
        session, actor=actor, entity="purchase", entity_id=purchase.id, op="create",
        after=body.model_dump(mode="json", exclude_none=True), version_after=purchase.version,
    )  # fmt: skip
    if body.create_items:
        for i, line in enumerate(purchase.lines):
            _create_line_items(session, actor, line, ["lines", i])
    commit(session)
    return purchase_out(session, purchase)


@router.get("/purchases/{purchase_id}")
def get_purchase(purchase_id: int, session: SessionDep):
    return purchase_out(session, get_or_404(session, Purchase, purchase_id))


@router.patch("/purchases/{purchase_id}")
def patch_purchase(purchase_id: int, body: PurchasePatch, session: SessionDep, actor: ActorDep,
                   if_match: IfMatch = None):  # fmt: skip
    purchase = get_or_404(session, Purchase, purchase_id)
    require_version(purchase, body.version, if_match)
    values = body.model_dump(mode="json", exclude_unset=True, exclude={"version"})
    if "purchased_on" in values and values["purchased_on"] is None:
        raise validation(["purchased_on"], "required", "purchased_on 不能为空")
    if {"store_name", "order_no"} & values.keys():
        _check_duplicate_order(
            session, values.get("store_name", purchase.store_name), values.get("order_no", purchase.order_no),
            purchase.id,
        )  # fmt: skip
    touched = changed_fields(purchase, values)
    if touched:
        before = {k: getattr(purchase, k) for k in touched}
        for k in touched:
            setattr(purchase, k, values[k])
        touch(purchase)
        log_change(
            session, actor=actor, entity="purchase", entity_id=purchase.id, op="update",
            before=before, after={k: values[k] for k in touched}, version_after=purchase.version,
        )  # fmt: skip
        commit(session)
    return purchase_out(session, purchase)


@router.delete("/purchases/{purchase_id}", status_code=204)
def delete_purchase(purchase_id: int, session: SessionDep, actor: ActorDep, if_match: IfMatch = None,
                    version: int | None = None):  # fmt: skip
    purchase = get_or_404(session, Purchase, purchase_id)
    require_version(purchase, version, if_match)
    for line in purchase.lines:
        guard(actor, "purchase_line", line, {DELETE})
        if _active_items(session, line.id):
            raise ApiError(409, "IN_USE", f"购买明细 {line.id} 仍关联衣物，不能删除购买记录")
    purchase.deleted_at = now_iso()
    touch(purchase)
    log_change(
        session, actor=actor, entity="purchase", entity_id=purchase.id, op="delete", version_after=purchase.version
    )
    commit(session)
    return Response(status_code=204)


@router.post("/purchases/{purchase_id}/restore")
def restore_purchase(purchase_id: int, body: Versioned, session: SessionDep, actor: ActorDep,
                     if_match: IfMatch = None):  # fmt: skip
    """撤销购买记录的软删除。店铺 + 订单号唯一性按当前数据重新检查。"""
    purchase = get_or_404(session, Purchase, purchase_id, include_deleted=True)
    if purchase.deleted_at is None:
        raise ApiError(409, "NOT_DELETED", f"购买记录 {purchase.id} 没有被删除")
    require_version(purchase, body.version, if_match)
    for line in purchase.lines:
        guard(actor, "purchase_line", line, {DELETE})
    _check_duplicate_order(session, purchase.store_name, purchase.order_no, purchase.id)
    purchase.deleted_at = None
    touch(purchase)
    log_change(
        session, actor=actor, entity="purchase", entity_id=purchase.id, op="restore", version_after=purchase.version
    )
    commit(session)
    return purchase_out(session, purchase)


@router.post("/purchases/{purchase_id}/lines", status_code=201)
def add_line(purchase_id: int, body: LineAdd, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    purchase = get_or_404(session, Purchase, purchase_id)
    require_version(purchase, body.version, if_match)
    line = _build_line(session, body, [])
    purchase.lines.append(line)
    touch(purchase)
    session.flush()
    log_change(
        session, actor=actor, entity="purchase", entity_id=purchase.id, op="update",
        after={"lines_added": [line.id]}, version_after=purchase.version,
    )  # fmt: skip
    if body.create_items:
        _create_line_items(session, actor, line, [])
    commit(session)
    return purchase_out(session, purchase)


@router.get("/purchase-lines/{line_id}")
def get_line(line_id: int, session: SessionDep):
    return line_out(session, get_or_404(session, PurchaseLine, line_id))


def _apply_line_change(session, line: PurchaseLine, values: dict, actor: str) -> tuple[set[str], list]:
    """购买明细修改的公共部分：保护（转提议）、数量/商品一致性、审计、重算衣物。

    返回 (实际生效的字段, 生成的提议)。
    """
    if "product_id" in values:
        if values["product_id"] is None:
            values["product_match"] = "unmatched"
        else:
            _product_or_422(session, values["product_id"], ["product_id"])
            values.setdefault("product_match", "confirmed")
    elif "product_match" in values and line.product_id is None:
        raise validation(["product_match"], "requires_product", "该明细尚未关联商品")
    touched = changed_fields(line, values)
    proposals = propose_blocked(session, actor, "purchase_line", line, values, touched)
    if not touched:
        return touched, proposals
    items = _active_items(session, line.id)
    if "product_id" in touched and any(i.product_id != values["product_id"] for i in items):
        raise ApiError(
            409, "IN_USE", "该明细已生成衣物，且衣物属于其他商品；请先修改或解除衣物的关联",
            [{"item_ids": [i.id for i in items]}],
        )  # fmt: skip
    if "quantity" in touched and values["quantity"] < len(items):
        raise validation(["quantity"], "less_than_items", f"数量不能少于已生成的衣物件数 {len(items)}")
    before = {k: getattr(line, k) for k in touched}
    for k in touched:
        setattr(line, k, values[k])
    touch(line)
    session.flush()
    log_change(
        session, actor=actor, entity="purchase_line", entity_id=line.id, op="update",
        before=before, after={k: values[k] for k in touched}, version_after=line.version,
    )  # fmt: skip
    session.refresh(line, ["product"])
    refresh_items(session, items_of_line(session, line.id), upstream_actor=actor)
    return touched, proposals


def _line_response(session, line: PurchaseLine, applied: set[str], proposals: list):
    commit(session)
    if proposals:
        return accepted_response(line_out(session, line), applied, proposals)
    return line_out(session, line)


@router.get("/purchase-lines/{line_id}/match-candidates")
def match_candidates(line_id: int, session: SessionDep, limit: int = 10):
    """为未匹配的明细列出候选商品与理由，不写入任何数据。

    只做两种匹配：①小票商品番号与商品的 item_no 编号相同（同一编号体系）；②名称相似度。
    不会把小票编号与详情页编号互相推断（R2）。
    """
    line = get_or_404(session, PurchaseLine, line_id)
    candidates: dict[int, dict] = {}
    if line.item_code_raw:
        q = (
            select(Product)
            .join(ProductIdentifier, ProductIdentifier.product_id == Product.id)
            .where(
                Product.deleted_at.is_(None),
                ProductIdentifier.scheme == "item_no",
                ProductIdentifier.value_norm == normalize_identifier(line.item_code_raw),
            )
        )
        for p in session.scalars(q):
            candidates[p.id] = {"product": product_summary(p), "score": 1.0, "reasons": ["identifier:item_no"]}
    if line.name_raw:
        target = normalize_text(line.name_raw)
        for p in session.scalars(select(Product).where(Product.deleted_at.is_(None))):
            best = max(
                (
                    SequenceMatcher(None, target, normalize_text(n)).ratio()
                    for n in (p.name_ja, p.name_zh, p.name_en)
                    if n
                ),
                default=0.0,
            )
            if best >= 0.5:
                entry = candidates.setdefault(p.id, {"product": product_summary(p), "score": 0.0, "reasons": []})
                entry["score"] = max(entry["score"], round(best, 3))
                entry["reasons"].append(f"name_similarity:{best:.2f}")
    ranked = sorted(candidates.values(), key=lambda c: -c["score"])[: max(1, min(limit, 50))]
    return {"line_id": line.id, "current_product_id": line.product_id, "candidates": ranked}


@router.patch("/purchase-lines/{line_id}")
def patch_line(line_id: int, body: LinePatch, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    line = get_or_404(session, PurchaseLine, line_id)
    require_version(line, body.version, if_match)
    values = body.model_dump(exclude_unset=True, include=set(LINE_FIELDS))
    if "quantity" in values and values["quantity"] is None:
        raise validation(["quantity"], "required", "quantity 不能为空")
    if "attributes" in values and values["attributes"] is None:
        values["attributes"] = {}
    return _line_response(session, line, *_apply_line_change(session, line, values, actor))


@router.post("/purchase-lines/{line_id}/match")
def match_line(line_id: int, body: MatchIn, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    line = get_or_404(session, PurchaseLine, line_id)
    require_version(line, body.version, if_match)
    values = {"product_id": body.product_id, "product_match": body.product_match}
    return _line_response(session, line, *_apply_line_change(session, line, values, actor))


@router.delete("/purchase-lines/{line_id}", status_code=204)
def delete_line(line_id: int, session: SessionDep, actor: ActorDep, if_match: IfMatch = None,
                version: int | None = None):  # fmt: skip
    """删除明细属于购买记录（聚合根）的变化：需要 purchase 的 version。"""
    line = get_or_404(session, PurchaseLine, line_id)
    purchase = line.purchase
    require_version(purchase, version, if_match)
    guard(actor, "purchase_line", line, {DELETE})
    if _active_items(session, line.id):
        raise ApiError(409, "IN_USE", "该明细仍关联衣物，不能删除")
    before = {k: getattr(line, k) for k in LINE_FIELDS}
    purchase.lines.remove(line)
    touch(purchase)
    log_change(
        session, actor=actor, entity="purchase_line", entity_id=line_id, op="delete", before=before,
    )  # fmt: skip
    log_change(
        session, actor=actor, entity="purchase", entity_id=purchase.id, op="update",
        after={"lines_removed": [line_id]}, version_after=purchase.version,
    )  # fmt: skip
    commit(session)
    return Response(status_code=204)


def _set_line_verification(session, line_id: int, body: Versioned, actor: str, if_match, verified: bool):
    guard_privileged(actor, "核实/取消核实")
    line = get_or_404(session, PurchaseLine, line_id)
    require_version(line, body.version, if_match)
    line.verification = "verified" if verified else "unverified"
    line.verified_at = now_iso() if verified else None
    touch(line)
    log_change(
        session, actor=actor, entity="purchase_line", entity_id=line.id, op="verify" if verified else "unverify",
        version_after=line.version,
    )  # fmt: skip
    commit(session)
    return line_out(session, line)


@router.post("/purchase-lines/{line_id}/verify")
def verify_line(line_id: int, body: Versioned, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    return _set_line_verification(session, line_id, body, actor, if_match, True)


@router.post("/purchase-lines/{line_id}/unverify")
def unverify_line(line_id: int, body: Versioned, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    return _set_line_verification(session, line_id, body, actor, if_match, False)
