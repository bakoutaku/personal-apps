"""衣物有效颜色/尺寸解析（DATA_MODEL R1）与搜索索引维护。

优先级（按「组」整体回退，不逐字段混合）：
  颜色组 code/name/hex：衣物手动值 → 购买明细 → 商品默认色（is_default=1）→ 空
  尺寸组 label/system ：衣物手动值 → 购买明细 → 商品仅有一个尺码时的该尺码 → 空
"""

from collections.abc import Iterable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models import PurchaseLine, WardrobeItem
from .colors import color_family, display_swatch
from .common import log_change
from .text import normalize_text

EFF_FIELDS = (
    "eff_color_code", "eff_color_name", "eff_color_hex", "eff_color_family",
    "eff_size_label", "eff_size_system", "eff_sources",
)  # fmt: skip


def _has_color(obj) -> bool:
    return any(getattr(obj, f) for f in ("color_code", "color_name", "color_hex"))


def compute_effective(item: WardrobeItem) -> dict:
    line = item.purchase_line
    product = item.product

    color = {"code": None, "name": None, "hex": None}
    if _has_color(item):
        color, color_src = {"code": item.color_code, "name": item.color_name, "hex": item.color_hex}, "item"
    elif line is not None and _has_color(line):
        color, color_src = {"code": line.color_code, "name": line.color_name, "hex": line.color_hex}, "purchase_line"
    else:
        default = next((c for c in product.colors if c.is_default), None)
        if default is not None:
            name = default.name_ja or default.name_zh
            color, color_src = {"code": default.color_code, "name": name, "hex": default.hex}, "product_default"
        else:
            color_src = None

    if item.size_label:
        size, size_src = {"label": item.size_label, "system": item.size_system}, "item"
    elif line is not None and line.size_label:
        size, size_src = {"label": line.size_label, "system": line.size_system}, "purchase_line"
    elif len(product.sizes) == 1:
        only = product.sizes[0]
        size, size_src = {"label": only.size_label, "system": only.size_system}, "product_default"
    else:
        size, size_src = {"label": None, "system": None}, None

    family = (item.attributes or {}).get("color_family_override") or color_family(color["hex"])
    return {
        "eff_color_code": color["code"],
        "eff_color_name": color["name"],
        "eff_color_hex": color["hex"],
        "eff_color_family": family,
        "eff_size_label": size["label"],
        "eff_size_system": size["system"],
        "eff_sources": {"color": color_src, "size": size_src},
    }


def resolved_view(item: WardrobeItem) -> dict:
    return {
        "color": {
            "code": item.eff_color_code,
            "name": item.eff_color_name,
            "hex": item.eff_color_hex,
            "family": item.eff_color_family,
            "source": (item.eff_sources or {}).get("color"),
        },
        "size": {
            "label": item.eff_size_label,
            "system": item.eff_size_system,
            "source": (item.eff_sources or {}).get("size"),
        },
    }


def color_swatch(item: WardrobeItem) -> dict:
    """圆点显示用的颜色 {hex, source}：hex 为空时按颜色名称 / 色号推算示意色（source 为 name / name_code）。"""
    brand = item.product.brand if item.product else None
    return display_swatch(item.eff_color_hex, item.eff_color_name, item.eff_color_code, brand.slug if brand else None)


def refresh_items(session: Session, items: Iterable[WardrobeItem], *, upstream_actor: str | None = None) -> None:
    """重算 eff_* 缓存并更新搜索索引。

    upstream_actor 不为空表示由上游（商品/购买明细）变化触发：缓存变化写 change_log(actor=system)，
    但不增加衣物 version（衣物自身数据没有变）。
    """
    session.flush()
    for item in items:
        new = compute_effective(item)
        old = {k: getattr(item, k) for k in EFF_FIELDS}
        if new != old:
            for k, v in new.items():
                setattr(item, k, v)
            if upstream_actor is not None and item.id is not None:
                changed = [k for k in EFF_FIELDS if old[k] != new[k]]
                log_change(
                    session,
                    actor="system",
                    entity="wardrobe_item",
                    entity_id=item.id,
                    op="update",
                    before={k: old[k] for k in changed},
                    after={k: new[k] for k in changed} | {"triggered_by": upstream_actor},
                    version_after=item.version,
                )
        session.flush()
        index_item(session, item)


def items_of_product(session: Session, product_id: int) -> list[WardrobeItem]:
    return list(session.scalars(select(WardrobeItem).where(WardrobeItem.product_id == product_id)))


def items_of_line(session: Session, line_id: int) -> list[WardrobeItem]:
    return list(session.scalars(select(WardrobeItem).where(WardrobeItem.purchase_line_id == line_id)))


def items_of_lines(session: Session, lines: Iterable[PurchaseLine]) -> list[WardrobeItem]:
    ids = [ln.id for ln in lines if ln.id is not None]
    if not ids:
        return []
    return list(session.scalars(select(WardrobeItem).where(WardrobeItem.purchase_line_id.in_(ids))))


def _join(*parts) -> str:
    return normalize_text(" ".join(p for p in parts if p))


def index_item(session: Session, item: WardrobeItem) -> None:
    session.execute(text("DELETE FROM search_index WHERE rowid = :id"), {"id": item.id})
    if item.deleted_at is not None:
        return
    p, line = item.product, item.purchase_line
    brand = p.brand
    row = {
        "id": item.id,
        "names": _join(p.name_ja, p.name_zh, p.name_en, line.name_raw if line else None),
        "brand": _join(*(brand.name, brand.name_ja, brand.name_zh, brand.slug) if brand else ()),
        "codes": _join(*(i.value for i in p.identifiers), line.item_code_raw if line else None, item.eff_color_code),
        "colors": _join(item.eff_color_name, item.eff_color_family),
        "materials": _join(p.material_text, *(m.fiber for m in p.materials)),
        "tags": _join(*(t.name for t in item.tags)),
        "notes": _join(item.notes, item.location, item.alterations),
    }
    session.execute(
        text(
            "INSERT INTO search_index(rowid, names, brand, codes, colors, materials, tags, notes) "
            "VALUES (:id, :names, :brand, :codes, :colors, :materials, :tags, :notes)"
        ),
        row,
    )


def reindex_all(session: Session) -> int:
    session.execute(text("DELETE FROM search_index"))
    items = list(session.scalars(select(WardrobeItem).where(WardrobeItem.deleted_at.is_(None))))
    for item in items:
        index_item(session, item)
    return len(items)
