"""变更历史与全量导出。"""

from fastapi import APIRouter
from sqlalchemy import func, select

from ..import_schema import FORMAT
from ..models import ChangeLog, Outfit, Product, Purchase, WardrobeItem
from ..services.common import now_iso
from .deps import PagingDep, SessionDep, page

router = APIRouter(tags=["data"])

PRODUCT_SCALARS = (
    "origin", "name_ja", "name_zh", "name_en", "gender", "detail_url", "season_label", "material_text", "care_text",
    "care_symbols", "description", "list_price", "currency", "attributes", "notes",
)  # fmt: skip
LINE_SCALARS = (
    "item_code_raw", "name_raw", "color_code", "color_name", "color_hex", "size_label", "size_system", "quantity",
    "unit_price", "discount_amount", "notes", "attributes",
)  # fmt: skip
ITEM_SCALARS = (
    "color_code", "color_name", "color_hex", "size_label", "size_system", "status", "condition", "acquired_on",
    "retired_on", "refund_amount", "location", "alterations", "wear_count", "last_worn_on", "notes", "attributes",
)  # fmt: skip
OUTFIT_SCALARS = ("name", "description", "season", "occasion", "rating", "cover_image_id", "attributes")


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None and v != [] and v != {}}


@router.get("/changes")
def list_changes(
    session: SessionDep,
    paging: PagingDep,
    entity: str | None = None,
    entity_id: int | None = None,
    import_job_id: int | None = None,
    proposal_id: int | None = None,
    actor: str | None = None,
    op: str | None = None,
):
    """审计日志（新的在前）。"""
    limit, offset = paging
    q = select(ChangeLog)
    for col, val in (
        (ChangeLog.entity, entity),
        (ChangeLog.entity_id, entity_id),
        (ChangeLog.import_job_id, import_job_id),
        (ChangeLog.proposal_id, proposal_id),
        (ChangeLog.actor, actor),
        (ChangeLog.op, op),
    ):
        if val is not None:
            q = q.where(col == val)
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rows = session.scalars(q.order_by(ChangeLog.id.desc()).limit(limit).offset(offset))
    return page(
        [
            {k: getattr(c, k) for k in ("id", "occurred_at", "actor", "entity", "entity_id", "op", "before", "after",
                                         "version_after", "import_job_id", "proposal_id")}
            for c in rows
        ],
        total, limit, offset,
    )  # fmt: skip


@router.get("/export")
def export_all(session: SessionDep, include_ids: bool = True):
    """导出全部未删除数据，格式与 wardrobe.import/v1 相同。

    include_ids=true（默认）：带 id，修改后导入回同一个数据库会按 id 精确对应。
    include_ids=false：只用 ref 互相引用，可导入到另一个数据库。
    """
    products = list(session.scalars(select(Product).where(Product.deleted_at.is_(None)).order_by(Product.id)))
    purchases = list(session.scalars(select(Purchase).where(Purchase.deleted_at.is_(None)).order_by(Purchase.id)))
    items = list(
        session.scalars(select(WardrobeItem).where(WardrobeItem.deleted_at.is_(None)).order_by(WardrobeItem.id))
    )
    outfits = list(session.scalars(select(Outfit).where(Outfit.deleted_at.is_(None)).order_by(Outfit.id)))
    exported_products = {p.id for p in products}
    exported_lines = {ln.id for pur in purchases for ln in pur.lines}
    exported_items = {i.id for i in items}

    def ident(obj, prefix):
        return {"ref": f"{prefix}{obj.id}", **({"id": obj.id} if include_ids else {})}

    def product_link(product_id):
        if product_id is None:
            return {}
        if not include_ids and product_id in exported_products:
            return {"product_ref": f"p{product_id}"}
        return {"product_id": product_id}

    out_products = []
    for p in products:
        out_products.append(
            _clean(
                {
                    **ident(p, "p"),
                    "brand": p.brand.slug if p.brand else None,
                    "category": p.category.slug if p.category else None,
                    **{k: getattr(p, k) for k in PRODUCT_SCALARS},
                    "identifiers": [{"scheme": i.scheme, "value": i.value, "source": i.source} for i in p.identifiers],
                    "colors": [
                        _clean({"color_code": c.color_code, "name_ja": c.name_ja, "name_zh": c.name_zh, "hex": c.hex,
                                "is_default": bool(c.is_default) or None, "sort_order": c.sort_order or None})
                        for c in p.colors
                    ],
                    "sizes": [_clean({"size_label": s.size_label, "size_system": s.size_system,
                                      "size_detail": s.size_detail}) for s in p.sizes],
                    "materials": [
                        _clean({"part": m.part, "part_raw": m.part_raw, "fiber": m.fiber, "fiber_raw": m.fiber_raw,
                                "percent": m.percent})
                        for m in p.materials
                    ],
                    "images": [
                        _clean({"image_id": i.image_id, "role": i.role, "color_code": i.color_code})
                        for i in p.images
                    ],
                }
            )
        )  # fmt: skip

    out_purchases = []
    for pur in purchases:
        lines = []
        for ln in pur.lines:
            line = {**ident(ln, "l"), **product_link(ln.product_id), **{k: getattr(ln, k) for k in LINE_SCALARS}}
            if ln.product_match == "suggested":
                line["product_match"] = "suggested"
            lines.append(_clean(line))
        out_purchases.append(
            _clean(
                {
                    **ident(pur, "o"),
                    **{k: getattr(pur, k) for k in ("purchased_on", "channel", "store_name", "order_no",
                                                    "total_amount", "currency", "notes")},
                    "lines": lines,
                }
            )
        )  # fmt: skip

    out_items = []
    for it in items:
        link: dict = {}
        if it.purchase_line_id is not None:
            if not include_ids and it.purchase_line_id in exported_lines:
                link["purchase_line_ref"] = f"l{it.purchase_line_id}"
            else:
                link["purchase_line_id"] = it.purchase_line_id
        out_items.append(
            _clean(
                {
                    **ident(it, "i"),
                    **product_link(it.product_id),
                    **link,
                    "category": it.category.slug if it.category else None,
                    **{k: getattr(it, k) for k in ITEM_SCALARS},
                    "favorite": bool(it.favorite) or None,
                    "tags": [t.name for t in it.tags],
                    "images": [{"image_id": x.image_id, "role": x.role} for x in it.images],
                }
            )
        )

    out_outfits = []
    for o in outfits:
        entries = []
        for oi in o.items:
            ref = (
                {"item_ref": f"i{oi.item_id}"}
                if not include_ids and oi.item_id in exported_items
                else {"item_id": oi.item_id}
            )
            entries.append({**ref, "slot": oi.slot, "sort_order": oi.sort_order})
        out_outfits.append(
            _clean(
                {
                    **ident(o, "f"),
                    **{k: getattr(o, k) for k in OUTFIT_SCALARS},
                    "items": entries,
                    "tags": [t.name for t in o.tags],
                }
            )
        )

    return {
        "format": FORMAT,
        "source_label": f"export {now_iso()}",
        "products": out_products,
        "purchases": out_purchases,
        "items": out_items,
        "outfits": out_outfits,
    }
