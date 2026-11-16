"""SQLAlchemy ORM 模型。表结构以迁移 SQL 为准，测试会校验两者列名一致。"""

import json
from typing import Any

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class JSONText(TypeDecorator):
    """以 TEXT 存储的 JSON（保留中日文原文，不转义）。"""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True)

    def process_result_value(self, value, dialect):
        return None if value is None else json.loads(value)


class Base(DeclarativeBase):
    pass


def text_col(nullable: bool = True, **kw) -> Any:
    return mapped_column(Text, nullable=nullable, **kw)


class Brand(Base):
    __tablename__ = "brand"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = text_col(False)
    name: Mapped[str] = text_col(False)
    name_ja: Mapped[str | None] = text_col()
    name_zh: Mapped[str | None] = text_col()
    website: Mapped[str | None] = text_col()
    created_at: Mapped[str] = text_col(False)
    updated_at: Mapped[str] = text_col(False)


class Category(Base):
    __tablename__ = "category"
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"))
    level: Mapped[int] = mapped_column(Integer)
    slug: Mapped[str] = text_col(False)
    name_zh: Mapped[str] = text_col(False)
    name_ja: Mapped[str | None] = text_col()
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = text_col(False)
    updated_at: Mapped[str] = text_col(False)


class Tag(Base):
    __tablename__ = "tag"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = text_col(False)
    name_norm: Mapped[str] = text_col(False)
    kind: Mapped[str] = text_col(False, default="free")
    color_hex: Mapped[str | None] = text_col()
    created_at: Mapped[str] = text_col(False)


class ImportJob(Base):
    __tablename__ = "import_job"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = text_col(False, default="previewed")
    actor: Mapped[str] = text_col(False)
    source_label: Mapped[str | None] = text_col()
    payload_sha256: Mapped[str] = text_col(False)
    payload: Mapped[str] = text_col(False)
    options: Mapped[dict] = mapped_column(JSONText, default=dict)
    summary: Mapped[dict] = mapped_column(JSONText, default=dict)
    error_message: Mapped[str | None] = text_col()
    created_at: Mapped[str] = text_col(False)
    committed_at: Mapped[str | None] = text_col()
    reverted_at: Mapped[str | None] = text_col()
    backup_file: Mapped[str | None] = text_col()


class Image(Base):
    __tablename__ = "image"
    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = text_col(False)
    mime: Mapped[str] = text_col(False)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = text_col(False)
    thumb_path: Mapped[str] = text_col(False)
    source_type: Mapped[str] = text_col(False)
    source_url: Mapped[str | None] = text_col()
    source_note: Mapped[str | None] = text_col()
    dominant_hex: Mapped[str | None] = text_col()
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_job.id"))
    created_at: Mapped[str] = text_col(False)


