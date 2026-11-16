"""品牌、分类、标签。字典实体无 version 列，采用后写生效（API §1.6）。"""

from typing import Literal

from fastapi import APIRouter, Response
from sqlalchemy import func, select

from ..errors import ApiError, not_found
from ..models import Brand, Category, ItemTag, OutfitTag, Product, Tag, WardrobeItem
from ..schemas import BrandIn, BrandPatch, CategoryIn, CategoryPatch, TagIn, TagPatch
from ..services import categories as cats
from ..services.common import commit, log_change, now_iso, snapshot
from ..services.resolve import refresh_items
from ..services.text import normalize_tag
from .deps import ActorDep, SessionDep
from .serializers import brand_out, category_out, tag_out

router = APIRouter()


# ───────────── 品牌 ─────────────


@router.get("/brands", tags=["dictionaries"])
def list_brands(session: SessionDep):
    return {"items": [brand_out(b) for b in session.scalars(select(Brand).order_by(Brand.id))]}


@router.post("/brands", status_code=201, tags=["dictionaries"])
def create_brand(body: BrandIn, session: SessionDep, actor: ActorDep):
    if session.scalar(select(Brand).where(Brand.slug == body.slug)):
        raise ApiError(409, "DUPLICATE", f"品牌 slug {body.slug!r} 已存在")
    now = now_iso()
    brand = Brand(**body.model_dump(), created_at=now, updated_at=now)
    session.add(brand)
    session.flush()
    log_change(session, actor=actor, entity="brand", entity_id=brand.id, op="create", after=body.model_dump())
    commit(session)
    return brand_out(brand)


@router.patch("/brands/{brand_id}", tags=["dictionaries"])
def patch_brand(brand_id: int, body: BrandPatch, session: SessionDep, actor: ActorDep):
    brand = session.get(Brand, brand_id)
    if brand is None:
        raise not_found("brand", brand_id)
    values = body.model_dump(exclude_unset=True)
    before = snapshot(brand, list(values))
    for k, v in values.items():
        setattr(brand, k, v)
    brand.updated_at = now_iso()
    log_change(session, actor=actor, entity="brand", entity_id=brand.id, op="update", before=before, after=values)
    # 品牌名在衣物搜索索引中，改名后刷新所有相关衣物（BUG-008）
    items = session.scalars(
        select(WardrobeItem).join(Product, Product.id == WardrobeItem.product_id).where(Product.brand_id == brand.id)
    ).all()
    refresh_items(session, items)
    commit(session)
    return brand_out(brand)


# ───────────── 分类 ─────────────


def _tree(session) -> list[dict]:
    cmap = cats.children_map(session)

    def build(parent_id):
        return [{**category_out(c), "children": build(c.id)} for c in cmap.get(parent_id, [])]

    return build(None)


@router.get("/categories", tags=["dictionaries"])
def list_categories(session: SessionDep, format: Literal["tree", "flat"] = "tree"):
    if format == "flat":
        rows = session.scalars(select(Category).order_by(Category.level, Category.sort_order, Category.id))
        return {"items": [category_out(c) for c in rows]}
    return {"items": _tree(session)}


@router.post("/categories", status_code=201, tags=["dictionaries"])
def create_category(body: CategoryIn, session: SessionDep, actor: ActorDep):
    if session.scalar(select(Category).where(Category.slug == body.slug)):
        raise ApiError(409, "DUPLICATE", f"分类 slug {body.slug!r} 已存在")
    parent = cats.resolve_category(session, body.parent, "parent")
    now = now_iso()
    cat = Category(
        slug=body.slug, name_zh=body.name_zh, name_ja=body.name_ja, sort_order=body.sort_order,
        created_at=now, updated_at=now,
    )  # fmt: skip
    cats.place(session, cat, parent)
    session.add(cat)
    session.flush()
    log_change(session, actor=actor, entity="category", entity_id=cat.id, op="create", after=category_out(cat))
    commit(session)
    return category_out(cat)


