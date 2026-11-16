"""请求体模型。extra="forbid"：拼错的字段名直接 422，而不是被静默忽略（对 AI 调用尤其重要）。"""

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from .services.colors import COLOR_FAMILIES, normalize_hex
from .services.text import clean_str

Hex = Annotated[str, AfterValidator(normalize_hex)]
Str = Annotated[str, AfterValidator(clean_str)]
NonEmpty = Annotated[str, Field(min_length=1, max_length=500), AfterValidator(lambda s: s.strip())]
Money = Annotated[int, Field(ge=0)]
Ref = int | str

Scheme = Literal["detail_page_id", "item_no", "jan", "sku", "other"]
SizeSystem = Literal["alpha", "waist_cm", "shoe_cm", "numeric", "free", "other"]
Gender = Literal["men", "women", "unisex", "kids", "baby"]
ItemStatus = Literal["owned", "wishlist", "returned", "disposed", "sold", "given_away", "lost"]
Condition = Literal["new", "good", "fair", "worn", "damaged"]
Channel = Literal["store", "online", "gift", "secondhand", "other"]
TagKind = Literal["free", "season", "occasion", "style", "fit", "status"]
Season = Literal["spring", "summer", "autumn", "winter", "all"]
Slot = Literal["outer", "top", "inner", "bottom", "dress", "shoes", "bag", "accessory", "other"]
ProductImageRole = Literal["main", "gallery", "color", "detail", "model", "size_chart"]
ItemImageRole = Literal["main", "gallery", "detail", "tag_label", "receipt"]
SourceType = Literal["user_upload", "user_photo", "official_site", "ai_generated", "other"]

ENUMS: dict[str, list[str]] = {
    "identifier_scheme": list(Scheme.__args__),
    "size_system": list(SizeSystem.__args__),
    "gender": list(Gender.__args__),
    "item_status": list(ItemStatus.__args__),
    "condition": list(Condition.__args__),
    "purchase_channel": list(Channel.__args__),
    "tag_kind": list(TagKind.__args__),
    "season": list(Season.__args__),
    "outfit_slot": list(Slot.__args__),
    "product_image_role": list(ProductImageRole.__args__),
    "item_image_role": list(ItemImageRole.__args__),
    "image_source_type": list(SourceType.__args__),
    "color_family": list(COLOR_FAMILIES),
    "product_match": ["unmatched", "suggested", "confirmed"],
    "verification": ["unverified", "verified"],
}


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Versioned(In):
    version: int | None = Field(None, description="父记录当前 version；也可用 If-Match 头")


# ───────────── 字典 ─────────────


class BrandIn(In):
    slug: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,49}$")]
    name: NonEmpty
    name_ja: Str | None = None
    name_zh: Str | None = None
    website: Str | None = None


class BrandPatch(In):
    name: NonEmpty | None = None
    name_ja: Str | None = None
    name_zh: Str | None = None
    website: Str | None = None


class CategoryIn(In):
    slug: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")]
    name_zh: NonEmpty
    name_ja: Str | None = None
    parent: Ref | None = Field(None, description="父分类 id 或 slug；省略为一级分类")
    sort_order: int = 0


class CategoryPatch(In):
    name_zh: NonEmpty | None = None
    name_ja: Str | None = None
    sort_order: int | None = None
    parent: Ref | None = Field(None, description="移动分类：新父分类 id/slug；显式传 null 移到第一级")


class TagIn(In):
    name: NonEmpty
    kind: TagKind = "free"
    color_hex: Hex | None = None


class TagPatch(In):
    name: NonEmpty | None = None
    kind: TagKind | None = None
    color_hex: Hex | None = None


# ───────────── 商品 ─────────────


class IdentifierIn(In):
    scheme: Scheme
    value: NonEmpty
    source: Str | None = None


class ColorIn(In):
    color_code: Str | None = None
    name_ja: Str | None = None
    name_zh: Str | None = None
    hex: Hex | None = None
    is_default: bool = False
    sort_order: int = 0

    @model_validator(mode="after")
    def _some_value(self):
        if not (self.color_code or self.name_ja or self.name_zh or self.hex):
            raise ValueError("颜色至少需要 color_code、name_ja、name_zh、hex 之一")
        return self


class SizeIn(In):
    size_label: NonEmpty
    size_system: SizeSystem = "alpha"
    size_detail: dict[str, Any] | None = None
    sort_order: int = 0


class MaterialIn(In):
    part: NonEmpty = "body"
    part_raw: Str | None = None
    fiber: NonEmpty
    fiber_raw: Str | None = None
    percent: Annotated[float, Field(gt=0, le=100)] | None = None


class ProductFields(In):
    brand: str | None = Field(None, description="品牌 slug")
    brand_id: int | None = None
    category: str | None = Field(None, description="分类 slug")
    category_id: int | None = None
    name_ja: Str | None = None
    name_zh: Str | None = None
    name_en: Str | None = None
    gender: Gender | None = None
    detail_url: Str | None = None
    season_label: Str | None = None
    material_text: Str | None = None
    care_text: Str | None = None
    care_symbols: list[str] | None = None
    description: Str | None = None
    list_price: Money | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    attributes: dict[str, Any] | None = None
    notes: Str | None = None


