"""响应体构造。字段命名与请求体一致，方便 AI 读出后修改再写回。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Brand,
    Category,
    Image,
    Outfit,
    OutfitItem,
    Product,
    Purchase,
    PurchaseLine,
    Tag,
    WardrobeItem,
)
from ..services.categories import path_of
from ..services.resolve import color_swatch, resolved_view
from ..storage.images import media_url


def brand_out(b: Brand | None) -> dict | None:
    if b is None:
        return None
    return {k: getattr(b, k) for k in ("id", "slug", "name", "name_ja", "name_zh", "website")}


def category_out(c: Category) -> dict:
    return {k: getattr(c, k) for k in ("id", "slug", "name_zh", "name_ja", "level", "parent_id", "sort_order")}


def category_ref(session: Session, c: Category | None) -> dict | None:
    if c is None:
        return None
    path = path_of(session, c)
    return {"id": c.id, "slug": c.slug, "path": [p.name_zh for p in path], "path_slugs": [p.slug for p in path]}


def tag_out(t: Tag) -> dict:
    return {"id": t.id, "name": t.name, "kind": t.kind, "color_hex": t.color_hex}


def image_out(img: Image) -> dict:
    return {
        "id": img.id,
        "sha256": img.sha256,
        "mime": img.mime,
        "width": img.width,
        "height": img.height,
        "bytes": img.bytes,
        "url": media_url(img.storage_path),
        "thumb_url": media_url(img.thumb_path),
        "source_type": img.source_type,
        "source_url": img.source_url,
        "source_note": img.source_note,
        "created_at": img.created_at,
    }


def product_summary(p: Product) -> dict:
    return {
        "id": p.id,
        "brand": p.brand.name if p.brand else None,
        "name_ja": p.name_ja,
        "name_zh": p.name_zh,
        "name_en": p.name_en,
        "origin": p.origin,
        "verification": p.verification,
    }


def product_out(session: Session, p: Product) -> dict:
    item_count = session.scalar(
        select(func.count())
        .select_from(WardrobeItem)
        .where(WardrobeItem.product_id == p.id, WardrobeItem.deleted_at.is_(None))
    )
    return {
        "id": p.id,
        "version": p.version,
        "origin": p.origin,
        "brand": brand_out(p.brand),
        "category": category_ref(session, p.category),
        "name_ja": p.name_ja,
        "name_zh": p.name_zh,
        "name_en": p.name_en,
        "gender": p.gender,
        "detail_url": p.detail_url,
        "season_label": p.season_label,
        "material_text": p.material_text,
        "care_text": p.care_text,
        "care_symbols": p.care_symbols,
        "description": p.description,
        "list_price": p.list_price,
        "currency": p.currency,
        "verification": p.verification,
        "verified_at": p.verified_at,
        "attributes": p.attributes,
        "notes": p.notes,
        "identifiers": [{"id": i.id, "scheme": i.scheme, "value": i.value, "source": i.source} for i in p.identifiers],
        "colors": [
            {
                "id": c.id,
                "color_code": c.color_code,
                "name_ja": c.name_ja,
                "name_zh": c.name_zh,
                "hex": c.hex,
                "color_family": c.color_family,
                "is_default": bool(c.is_default),
                "sort_order": c.sort_order,
            }
            for c in p.colors
        ],
        "sizes": [
            {"id": s.id, "size_label": s.size_label, "size_system": s.size_system, "size_detail": s.size_detail}
            for s in p.sizes
        ],
        "materials": [
            {
                "part": m.part,
                "part_raw": m.part_raw,
                "fiber": m.fiber,
                "fiber_raw": m.fiber_raw,
                "percent": m.percent,
            }
            for m in p.materials
        ],
        "images": [
            {"role": pi.role, "color_code": pi.color_code, "sort_order": pi.sort_order, **image_out(pi.image)}
            for pi in p.images
        ],
        "item_count": item_count,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


def returned_quantity(session: Session, line_id: int) -> int:
    return session.scalar(
        select(func.count())
        .select_from(WardrobeItem)
        .where(
            WardrobeItem.purchase_line_id == line_id,
            WardrobeItem.status == "returned",
            WardrobeItem.deleted_at.is_(None),
        )
    )


def line_out(session: Session, ln: PurchaseLine) -> dict:
    item_ids = list(
        session.scalars(
            select(WardrobeItem.id).where(WardrobeItem.purchase_line_id == ln.id, WardrobeItem.deleted_at.is_(None))
        )
    )
    return {
        "id": ln.id,
        "version": ln.version,
        "purchase_id": ln.purchase_id,
        "product_id": ln.product_id,
        "product": product_summary(ln.product) if ln.product else None,
        "product_match": ln.product_match,
        **{
            k: getattr(ln, k)
            for k in (
                "item_code_raw",
                "name_raw",
                "color_code",
                "color_name",
                "color_hex",
                "size_label",
                "size_system",
                "quantity",
                "unit_price",
                "discount_amount",
                "verification",
                "verified_at",
                "attributes",
                "notes",
            )
        },  # fmt: skip
        "returned_quantity": returned_quantity(session, ln.id),
        "item_ids": item_ids,
    }


def purchase_out(session: Session, p: Purchase) -> dict:
    return {
        "id": p.id,
        "version": p.version,
        **{
            k: getattr(p, k)
            for k in ("purchased_on", "channel", "store_name", "order_no", "total_amount", "currency", "notes")
        },
        "lines": [line_out(session, ln) for ln in p.lines],
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


def main_image(item: WardrobeItem) -> Image | None:
    """衣物自己的照片优先；没有时用商品图，优先这件衣物有效颜色的图（同款不同色各显示各的）。"""
    if item.images:
        return next((x for x in item.images if x.role == "main"), item.images[0]).image
    links = item.product.images
    if not links:
        return None
    same_color = [x for x in links if item.eff_color_code and x.color_code == item.eff_color_code]
    pool = same_color or links
    return next((x for x in pool if x.role == "main"), pool[0]).image


def item_list_out(session: Session, item: WardrobeItem) -> dict:
    p = item.product
    img = main_image(item)
    category = item.category or p.category
    return {
        "id": item.id,
        "version": item.version,
        "product_id": p.id,
        "name": p.name_ja or p.name_zh or p.name_en,
        "name_ja": p.name_ja,
        "name_zh": p.name_zh,
        "brand": p.brand.name if p.brand else None,
        "category": category_ref(session, category),
        "thumb_url": media_url(img.thumb_path) if img else None,
        "resolved": resolved_view(item),
        "color_swatch": color_swatch(item),
        "tags": [t.name for t in item.tags],
        "status": item.status,
        "favorite": bool(item.favorite),
        "acquired_on": item.acquired_on,
        "verification": item.verification,
    }


def item_overview_out(session: Session, item: WardrobeItem) -> dict:
    """衣橱总览一行：名称、颜色、尺码、材质、分类、适穿季节等，一次给全，便于浏览或由 AI 读取。"""
    p = item.product
    category = item.category or p.category
    resolved = resolved_view(item)
    return {
        "id": item.id,
        "product_id": p.id,
        "name_ja": p.name_ja,
        "name_zh": p.name_zh,
        "name_en": p.name_en,
        "brand": p.brand.name if p.brand else None,
        "item_no": next((i.value for i in p.identifiers if i.scheme == "item_no"), None),
        "category": category_ref(session, category),
        "color": {**resolved["color"], "swatch": color_swatch(item)["hex"]},
        "size": resolved["size"],
        "material_text": p.material_text,
        "materials": [
            {"part": m.part, "fiber": m.fiber, "fiber_raw": m.fiber_raw, "percent": m.percent} for m in p.materials
        ],
        "seasons": [t.name for t in item.tags if t.kind == "season"],
        "tags": [t.name for t in item.tags],
        "status": item.status,
    }


def item_detail_out(session: Session, item: WardrobeItem) -> dict:
    outfits = session.scalars(
        select(Outfit)
        .join(OutfitItem, OutfitItem.outfit_id == Outfit.id)
        .where(OutfitItem.item_id == item.id, Outfit.deleted_at.is_(None))
    )
    line = item.purchase_line
    return {
        **item_list_out(session, item),
        **{
            k: getattr(item, k)
            for k in (
                "purchase_line_id",
                "category_id",
                "color_code",
                "color_name",
                "color_hex",
                "size_label",
                "size_system",
                "condition",
                "retired_on",
                "refund_amount",
                "location",
                "alterations",
                "wear_count",
                "last_worn_on",
                "verified_at",
                "attributes",
                "notes",
                "created_at",
                "updated_at",
            )
        },  # fmt: skip
        "product": product_out(session, item.product),
        "purchase": (
            {
                "purchase_id": line.purchase_id,
                "purchased_on": line.purchase.purchased_on,
                "store_name": line.purchase.store_name,
                "currency": line.purchase.currency,
                "line": line_out(session, line),
            }
            if line
            else None
        ),
        "images": [{"role": x.role, "sort_order": x.sort_order, **image_out(x.image)} for x in item.images],
        "tag_details": [tag_out(t) for t in item.tags],
        "outfits": [{"id": o.id, "name": o.name} for o in outfits],
    }


def outfit_out(session: Session, o: Outfit) -> dict:
    return {
        "id": o.id,
        "version": o.version,
        **{k: getattr(o, k) for k in ("name", "description", "season", "occasion", "rating", "attributes")},
        "cover_image": image_out(o.cover_image) if o.cover_image else None,
        "items": [
            {"slot": oi.slot, "sort_order": oi.sort_order, "item": item_list_out(session, oi.item)} for oi in o.items
        ],
        "tags": [t.name for t in o.tags],
        "images": [{"sort_order": x.sort_order, **image_out(x.image)} for x in o.images],
        "created_at": o.created_at,
        "updated_at": o.updated_at,
    }
