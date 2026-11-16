"""Phase 5A 本地 AI 建议的请求体。与 schemas.py 相同：extra="forbid"，拼错的字段直接 422。"""

from typing import Annotated

from pydantic import Field, model_validator

from .schemas import Hex, In, NonEmpty, Str

Unit = Annotated[float, Field(ge=0, le=1)]


class Region(In):
    """归一化区域：以 EXIF 方向修正之后的原图为坐标系，左上角为原点，取值 0～1。"""

    x: Unit
    y: Unit
    w: Annotated[float, Field(gt=0, le=1)]
    h: Annotated[float, Field(gt=0, le=1)]

    @model_validator(mode="after")
    def _inside(self):
        # 容许浮点误差，但不能越出图片
        if self.x + self.w > 1 + 1e-9 or self.y + self.h > 1 + 1e-9:
            raise ValueError("区域超出图片范围：需要 x + w ≤ 1 且 y + h ≤ 1")
        return self


class ColorAnalysisIn(In):
    image_id: int = Field(description="这件衣物自己已关联的图片 ID（不接受路径或 URL）")
    region: Region | None = Field(None, description="可选的归一化区域；省略为整张图片")


class ColorSuggestionIn(In):
    version: int = Field(description="生成建议时看到的衣物 version；与当前不一致返回 409 VERSION_CONFLICT")
    image_id: int
    region: Region | None = None
    candidate_hex: Hex = Field(description="从分析结果中选中的候选 HEX；服务端会重新计算并核对")
    color_code: Str | None = Field(None, description="可选的颜色编号；省略为 null（不会从 HEX 推测官方色号）")
    color_name: Str | None = Field(None, description="可选的颜色名称；省略为 null")


# ───────────── Phase 5C：标签 / 分类规则建议 ─────────────


class TagSuggestionCreate(In):
    version: int = Field(description="生成建议时看到的衣物 version；不一致返回 409 VERSION_CONFLICT")
    tags: list[NonEmpty] = Field(default_factory=list, description="从建议中选中的标签（只追加）")
    category_id: int | None = Field(None, description="选中的分类建议（只适用于还没有有效分类的衣物）")


class BatchSuggestionItem(TagSuggestionCreate):
    item_id: int


class BatchSuggestionCreate(In):
    items: Annotated[list[BatchSuggestionItem], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def _unique_items(self):
        ids = [e.item_id for e in self.items]
        if len(set(ids)) != len(ids):
            dup = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"同一件衣物在一次批量中只能出现一次（重复：{'、'.join(f'#{i}' for i in dup)}）")
        return self