class Product(Base):
    __tablename__ = "product"
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brand.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"))
    origin: Mapped[str] = text_col(False, default="catalog")
    name_ja: Mapped[str | None] = text_col()
    name_zh: Mapped[str | None] = text_col()
    name_en: Mapped[str | None] = text_col()
    gender: Mapped[str | None] = text_col()
    detail_url: Mapped[str | None] = text_col()
    season_label: Mapped[str | None] = text_col()
    material_text: Mapped[str | None] = text_col()
    care_text: Mapped[str | None] = text_col()
    care_symbols: Mapped[list] = mapped_column(JSONText, default=list)
    description: Mapped[str | None] = text_col()
    list_price: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = text_col(False, default="JPY")
    verification: Mapped[str] = text_col(False, default="unverified")
    verified_at: Mapped[str | None] = text_col()
    attributes: Mapped[dict] = mapped_column(JSONText, default=dict)
    notes: Mapped[str | None] = text_col()
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_job.id"))
    created_at: Mapped[str] = text_col(False)
    updated_at: Mapped[str] = text_col(False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[str | None] = text_col()

    brand: Mapped[Brand | None] = relationship()
    category: Mapped[Category | None] = relationship()
    identifiers: Mapped[list["ProductIdentifier"]] = relationship(
        cascade="all, delete-orphan", order_by="ProductIdentifier.id"
    )
    colors: Mapped[list["ProductColor"]] = relationship(
        cascade="all, delete-orphan", order_by="(ProductColor.sort_order, ProductColor.id)"
    )
    sizes: Mapped[list["ProductSize"]] = relationship(
        cascade="all, delete-orphan", order_by="(ProductSize.sort_order, ProductSize.id)"
    )
    materials: Mapped[list["MaterialComponent"]] = relationship(
        cascade="all, delete-orphan", order_by="(MaterialComponent.sort_order, MaterialComponent.id)"
    )
    images: Mapped[list["ProductImage"]] = relationship(
        cascade="all, delete-orphan", order_by="(ProductImage.sort_order, ProductImage.image_id)"
    )


class ProductIdentifier(Base):
    __tablename__ = "product_identifier"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    scheme: Mapped[str] = text_col(False)
    value: Mapped[str] = text_col(False)
    value_norm: Mapped[str] = text_col(False)
    source: Mapped[str | None] = text_col()
    created_at: Mapped[str] = text_col(False)


class ProductColor(Base):
    __tablename__ = "product_color"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    color_code: Mapped[str | None] = text_col()
    name_ja: Mapped[str | None] = text_col()
    name_zh: Mapped[str | None] = text_col()
    hex: Mapped[str | None] = text_col()
    color_family: Mapped[str | None] = text_col()
    is_default: Mapped[bool] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ProductSize(Base):
    __tablename__ = "product_size"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    size_label: Mapped[str] = text_col(False)
    size_system: Mapped[str] = text_col(False, default="alpha")
    size_detail: Mapped[dict | None] = mapped_column(JSONText)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class MaterialComponent(Base):
    __tablename__ = "material_component"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    part: Mapped[str] = text_col(False, default="body")
    part_raw: Mapped[str | None] = text_col()
    fiber: Mapped[str] = text_col(False)
    fiber_raw: Mapped[str | None] = text_col()
    percent: Mapped[float | None] = mapped_column()
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ProductImage(Base):
    __tablename__ = "product_image"
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("image.id"), primary_key=True)
    role: Mapped[str] = text_col(False, default="gallery")
    color_code: Mapped[str | None] = text_col()
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    image: Mapped[Image] = relationship()


class Purchase(Base):
    __tablename__ = "purchase"
    id: Mapped[int] = mapped_column(primary_key=True)
    purchased_on: Mapped[str] = text_col(False)
    channel: Mapped[str] = text_col(False, default="store")
    store_name: Mapped[str | None] = text_col()
    order_no: Mapped[str | None] = text_col()
    total_amount: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = text_col(False, default="JPY")
    notes: Mapped[str | None] = text_col()
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_job.id"))
    created_at: Mapped[str] = text_col(False)
    updated_at: Mapped[str] = text_col(False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[str | None] = text_col()

    lines: Mapped[list["PurchaseLine"]] = relationship(
        back_populates="purchase", cascade="all, delete-orphan", order_by="PurchaseLine.id"
    )


class PurchaseLine(Base):
    __tablename__ = "purchase_line"
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchase.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("product.id"))
    product_match: Mapped[str] = text_col(False, default="unmatched")
    item_code_raw: Mapped[str | None] = text_col()
    name_raw: Mapped[str | None] = text_col()
    color_code: Mapped[str | None] = text_col()
    color_name: Mapped[str | None] = text_col()
    color_hex: Mapped[str | None] = text_col()
    size_label: Mapped[str | None] = text_col()
    size_system: Mapped[str | None] = text_col()
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[int | None] = mapped_column(Integer)
    discount_amount: Mapped[int | None] = mapped_column(Integer)
    verification: Mapped[str] = text_col(False, default="unverified")
    verified_at: Mapped[str | None] = text_col()
    attributes: Mapped[dict] = mapped_column(JSONText, default=dict)
    notes: Mapped[str | None] = text_col()
    created_at: Mapped[str] = text_col(False)
    updated_at: Mapped[str] = text_col(False)
    version: Mapped[int] = mapped_column(Integer, default=1)

    purchase: Mapped[Purchase] = relationship(back_populates="lines")
    product: Mapped[Product | None] = relationship()


