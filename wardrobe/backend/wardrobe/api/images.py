"""图片上传与管理。文件按内容去重；删除记录后在提交之后清理孤儿文件。"""

from typing import Annotated

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from sqlalchemy import func, select

from ..errors import ApiError, not_found
from ..models import Image, ItemImage, Outfit, OutfitImage, ProductImage
from ..schemas import SourceType
from ..services.common import commit, log_change, now_iso
from ..storage.images import ImageRejected, gc_orphans, image_lock, store_image
from .deps import ActorDep, SessionDep, SettingsDep
from .serializers import image_out

router = APIRouter(prefix="/images", tags=["images"])


def _references(session, image_id: int) -> dict[str, list[int]]:
    return {
        "products": list(session.scalars(select(ProductImage.product_id).where(ProductImage.image_id == image_id))),
        "items": list(session.scalars(select(ItemImage.item_id).where(ItemImage.image_id == image_id))),
        "outfits": sorted(
            set(session.scalars(select(OutfitImage.outfit_id).where(OutfitImage.image_id == image_id)))
            | set(session.scalars(select(Outfit.id).where(Outfit.cover_image_id == image_id)))
        ),
    }


@router.post("", status_code=201)
def upload_image(
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
    response: Response,
    file: Annotated[UploadFile, File(description="JPEG / PNG / WebP")],
    source_type: Annotated[SourceType, Form()] = "user_upload",
    source_url: Annotated[str | None, Form()] = None,
    source_note: Annotated[str | None, Form()] = None,
):
    data = file.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", f"文件超过 {settings.max_upload_bytes // (1024 * 1024)} MB 上限")
    # 写文件到提交记录都在 image_lock 内，GC 不会在两者之间把文件当作孤儿删除（BUG-009）
    with image_lock(settings):
        try:
            stored = store_image(settings, data)
        except ImageRejected as exc:
            raise ApiError(422, "INVALID_IMAGE", str(exc)) from exc

        existing = session.scalar(select(Image).where(Image.sha256 == stored.sha256))
        if existing is not None:
            response.status_code = 200
            return {**image_out(existing), "deduplicated": True}
        return _insert_image(session, stored, actor, source_type, source_url, source_note)


def _insert_image(session, stored, actor, source_type, source_url, source_note) -> dict:
    img = Image(
        sha256=stored.sha256, mime=stored.mime, width=stored.width, height=stored.height, bytes=stored.bytes,
        storage_path=stored.storage_path, thumb_path=stored.thumb_path, source_type=source_type,
        source_url=(source_url or "").strip() or None, source_note=(source_note or "").strip() or None,
        created_at=now_iso(),
    )  # fmt: skip
    session.add(img)
    session.flush()
    log_change(
        session, actor=actor, entity="image", entity_id=img.id, op="create",
        after={"sha256": img.sha256, "source_type": source_type, "source_url": img.source_url},
    )  # fmt: skip
    commit(session)
    return {**image_out(img), "deduplicated": False}


@router.get("")
def list_images(session: SessionDep, limit: int = 50, offset: int = 0):
    limit = max(1, min(limit, 200))
    total = session.scalar(select(func.count()).select_from(Image))
    rows = session.scalars(select(Image).order_by(Image.id.desc()).limit(limit).offset(max(0, offset)))
    return {"items": [image_out(i) for i in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/{image_id}")
def get_image(image_id: int, session: SessionDep):
    img = session.get(Image, image_id)
    if img is None:
        raise not_found("image", image_id)
    return {**image_out(img), "references": _references(session, image_id)}


@router.delete("/{image_id}", status_code=204)
def delete_image(image_id: int, request: Request, session: SessionDep, settings: SettingsDep, actor: ActorDep):
    img = session.get(Image, image_id)
    if img is None:
        raise not_found("image", image_id)
    refs = _references(session, image_id)
    if any(refs.values()):
        raise ApiError(409, "IN_USE", "图片仍被引用，请先解除关联", [refs])
    sha = img.sha256
    log_change(session, actor=actor, entity="image", entity_id=img.id, op="delete", before={"sha256": sha})
    session.delete(img)
    commit(session)
    gc_orphans(settings, request.app.state.sessionmaker, only_sha={sha})  # 提交之后才删文件（DATA_MODEL 5.1）
    return Response(status_code=204)
