"""Phase 5B：相似衣物（只读）。规则见 services/similar.py 与 docs/PHASE5B_SIMILAR_ITEMS.md。"""

from typing import Literal

from fastapi import APIRouter, Query

from ..models import WardrobeItem
from ..services.common import get_or_404
from ..services.similar import rules, similar_items
from .deps import SessionDep
from .serializers import item_list_out

router = APIRouter(prefix="/items", tags=["similar"])


@router.get("/{item_id}/similar")
def get_similar(
    item_id: int,
    session: SessionDep,
    status: Literal["owned", "all"] = "owned",
    limit: int = Query(8, ge=1, le=24),
):
    """不修改任何数据（GET，普通读事务）。默认只推荐持有中的衣物；status=all 时包含其他状态。"""
    target = get_or_404(session, WardrobeItem, item_id)
    ranked = similar_items(session, target, include_all_status=status == "all", limit=limit)
    return {
        "item_id": target.id,
        **rules(),
        "status": status,
        "items": [
            {"score": s, "reasons": reasons, "item": item_list_out(session, other)} for s, _n, other, reasons in ranked
        ],
    }