class WardrobeItem(Base):
    __tablename__ = "wardrobe_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    purchase_line_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_line.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"))
    color_code: Mapped[str | None] = text_col()
    color_name: Mapped[str | None] = text_col()
    color_hex: Mapped[str | None] = text_col()
    size_label: Mapped[str | None] = text_col()
    size_system: Mapped[str | None] = text_col()
    eff_color_code: Mapped[str | None] = text_col()
    eff_color_name: Mapped[str | None] = text_col()
    eff_color_hex: Mapped[str | None] = text_col()
    eff_color_family: Mapped[str | None] = text_col()
    eff_size_label: Mapped[str | None] = text_col()
    eff_size_system: Mapped[str | None] = text_col()
    eff_sources: Mapped[dict] = mapped_column(JSONText, default=dict)
    status: Mapped[str] = text_col(False, default="owned")
    condition: Mapped[str | None] = text_col()
    acquired_on: Mapped[str | None] = text_col()
    retired_on: Mapped[str | None] = text_col()
    refund_amount: Mapped[int | None] = mapped_column(Integer)
    location: Mapped[str | None] = text_col()
    alterations: Mapped[str | None] = text_col()
    wear_count: Mapped[int] = mapped_column(Integer, default=0)
    last_worn_on: Mapped[str | None] = text_col()
    favorite: Mapped[bool] = mapped_column(Integer, default=0)
    verification: Mapped[str] = text_col(False, default="unverified")
    verified_at: Mapped[str | None] = text_col()
    attributes: Mapped[dict] = mapped_column(JSONText, default=dict)
    notes: Mapped[str | None] = text_col()
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_job.id"))
    created_at: Mapped[str] = text_col(False)
    updated_at: Mapped[str] = text_col(False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[str | None] = text_col()

    product: Mapped[Product] = relationship()
    purchase_line: Mapped[PurchaseLine | None] = relationship()
    category: Mapped[Category | None] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary="item_tag", order_by="Tag.name_norm")
    images: Mapped[list["ItemImage"]] = relationship(
        cascade="all, delete-orphan", order_by="(ItemImage.sort_order, ItemImage.image_id)"
    )


class ItemTag(Base):
    __tablename__ = "item_tag"
    item_id: Mapped[int] = mapped_column(ForeignKey("wardrobe_item.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id"), primary_key=True)


class ItemImage(Base):
    __tablename__ = "item_image"
    item_id: Mapped[int] = mapped_column(ForeignKey("wardrobe_item.id"), primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("image.id"), primary_key=True)
    role: Mapped[str] = text_col(False, default="gallery")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    image: Mapped[Image] = relationship()


