"""商品业务：品牌/分类引用解析、编号查重、颜色/尺码/材质子集合。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError, validation
from ..models import (
    Brand,
    MaterialComponent,
    Product,
    ProductColor,
    ProductIdentifier,
    ProductSize,
    Tag,
)
from ..schemas import ColorIn, IdentifierIn, MaterialIn, ProductCreate, ProductFields, SizeIn
from .categories import resolve_category
from .colors import color_family
from .common import log_change, now_iso
from .materials import parse_material_text
from .text import normalize_identifier, normalize_tag

SCALAR_FIELDS = (
    "name_ja", "name_zh", "name_en", "gender", "detail_url", "season_label", "material_text", "care_text",
    "care_symbols", "description", "list_price", "currency", "attributes", "notes",
)  # fmt: skip


def resolve_brand(session: Session, slug: str | None, brand_id: int | None) -> Brand | None:
    if slug is None and brand_id is None:
        return None
    brand = session.get(Brand, brand_id) if brand_id is not None else None
    if brand_id is not None and brand is None:
        raise validation(["brand_id"], "not_found", f"品牌 id {brand_id} 不存在")
    if slug is not None:
        by_slug = session.scalar(select(Brand).where(Brand.slug == slug.strip().lower()))
        if by_slug is None:
            raise validation(["brand"], "not_found", f"品牌 {slug!r} 不存在", "可用 GET /api/v1/brands 查看")
        if brand is not None and brand.id != by_slug.id:
            raise validation(["brand"], "conflict", "brand 与 brand_id 指向不同品牌")
        brand = by_slug
    return brand


def resolve_refs(session: Session, body: ProductFields) -> dict:
    """把 brand/brand_id、category/category_id 换成外键值，只返回请求中出现过的键。"""
    out: dict = {}
    sent = body.model_fields_set
    if {"brand", "brand_id"} & sent:
        brand = resolve_brand(session, body.brand, body.brand_id)
        out["brand_id"] = brand.id if brand else None
    if {"category", "category_id"} & sent:
        if body.category is not None and body.category_id is not None:
            a = resolve_category(session, body.category)
            b = resolve_category(session, body.category_id, "category_id")
            if a.id != b.id:
                raise validation(["category"], "conflict", "category 与 category_id 指向不同分类")
        cat = resolve_category(session, body.category if body.category is not None else body.category_id)
        out["category_id"] = cat.id if cat else None
    return out


def check_identifier_unique(session: Session, brand_id: int | None, ident: IdentifierIn, exclude_product: int | None):
    """同一品牌下 (scheme, value_norm) 唯一。不同 scheme 的相同值互不影响（R2）。"""
    norm = normalize_identifier(ident.value)
    q = (
        select(Product.id)
        .join(ProductIdentifier, ProductIdentifier.product_id == Product.id)
        .where(
            ProductIdentifier.scheme == ident.scheme,
            ProductIdentifier.value_norm == norm,
            Product.deleted_at.is_(None),
            Product.brand_id.is_(None) if brand_id is None else Product.brand_id == brand_id,
        )
    )
    if exclude_product is not None:
        q = q.where(Product.id != exclude_product)
    existing = session.scalar(q)
    if existing is not None:
        raise ApiError(
            409,
            "DUPLICATE",
            f"同品牌下已有商品使用 {ident.scheme}={ident.value}",
            [{"loc": ["identifiers"], "existing_id": existing, "scheme": ident.scheme, "value": ident.value}],
        )
    return norm


def build_identifier(session: Session, product: Product, ident: IdentifierIn) -> ProductIdentifier:
    norm = check_identifier_unique(session, product.brand_id, ident, product.id)
    if any(i.scheme == ident.scheme and i.value_norm == norm for i in product.identifiers):
        raise ApiError(409, "DUPLICATE", f"该商品已有 {ident.scheme}={ident.value}")
    return ProductIdentifier(
        scheme=ident.scheme, value=ident.value, value_norm=norm, source=ident.source, created_at=now_iso()
    )


def build_colors(colors: list[ColorIn]) -> list[ProductColor]:
    defaults = [i for i, c in enumerate(colors) if c.is_default]
    if len(defaults) > 1:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "一个商品最多只能有一个默认颜色",
            [{"loc": ["colors", i, "is_default"], "code": "multiple_defaults", "message": "重复的默认颜色"}
             for i in defaults],
        )  # fmt: skip
    seen = set()
    out = []
    for i, c in enumerate(colors):
        key = (c.color_code, c.name_ja)
        if key in seen:
            raise validation(["colors", i], "duplicate", f"重复的颜色 {c.color_code} {c.name_ja}")
        seen.add(key)
        out.append(
            ProductColor(
                color_code=c.color_code,
                name_ja=c.name_ja,
                name_zh=c.name_zh,
                hex=c.hex,
                color_family=color_family(c.hex),
                is_default=1 if c.is_default else 0,
                sort_order=c.sort_order or i,
            )
        )
    return out


def build_sizes(sizes: list[SizeIn]) -> list[ProductSize]:
    labels = [s.size_label for s in sizes]
    if len(set(labels)) != len(labels):
        raise validation(["sizes"], "duplicate", "尺码重复")
    return [
        ProductSize(size_label=s.size_label, size_system=s.size_system, size_detail=s.size_detail,
                    sort_order=s.sort_order or i)
        for i, s in enumerate(sizes)
    ]  # fmt: skip


def build_materials(materials: list[MaterialIn] | None, material_text: str | None) -> tuple[list, list[dict]]:
    if materials is not None:
        return [
            MaterialComponent(part=m.part, part_raw=m.part_raw, fiber=m.fiber, fiber_raw=m.fiber_raw,
                              percent=m.percent, sort_order=i)
            for i, m in enumerate(materials)
        ], []  # fmt: skip
    if not material_text:
        return [], []
    parsed, warnings = parse_material_text(material_text)
    return [
        MaterialComponent(part=m.part, part_raw=m.part_raw, fiber=m.fiber, fiber_raw=m.fiber_raw,
                          percent=m.percent, sort_order=i)
        for i, m in enumerate(parsed)
    ], warnings  # fmt: skip


def create_product(session: Session, body: ProductCreate, actor: str) -> tuple[Product, list[dict]]:
    now = now_iso()
    refs = resolve_refs(session, body)
    values = {f: getattr(body, f) for f in SCALAR_FIELDS if getattr(body, f) is not None}
    product = Product(origin=body.origin, created_at=now, updated_at=now, version=1, **refs, **values)
    product.care_symbols = body.care_symbols or []
    product.attributes = body.attributes or {}
    session.add(product)
    session.flush()

    seen = set()
    for i, ident in enumerate(body.identifiers):
        key = (ident.scheme, normalize_identifier(ident.value))
        if key in seen:
            raise validation(["identifiers", i], "duplicate", f"重复的编号 {ident.scheme}={ident.value}")
        seen.add(key)
        product.identifiers.append(build_identifier(session, product, ident))
    product.colors = build_colors(body.colors)
    product.sizes = build_sizes(body.sizes)
    product.materials, warnings = build_materials(body.materials, body.material_text)
    session.flush()
    log_change(
        session,
        actor=actor,
        entity="product",
        entity_id=product.id,
        op="create",
        after=body.model_dump(mode="json", exclude_none=True),
        version_after=product.version,
    )
    return product, warnings


def collection_snapshot(product: Product, name: str) -> list[dict]:
    """子集合的完整快照。键名与请求模型（IdentifierIn / ColorIn / SizeIn / MaterialIn）一致，
    因此既可以写入审计日志，也可以直接用来重建集合（导入撤销、修改提议）。"""
    rows = getattr(product, name)
    if name == "identifiers":
        return [{"scheme": r.scheme, "value": r.value, "source": r.source} for r in rows]
    if name == "colors":
        return [
            {"color_code": r.color_code, "name_ja": r.name_ja, "name_zh": r.name_zh, "hex": r.hex,
             "is_default": bool(r.is_default), "sort_order": r.sort_order}
            for r in rows
        ]  # fmt: skip
    if name == "sizes":
        return [
            {"size_label": r.size_label, "size_system": r.size_system, "size_detail": r.size_detail,
             "sort_order": r.sort_order}
            for r in rows
        ]  # fmt: skip
    if name == "materials":
        return [
            {"part": r.part, "part_raw": r.part_raw, "fiber": r.fiber, "fiber_raw": r.fiber_raw, "percent": r.percent}
            for r in rows
        ]
    if name == "images":
        return [
            {"image_id": r.image_id, "role": r.role, "color_code": r.color_code, "sort_order": r.sort_order}
            for r in rows
        ]
    raise KeyError(name)


def replace_collection(session: Session, product: Product, name: str, rows: list) -> None:
    """先删除并 flush 旧行，再插入新行。

    SQLAlchemy 默认先 INSERT 后 DELETE，直接整体赋值会与唯一索引（默认色、尺码）冲突。
    """
    getattr(product, name).clear()
    session.flush()
    setattr(product, name, rows)
    session.flush()


def get_or_create_tags(session: Session, names: list[str]) -> list[Tag]:
    out: list[Tag] = []
    seen = set()
    for name in names:
        norm = normalize_tag(name)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        tag = session.scalar(select(Tag).where(Tag.name_norm == norm))
        if tag is None:
            tag = Tag(name=name.strip(), name_norm=norm, kind="free", created_at=now_iso())
            session.add(tag)
            session.flush()
            # 记录隐式创建的标签，导入撤销时据此判断标签是否由该批次创建
            log_change(session, actor="system", entity="tag", entity_id=tag.id, op="create", after={"name": tag.name})
        out.append(tag)
    return out
