"""衣物 WardrobeItem：衣橱主列表、详情、修改、退货、标签与图片。"""

from dataclasses import dataclass, field
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select

from ..errors import ApiError, validation
from ..models import (
    Brand,
    Category,
    Image,
    ItemImage,
    ItemTag,
    MaterialComponent,
    Outfit,
    OutfitItem,
    Product,
    PurchaseLine,
    Tag,
    WardrobeItem,
)
from ..schemas import ItemCreate, ItemImageLink, ItemPatch, ReturnIn, TagsPut, Versioned, WearIn
from ..services import products as product_svc
from ..services.categories import descendant_ids, path_of, resolve_category
from ..services.common import commit, get_or_404, log_change, now_iso, require_version, touch
from ..services.items import create_item, validate_item_links
from ..services.proposals import accepted_response, propose_blocked
from ..services.protection import DELETE, changed_fields, guard, guard_privileged
from ..services.quick_groups import BY_KEY as QUICK_GROUPS
from ..services.quick_groups import GROUPS, group_clause
from ..services.resolve import refresh_items
from ..services.search import item_search_clause
from ..services.text import normalize_tag
from .deps import ActorDep, IfMatch, PagingDep, SessionDep, page
from .serializers import item_detail_out, item_list_out, item_overview_out

router = APIRouter(prefix="/items", tags=["items"])

ITEM_FIELDS = (
    "product_id", "purchase_line_id", "category_id", "color_code", "color_name", "color_hex", "size_label",
    "size_system", "status", "condition", "acquired_on", "retired_on", "refund_amount", "location",
    "alterations", "wear_count", "last_worn_on", "favorite", "notes", "attributes",
)  # fmt: skip

SORTS = {
    "created_at": WardrobeItem.created_at,
    "acquired_on": WardrobeItem.acquired_on,
    "wear_count": WardrobeItem.wear_count,
    "color": WardrobeItem.eff_color_family,
    "name": func.coalesce(Product.name_ja, Product.name_zh, Product.name_en),
    "id": WardrobeItem.id,
}


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


def _line_or_422(session, line_id: int) -> PurchaseLine:
    line = session.get(PurchaseLine, line_id)
    if line is None:
        raise validation(["purchase_line_id"], "not_found", f"购买明细 {line_id} 不存在")
    return line


@dataclass
class ItemFilters:
    """衣橱列表的筛选条件。列表与筛选统计（facets）共用，保证两者规则一致。"""

    q: str | None = None
    category: str | None = None
    group: str | None = None  # 快捷分组（services/quick_groups.py），如 tshirt、short_sleeve
    brand: str | None = None
    tag: str | None = None
    tag_mode: str = "all"
    color: str | None = None
    size: str | None = None
    status: str = "owned"
    material: str | None = None
    acquired_from: date | None = None
    acquired_to: date | None = None
    verification: str | None = None
    favorite: bool | None = None
    tag_exact: list[str] = field(default_factory=list, init=False)
    size_exact: list[str] = field(default_factory=list, init=False)


def parse_filters(
    filters: Annotated[ItemFilters, Depends()],
    tag_exact: Annotated[list[str] | None, Query(description="完整标签名，可重复；不按逗号拆分")] = None,
    size_exact: Annotated[list[str] | None, Query(description="完整尺码，可重复；不按逗号拆分")] = None,
) -> ItemFilters:
    filters.tag_exact = tag_exact or []
    filters.size_exact = size_exact or []
    return filters


FiltersDep = Annotated[ItemFilters, Depends(parse_filters)]


