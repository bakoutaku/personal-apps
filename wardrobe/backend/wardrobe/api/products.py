"""商品 Product。所有修改走：取记录 → 版本检查 → 核实保护 → 修改 → 重算衣物 → 审计 → 提交。"""

from fastapi import APIRouter, Response
from sqlalchemy import func, or_, select

from ..errors import ApiError
from ..models import (
    Brand,
    Image,
    Product,
    ProductIdentifier,
    ProductImage,
    WardrobeItem,
)
from ..schemas import (
    ColorsPut,
    IdentifierAdd,
    IdentifierIn,
    LookupIn,
    MaterialsPut,
    ProductCreate,
    ProductImageLink,
    ProductPatch,
    SizesPut,
    Versioned,
)
from ..services import products as svc
from ..services.categories import descendant_ids, resolve_category
from ..services.common import commit, get_or_404, log_change, now_iso, require_version, touch
from ..services.proposals import accepted_response, blocked_fields, create_proposal, propose_blocked
from ..services.protection import DELETE, changed_fields, guard, guard_privileged
from ..services.resolve import items_of_product, refresh_items
from ..services.text import normalize_identifier
from .deps import ActorDep, IfMatch, PagingDep, SessionDep, page
from .serializers import product_out

router = APIRouter(prefix="/products", tags=["products"])


def _load(session, product_id: int) -> Product:
    return get_or_404(session, Product, product_id)


def _finish(session, product: Product, actor: str, field: str, before, *, refresh: bool = True) -> dict:
    """子集合修改的公共收尾：父记录 version+1、审计、重算衣物。"""
    touch(product)
    session.flush()
    log_change(
        session, actor=actor, entity="product", entity_id=product.id, op="update",
        before={field: before}, after={field: svc.collection_snapshot(product, field)}, version_after=product.version,
    )  # fmt: skip
    if refresh:
        refresh_items(session, items_of_product(session, product.id), upstream_actor=actor)
    commit(session)
    return product_out(session, product)


@router.get("")
def list_products(
    session: SessionDep,
    paging: PagingDep,
    brand: str | None = None,
    category: str | None = None,
    q: str | None = None,
    identifier: str | None = None,
    verification: str | None = None,
    origin: str | None = None,
):
    limit, offset = paging
    query = select(Product).where(Product.deleted_at.is_(None))
    if brand:
        query = query.join(Brand, Brand.id == Product.brand_id).where(Brand.slug.in_(brand.split(",")))
    if category:
        cat = resolve_category(session, int(category) if category.isdigit() else category)
        query = query.where(Product.category_id.in_(descendant_ids(session, cat.id)))
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Product.name_ja.like(like), Product.name_zh.like(like), Product.name_en.like(like)))
    if identifier:
        scheme, _, value = identifier.partition(":")
        if not value:
            raise ApiError(422, "VALIDATION_ERROR", "identifier 参数格式为 scheme:value，例如 item_no:465185")
        query = query.where(
            Product.id.in_(
                select(ProductIdentifier.product_id).where(
                    ProductIdentifier.scheme == scheme, ProductIdentifier.value_norm == normalize_identifier(value)
                )
            )
        )
    if verification:
        query = query.where(Product.verification == verification)
    if origin:
        query = query.where(Product.origin == origin)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.scalars(query.order_by(Product.id.desc()).limit(limit).offset(offset))
    return page([product_out(session, p) for p in rows], total, limit, offset)


@router.post("", status_code=201)
def create_product(body: ProductCreate, session: SessionDep, actor: ActorDep):
    product, warnings = svc.create_product(session, body, actor)
    commit(session)
    return {**product_out(session, product), "warnings": warnings}


@router.post("/lookup")
def lookup_product(body: LookupIn, session: SessionDep):
    """按编号精确查找。只在同一 scheme 内匹配，不做跨体系推断（R2）。"""
    query = (
        select(Product)
        .join(ProductIdentifier, ProductIdentifier.product_id == Product.id)
        .where(
            Product.deleted_at.is_(None),
            ProductIdentifier.scheme == body.scheme,
            ProductIdentifier.value_norm == normalize_identifier(body.value),
        )
    )
    if body.brand:
        brand = svc.resolve_brand(session, body.brand, None)
        query = query.where(Product.brand_id == brand.id)
    return {"items": [product_out(session, p) for p in session.scalars(query)]}


@router.get("/{product_id}")
def get_product(product_id: int, session: SessionDep):
    return product_out(session, _load(session, product_id))


