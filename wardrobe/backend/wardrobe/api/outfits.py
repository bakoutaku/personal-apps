"""穿搭 Outfit。条目、标签、图片属于穿搭（聚合根），修改都要带穿搭的 version。"""

from fastapi import APIRouter, Response
from sqlalchemy import func, select

from ..errors import ApiError, validation
from ..models import Image, Outfit, OutfitImage, OutfitItem, OutfitTag, Tag, WardrobeItem
from ..schemas import OutfitCreate, OutfitImageLink, OutfitItemIn, OutfitItemsPut, OutfitPatch, TagsPut
from ..services.common import commit, get_or_404, log_change, now_iso, require_version, touch
from ..services.products import get_or_create_tags
from ..services.text import normalize_tag
from .deps import ActorDep, IfMatch, PagingDep, SessionDep, page
from .serializers import outfit_out

router = APIRouter(prefix="/outfits", tags=["outfits"])


def _build_items(session, items: list[OutfitItemIn]) -> list[OutfitItem]:
    seen = set()
    out = []
    for i, it in enumerate(items):
        if it.item_id in seen:
            raise validation(["items", i, "item_id"], "duplicate", f"衣物 {it.item_id} 重复")
        seen.add(it.item_id)
        item = session.get(WardrobeItem, it.item_id)
        if item is None or item.deleted_at is not None:
            raise validation(["items", i, "item_id"], "not_found", f"衣物 {it.item_id} 不存在")
        out.append(OutfitItem(item_id=it.item_id, slot=it.slot, sort_order=it.sort_order or i))
    return out


def _check_cover(session, image_id: int | None) -> None:
    if image_id is not None and session.get(Image, image_id) is None:
        raise validation(["cover_image_id"], "not_found", f"图片 {image_id} 不存在")


def _items_snapshot(o: Outfit) -> list[dict]:
    return [{"item_id": x.item_id, "slot": x.slot} for x in o.items]


@router.get("")
def list_outfits(
    session: SessionDep,
    paging: PagingDep,
    tag: str | None = None,
    season: str | None = None,
    contains_item: int | None = None,
    q: str | None = None,
):
    limit, offset = paging
    query = select(Outfit).where(Outfit.deleted_at.is_(None))
    if tag:
        query = query.where(
            Outfit.id.in_(
                select(OutfitTag.outfit_id)
                .join(Tag, Tag.id == OutfitTag.tag_id)
                .where(Tag.name_norm == normalize_tag(tag))
            )
        )
    if season:
        query = query.where(Outfit.season == season)
    if contains_item is not None:
        query = query.where(Outfit.id.in_(select(OutfitItem.outfit_id).where(OutfitItem.item_id == contains_item)))
    if q:
        query = query.where(Outfit.name.like(f"%{q.strip()}%"))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.scalars(query.order_by(Outfit.id.desc()).limit(limit).offset(offset))
    return page([outfit_out(session, o) for o in rows], total, limit, offset)


@router.post("", status_code=201)
def create_outfit(body: OutfitCreate, session: SessionDep, actor: ActorDep):
    _check_cover(session, body.cover_image_id)
    now = now_iso()
    outfit = Outfit(
        **body.model_dump(exclude={"items", "tags", "attributes"}),
        attributes=body.attributes or {}, created_at=now, updated_at=now, version=1,
    )  # fmt: skip
    session.add(outfit)
    outfit.items = _build_items(session, body.items)
    outfit.tags = get_or_create_tags(session, body.tags)
    session.flush()
    log_change(
        session, actor=actor, entity="outfit", entity_id=outfit.id, op="create",
        after=body.model_dump(mode="json", exclude_none=True), version_after=outfit.version,
    )  # fmt: skip
    commit(session)
    return outfit_out(session, outfit)


@router.get("/{outfit_id}")
def get_outfit(outfit_id: int, session: SessionDep):
    return outfit_out(session, get_or_404(session, Outfit, outfit_id))