def filtered_query(session, f: ItemFilters, skip: str | None = None):
    """按筛选条件构造衣物查询。skip 指定的维度不参与筛选（用于计算该维度自身的选项计数）。"""
    query = (
        select(WardrobeItem)
        .join(Product, Product.id == WardrobeItem.product_id)
        .where(WardrobeItem.deleted_at.is_(None))
    )
    if f.status != "all" and skip != "status":
        query = query.where(WardrobeItem.status.in_(_csv(f.status)))
    if f.category and skip != "category":
        cat = resolve_category(session, int(f.category) if f.category.isdigit() else f.category)
        query = query.where(
            func.coalesce(WardrobeItem.category_id, Product.category_id).in_(descendant_ids(session, cat.id))
        )
    if f.group and skip != "group":
        if f.group not in QUICK_GROUPS:
            raise validation(["group"], "unknown_group", f"group 只能是 {', '.join(QUICK_GROUPS)}")
        query = query.where(group_clause(session, QUICK_GROUPS[f.group]))
    if f.brand and skip != "brand":
        query = query.where(Product.brand_id.in_(select(Brand.id).where(Brand.slug.in_(_csv(f.brand)))))
    if (f.tag or f.tag_exact) and skip != "tag":
        norms = list(dict.fromkeys(normalize_tag(t) for t in [*_csv(f.tag), *f.tag_exact] if t.strip()))
        tagged = select(ItemTag.item_id).join(Tag, Tag.id == ItemTag.tag_id)
        if f.tag_mode == "any":
            query = query.where(WardrobeItem.id.in_(tagged.where(Tag.name_norm.in_(norms))))
        else:
            for n in norms:
                query = query.where(WardrobeItem.id.in_(tagged.where(Tag.name_norm == n)))
    if f.color and skip != "color":
        query = query.where(WardrobeItem.eff_color_family.in_(_csv(f.color)))
    if (f.size or f.size_exact) and skip != "size":
        query = query.where(WardrobeItem.eff_size_label.in_([*_csv(f.size), *f.size_exact]))
    if f.material and skip != "material":
        query = query.where(
            Product.id.in_(select(MaterialComponent.product_id).where(MaterialComponent.fiber.in_(_csv(f.material))))
        )
    if f.acquired_from:
        query = query.where(WardrobeItem.acquired_on >= f.acquired_from.isoformat())
    if f.acquired_to:
        query = query.where(WardrobeItem.acquired_on <= f.acquired_to.isoformat())
    if f.verification:
        query = query.where(WardrobeItem.verification == f.verification)
    if f.favorite is not None:
        query = query.where(WardrobeItem.favorite == (1 if f.favorite else 0))
    if f.q:
        clause = item_search_clause(f.q)
        if clause is not None:
            query = query.where(clause)
    return query


@router.get("")
def list_items(session: SessionDep, paging: PagingDep, filters: FiltersDep, sort: str = "-created_at"):
    limit, offset = paging
    query = filtered_query(session, filters)
    key = sort.lstrip("-")
    if key not in SORTS:
        raise ApiError(422, "VALIDATION_ERROR", f"sort 只能是 {', '.join(SORTS)}（可加 - 表示倒序）")
    col = SORTS[key]
    order = col.desc() if sort.startswith("-") else col.asc()
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.scalars(query.order_by(order.nulls_last(), WardrobeItem.id.desc()).limit(limit).offset(offset))
    return page([item_list_out(session, i) for i in rows], total, limit, offset)


@router.get("/facets")
def item_facets(session: SessionDep, filters: FiltersDep):
    """筛选侧栏的选项与计数。每个维度的计数应用其他所有筛选条件，但不应用该维度自身
    （选中「藏青」后，颜色维度仍显示其他颜色各有多少件）。分类计数已包含子孙分类。"""

    def ids(skip: str):
        return filtered_query(session, filters, skip).with_only_columns(WardrobeItem.id).scalar_subquery()

    def grouped(col, skip: str, *joins) -> dict:
        q = select(col, func.count(func.distinct(WardrobeItem.id))).select_from(WardrobeItem)
        for target, on in joins:
            q = q.join(target, on)
        q = q.where(WardrobeItem.id.in_(ids(skip)), col.is_not(None)).group_by(col)
        return {k: n for k, n in session.execute(q)}

    product_join = (Product, Product.id == WardrobeItem.product_id)
    by_leaf = grouped(func.coalesce(WardrobeItem.category_id, Product.category_id), "category", product_join)
    by_category: dict[int, int] = {}
    for cat_id, n in by_leaf.items():
        node = session.get(Category, cat_id)
        while node is not None:  # 计入所有祖先
            by_category[node.id] = by_category.get(node.id, 0) + n
            node = session.get(Category, node.parent_id) if node.parent_id else None

    brands = grouped(Brand.slug, "brand", product_join, (Brand, Brand.id == Product.brand_id))
    materials = grouped(
        MaterialComponent.fiber,
        "material",
        product_join,
        (MaterialComponent, MaterialComponent.product_id == Product.id),
    )
    tags = grouped(Tag.name, "tag", (ItemTag, ItemTag.item_id == WardrobeItem.id), (Tag, Tag.id == ItemTag.tag_id))
    base = filtered_query(session, filters, "group").subquery()
    groups = [
        {
            "key": g.key,
            "label": g.label,
            "more": g.more,
            "count": session.scalar(
                select(func.count())
                .select_from(WardrobeItem)
                .join(Product, Product.id == WardrobeItem.product_id)
                .where(WardrobeItem.id.in_(select(base.c.id)), group_clause(session, g))
            ),
        }
        for g in GROUPS
    ]
    return {
        "total": session.scalar(select(func.count()).select_from(filtered_query(session, filters).subquery())),
        "category": {str(k): v for k, v in by_category.items()},
        "brand": brands,
        "color": grouped(WardrobeItem.eff_color_family, "color"),
        "size": grouped(WardrobeItem.eff_size_label, "size"),
        "tag": tags,
        "status": grouped(WardrobeItem.status, "status"),
        "material": materials,
        "groups": groups,
    }