@router.patch("/{product_id}")
def patch_product(product_id: int, body: ProductPatch, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    product = _load(session, product_id)
    require_version(product, body.version, if_match)
    values = svc.resolve_refs(session, body)
    for f in svc.SCALAR_FIELDS:
        if f in body.model_fields_set:
            values[f] = getattr(body, f)
    if "care_symbols" in values and values["care_symbols"] is None:
        values["care_symbols"] = []
    if "attributes" in values and values["attributes"] is None:
        values["attributes"] = {}
    for name in ("name_ja", "name_zh", "name_en"):
        if (
            name in values
            and values[name] is None
            and not any(values.get(n, getattr(product, n)) for n in ("name_ja", "name_zh", "name_en") if n != name)
        ):
            raise ApiError(422, "VALIDATION_ERROR", "name_ja、name_zh、name_en 至少需要保留一个")
    touched = changed_fields(product, values)
    proposals = propose_blocked(session, actor, "product", product, values, touched)
    if not touched:
        if proposals:
            commit(session)
            return accepted_response(product_out(session, product), [], proposals)
        return product_out(session, product)
    if "brand_id" in touched:  # 编号唯一性按品牌划分，换品牌要重新检查
        for ident in product.identifiers:
            svc.check_identifier_unique(
                session, values["brand_id"], IdentifierIn(scheme=ident.scheme, value=ident.value), product.id
            )
    before = {k: getattr(product, k) for k in touched}
    for k in touched:
        setattr(product, k, values[k])
    touch(product)
    session.flush()
    log_change(
        session, actor=actor, entity="product", entity_id=product.id, op="update",
        before=before, after={k: values[k] for k in touched}, version_after=product.version,
    )  # fmt: skip
    refresh_items(session, items_of_product(session, product.id), upstream_actor=actor)
    commit(session)
    if proposals:
        return accepted_response(product_out(session, product), touched, proposals)
    return product_out(session, product)


def _propose_collection(session, product: Product, actor: str, field: str, proposed: list[dict]):
    """整体替换子集合的请求触及已核实商品时，生成一条提议（proposed 为完整的新列表）。"""
    p = create_proposal(
        session, actor=actor, entity="product", entity_id=product.id, field=field,
        current=svc.collection_snapshot(product, field), proposed=proposed,
    )  # fmt: skip
    commit(session)
    return accepted_response(product_out(session, product), [], [p])


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: int, session: SessionDep, actor: ActorDep, if_match: IfMatch = None,
                   version: int | None = None):  # fmt: skip
    product = _load(session, product_id)
    require_version(product, version, if_match)
    guard(actor, "product", product, {DELETE})
    in_use = session.scalar(
        select(func.count())
        .select_from(WardrobeItem)
        .where(WardrobeItem.product_id == product.id, WardrobeItem.deleted_at.is_(None))
    )
    if in_use:
        raise ApiError(409, "IN_USE", f"商品仍有 {in_use} 件衣物引用，不能删除")
    product.deleted_at = now_iso()
    touch(product)
    log_change(session, actor=actor, entity="product", entity_id=product.id, op="delete", version_after=product.version)
    commit(session)
    return Response(status_code=204)