class ProductCreate(ProductFields):
    origin: Literal["catalog", "manual"] = "catalog"
    identifiers: list[IdentifierIn] = []
    colors: list[ColorIn] = []
    sizes: list[SizeIn] = []
    materials: list[MaterialIn] | None = Field(None, description="省略且提供 material_text 时自动解析")

    @model_validator(mode="after")
    def _has_name(self):
        if not (self.name_ja or self.name_zh or self.name_en):
            raise ValueError("name_ja、name_zh、name_en 至少需要一个")
        return self


class ProductPatch(ProductFields, Versioned):
    pass


class ColorsPut(Versioned):
    colors: list[ColorIn]


class SizesPut(Versioned):
    sizes: list[SizeIn]


class MaterialsPut(Versioned):
    materials: list[MaterialIn] | None = Field(None, description="省略时按商品 material_text 重新解析")


class IdentifierAdd(IdentifierIn, Versioned):
    pass


class ProductImageLink(Versioned):
    image_id: int
    role: ProductImageRole = "gallery"
    color_code: Str | None = None
    sort_order: int = 0


class LookupIn(In):
    brand: str | None = None
    scheme: Scheme
    value: NonEmpty


# ───────────── 购买 ─────────────


class LineFields(In):
    product_id: int | None = None
    product_match: Literal["suggested", "confirmed"] | None = Field(
        None, description="给出 product_id 时默认 confirmed；不确定时传 suggested"
    )
    item_code_raw: Str | None = None
    name_raw: Str | None = None
    color_code: Str | None = None
    color_name: Str | None = None
    color_hex: Hex | None = None
    size_label: Str | None = None
    size_system: SizeSystem | None = None
    unit_price: Money | None = None
    discount_amount: Money | None = None
    notes: Str | None = None
    attributes: dict[str, Any] | None = None


class LineIn(LineFields):
    quantity: Annotated[int, Field(ge=1, le=99)] = 1


class PurchaseCreate(In):
    purchased_on: date
    channel: Channel = "store"
    store_name: Str | None = None
    order_no: Str | None = None
    total_amount: Money | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "JPY"
    notes: Str | None = None
    lines: list[LineIn] = []
    create_items: bool = Field(False, description="按每行 quantity 自动生成衣物（需要 product_id）")


class PurchasePatch(Versioned):
    purchased_on: date | None = None
    channel: Channel | None = None
    store_name: Str | None = None
    order_no: Str | None = None
    total_amount: Money | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    notes: Str | None = None


class LineAdd(LineIn, Versioned):
    create_items: bool = False


class LinePatch(LineFields, Versioned):
    quantity: Annotated[int, Field(ge=1, le=99)] | None = None


class MatchIn(Versioned):
    product_id: int
    product_match: Literal["suggested", "confirmed"] = "confirmed"


# ───────────── 衣物 ─────────────


class ItemFields(In):
    category: str | None = None
    category_id: int | None = None
    color_code: Str | None = None
    color_name: Str | None = None
    color_hex: Hex | None = None
    size_label: Str | None = None
    size_system: SizeSystem | None = None
    condition: Condition | None = None
    acquired_on: date | None = None
    location: Str | None = None
    alterations: Str | None = None
    favorite: bool | None = None
    notes: Str | None = None
    attributes: dict[str, Any] | None = None


class ItemCreate(ItemFields):
    product_id: int | None = None
    product: ProductCreate | None = Field(None, description="内联新建商品（无官方资料时 origin 自动为 manual）")
    purchase_line_id: int | None = None
    status: ItemStatus = "owned"
    tags: list[NonEmpty] = []

    @model_validator(mode="after")
    def _product_ref(self):
        if self.product_id is not None and self.product is not None:
            raise ValueError("product_id 与 product 只能二选一")
        if self.status == "returned":
            raise ValueError("新建衣物不能直接为 returned，请用 POST /items/{id}/return")
        return self


class ItemPatch(ItemFields, Versioned):
    product_id: int | None = None
    purchase_line_id: int | None = None
    status: ItemStatus | None = None
    retired_on: date | None = None
    refund_amount: Money | None = None
    wear_count: Annotated[int, Field(ge=0)] | None = None
    last_worn_on: date | None = None


class TagsPut(Versioned):
    tags: list[NonEmpty]


class ReturnIn(Versioned):
    returned_on: date
    refund_amount: Money | None = None


class WearIn(Versioned):
    worn_on: date | None = Field(None, description="穿着日期，默认今天")


class ItemImageLink(Versioned):
    image_id: int
    role: ItemImageRole = "gallery"
    sort_order: int = 0


# ───────────── 穿搭 ─────────────


class OutfitItemIn(In):
    item_id: int
    slot: Slot = "other"
    sort_order: int = 0


class OutfitFields(In):
    description: Str | None = None
    season: Season | None = None
    occasion: Str | None = None
    rating: Annotated[int, Field(ge=1, le=5)] | None = None
    cover_image_id: int | None = None
    attributes: dict[str, Any] | None = None


class OutfitCreate(OutfitFields):
    name: NonEmpty
    items: list[OutfitItemIn] = []
    tags: list[NonEmpty] = []


class OutfitPatch(OutfitFields, Versioned):
    name: NonEmpty | None = None


class OutfitItemsPut(Versioned):
    items: list[OutfitItemIn]


class OutfitImageLink(Versioned):
    image_id: int
    sort_order: int = 0
