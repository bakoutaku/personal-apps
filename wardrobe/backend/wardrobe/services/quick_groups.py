"""衣橱与挑选衣物用的快捷分组（「T恤」「衬衫」「半袖」…）。

每组由分类（含子孙）、只算该分类本身的分类（不含子孙）和标签组成，满足任一即属于该组。
分类按 slug 指定，库里不存在的 slug 忽略（用户可能改过分类树）。
「T恤」包含只分到「T恤·针织」这一层的衣物，但不包含其下的针织衫、卫衣；「半袖」= 短袖T恤分类，或带「短袖」「无袖」标签
（商品名称含「半袖」「5分袖」「ノースリーブ」等时，标签建议会给出这两个标签）。
more=True 的组在界面上收进「更多」。
"""

from dataclasses import dataclass

from sqlalchemy import false, func, or_, select

from ..models import Category, ItemTag, Product, Tag, WardrobeItem
from .categories import descendant_ids
from .text import normalize_tag


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    subtree: tuple[str, ...] = ()
    exact: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    more: bool = False


GROUPS: tuple[Group, ...] = (
    Group("tshirt", "T恤", subtree=("tops-tshirt-short", "tops-tshirt-long"), exact=("tops-tshirt",)),
    Group("shirt", "衬衫", subtree=("tops-shirt", "tops-polo")),
    Group("short_sleeve", "半袖", subtree=("tops-tshirt-short",), tags=("短袖", "无袖")),
    Group("knit", "毛衣", subtree=("tops-knit",)),
    Group("hoodie", "帽衫", subtree=("tops-sweat",)),
    Group("outer", "外套", subtree=("outer",)),
    Group("pants", "长裤", subtree=("bottoms-pants",)),
    Group("shorts", "短裤", subtree=("bottoms-shorts",)),
    Group("skirt", "裙子", subtree=("bottoms-skirt",)),
    Group("dress", "连衣裙", subtree=("dresses",)),
    Group("shoes", "鞋", subtree=("shoes",)),
    Group(
        "inner",
        "内衣",
        subtree=("innerwear-heattech", "innerwear-airism", "innerwear-underwear", "innerwear-loungewear"),
        exact=("innerwear",),
        more=True,
    ),
    Group("socks", "袜子", subtree=("innerwear-socks",), more=True),
    Group("hat", "帽子", subtree=("accessories-hat",), more=True),
    Group("bag", "包", subtree=("bags",), more=True),
    Group("accessory", "配饰", subtree=("accessories-belt", "accessories-scarf"), exact=("accessories",), more=True),
)
BY_KEY = {g.key: g for g in GROUPS}


def group_clause(session, group: Group):
    """属于该组的衣物条件（用于 WHERE）。"""
    by_slug = {c.slug: c.id for c in session.scalars(select(Category))}
    cat_ids: set[int] = set()
    for slug in group.subtree:
        if slug in by_slug:
            cat_ids |= set(descendant_ids(session, by_slug[slug]))
    cat_ids |= {by_slug[s] for s in group.exact if s in by_slug}
    parts = []
    if cat_ids:
        parts.append(func.coalesce(WardrobeItem.category_id, Product.category_id).in_(cat_ids))
    if group.tags:
        norms = [normalize_tag(t) for t in group.tags]
        tagged = select(ItemTag.item_id).join(Tag, Tag.id == ItemTag.tag_id).where(Tag.name_norm.in_(norms))
        parts.append(WardrobeItem.id.in_(tagged))
    return or_(*parts) if parts else false()
