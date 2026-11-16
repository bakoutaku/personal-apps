"""Phase 5A-1：从本地照片颜色分析显式生成「待确认」的颜色提议。

与 Phase 2 的被动提议（受限请求方修改已核实记录）不同：这里无论衣物是否已核实、请求方是谁，
都只新增一条 pending 提议和它的来源上下文，不修改衣物、购买明细或商品。接受仍走 /proposals。
"""

import threading
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..config import Settings
from ..errors import ApiError, not_found, validation
from ..models import AISuggestionContext, ChangeProposal, Image, ItemImage, WardrobeItem
from .color_analysis import ColorAnalysisError, analyze_file
from .common import now_iso
from .proposals import create_proposal, current_value

# 提议的 reason 只是给人看的简短说明；机器可读的来源全部在 ai_suggestion_context
REASON = "本地照片颜色分析的候选（像素统计，不是语义识别）"


@dataclass(frozen=True)
class Source:
    """分析开始时读取的快照。计算在数据库事务之外进行，写入前会重新核对（整个快照相等才算未变化）。

    颜色也属于同一个快照：分析响应中的 item_version 与 current_color / resolved_color 来自同一时刻。
    """

    item_id: int
    item_version: int
    image_id: int
    image_sha256: str
    storage_path: str
    current_color: dict
    resolved_color: dict


def load_source(session: Session, item_id: int, image_id: int) -> Source:
    item = session.get(WardrobeItem, item_id)
    if item is None or item.deleted_at is not None:
        raise not_found("wardrobe_item", item_id)
    img = session.get(Image, image_id)
    # 只能分析这件衣物自己已关联的图片；不存在与未关联给出同一个错误，不暴露其他图片
    if img is None or session.get(ItemImage, (item_id, image_id)) is None:
        raise validation(["image_id"], "not_linked", f"图片 {image_id} 不是衣物 {item_id} 自己已关联的图片")
    resolved = {
        "code": item.eff_color_code,
        "name": item.eff_color_name,
        "hex": item.eff_color_hex,
        "family": item.eff_color_family,
        "source": (item.eff_sources or {}).get("color"),
    }
    current = current_value("wardrobe_item", item, "color")
    return Source(item.id, item.version, img.id, img.sha256, img.storage_path, current, resolved)


# 同时进行的分析数量上限：解码大图（尤其非 JPEG）会占用数百 MB 内存，避免并发请求叠加
_ANALYSIS_SLOTS = threading.BoundedSemaphore(2)


def run_analysis(settings: Settings, source: Source, region: dict | None) -> dict:
    try:
        with _ANALYSIS_SLOTS:
            return analyze_file(settings.images_dir / source.storage_path, source.image_sha256, region)
    except ColorAnalysisError as exc:
        status = 409 if exc.code == "IMAGE_UNAVAILABLE" else 422
        raise ApiError(status, exc.code, exc.message) from exc


def analysis_out(source: Source, result: dict) -> dict:
    return {
        "item_id": source.item_id,
        "item_version": source.item_version,
        "image_id": source.image_id,
        "image_sha256": source.image_sha256,
        "current_color": dict(source.current_color),
        "resolved_color": dict(source.resolved_color),
        **result,
    }


def create_color_suggestion(
    session: Session,
    *,
    actor: str,
    source: Source,
    result: dict,
    candidate_hex: str,
    color_code: str | None,
    color_name: str | None,
) -> ChangeProposal:
    """调用方已在写事务内重新 load_source 并核对 version。这里核对候选并创建提议与上下文。"""
    if result["status"] != "ok":
        raise validation(["candidate_hex"], "no_suggestion", "这张图片（区域）没有可用的颜色候选，未生成建议")
    chosen = next((c for c in result["candidates"] if c["hex"] == candidate_hex), None)
    if chosen is None:
        raise validation(
            ["candidate_hex"], "not_a_candidate", f"{candidate_hex} 不在本次分析的候选中",
            "请先调用 color-analysis，并从返回的 candidates 中选择",
        )  # fmt: skip
    item = session.get(WardrobeItem, source.item_id)
    current = current_value("wardrobe_item", item, "color")
    # 整组写入：color_code / color_name 只来自调用方（省略为 null，即清空原覆盖值），从不由 HEX 推测
    proposed = {"color_code": color_code, "color_name": color_name, "color_hex": candidate_hex}
    if proposed == current:
        raise validation(["candidate_hex"], "no_change", "建议的颜色与衣物当前的颜色覆盖值相同，未生成建议")
    p = create_proposal(
        session, actor=actor, entity="wardrobe_item", entity_id=item.id, field="color",
        current=current, proposed=proposed, reason=REASON,
    )  # fmt: skip
    session.add(
        AISuggestionContext(
            proposal_id=p.id,
            kind="color",
            target_version=source.item_version,
            image_id=source.image_id,
            image_sha256=source.image_sha256,
            region=result["region"],
            algorithm=result["algorithm"],
            parameters=result["parameters"],
            candidate=chosen,
            candidates=result["candidates"],
            created_at=now_iso(),
        )
    )
    session.flush()
    session.refresh(p, ["ai_context"])
    return p
