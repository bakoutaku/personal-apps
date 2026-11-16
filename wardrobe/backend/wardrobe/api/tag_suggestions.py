"""Phase 5C：标签 / 分类规则建议（规则见 services/tag_category_suggestions.py 与 docs/PHASE5C_TAG_CATEGORY_SUGGESTIONS.md）。

* GET 接口只读：计算候选，不写任何数据。
* POST 只新增 pending 提议（标签：追加；分类：写入衣物自身分类）和规则依据；接受 / 拒绝仍使用 /proposals。
"""

from fastapi import APIRouter, Query

from ..ai_schemas import BatchSuggestionCreate, TagSuggestionCreate
from ..errors import ApiError
from ..models import WardrobeItem
from ..services.common import commit, get_or_404
from ..services.proposals import proposal_out
from ..services.tag_category_suggestions import Library, create_suggestions, rules, suggestions_for
from .deps import ActorDep, SessionDep
from .serializers import item_list_out

router = APIRouter(tags=["tag-suggestions"])


def _public(s: dict) -> dict:
    return {**s, "tags": [{k: t[k] for k in ("name", "reasons", "evidence")} for t in s["tags"]]}


@router.get("/items/{item_id}/tag-suggestions")
def get_item_suggestions(item_id: int, session: SessionDep):
    item = get_or_404(session, WardrobeItem, item_id)
    return {**rules(), **_public(suggestions_for(session, item))}


@router.post("/items/{item_id}/tag-suggestions", status_code=201)
def create_item_suggestions(item_id: int, body: TagSuggestionCreate, session: SessionDep, actor: ActorDep):
    item = get_or_404(session, WardrobeItem, item_id)
    proposals = create_suggestions(
        session, actor=actor, item=item, version=body.version, tags=body.tags, category_id=body.category_id
    )
    commit(session)
    return {"proposals": [proposal_out(p) for p in proposals]}


@router.get("/tag-suggestions")
def list_suggestions(session: SessionDep, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    """批量预览：持有中、至少有一条建议的衣物（新的在前）。只读。整库资料只读一次（Library），逐件复用。"""
    lib = Library(session)
    found = []
    for item in sorted(lib.owned, key=lambda it: -it.id):
        s = suggestions_for(session, item, lib)
        if s["tags"] or s["category"]:
            found.append((item, s))
    page = found[offset : offset + limit]
    return {
        **rules(),
        "total": len(found),
        "limit": limit,
        "offset": offset,
        "items": [{"item": item_list_out(session, it), **_public(s)} for it, s in page],
    }


@router.post("/tag-suggestions/batch", status_code=201)
def create_batch(body: BatchSuggestionCreate, session: SessionDep, actor: ActorDep):
    """逐件处理；每件在自己的保存点内，失败的衣物不影响其他衣物，结果逐件返回。"""
    session.info["defer_commit"] = True
    lib = Library(session)  # 生成提议不改变标签与分类，整批共用一次读取
    results = []
    for entry in body.items:
        try:
            with session.begin_nested():
                item = get_or_404(session, WardrobeItem, entry.item_id)
                ps = create_suggestions(
                    session, actor=actor, item=item, version=entry.version, tags=entry.tags,
                    category_id=entry.category_id, lib=lib,
                )  # fmt: skip
            results.append({"item_id": entry.item_id, "ok": True, "proposals": [proposal_out(p) for p in ps]})
        except ApiError as exc:
            results.append({"item_id": entry.item_id, "ok": False, "error": {"code": exc.code, "message": exc.message}})
    session.info["defer_commit"] = False
    commit(session)
    ok_count = sum(r["ok"] for r in results)
    return {"results": results, "succeeded": ok_count, "failed": len(results) - ok_count}
