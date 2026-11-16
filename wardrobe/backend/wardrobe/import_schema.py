"""批量导入格式 wardrobe.import/v1（API §10）。

* 所有对象都可以带 ref（批内临时引用名），用 product_ref / purchase_line_ref / item_ref 互相引用；
  也可以用 id 直接指向已有记录（例如由 GET /export 导出后修改再导入）。
* extra="forbid"：拼错的字段直接报错，错误位置精确到 ["purchases", 0, "lines", 1, "color_hex"]。
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import ApiError
from .schemas import (
    ColorIn,
    IdentifierIn,
    ItemFields,
    ItemImageRole,
    ItemStatus,
    LineFields,
    MaterialIn,
    NonEmpty,
    OutfitFields,
    ProductFields,
    ProductImageRole,
    SizeIn,
    Slot,
    Str,
)

FORMAT = "wardrobe.import/v1"
RefName = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImportOptions(_In):
    on_existing: Literal["skip", "update_unverified", "fill_empty"] = Field(
        "update_unverified",
        description="匹配到已有记录时：skip 不改；update_unverified 覆盖不同的字段；fill_empty 只填空字段。"
        "已核实记录的受保护字段在任何模式下都只生成修改提议。",
    )
    allow_partial: bool = Field(False, description="true 时提交会跳过出错的行（及依赖它们的行）")


class ImageLinkIn(_In):
    image_id: int = Field(description="先用 POST /images 上传得到的图片 id")
    role: str = "gallery"
    color_code: Str | None = None
    sort_order: int = 0


class ImportProduct(ProductFields):
    ref: RefName | None = None
    id: int | None = Field(None, description="直接指定已有商品")
    origin: Literal["catalog", "manual"] | None = None
    identifiers: list[IdentifierIn] = []
    colors: list[ColorIn] = []
    sizes: list[SizeIn] = []
    materials: list[MaterialIn] | None = None
    images: list[ImageLinkIn] = []

    @model_validator(mode="after")
    def _check(self):
        # 名称只在「需要新建」时才必需：只靠编号指向已有商品的行可以不带名称（执行时检查）
        for img in self.images:
            if img.role not in ProductImageRole.__args__:
                raise ValueError(f"商品图片 role 只能是 {', '.join(ProductImageRole.__args__)}")
        return self


class ImportLine(LineFields):
    ref: RefName | None = None
    id: int | None = Field(None, description="直接指定已有购买明细")
    product_ref: RefName | None = None
    quantity: Annotated[int, Field(ge=1, le=99)] = 1

    @model_validator(mode="after")
    def _check(self):
        if self.product_ref is not None and self.product_id is not None:
            raise ValueError("product_ref 与 product_id 只能二选一")
        return self


class ImportPurchase(_In):
    ref: RefName | None = None
    id: int | None = Field(None, description="直接指定已有购买记录")
    purchased_on: date | None = None
    channel: Literal["store", "online", "gift", "secondhand", "other"] | None = None
    store_name: Str | None = None
    order_no: Str | None = None
    total_amount: Annotated[int, Field(ge=0)] | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    notes: Str | None = None
    lines: list[ImportLine] = []
    create_items: bool = Field(False, description="按每行 quantity 补齐衣物（已有衣物计入）")

    @model_validator(mode="after")
    def _check(self):
        if self.id is None and self.purchased_on is None:
            raise ValueError("新购买记录需要 purchased_on")
        return self


class ItemImageIn(_In):
    image_id: int
    role: ItemImageRole = "gallery"
    sort_order: int = 0


class ImportItem(ItemFields):
    ref: RefName | None = None
    id: int | None = Field(None, description="直接指定已有衣物")
    product_id: int | None = None
    product_ref: RefName | None = None
    purchase_line_id: int | None = None
    purchase_line_ref: RefName | None = None
    status: ItemStatus | None = None
    retired_on: date | None = None
    refund_amount: Annotated[int, Field(ge=0)] | None = None
    wear_count: Annotated[int, Field(ge=0)] | None = None
    last_worn_on: date | None = None
    tags: list[NonEmpty] = Field([], description="追加的标签（不会移除已有标签）")
    images: list[ItemImageIn] = []

    @model_validator(mode="after")
    def _check(self):
        if self.product_ref is not None and self.product_id is not None:
            raise ValueError("product_ref 与 product_id 只能二选一")
        if self.purchase_line_ref is not None and self.purchase_line_id is not None:
            raise ValueError("purchase_line_ref 与 purchase_line_id 只能二选一")
        return self


class ImportOutfitItem(_In):
    item_id: int | None = None
    item_ref: RefName | None = None
    slot: Slot = "other"
    sort_order: int = 0

    @model_validator(mode="after")
    def _check(self):
        if (self.item_id is None) == (self.item_ref is None):
            raise ValueError("item_id 与 item_ref 需要且只能给出一个")
        return self


class ImportOutfit(OutfitFields):
    ref: RefName | None = None
    id: int | None = None
    name: NonEmpty | None = None
    items: list[ImportOutfitItem] | None = Field(None, description="给出时整体替换穿搭的衣物列表")
    tags: list[NonEmpty] = []

    @model_validator(mode="after")
    def _check(self):
        if self.id is None and not self.name:
            raise ValueError("新穿搭需要 name")
        return self


class ImportPayload(_In):
    format: Literal["wardrobe.import/v1"]
    source_label: Str | None = None
    options: ImportOptions = ImportOptions()
    products: list[ImportProduct] = []
    purchases: list[ImportPurchase] = []
    items: list[ImportItem] = []
    outfits: list[ImportOutfit] = []


def check_refs(payload: ImportPayload) -> None:
    """ref 在同类中唯一，且引用的 ref 必须在 payload 中定义。错误位置精确到字段。"""
    errors: list[dict] = []

    def dup_check(kind: str, pairs: list[tuple[list, str | None]]) -> set[str]:
        seen: set[str] = set()
        for loc, ref in pairs:
            if ref is None:
                continue
            if ref in seen:
                errors.append({"loc": [*loc, "ref"], "code": "duplicate_ref", "message": f"{kind} ref {ref!r} 重复"})
            seen.add(ref)
        return seen

    products = dup_check("product", [(["products", i], p.ref) for i, p in enumerate(payload.products)])
    dup_check("purchase", [(["purchases", i], p.ref) for i, p in enumerate(payload.purchases)])
    lines = dup_check(
        "purchase_line",
        [
            (["purchases", i, "lines", j], ln.ref)
            for i, p in enumerate(payload.purchases)
            for j, ln in enumerate(p.lines)
        ],
    )
    items = dup_check("item", [(["items", i], it.ref) for i, it in enumerate(payload.items)])
    dup_check("outfit", [(["outfits", i], o.ref) for i, o in enumerate(payload.outfits)])

    def need(loc: list, ref: str | None, defined: set[str], kind: str) -> None:
        if ref is not None and ref not in defined:
            errors.append({"loc": loc, "code": "unknown_ref", "message": f"未定义的 {kind} ref {ref!r}"})

    for i, p in enumerate(payload.purchases):
        for j, ln in enumerate(p.lines):
            need(["purchases", i, "lines", j, "product_ref"], ln.product_ref, products, "product")
    for i, it in enumerate(payload.items):
        need(["items", i, "product_ref"], it.product_ref, products, "product")
        need(["items", i, "purchase_line_ref"], it.purchase_line_ref, lines, "purchase_line")
    for i, o in enumerate(payload.outfits):
        for j, oi in enumerate(o.items or []):
            need(["outfits", i, "items", j, "item_ref"], oi.item_ref, items, "item")

    if not (payload.products or payload.purchases or payload.items or payload.outfits):
        errors.append({"loc": [], "code": "empty", "message": "导入内容为空"})
    if errors:
        raise ApiError(422, "VALIDATION_ERROR", f"{len(errors)} 处引用错误", errors)
