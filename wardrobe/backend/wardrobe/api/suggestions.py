"""Phase 5A-1：衣物照片的本地颜色分析与颜色建议（API 契约见 docs/PHASE5A_BACKEND_CONTRACT.md）。

* color-analysis 只读：不写衣物、图片主色或提议。像素计算在数据库事务之外进行，不长时间占用写锁。
* color-suggestions 只新增一条 pending 颜色提议和来源上下文；接受/拒绝仍使用 /proposals。
"""

from fastapi import APIRouter, Request

from ..ai_schemas import ColorAnalysisIn, ColorSuggestionIn
from ..db import IMMEDIATE
from ..errors import ApiError
from ..models import WardrobeItem
from ..services.ai_suggestions import analysis_out, create_color_suggestion, load_source, run_analysis
from ..services.common import actor_of, commit, require_version
from ..services.proposals import proposal_out

router = APIRouter(prefix="/items", tags=["ai-suggestions"])


@router.post("/{item_id}/color-analysis")
def color_analysis(item_id: int, body: ColorAnalysisIn, request: Request):
    factory = request.app.state.sessionmaker
    region = body.region.model_dump() if body.region else None
    with factory() as session:  # 普通读事务
        source = load_source(session, item_id, body.image_id)
    result = run_analysis(request.app.state.settings, source, region)
    return analysis_out(source, result)


@router.post("/{item_id}/color-suggestions", status_code=201)
def color_suggestions(item_id: int, body: ColorSuggestionIn, request: Request):
    factory = request.app.state.sessionmaker
    region = body.region.model_dump() if body.region else None
    with factory() as session:
        source = load_source(session, item_id, body.image_id)
        require_version(session.get(WardrobeItem, item_id), body.version)
    # 服务端自己重新计算，不信任客户端给出的候选
    result = run_analysis(request.app.state.settings, source, region)

    with factory() as session:
        session.connection(execution_options={IMMEDIATE: True})
        # 写锁内重新核对：计算期间衣物、图片或关联若有变化，不能为旧上下文生成建议。
        # 计算期间图片被解除关联也属于「来源已变化」（409），与一开始就选错图片（422）区分
        try:
            latest = load_source(session, item_id, body.image_id)
        except ApiError as exc:
            if exc.status != 422:
                raise
            raise ApiError(409, "VERSION_CONFLICT", "分析期间这张图片已不再关联到这件衣物，请重新分析") from exc
        require_version(session.get(WardrobeItem, item_id), body.version)
        if latest != source:
            raise ApiError(409, "VERSION_CONFLICT", "分析期间图片或衣物已变化，请重新分析")
        p = create_color_suggestion(
            session, actor=actor_of(request), source=latest, result=result,
            candidate_hex=body.candidate_hex, color_code=body.color_code, color_name=body.color_name,
        )  # fmt: skip
        commit(session)
        return {"proposal": proposal_out(p), "analysis": analysis_out(latest, result)}