@router.patch("/{outfit_id}")
def patch_outfit(outfit_id: int, body: OutfitPatch, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    outfit = get_or_404(session, Outfit, outfit_id)
    require_version(outfit, body.version, if_match)
    values = body.model_dump(exclude_unset=True, exclude={"version"})
    if "name" in values and values["name"] is None:
        raise validation(["name"], "required", "name 不能为空")
    if "attributes" in values and values["attributes"] is None:
        values["attributes"] = {}
    if "cover_image_id" in values:
        _check_cover(session, values["cover_image_id"])
    changed = {k: v for k, v in values.items() if getattr(outfit, k) != v}
    if changed:
        before = {k: getattr(outfit, k) for k in changed}
        for k, v in changed.items():
            setattr(outfit, k, v)
        touch(outfit)
        log_change(
            session, actor=actor, entity="outfit", entity_id=outfit.id, op="update",
            before=before, after=changed, version_after=outfit.version,
        )  # fmt: skip
        commit(session)
    return outfit_out(session, outfit)


@router.delete("/{outfit_id}", status_code=204)
def delete_outfit(outfit_id: int, session: SessionDep, actor: ActorDep, if_match: IfMatch = None,
                  version: int | None = None):  # fmt: skip
    outfit = get_or_404(session, Outfit, outfit_id)
    require_version(outfit, version, if_match)
    outfit.deleted_at = now_iso()
    touch(outfit)
    log_change(session, actor=actor, entity="outfit", entity_id=outfit.id, op="delete", version_after=outfit.version)
    commit(session)
    return Response(status_code=204)


@router.put("/{outfit_id}/items")
def put_outfit_items(outfit_id: int, body: OutfitItemsPut, session: SessionDep, actor: ActorDep,
                     if_match: IfMatch = None):  # fmt: skip
    outfit = get_or_404(session, Outfit, outfit_id)
    require_version(outfit, body.version, if_match)
    before = _items_snapshot(outfit)
    rows = _build_items(session, body.items)
    outfit.items.clear()
    session.flush()
    outfit.items = rows
    touch(outfit)
    session.flush()
    log_change(
        session, actor=actor, entity="outfit", entity_id=outfit.id, op="update",
        before={"items": before}, after={"items": _items_snapshot(outfit)}, version_after=outfit.version,
    )  # fmt: skip
    commit(session)
    return outfit_out(session, outfit)


@router.put("/{outfit_id}/tags")
def put_outfit_tags(outfit_id: int, body: TagsPut, session: SessionDep, actor: ActorDep, if_match: IfMatch = None):
    outfit = get_or_404(session, Outfit, outfit_id)
    require_version(outfit, body.version, if_match)
    before = [t.name for t in outfit.tags]
    outfit.tags = get_or_create_tags(session, body.tags)
    touch(outfit)
    log_change(
        session, actor=actor, entity="outfit", entity_id=outfit.id, op="update",
        before={"tags": before}, after={"tags": [t.name for t in outfit.tags]}, version_after=outfit.version,
    )  # fmt: skip
    commit(session)
    return outfit_out(session, outfit)


@router.post("/{outfit_id}/images", status_code=201)
def add_outfit_image(outfit_id: int, body: OutfitImageLink, session: SessionDep, actor: ActorDep,
                     if_match: IfMatch = None):  # fmt: skip
    outfit = get_or_404(session, Outfit, outfit_id)
    require_version(outfit, body.version, if_match)
    get_or_404(session, Image, body.image_id)
    if any(x.image_id == body.image_id for x in outfit.images):
        raise ApiError(409, "DUPLICATE", "该图片已关联到此穿搭")
    outfit.images.append(OutfitImage(image_id=body.image_id, sort_order=body.sort_order))
    touch(outfit)
    log_change(
        session, actor=actor, entity="outfit", entity_id=outfit.id, op="update",
        after={"images_added": [body.image_id]}, version_after=outfit.version,
    )  # fmt: skip
    commit(session)
    return outfit_out(session, outfit)


@router.delete("/{outfit_id}/images/{image_id}")
def remove_outfit_image(outfit_id: int, image_id: int, session: SessionDep, actor: ActorDep,
                        if_match: IfMatch = None, version: int | None = None):  # fmt: skip
    outfit = get_or_404(session, Outfit, outfit_id)
    require_version(outfit, version, if_match)
    link = next((x for x in outfit.images if x.image_id == image_id), None)
    if link is None:
        raise ApiError(404, "NOT_FOUND", f"穿搭 {outfit_id} 没有关联图片 {image_id}")
    outfit.images.remove(link)
    touch(outfit)
    log_change(
        session, actor=actor, entity="outfit", entity_id=outfit.id, op="update",
        before={"images_removed": [image_id]}, version_after=outfit.version,
    )  # fmt: skip
    commit(session)
    return outfit_out(session, outfit)