@router.get("/overview")
def item_overview(session: SessionDep, filters: FiltersDep):
    """衣橱总览：符合筛选条件的全部衣物（默认持有中），不分页，按分类、名称排序。"""
    items = list(session.scalars(filtered_query(session, filters)))

    def order(item: WardrobeItem):
        path = path_of(session, item.category or item.product.category)
        name = item.product.name_ja or item.product.name_zh or item.product.name_en or ""
        return (not path, [(c.sort_order, c.id) for c in path], name, item.id)  # 未分类排最后

    rows = [item_overview_out(session, i) for i in sorted(items, key=order)]
    return {"items": rows, "total": len(rows)}


@router.post("", status_code=201)
def create_item_route(body: ItemCreate, session: SessionDep, actor: ActorDep):
    warnings: list = []
    line = _line_or_422(session, body.purchase_line_id) if body.purchase_line_id is not None else None
    if body.product is not None:
        inline = body.product
        if "origin" not in inline.model_fields_set:
            inline = inline.model_copy(update={"origin": "manual"})
        product, warnings = product_svc.create_product(session, inline, actor)
    elif body.product_id is not None:
        product = get_or_404(session, Product, body.product_id)
    elif line is not None and line.product is not None:
        product = line.product
    else:
        raise validation(["product_id"], "required", "需要 product_id、内联 product，或已关联商品的 purchase_line_id")

    values = body.model_dump(
        mode="json", exclude_unset=True,
        exclude={"product_id", "product", "purchase_line_id", "tags", "category", "category_id"},
    )  # fmt: skip
    if {"category", "category_id"} & body.model_fields_set:
        cat = resolve_category(session, body.category if body.category is not None else body.category_id)
        values["category_id"] = cat.id if cat else None
    item = create_item(session, actor=actor, product=product, line=line, values=values, tags=body.tags)
    commit(session)
    return {**item_detail_out(session, item), "warnings": warnings}


@router.get("/{item_id}")
def get_item(item_id: int, session: SessionDep):
    return item_detail_out(session, get_or_404(session, WardrobeItem, item_id))


def _validate_final_state(item: WardrobeItem, values: dict) -> None:
    status = values.get("status", item.status)
    refund = values.get("refund_amount", item.refund_amount)
    if refund is not None and status != "returned":
        raise validation(
            ["refund_amount"], "requires_returned", "只有 status=returned 的衣物可以有 refund_amount",
            "把状态改离 returned 时，请同时把 refund_amount 设为 null",
        )  # fmt: skip
    acquired = values.get("acquired_on", item.acquired_on)
    retired = values.get("retired_on", item.retired_on)
    if acquired and retired and retired < acquired:
        raise validation(["retired_on"], "before_acquired", f"离开日期 {retired} 早于取得日期 {acquired}")