class Outfit(Base):
    __tablename__ = "outfit"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = text_col(False)
    description: Mapped[str | None] = text_col()
    season: Mapped[str | None] = text_col()
    occasion: Mapped[str | None] = text_col()
    rating: Mapped[int | None] = mapped_column(Integer)
    cover_image_id: Mapped[int | None] = mapped_column(ForeignKey("image.id"))
    attributes: Mapped[dict] = mapped_column(JSONText, default=dict)
    created_at: Mapped[str] = text_col(False)
    updated_at: Mapped[str] = text_col(False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[str | None] = text_col()

    items: Mapped[list["OutfitItem"]] = relationship(
        cascade="all, delete-orphan", order_by="(OutfitItem.sort_order, OutfitItem.item_id)"
    )
    tags: Mapped[list[Tag]] = relationship(secondary="outfit_tag", order_by="Tag.name_norm")
    images: Mapped[list["OutfitImage"]] = relationship(
        cascade="all, delete-orphan", order_by="(OutfitImage.sort_order, OutfitImage.image_id)"
    )
    cover_image: Mapped[Image | None] = relationship()


class OutfitItem(Base):
    __tablename__ = "outfit_item"
    outfit_id: Mapped[int] = mapped_column(ForeignKey("outfit.id"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("wardrobe_item.id"), primary_key=True)
    slot: Mapped[str] = text_col(False, default="other")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    item: Mapped[WardrobeItem] = relationship()


class OutfitTag(Base):
    __tablename__ = "outfit_tag"
    outfit_id: Mapped[int] = mapped_column(ForeignKey("outfit.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id"), primary_key=True)


class OutfitImage(Base):
    __tablename__ = "outfit_image"
    outfit_id: Mapped[int] = mapped_column(ForeignKey("outfit.id"), primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("image.id"), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    image: Mapped[Image] = relationship()


class ImportRow(Base):
    __tablename__ = "import_row"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("import_job.id"))
    row_index: Mapped[int] = mapped_column(Integer)
    entity: Mapped[str] = text_col(False)
    ref: Mapped[str | None] = text_col()
    action: Mapped[str] = text_col(False)
    target_id: Mapped[int | None] = mapped_column(Integer)
    match_reason: Mapped[str | None] = text_col()
    normalized: Mapped[dict | None] = mapped_column(JSONText)
    diff: Mapped[dict | None] = mapped_column(JSONText)
    errors: Mapped[list] = mapped_column(JSONText, default=list)
    warnings: Mapped[list] = mapped_column(JSONText, default=list)


class ChangeProposal(Base):
    __tablename__ = "change_proposal"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity: Mapped[str] = text_col(False)
    entity_id: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = text_col(False)
    current_value: Mapped[Any] = mapped_column(JSONText)
    proposed_value: Mapped[Any] = mapped_column(JSONText)
    reason: Mapped[str | None] = text_col()
    actor: Mapped[str] = text_col(False)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_job.id"))
    status: Mapped[str] = text_col(False, default="pending")
    created_at: Mapped[str] = text_col(False)
    decided_at: Mapped[str | None] = text_col()
    # 只有 Phase 5A 主动生成的 AI 建议才有；历史提议为 None
    ai_context: Mapped["AISuggestionContext | None"] = relationship(uselist=False, passive_deletes=True)
    # Phase 5C 规则建议（标签 / 分类）的依据；与 ai_context 互斥
    rule_context: Mapped["RuleSuggestionContext | None"] = relationship(uselist=False, passive_deletes=True)


class RuleSuggestionContext(Base):
    """规则建议（标签 / 分类）的依据（迁移 0003）。与提议一对一。"""

    __tablename__ = "rule_suggestion_context"
    proposal_id: Mapped[int] = mapped_column(ForeignKey("change_proposal.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = text_col(False)
    target_version: Mapped[int] = mapped_column(Integer)
    algorithm: Mapped[str] = text_col(False)
    evidence: Mapped[dict] = mapped_column(JSONText)
    created_at: Mapped[str] = text_col(False)


class AISuggestionContext(Base):
    """AI 建议的可审计来源（迁移 0002）。与提议一对一；image_id 在图片删除后置空，SHA256 保留。"""

    __tablename__ = "ai_suggestion_context"
    proposal_id: Mapped[int] = mapped_column(ForeignKey("change_proposal.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = text_col(False)
    target_version: Mapped[int] = mapped_column(Integer)
    image_id: Mapped[int | None] = mapped_column(ForeignKey("image.id", ondelete="SET NULL"))
    image_sha256: Mapped[str] = text_col(False)
    region: Mapped[dict | None] = mapped_column(JSONText)
    algorithm: Mapped[str] = text_col(False)
    parameters: Mapped[dict] = mapped_column(JSONText)
    candidate: Mapped[dict] = mapped_column(JSONText)
    candidates: Mapped[list] = mapped_column(JSONText)
    created_at: Mapped[str] = text_col(False)


class ChangeLog(Base):
    __tablename__ = "change_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[str] = text_col(False)
    actor: Mapped[str] = text_col(False)
    entity: Mapped[str] = text_col(False)
    entity_id: Mapped[int] = mapped_column(Integer)
    op: Mapped[str] = text_col(False)
    before: Mapped[dict | None] = mapped_column(JSONText)
    after: Mapped[dict | None] = mapped_column(JSONText)
    version_after: Mapped[int | None] = mapped_column(Integer)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_job.id"))
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("change_proposal.id"))
