"""健康检查、元数据、搜索、备份。"""

from fastapi import APIRouter
from sqlalchemy import func, or_, select

from .. import __version__
from ..db import current_revision, head_revision
from ..errors import ApiError
from ..models import Base, Outfit, Product, WardrobeItem
from ..schemas import ENUMS
from ..services.common import commit
from ..services.resolve import reindex_all
from ..services.search import item_search_clause
from ..storage.backup import BackupError, create_backup, list_backups
from .deps import SessionDep, SettingsDep
from .serializers import item_list_out, product_summary

router = APIRouter(tags=["system"])

COUNTED = ("brand", "category", "tag", "product", "purchase", "purchase_line", "wardrobe_item", "outfit", "image")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/meta")
def meta(session: SessionDep, settings: SettingsDep):
    """应用版本、schema 版本、表计数、全部枚举值。AI 构造数据前可先读取。"""
    tables = Base.metadata.tables
    counts = {t: session.scalar(select(func.count()).select_from(tables[t])) for t in COUNTED}
    return {
        "app_version": __version__,
        "schema_revision": current_revision(session.get_bind()),
        "schema_head": head_revision(),
        "data_dir": str(settings.data_dir),
        "counts": counts,
        "enums": ENUMS,
        "client_header": "X-Wardrobe-Client",
        "privileged_clients": ["web-ui", "cli"],
    }


@router.get("/search")
def search(q: str, session: SessionDep, limit: int = 20):
    """跨衣物 / 商品 / 穿搭的混合搜索。"""
    limit = max(1, min(limit, 100))
    items = []
    clause = item_search_clause(q)
    if clause is not None:
        rows = session.scalars(
            select(WardrobeItem).where(WardrobeItem.deleted_at.is_(None), clause).order_by(WardrobeItem.id.desc())
            .limit(limit)
        )  # fmt: skip
        items = [item_list_out(session, i) for i in rows]
    like = f"%{q.strip()}%"
    products = session.scalars(
        select(Product)
        .where(
            Product.deleted_at.is_(None),
            or_(Product.name_ja.like(like), Product.name_zh.like(like), Product.name_en.like(like)),
        )
        .limit(limit)
    )
    outfits = session.scalars(select(Outfit).where(Outfit.deleted_at.is_(None), Outfit.name.like(like)).limit(limit))
    return {
        "items": items,
        "products": [product_summary(p) for p in products],
        "outfits": [{"id": o.id, "name": o.name} for o in outfits],
    }


@router.post("/search/reindex")
def reindex(session: SessionDep):
    count = reindex_all(session)
    commit(session)
    return {"indexed": count}


@router.get("/backups")
def get_backups(settings: SettingsDep):
    return {"items": list_backups(settings)}


@router.post("/backups", status_code=201)
def post_backup(settings: SettingsDep):
    try:
        path = create_backup(settings, "manual")
    except BackupError as exc:
        raise ApiError(500, "BACKUP_FAILED", str(exc)) from exc
    return {"name": path.name, "bytes": path.stat().st_size}
