"""已核实记录保护（DATA_MODEL R4）。

Phase 1：受限请求方（非 web-ui / cli）触及已核实记录的受保护字段 → 409 VERIFIED_PROTECTED。
所有写入口都调用 guard()，且在任何修改之前调用；即使之后出错，请求事务也会整体回滚。
"""

from typing import Any

from ..errors import ApiError
from ..security import is_privileged

# 虚拟字段：子集合与删除
DELETE = "_delete"

PROTECTED: dict[str, frozenset[str]] = {
    "product": frozenset(
        {
            "brand_id", "category_id", "name_ja", "name_zh", "name_en", "gender", "detail_url",
            "material_text", "care_text", "care_symbols", "list_price", "currency", "origin", "season_label",
            "identifiers", "colors", "sizes", "materials", DELETE,
        }
    ),
    "purchase_line": frozenset(
        {
            "product_id", "product_match", "item_code_raw", "name_raw", "color_code", "color_name",
            "color_hex", "size_label", "size_system", "quantity", "unit_price", "discount_amount", DELETE,
        }
    ),
    "wardrobe_item": frozenset(
        {
            "product_id", "purchase_line_id", "category_id", "color_code", "color_name", "color_hex",
            "size_label", "size_system", "status", "acquired_on", "retired_on", "refund_amount", DELETE,
        }
    ),
}  # fmt: skip


def changed_fields(obj: Any, values: dict[str, Any]) -> set[str]:
    """只把值真正变化的字段视为「触及」：AI 原样回传已核实值不会被拒绝。"""
    return {k for k, v in values.items() if getattr(obj, k, None) != v}


def guard(actor: str, entity: str, obj: Any, touched: set[str]) -> None:
    if obj.verification != "verified" or is_privileged(actor):
        return
    blocked = sorted(touched & PROTECTED[entity])
    if blocked:
        raise ApiError(
            409,
            "VERIFIED_PROTECTED",
            f"{entity} {obj.id} 已核实，请求方 {actor!r} 不能修改受保护字段：{', '.join(blocked)}",
            [{"loc": [f], "code": "protected"} for f in blocked],
        )


def guard_privileged(actor: str, action: str) -> None:
    """核实/取消核实等操作只允许 web-ui / cli。"""
    if not is_privileged(actor):
        raise ApiError(403, "PRIVILEGED_ONLY", f"{action} 只允许 web-ui 或 cli 执行，当前请求方 {actor!r}")
