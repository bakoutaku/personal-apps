"""衣物创建与校验，购买记录 create_items 与 POST /items 共用。"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import ApiError, validation
from ..models import Product, PurchaseLine, WardrobeItem
from .common import log_change, now_iso
from .products import get_or_create_tags
from .resolve import refresh_items


def check_line_product(line: PurchaseLine | None, product: Product, loc: str = "purchase_line_id") -> None:
    if line is not None and line.product_id is not None and line.product_id != product.id:
        raise validation(
            [loc], "product_mismatch",
            f"购买明细 {line.id} 关联的是商品 {line.product_id}，与衣物的商品 {product.id} 不一致",
        )  # fmt: skip


def check_line_capacity(session: Session, line: PurchaseLine, exclude_item_id: int | None = None) -> None:
    """一个购买明细关联的衣物（含已退货、不含已删除）不能超过 quantity（BUG-006）。

    在写请求的 BEGIN IMMEDIATE 事务内调用，并发请求不会同时通过检查。
    """
    q = (
        select(func.count())
        .select_from(WardrobeItem)
        .where(WardrobeItem.purchase_line_id == line.id, WardrobeItem.deleted_at.is_(None))
    )
    if exclude_item_id is not None:
        q = q.where(WardrobeItem.id != exclude_item_id)
    linked = session.scalar(q)
    if linked >= line.quantity:
        raise ApiError(
            409, "LINE_FULL",
            f"购买明细 {line.id} 的数量为 {line.quantity}，已有 {linked} 件衣物关联（含已退货），不能再关联",
            [{"loc": ["purchase_line_id"], "quantity": line.quantity, "linked": linked}],
        )  # fmt: skip


def check_dependencies_active(product: Product, line: PurchaseLine | None) -> None:
    """活动衣物引用的商品与购买记录都必须未删除（BUG-007）。"""
    if product.deleted_at is not None:
        raise ApiError(
            409, "DEPENDENCY_DELETED", f"商品 {product.id} 已删除，请先恢复商品或改用其他商品",
            [{"loc": ["product_id"], "product_id": product.id}],
        )  # fmt: skip
    if line is not None and line.purchase.deleted_at is not None:
        raise ApiError(
            409, "DEPENDENCY_DELETED", f"购买记录 {line.purchase_id} 已删除，请先恢复购买记录或解除关联",
            [{"loc": ["purchase_line_id"], "purchase_id": line.purchase_id}],
        )  # fmt: skip


def validate_item_links(
    session: Session, product: Product, line: PurchaseLine | None, *, exclude_item_id: int | None = None
) -> None:
    """活动衣物的关联不变量，新建、改关联、恢复三个入口统一调用（BUG-006 / 007 / 010）：

    1. 衣物的商品与购买明细当前匹配的商品一致（明细未匹配时不限制）
    2. 商品与购买记录都未删除
    3. 购买明细关联的衣物数不超过 quantity
    """
    check_line_product(line, product)
    check_dependencies_active(product, line)
    if line is not None:
        check_line_capacity(session, line, exclude_item_id=exclude_item_id)


def create_item(
    session: Session,
    *,
    actor: str,
    product: Product,
    line: PurchaseLine | None,
    values: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> WardrobeItem:
    validate_item_links(session, product, line)
    values = dict(values or {})
    if values.get("acquired_on") is None and line is not None:
        values["acquired_on"] = line.purchase.purchased_on
    now = now_iso()
    item = WardrobeItem(
        product=product,
        purchase_line=line,
        created_at=now,
        updated_at=now,
        version=1,
        attributes=values.pop("attributes", None) or {},
        favorite=1 if values.pop("favorite", False) else 0,
        **values,
    )
    session.add(item)
    session.flush()
    if tags:
        item.tags = get_or_create_tags(session, tags)
    refresh_items(session, [item])
    log_change(
        session, actor=actor, entity="wardrobe_item", entity_id=item.id, op="create",
        after={"product_id": product.id, "purchase_line_id": line.id if line else None, **values,
               "tags": [t.name for t in item.tags]},
        version_after=item.version,
    )  # fmt: skip
    return item