@router.patch("/{item_id}")
def patch_item(item_id: int, body: ItemPatch, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    item = get_or_404(session, WardrobeItem, item_id)
    require_version(item, body.version, if_match)
    values = body.model_dump(
        mode="json", exclude_unset=True, exclude={"version", "category", "category_id"}, include=set(ITEM_FIELDS)
    )
    if {"category", "category_id"} & body.model_fields_set:
        cat = resolve_category(session, body.category if body.category is not None else body.category_id)
        values["category_id"] = cat.id if cat else None
    for required in ("product_id", "status", "wear_count", "favorite"):
        if required in values and values[required] is None:
            raise validation([required], "required", f"{required} 不能为空")
    if "favorite" in values:
        values["favorite"] = 1 if values["favorite"] else 0
    if "attributes" in values and values["attributes"] is None:
        values["attributes"] = {}

    touched = changed_fields(item, values)
    proposals = propose_blocked(session, actor, "wardrobe_item", item, values, touched)
    if not touched:
        if proposals:
            commit(session)
            return accepted_response(item_detail_out(session, item), [], proposals)
        return item_detail_out(session, item)

    product = get_or_404(session, Product, values["product_id"]) if "product_id" in touched else item.product
    line_id = values.get("purchase_line_id", item.purchase_line_id)
    line = _line_or_422(session, line_id) if line_id is not None else None
    if {"product_id", "purchase_line_id"} & touched:
        validate_item_links(session, product, line, exclude_item_id=item.id)
    _validate_final_state(item, values)

    before = {k: getattr(item, k) for k in touched}
    for k in touched:
        setattr(item, k, values[k])
    touch(item)
    session.flush()
    session.refresh(item, ["product", "purchase_line"])
    log_change(
        session, actor=actor, entity="wardrobe_item", entity_id=item.id, op="update",
        before=before, after={k: values[k] for k in touched}, version_after=item.version,
    )  # fmt: skip
    refresh_items(session, [item])
    commit(session)
    if proposals:
        return accepted_response(item_detail_out(session, item), touched, proposals)
    return item_detail_out(session, item)


@router.post("/{item_id}/return")
def return_item(item_id: int, body: ReturnIn, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    """单件退货（R5）：只改这件衣物，购买记录保持原样。"""
    item = get_or_404(session, WardrobeItem, item_id)
    require_version(item, body.version, if_match)
    if item.status == "returned":
        raise ApiError(409, "ALREADY_RETURNED", f"衣物 {item.id} 已是退货状态")
    values = {"status": "returned", "retired_on": body.returned_on.isoformat(), "refund_amount": body.refund_amount}
    _validate_final_state(item, values)
    proposals = propose_blocked(session, actor, "wardrobe_item", item, dict(values), changed_fields(item, values))
    if proposals:
        commit(session)
        return accepted_response(item_detail_out(session, item), [], proposals)
    before = {k: getattr(item, k) for k in values}
    for k, v in values.items():
        setattr(item, k, v)
    touch(item)
    log_change(
        session, actor=actor, entity="wardrobe_item", entity_id=item.id, op="update",
        before=before, after=values, version_after=item.version,
    )  # fmt: skip
    commit(session)
    return item_detail_out(session, item)


@router.post("/{item_id}/wear")
def wear_item(item_id: int, body: WearIn, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    """记录穿着一次：wear_count + 1，last_worn_on 取较晚的日期。不受核实保护。"""
    item = get_or_404(session, WardrobeItem, item_id)
    require_version(item, body.version, if_match)
    worn_on = (body.worn_on or date.today()).isoformat()
    if item.acquired_on and worn_on < item.acquired_on:
        raise validation(["worn_on"], "before_acquired", f"穿着日期 {worn_on} 早于取得日期 {item.acquired_on}")
    before = {"wear_count": item.wear_count, "last_worn_on": item.last_worn_on}
    item.wear_count += 1
    item.last_worn_on = max(worn_on, item.last_worn_on or worn_on)
    touch(item)
    log_change(
        session, actor=actor, entity="wardrobe_item", entity_id=item.id, op="update", before=before,
        after={"wear_count": item.wear_count, "last_worn_on": item.last_worn_on}, version_after=item.version,
    )  # fmt: skip
    commit(session)
    return item_detail_out(session, item)


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: int, session: SessionDep, actor: ActorDep, if_match: IfMatch = None,
                version: int | None = None):  # fmt: skip
    item = get_or_404(session, WardrobeItem, item_id)
    require_version(item, version, if_match)
    guard(actor, "wardrobe_item", item, {DELETE})
    outfit_ids = list(
        session.scalars(
            select(Outfit.id)
            .join(OutfitItem, OutfitItem.outfit_id == Outfit.id)
            .where(OutfitItem.item_id == item.id, Outfit.deleted_at.is_(None))
        )
    )
    if outfit_ids:
        raise ApiError(
            409, "IN_USE", "衣物仍在穿搭中使用；不再拥有请改 status，而不是删除", [{"outfit_ids": outfit_ids}]
        )
    item.deleted_at = now_iso()
    touch(item)
    log_change(session, actor=actor, entity="wardrobe_item", entity_id=item.id, op="delete",
               version_after=item.version)  # fmt: skip
    refresh_items(session, [item])
    commit(session)
    return Response(status_code=204)


@router.post("/{item_id}/restore")
def restore_item(item_id: int, body: Versioned, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    item = get_or_404(session, WardrobeItem, item_id, include_deleted=True)
    if item.deleted_at is None:
        raise ApiError(409, "NOT_DELETED", f"衣物 {item.id} 没有被删除")
    require_version(item, body.version, if_match)
    guard(actor, "wardrobe_item", item, {DELETE})
    # 删除期间明细可能被改配到其他商品、依赖可能被删除、名额可能被占用：恢复前重新校验全部关联，
    # 不会隐式修改或恢复其他记录（BUG-006 / 007 / 010）
    validate_item_links(session, item.product, item.purchase_line, exclude_item_id=item.id)
    item.deleted_at = None
    touch(item)
    log_change(session, actor=actor, entity="wardrobe_item", entity_id=item.id, op="restore",
               version_after=item.version)  # fmt: skip
    refresh_items(session, [item])
    commit(session)
    return item_detail_out(session, item)


@router.put("/{item_id}/tags")
def put_tags(item_id: int, body: TagsPut, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    item = get_or_404(session, WardrobeItem, item_id)
    require_version(item, body.version, if_match)
    before = [t.name for t in item.tags]
    item.tags = product_svc.get_or_create_tags(session, body.tags)
    touch(item)
    log_change(
        session, actor=actor, entity="wardrobe_item", entity_id=item.id, op="update",
        before={"tags": before}, after={"tags": [t.name for t in item.tags]}, version_after=item.version,
    )  # fmt: skip
    refresh_items(session, [item])
    commit(session)
    return item_detail_out(session, item)


@router.post("/{item_id}/images", status_code=201)
def add_item_image(item_id: int, body: ItemImageLink, session: SessionDep, actor: ActorDep,
                   if_match: IfMatch = None):  # fmt: skip
    item = get_or_404(session, WardrobeItem, item_id)
    require_version(item, body.version, if_match)
    get_or_404(session, Image, body.image_id)
    if any(x.image_id == body.image_id for x in item.images):
        raise ApiError(409, "DUPLICATE", "该图片已关联到此衣物")
    if body.role == "main":
        for x in item.images:
            if x.role == "main":
                x.role = "gallery"
    item.images.append(ItemImage(image_id=body.image_id, role=body.role, sort_order=body.sort_order))
    touch(item)
    log_change(
        session, actor=actor, entity="wardrobe_item", entity_id=item.id, op="update",
        after={"images_added": [body.image_id]}, version_after=item.version,
    )  # fmt: skip
    commit(session)
    return item_detail_out(session, item)


@router.delete("/{item_id}/images/{image_id}")
def remove_item_image(item_id: int, image_id: int, session: SessionDep, actor: ActorDep, if_match: IfMatch = None,
                      version: int | None = None):  # fmt: skip
    item = get_or_404(session, WardrobeItem, item_id)
    require_version(item, version, if_match)
    link = next((x for x in item.images if x.image_id == image_id), None)
    if link is None:
        raise ApiError(404, "NOT_FOUND", f"衣物 {item_id} 没有关联图片 {image_id}")
    item.images.remove(link)
    touch(item)
    log_change(
        session, actor=actor, entity="wardrobe_item", entity_id=item.id, op="update",
        before={"images_removed": [image_id]}, version_after=item.version,
    )  # fmt: skip
    commit(session)
    return item_detail_out(session, item)


def _set_item_verification(session, item_id: int, body: Versioned, actor: str, if_match, verified: bool):
    guard_privileged(actor, "核实/取消核实")
    item = get_or_404(session, WardrobeItem, item_id)
    require_version(item, body.version, if_match)
    item.verification = "verified" if verified else "unverified"
    item.verified_at = now_iso() if verified else None
    touch(item)
    log_change(
        session, actor=actor, entity="wardrobe_item", entity_id=item.id, op="verify" if verified else "unverify",
        version_after=item.version,
    )  # fmt: skip
    commit(session)
    return item_detail_out(session, item)


@router.post("/{item_id}/verify")
def verify_item(item_id: int, body: Versioned, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    return _set_item_verification(session, item_id, body, actor, if_match, True)


@router.post("/{item_id}/unverify")
def unverify_item(item_id: int, body: Versioned, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    return _set_item_verification(session, item_id, body, actor, if_match, False)