@router.post("/{product_id}/restore")
def restore_product(product_id: int, body: Versioned, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    """撤销商品的软删除。编号唯一性按当前数据重新检查。"""
    product = get_or_404(session, Product, product_id, include_deleted=True)
    if product.deleted_at is None:
        raise ApiError(409, "NOT_DELETED", f"商品 {product.id} 没有被删除")
    require_version(product, body.version, if_match)
    guard(actor, "product", product, {DELETE})
    for ident in product.identifiers:
        svc.check_identifier_unique(
            session, product.brand_id, IdentifierIn(scheme=ident.scheme, value=ident.value), product.id
        )
    product.deleted_at = None
    touch(product)
    log_change(
        session, actor=actor, entity="product", entity_id=product.id, op="restore", version_after=product.version
    )
    commit(session)
    return product_out(session, product)


@router.put("/{product_id}/colors")
def put_colors(product_id: int, body: ColorsPut, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    product = _load(session, product_id)
    require_version(product, body.version, if_match)
    rows = svc.build_colors(body.colors)  # 先校验，提议中不会出现非法列表
    if blocked_fields(actor, "product", product, {"colors"}):
        return _propose_collection(session, product, actor, "colors", [c.model_dump(mode="json") for c in body.colors])
    before = svc.collection_snapshot(product, "colors")
    svc.replace_collection(session, product, "colors", rows)
    return _finish(session, product, actor, "colors", before)


@router.put("/{product_id}/sizes")
def put_sizes(product_id: int, body: SizesPut, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    product = _load(session, product_id)
    require_version(product, body.version, if_match)
    rows = svc.build_sizes(body.sizes)
    if blocked_fields(actor, "product", product, {"sizes"}):
        return _propose_collection(session, product, actor, "sizes", [s.model_dump(mode="json") for s in body.sizes])
    before = svc.collection_snapshot(product, "sizes")
    svc.replace_collection(session, product, "sizes", rows)
    return _finish(session, product, actor, "sizes", before)


@router.put("/{product_id}/materials")
def put_materials(product_id: int, body: MaterialsPut, session: SessionDep, actor: ActorDep,
                  if_match: IfMatch = None):  # fmt: skip
    product = _load(session, product_id)
    require_version(product, body.version, if_match)
    rows, warnings = svc.build_materials(body.materials, product.material_text)
    if blocked_fields(actor, "product", product, {"materials"}):
        proposed = [
            {"part": m.part, "part_raw": m.part_raw, "fiber": m.fiber, "fiber_raw": m.fiber_raw, "percent": m.percent}
            for m in rows
        ]
        return _propose_collection(session, product, actor, "materials", proposed)
    before = svc.collection_snapshot(product, "materials")
    svc.replace_collection(session, product, "materials", rows)
    return {**_finish(session, product, actor, "materials", before), "warnings": warnings}


@router.post("/{product_id}/identifiers", status_code=201)
def add_identifier(product_id: int, body: IdentifierAdd, session: SessionDep, actor: ActorDep,
                   if_match: IfMatch = None):  # fmt: skip
    product = _load(session, product_id)
    require_version(product, body.version, if_match)
    new_ident = svc.build_identifier(session, product, body)  # 先做唯一性校验
    if blocked_fields(actor, "product", product, {"identifiers"}):
        proposed = [*svc.collection_snapshot(product, "identifiers"),
                    {"scheme": body.scheme, "value": body.value, "source": body.source}]  # fmt: skip
        return _propose_collection(session, product, actor, "identifiers", proposed)
    before = svc.collection_snapshot(product, "identifiers")
    product.identifiers.append(new_ident)
    return _finish(session, product, actor, "identifiers", before, refresh=True)


@router.delete("/{product_id}/identifiers/{identifier_id}")
def delete_identifier(product_id: int, identifier_id: int, session: SessionDep, actor: ActorDep,
                      if_match: IfMatch = None, version: int | None = None):  # fmt: skip
    product = _load(session, product_id)
    require_version(product, version, if_match)
    guard(actor, "product", product, {"identifiers"})
    target = next((i for i in product.identifiers if i.id == identifier_id), None)
    if target is None:
        raise ApiError(404, "NOT_FOUND", f"商品 {product_id} 没有编号 {identifier_id}")
    before = svc.collection_snapshot(product, "identifiers")
    product.identifiers.remove(target)
    return _finish(session, product, actor, "identifiers", before)


@router.post("/{product_id}/images", status_code=201)
def add_product_image(product_id: int, body: ProductImageLink, session: SessionDep, actor: ActorDep,
                      if_match: IfMatch = None):  # fmt: skip
    product = _load(session, product_id)
    require_version(product, body.version, if_match)
    get_or_404(session, Image, body.image_id)
    if any(pi.image_id == body.image_id for pi in product.images):
        raise ApiError(409, "DUPLICATE", "该图片已关联到此商品")
    before = svc.collection_snapshot(product, "images")
    if body.role == "main":
        for pi in product.images:
            if pi.role == "main":
                pi.role = "gallery"
    product.images.append(
        ProductImage(image_id=body.image_id, role=body.role, color_code=body.color_code, sort_order=body.sort_order)
    )
    return _finish(session, product, actor, "images", before, refresh=False)


@router.delete("/{product_id}/images/{image_id}")
def remove_product_image(product_id: int, image_id: int, session: SessionDep, actor: ActorDep,
                         if_match: IfMatch = None, version: int | None = None):  # fmt: skip
    product = _load(session, product_id)
    require_version(product, version, if_match)
    link = next((pi for pi in product.images if pi.image_id == image_id), None)
    if link is None:
        raise ApiError(404, "NOT_FOUND", f"商品 {product_id} 没有关联图片 {image_id}")
    before = svc.collection_snapshot(product, "images")
    product.images.remove(link)
    return _finish(session, product, actor, "images", before, refresh=False)


def _set_verification(session, product: Product, actor: str, body: Versioned, if_match, verified: bool):
    guard_privileged(actor, "核实/取消核实")
    require_version(product, body.version, if_match)
    product.verification = "verified" if verified else "unverified"
    product.verified_at = now_iso() if verified else None
    touch(product)
    log_change(
        session, actor=actor, entity="product", entity_id=product.id, op="verify" if verified else "unverify",
        version_after=product.version,
    )  # fmt: skip
    commit(session)
    return product_out(session, product)


@router.post("/{product_id}/verify")
def verify_product(product_id: int, body: Versioned, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    return _set_verification(session, _load(session, product_id), actor, body, if_match, True)


@router.post("/{product_id}/unverify")
def unverify_product(product_id: int, body: Versioned, session: SessionDep, actor: ActorDep,
                     if_match: IfMatch = None):  # fmt: skip
    return _set_verification(session, _load(session, product_id), actor, body, if_match, False)