@router.patch("/categories/{category_id}", tags=["dictionaries"])
def patch_category(category_id: int, body: CategoryPatch, session: SessionDep, actor: ActorDep):
    cat = cats.get_category(session, category_id)
    before = category_out(cat)
    values = body.model_dump(exclude_unset=True, exclude={"parent"})
    for k, v in values.items():
        setattr(cat, k, v)
    if "parent" in body.model_fields_set:
        cats.place(session, cat, cats.resolve_category(session, body.parent, "parent"))
    cat.updated_at = now_iso()
    session.flush()
    log_change(
        session, actor=actor, entity="category", entity_id=cat.id, op="update", before=before, after=category_out(cat)
    )
    commit(session)
    return category_out(cat)


@router.delete("/categories/{category_id}", status_code=204, tags=["dictionaries"])
def delete_category(category_id: int, session: SessionDep, actor: ActorDep):
    cat = cats.get_category(session, category_id)
    cats.ensure_deletable(session, cat)
    log_change(session, actor=actor, entity="category", entity_id=cat.id, op="delete", before=category_out(cat))
    session.delete(cat)
    commit(session)
    return Response(status_code=204)


# ───────────── 标签 ─────────────


def _tag_counts(session, tag_id: int) -> int:
    return (session.scalar(select(func.count()).select_from(ItemTag).where(ItemTag.tag_id == tag_id)) or 0) + (
        session.scalar(select(func.count()).select_from(OutfitTag).where(OutfitTag.tag_id == tag_id)) or 0
    )


@router.get("/tags", tags=["dictionaries"])
def list_tags(session: SessionDep, kind: str | None = None):
    q = select(Tag).order_by(Tag.kind, Tag.name_norm)
    if kind:
        q = q.where(Tag.kind == kind)
    return {"items": [{**tag_out(t), "usage": _tag_counts(session, t.id)} for t in session.scalars(q)]}


@router.post("/tags", tags=["dictionaries"])
def create_tag(body: TagIn, session: SessionDep, actor: ActorDep, response: Response):
    norm = normalize_tag(body.name)
    existing = session.scalar(select(Tag).where(Tag.name_norm == norm))
    if existing is not None:
        response.status_code = 200
        return {**tag_out(existing), "existing": True}
    tag = Tag(name=body.name, name_norm=norm, kind=body.kind, color_hex=body.color_hex, created_at=now_iso())
    session.add(tag)
    session.flush()
    log_change(session, actor=actor, entity="tag", entity_id=tag.id, op="create", after=tag_out(tag))
    commit(session)
    response.status_code = 201
    return {**tag_out(tag), "existing": False}


@router.patch("/tags/{tag_id}", tags=["dictionaries"])
def patch_tag(tag_id: int, body: TagPatch, session: SessionDep, actor: ActorDep):
    tag = session.get(Tag, tag_id)
    if tag is None:
        raise not_found("tag", tag_id)
    before = tag_out(tag)
    values = body.model_dump(exclude_unset=True)
    if "name" in values:
        norm = normalize_tag(values["name"])
        clash = session.scalar(select(Tag).where(Tag.name_norm == norm, Tag.id != tag.id))
        if clash:
            raise ApiError(409, "DUPLICATE", f"已有同名标签 {clash.name!r}", [{"existing_id": clash.id}])
        tag.name_norm = norm
    for k, v in values.items():
        setattr(tag, k, v)
    log_change(session, actor=actor, entity="tag", entity_id=tag.id, op="update", before=before, after=tag_out(tag))
    if "name" in values:  # 标签名在衣物搜索索引中（BUG-008）
        items = session.scalars(
            select(WardrobeItem).join(ItemTag, ItemTag.item_id == WardrobeItem.id).where(ItemTag.tag_id == tag.id)
        ).all()
        refresh_items(session, items)
    commit(session)
    return tag_out(tag)


@router.delete("/tags/{tag_id}", status_code=204, tags=["dictionaries"])
def delete_tag(tag_id: int, session: SessionDep, actor: ActorDep):
    tag = session.get(Tag, tag_id)
    if tag is None:
        raise not_found("tag", tag_id)
    if _tag_counts(session, tag.id):
        raise ApiError(409, "IN_USE", "标签仍被衣物或穿搭使用，请先移除")
    log_change(session, actor=actor, entity="tag", entity_id=tag.id, op="delete", before=tag_out(tag))
    session.delete(tag)
    commit(session)
    return Response(status_code=204)
