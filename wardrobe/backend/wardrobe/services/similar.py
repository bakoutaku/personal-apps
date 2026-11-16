"""Phase 5B：基于现有资料的相似衣物（规则 wardrobe-similar/1）。

只用分类、有效颜色族、标签三类已有资料，按固定权重打分，不使用图像模型或外部服务。
任何一方缺少某项资料（未分类、没有有效颜色、没有标签）时，该项不算匹配。

| 匹配 | 分值 | 理由 |
|---|---|---|
| 有效分类完全相同 | 4 | 同类衣物（分类名） |
| 否则：属于同一个二级分类 | 3 | 同属「二级分类名」 |
| 否则：只属于同一个一级分类 | 1 | 同属「一级分类名」（单独不足以推荐） |
| 有效颜色族相同 | 3 | 颜色相近（颜色族） |
| 每个共有标签（按规范化名称） | 2，最多计 3 个 | 共有标签：#… |

总分 ≥ MIN_SCORE（3）才推荐；按（总分降序、共有标签数降序、衣物 id 降序）排序。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Category, Product, WardrobeItem

ALGORITHM = "wardrobe-similar/1"
WEIGHTS = {"same_category": 4, "same_group": 3, "same_top": 1, "same_color_family": 3, "shared_tag": 2}
MAX_TAGS = 3
MIN_SCORE = 3

# 与前端 lib/labels.ts 的 COLOR_FAMILIES 一致
FAMILY_LABELS = {
    "black": "黑", "white": "白", "gray": "灰", "beige": "米", "brown": "棕", "red": "红", "pink": "粉",
    "orange": "橙", "yellow": "黄", "green": "绿", "blue": "蓝", "navy": "藏青", "purple": "紫", "multi": "多色",
}  # fmt: skip


def rules() -> dict:
    return {"algorithm": ALGORITHM, "weights": dict(WEIGHTS), "max_shared_tags": MAX_TAGS, "min_score": MIN_SCORE}


def _chain(cat_id: int | None, cats: dict[int, Category]) -> list[Category]:
    """从一级到该分类的路径。"""
    out: list[Category] = []
    while cat_id is not None and cat_id in cats:
        out.append(cats[cat_id])
        cat_id = cats[cat_id].parent_id
    return list(reversed(out))


def _effective_category(item: WardrobeItem) -> int | None:
    return item.category_id if item.category_id is not None else item.product.category_id


def score(target: WardrobeItem, other: WardrobeItem, cats: dict[int, Category]) -> tuple[int, list[dict], int]:
    total, reasons = 0, []
    a, b = _effective_category(target), _effective_category(other)
    if a is not None and b is not None:
        ca, cb = _chain(a, cats), _chain(b, cats)
        if a == b:
            total += WEIGHTS["same_category"]
            reasons.append(
                {"kind": "same_category", "label": f"同类衣物（{cats[a].name_zh}）", "points": WEIGHTS["same_category"]}
            )
        elif len(ca) >= 2 and len(cb) >= 2 and ca[1].id == cb[1].id:
            total += WEIGHTS["same_group"]
            reasons.append({"kind": "same_group", "label": f"同属「{ca[1].name_zh}」", "points": WEIGHTS["same_group"]})
        elif ca and cb and ca[0].id == cb[0].id:
            total += WEIGHTS["same_top"]
            reasons.append({"kind": "same_top", "label": f"同属「{ca[0].name_zh}」", "points": WEIGHTS["same_top"]})
    fa, fb = target.eff_color_family, other.eff_color_family
    if fa and fb and fa == fb:
        total += WEIGHTS["same_color_family"]
        reasons.append(
            {
                "kind": "same_color_family",
                "label": f"颜色相近（{FAMILY_LABELS.get(fa, fa)}）",
                "points": WEIGHTS["same_color_family"],
            }
        )
    mine = {t.name_norm: t.name for t in target.tags}
    shared = [t.name for t in other.tags if t.name_norm in mine]
    if shared:
        counted = shared[:MAX_TAGS]
        pts = WEIGHTS["shared_tag"] * len(counted)
        total += pts
        reasons.append(
            {"kind": "shared_tags", "label": "共有标签：" + "、".join(f"#{n}" for n in shared), "points": pts}
        )
    return total, reasons, len(shared)


def similar_items(session: Session, target: WardrobeItem, *, include_all_status: bool, limit: int) -> list[tuple]:
    cats = {c.id: c for c in session.scalars(select(Category))}
    q = (
        select(WardrobeItem)
        .where(WardrobeItem.deleted_at.is_(None), WardrobeItem.id != target.id)
        .options(selectinload(WardrobeItem.tags), selectinload(WardrobeItem.product).selectinload(Product.category))
    )
    if not include_all_status:
        q = q.where(WardrobeItem.status == "owned")
    ranked = []
    for other in session.scalars(q):
        total, reasons, n_tags = score(target, other, cats)
        if total >= MIN_SCORE:
            ranked.append((total, n_tags, other, reasons))
    ranked.sort(key=lambda r: (-r[0], -r[1], -r[2].id))
    return ranked[:limit]
