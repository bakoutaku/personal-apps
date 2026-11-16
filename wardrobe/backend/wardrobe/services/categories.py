"""分类树校验（DATA_MODEL R8）。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import ApiError, not_found, validation
from ..models import Category, Product, WardrobeItem

MAX_LEVEL = 3


def resolve_category(session: Session, ref: int | str | None, loc: str = "category") -> Category | None:
    """按 id 或 slug 查分类；None 表示未指定。"""
    if ref is None:
        return None
    if isinstance(ref, int):
        cat = session.get(Category, ref)
    else:
        cat = session.scalar(select(Category).where(Category.slug == ref))
    if cat is None:
        raise validation([loc], "not_found", f"分类 {ref!r} 不存在", "可用 GET /api/v1/categories 查看")
    return cat


def children_map(session: Session) -> dict[int | None, list[Category]]:
    result: dict[int | None, list[Category]] = {}
    for c in session.scalars(select(Category).order_by(Category.sort_order, Category.id)):
        result.setdefault(c.parent_id, []).append(c)
    return result


def descendant_ids(session: Session, root_id: int) -> list[int]:
    cmap = children_map(session)
    out, stack = [], [root_id]
    while stack:
        cid = stack.pop()
        out.append(cid)
        stack.extend(c.id for c in cmap.get(cid, []))
    return out


def subtree_height(session: Session, root_id: int) -> int:
    """以 root 为第 1 层的子树高度。"""
    cmap = children_map(session)

    def h(cid: int) -> int:
        return 1 + max((h(c.id) for c in cmap.get(cid, [])), default=0)

    return h(root_id)


def path_of(session: Session, category: Category | None) -> list[Category]:
    path = []
    while category is not None:
        path.append(category)
        category = session.get(Category, category.parent_id) if category.parent_id else None
    return list(reversed(path))


def place(session: Session, category: Category, parent: Category | None) -> None:
    """设置父节点并重算整棵子树 level；防循环、防超过三级。"""
    if parent is not None and category.id is not None:
        if parent.id in descendant_ids(session, category.id):
            raise validation(["parent"], "cycle", "不能把分类移动到自己或自己的子分类下面")
    new_level = 1 if parent is None else parent.level + 1
    height = subtree_height(session, category.id) if category.id is not None else 1
    if new_level + height - 1 > MAX_LEVEL:
        raise validation(
            ["parent"], "too_deep", f"分类最多 {MAX_LEVEL} 级：移动后子树会达到第 {new_level + height - 1} 级"
        )
    category.parent_id = parent.id if parent else None
    delta = new_level - (category.level or new_level)
    category.level = new_level
    if category.id is not None and delta:
        for cid in descendant_ids(session, category.id)[1:]:
            child = session.get(Category, cid)
            child.level += delta


def ensure_deletable(session: Session, category: Category) -> None:
    if session.scalar(select(func.count()).where(Category.parent_id == category.id)):
        raise ApiError(409, "IN_USE", "分类下还有子分类，不能删除")
    used = session.scalar(
        select(func.count()).select_from(Product).where(Product.category_id == category.id)
    ) or session.scalar(select(func.count()).select_from(WardrobeItem).where(WardrobeItem.category_id == category.id))
    if used:
        raise ApiError(409, "IN_USE", "分类仍被商品或衣物引用，不能删除")


def get_category(session: Session, ident: int) -> Category:
    cat = session.get(Category, ident)
    if cat is None:
        raise not_found("category", ident)
    return cat
