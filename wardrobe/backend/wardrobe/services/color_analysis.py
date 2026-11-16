"""本地照片颜色候选（Phase 5A-1，算法 wardrobe-color/1）。

只做像素颜色统计，不是衣物语义识别，也不做背景分割：背景、光线、花纹都会影响结果。
返回的 pixel_share 是「该颜色在分析区域不透明像素中的占比」，不是置信度或正确率。

步骤（参数见 PARAMETERS，任何改动都必须提升 ALGORITHM 版本号）：
1. 读取服务器保存的原图（不使用 3:4 缩略图：缩略图已裁剪且丢弃透明度），核对 SHA256；
2. JPEG 先按 decode_limit 降采样解码以限制内存，再按 EXIF 方向修正；
3. 转为 RGBA，按归一化区域裁剪（坐标系为方向修正后的整图）；
4. 最长边超过 max_side 时用最近邻缩小（不混合出原图中不存在的颜色）；
5. alpha < alpha_threshold 的像素视为透明，不参与统计；白色、黑色不会被当作背景删除；
6. 每通道取高 bucket_bits 位分桶，桶内取像素平均色；按（像素数降序、桶序号升序）依次合并到
   平均色距离小于 merge_distance 的已有簇，否则新建簇；
7. 簇按（像素数降序、HEX 升序）排序，取占比 ≥ min_share 的前 max_candidates 个。
"""

import hashlib
import io
import math
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageOps, UnidentifiedImageError

from ..storage.images import to_8bit
from .colors import color_family

# /2：16 位灰度等整数模式先按比例缩到 8 位（/1 会把它们截断成白色）；其余输入的结果与 /1 相同
ALGORITHM = "wardrobe-color/2"
PARAMETERS = {
    "decode_limit": 2048,
    "max_side": 256,
    "resample": "nearest",
    "alpha_threshold": 128,
    "bucket_bits": 4,
    "merge_distance": 28,
    "min_share": 0.03,
    "max_candidates": 5,
}


class ColorAnalysisError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _crop_box(region: dict | None, width: int, height: int) -> tuple[int, int, int, int]:
    if region is None:
        return 0, 0, width, height
    left = math.floor(region["x"] * width)
    top = math.floor(region["y"] * height)
    right = min(width, math.ceil((region["x"] + region["w"]) * width))
    bottom = min(height, math.ceil((region["y"] + region["h"]) * height))
    # 极窄区域至少保留 1 像素
    right = max(right, min(width, left + 1))
    bottom = max(bottom, min(height, top + 1))
    if left >= width or top >= height:
        raise ColorAnalysisError("REGION_EMPTY", "区域在图片之外，没有可分析的像素")
    return left, top, right, bottom


def _load(data: bytes) -> PILImage.Image:
    try:
        img = PILImage.open(io.BytesIO(data))
        if img.format == "JPEG":
            limit = PARAMETERS["decode_limit"]
            img.draft("RGB", (limit, limit))
        img.load()
        # 保持原模式：先裁剪、缩小，再转 RGBA，避免为整张大图额外复制一份 RGBA
        return ImageOps.exif_transpose(img)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, PILImage.DecompressionBombError) as exc:
        raise ColorAnalysisError("IMAGE_UNREADABLE", "原图无法读取或已损坏，不能分析") from exc


def analyze_file(path: Path, expected_sha256: str, region: dict | None = None) -> dict:
    """分析一张原图。只读文件，不访问数据库。失败抛 ColorAnalysisError。"""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ColorAnalysisError("IMAGE_UNAVAILABLE", "原图文件不存在或无法读取") from exc
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ColorAnalysisError("IMAGE_UNAVAILABLE", "原图文件内容与图片记录的 SHA256 不一致")
    return analyze_image(_load(data), region)


def _to_rgba(img: PILImage.Image) -> PILImage.Image:
    img = to_8bit(img)  # 16 位灰度先缩到 8 位（与缩略图同一规则）
    return img if img.mode == "RGBA" else img.convert("RGBA")


def analyze_image(img: PILImage.Image, region: dict | None = None) -> dict:
    """对已方向修正的图像做统计（供测试直接调用）。最近邻缩放与模式无关，因此先裁剪缩小再转 RGBA。"""
    width, height = img.size
    box = _crop_box(region, width, height)
    area = img.crop(box)
    max_side = PARAMETERS["max_side"]
    if max(area.size) > max_side:
        scale = max_side / max(area.size)
        size = (max(1, round(area.width * scale)), max(1, round(area.height * scale)))
        area = area.resize(size, PILImage.Resampling.NEAREST)
    area = _to_rgba(area)

    threshold = PARAMETERS["alpha_threshold"]
    shift = 8 - PARAMETERS["bucket_bits"]
    buckets: dict[tuple[int, int, int], list[int]] = {}
    opaque = transparent = 0
    # Pillow 13 起 getdata 已弃用；依赖声明允许更早版本时退回 getdata
    pixels = area.get_flattened_data() if hasattr(area, "get_flattened_data") else area.getdata()
    for r, g, b, a in pixels:
        if a < threshold:
            transparent += 1
            continue
        opaque += 1
        acc = buckets.setdefault((r >> shift, g >> shift, b >> shift), [0, 0, 0, 0])
        acc[0] += 1
        acc[1] += r
        acc[2] += g
        acc[3] += b

    stats = {
        "image_width": width,
        "image_height": height,
        "crop_box": list(box),
        "analyzed_width": area.width,
        "analyzed_height": area.height,
        "opaque_pixels": opaque,
        "transparent_pixels": transparent,
    }
    base = {"algorithm": ALGORITHM, "parameters": dict(PARAMETERS), "region": region, "stats": stats}
    if opaque == 0:
        return {**base, "status": "no_suggestion", "reason": "no_opaque_pixels", "candidates": []}

    clusters: list[list[float]] = []  # [count, sum_r, sum_g, sum_b]
    limit = PARAMETERS["merge_distance"]
    for _key, (n, sr, sg, sb) in sorted(buckets.items(), key=lambda kv: (-kv[1][0], kv[0])):
        mean = (sr / n, sg / n, sb / n)
        for c in clusters:
            if math.dist(mean, (c[1] / c[0], c[2] / c[0], c[3] / c[0])) < limit:
                c[0] += n
                c[1] += sr
                c[2] += sg
                c[3] += sb
                break
        else:
            clusters.append([n, sr, sg, sb])

    def hex_of(c: list[float]) -> str:
        return "#" + "".join(f"{min(255, round(v / c[0])):02X}" for v in c[1:])

    ranked = sorted(((int(c[0]), hex_of(c)) for c in clusters), key=lambda x: (-x[0], x[1]))
    candidates = [
        {
            "rank": i + 1,
            "hex": hx,
            "color_family": color_family(hx),
            "pixel_count": n,
            "pixel_share": round(n / opaque, 4),
        }
        for i, (n, hx) in enumerate(
            [x for x in ranked if x[0] / opaque >= PARAMETERS["min_share"]][: PARAMETERS["max_candidates"]]
        )
    ]
    if not candidates:
        return {**base, "status": "no_suggestion", "reason": "no_dominant_color", "candidates": []}
    return {**base, "status": "ok", "reason": None, "candidates": candidates}
