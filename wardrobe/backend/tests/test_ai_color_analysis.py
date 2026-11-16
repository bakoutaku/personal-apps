"""Phase 5A-1 本地颜色候选算法（wardrobe-color/2）。

全部使用程序生成的虚构图像；每个场景的预期值由构造方式直接推出（像素数 / 总像素），
不调用被测函数来生成预期。
"""

import hashlib
import io
import time

import pytest
from PIL import Image as PILImage

from wardrobe.services.color_analysis import (
    ALGORITHM,
    PARAMETERS,
    ColorAnalysisError,
    analyze_file,
    analyze_image,
)


def solid(color, size=(30, 40), mode="RGB"):
    return PILImage.new(mode, size, color)


def split(top, bottom, top_rows, size=(40, 100)):
    """上 top_rows 行为 top，其余为 bottom。"""
    img = PILImage.new("RGB", size, bottom)
    img.paste(top, (0, 0, size[0], top_rows))
    return img


def hexes(result):
    return [c["hex"] for c in result["candidates"]]


def shares(result):
    return [c["pixel_share"] for c in result["candidates"]]


def test_solid_color_is_a_single_candidate_with_full_share():
    r = analyze_image(solid((200, 30, 30)))
    assert r["status"] == "ok" and r["algorithm"] == ALGORITHM
    assert r["candidates"] == [
        {"rank": 1, "hex": "#C81E1E", "color_family": "red", "pixel_count": 1200, "pixel_share": 1.0}
    ]
    assert r["stats"]["opaque_pixels"] == 1200 and r["stats"]["transparent_pixels"] == 0


def test_two_colors_are_ordered_by_pixel_share():
    # 75 行藏青 + 25 行白色
    r = analyze_image(split((0x1F, 0x2A, 0x44), (255, 255, 255), 75))
    assert hexes(r) == ["#1F2A44", "#FFFFFF"]
    assert shares(r) == [0.75, 0.25]
    assert [c["color_family"] for c in r["candidates"]] == ["navy", "white"]


@pytest.mark.parametrize(
    ("color", "hex_", "family"), [((255, 255, 255), "#FFFFFF", "white"), ((0, 0, 0), "#000000", "black")]
)
def test_white_and_black_garments_are_not_discarded_as_background(color, hex_, family):
    r = analyze_image(solid(color))
    assert r["status"] == "ok"
    assert r["candidates"][0]["hex"] == hex_ and r["candidates"][0]["color_family"] == family


def test_navy_on_black_background_stays_separate_and_region_isolates_the_garment():
    # 100x100 黑色背景，中间 40x40 藏青（16%）
    img = PILImage.new("RGB", (100, 100), (0x1A, 0x1A, 0x1A))
    img.paste((0x1F, 0x2A, 0x44), (30, 30, 70, 70))
    whole = analyze_image(img)
    assert hexes(whole) == ["#1A1A1A", "#1F2A44"]
    assert shares(whole) == [0.84, 0.16]
    inner = analyze_image(img, {"x": 0.3, "y": 0.3, "w": 0.4, "h": 0.4})
    assert hexes(inner) == ["#1F2A44"] and shares(inner) == [1.0]
    assert inner["stats"]["crop_box"] == [30, 30, 70, 70]


def test_equal_stripes_tie_break_by_hex():
    img = PILImage.new("RGB", (20, 20))
    for y in range(20):
        img.paste((220, 20, 20) if y % 2 else (20, 20, 220), (0, y, 20, y + 1))
    r = analyze_image(img)
    assert hexes(r) == ["#1414DC", "#DC1414"]  # 并列时按 HEX 升序
    assert shares(r) == [0.5, 0.5]


def test_transparent_pixels_are_excluded():
    img = PILImage.new("RGBA", (40, 40), (255, 255, 255, 0))
    img.paste((40, 140, 60, 255), (10, 10, 30, 30))  # 400 个不透明像素
    r = analyze_image(img)
    assert hexes(r) == ["#288C3C"] and shares(r) == [1.0]
    assert r["stats"]["opaque_pixels"] == 400 and r["stats"]["transparent_pixels"] == 1200


def test_fully_transparent_image_gives_no_suggestion():
    r = analyze_image(PILImage.new("RGBA", (20, 20), (200, 0, 0, 0)))
    assert r["status"] == "no_suggestion" and r["reason"] == "no_opaque_pixels" and r["candidates"] == []


def test_alpha_threshold_boundary():
    img = PILImage.new("RGBA", (10, 2))
    img.paste((255, 0, 0, PARAMETERS["alpha_threshold"] - 1), (0, 0, 10, 1))  # 透明
    img.paste((0, 0, 255, PARAMETERS["alpha_threshold"]), (0, 1, 10, 2))  # 不透明
    r = analyze_image(img)
    assert hexes(r) == ["#0000FF"]
    assert r["stats"]["opaque_pixels"] == 10 and r["stats"]["transparent_pixels"] == 10


def test_palette_png_transparency_is_respected(tmp_path):
    img = PILImage.new("P", (10, 10), 0)
    img.putpalette([255, 0, 0, 0, 128, 0] + [0] * 762)
    img.paste(1, (0, 0, 10, 3))  # 30 个绿色像素
    buf = io.BytesIO()
    img.save(buf, "PNG", transparency=0)  # 红色（索引 0）为透明
    path = tmp_path / "p.png"
    path.write_bytes(buf.getvalue())
    r = analyze_file(path, hashlib.sha256(buf.getvalue()).hexdigest())
    assert hexes(r) == ["#008000"] and r["stats"]["opaque_pixels"] == 30


def test_exif_orientation_is_applied_before_the_region(tmp_path):
    # 存储的像素：左半红、右半蓝（40x20）。Orientation=6 表示显示时顺时针旋转 90°，左边转到上方。
    stored = PILImage.new("RGB", (40, 20), (0, 0, 255))
    stored.paste((255, 0, 0), (0, 0, 20, 20))
    exif = PILImage.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    stored.save(buf, "PNG", exif=exif.tobytes())
    path = tmp_path / "rot.png"
    path.write_bytes(buf.getvalue())
    sha = hashlib.sha256(buf.getvalue()).hexdigest()
    top = analyze_file(path, sha, {"x": 0, "y": 0, "w": 1, "h": 0.5})
    assert hexes(top) == ["#FF0000"]
    assert top["stats"]["image_width"] == 20 and top["stats"]["image_height"] == 40


def test_tiny_image_and_very_narrow_region_keep_at_least_one_pixel():
    assert hexes(analyze_image(solid((10, 200, 10), size=(1, 1)))) == ["#0AC80A"]
    img = PILImage.new("RGB", (100, 10), (255, 255, 255))
    img.paste((0, 0, 0), (0, 0, 1, 10))  # 第一列黑色
    r = analyze_image(img, {"x": 0, "y": 0, "w": 0.0001, "h": 1})
    assert r["stats"]["crop_box"] == [0, 0, 1, 10]
    assert hexes(r) == ["#000000"]


def test_region_outside_the_image_is_an_error():
    with pytest.raises(ColorAnalysisError) as exc:
        analyze_image(solid((0, 0, 0), size=(10, 10)), {"x": 1.0, "y": 0, "w": 1e-12, "h": 1})
    assert exc.value.code == "REGION_EMPTY"


def test_small_noise_merges_into_one_candidate():
    img = PILImage.new("RGB", (30, 30))
    for x in range(30):
        for y in range(30):
            d = ((x * 7 + y * 3) % 13) - 6  # -6…+6 的确定性扰动，跨越分桶边界
            img.putpixel((x, y), (120 + d, 64 + d, 200 + d))
    r = analyze_image(img)
    assert len(r["candidates"]) == 1 and shares(r) == [1.0]


def test_many_far_apart_colors_below_min_share_give_no_suggestion():
    # 40 种互相距离 ≥ 64 的颜色，各占 2.5%（低于 3%）
    palette = [(r, g, b) for r in (0, 64, 128, 192) for g in (0, 64, 128, 192) for b in (0, 128, 255)][:40]
    img = PILImage.new("RGB", (40, 10))
    for x, c in enumerate(palette):
        img.paste(c, (x, 0, x + 1, 10))
    r = analyze_image(img)
    assert r["status"] == "no_suggestion" and r["reason"] == "no_dominant_color"


def test_at_most_five_candidates_in_share_order():
    colors = [(250, 0, 0), (0, 250, 0), (0, 0, 250), (250, 250, 0), (0, 250, 250), (250, 0, 250)]
    widths = [30, 25, 20, 12, 8, 5]  # 共 100 列
    img = PILImage.new("RGB", (100, 4))
    x = 0
    for c, w in zip(colors, widths, strict=True):
        img.paste(c, (x, 0, x + w, 4))
        x += w
    r = analyze_image(img)
    assert hexes(r) == ["#FA0000", "#00FA00", "#0000FA", "#FAFA00", "#00FAFA"]
    assert shares(r) == [0.3, 0.25, 0.2, 0.12, 0.08]
    assert [c["rank"] for c in r["candidates"]] == [1, 2, 3, 4, 5]


def test_large_image_is_downscaled_with_bounded_cost(tmp_path):
    img = split((200, 200, 0), (0, 0, 120), 1500, size=(2000, 3000))  # 上半黄色、下半深蓝
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    path = tmp_path / "big.jpg"
    path.write_bytes(buf.getvalue())
    start = time.perf_counter()
    r = analyze_file(path, hashlib.sha256(buf.getvalue()).hexdigest())
    elapsed = time.perf_counter() - start
    assert max(r["stats"]["analyzed_width"], r["stats"]["analyzed_height"]) <= PARAMETERS["max_side"]
    assert len(r["candidates"]) == 2 and abs(shares(r)[0] - 0.5) < 0.02
    assert {c["color_family"] for c in r["candidates"]} == {"yellow", "navy"}
    assert elapsed < 5, elapsed  # 宽松上限，只防止退化为逐像素处理整张原图


def test_results_are_deterministic():
    img = split((0x1F, 0x2A, 0x44), (230, 230, 230), 60)
    assert analyze_image(img) == analyze_image(img.copy())


def test_corrupt_missing_and_mismatched_files(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"\x89PNG not really")
    with pytest.raises(ColorAnalysisError) as exc:
        analyze_file(bad, hashlib.sha256(bad.read_bytes()).hexdigest())
    assert exc.value.code == "IMAGE_UNREADABLE"
    with pytest.raises(ColorAnalysisError) as exc:
        analyze_file(tmp_path / "missing.png", "0" * 64)
    assert exc.value.code == "IMAGE_UNAVAILABLE"
    good = tmp_path / "good.png"
    solid((1, 2, 3)).save(good, "PNG")
    with pytest.raises(ColorAnalysisError) as exc:
        analyze_file(good, "0" * 64)
    assert exc.value.code == "IMAGE_UNAVAILABLE"


# ───────────── 审查修复补充（P3-4 / P3-6） ─────────────


def test_jpeg_draft_bounds_the_decoded_size(tmp_path):
    """draft 只保证解码尺寸 ≥ 请求尺寸，因此每边 < 2 × decode_limit；stats 报告的是解码后的尺寸。"""
    img = split((200, 0, 0), (0, 0, 200), 3000, size=(5000, 6000))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    path = tmp_path / "huge.jpg"
    path.write_bytes(buf.getvalue())
    r = analyze_file(path, hashlib.sha256(buf.getvalue()).hexdigest())
    limit = PARAMETERS["decode_limit"]
    assert r["stats"]["image_width"] < 5000 and r["stats"]["image_height"] < 6000  # 确实走了降采样解码
    assert r["stats"]["image_width"] < 2 * limit and r["stats"]["image_height"] < 2 * limit


def test_downscaling_never_invents_blended_colours():
    """最近邻缩小：1 像素红蓝棋盘缩小后只能出现原图里有的颜色，不能出现混合的紫色。"""
    img = PILImage.new("RGB", (512, 512))
    for x in range(512):
        for y in range(512):
            img.putpixel((x, y), (255, 0, 0) if (x + y) % 2 else (0, 0, 255))
    r = analyze_image(img)
    assert set(hexes(r)) <= {"#FF0000", "#0000FF"}
    assert all(c["color_family"] in {"red", "blue"} for c in r["candidates"])


def test_sixteen_bit_greyscale_is_scaled_not_clipped_to_white(tmp_path):
    img = PILImage.new("I;16", (20, 20), 30000)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    path = tmp_path / "g16.png"
    path.write_bytes(buf.getvalue())
    r = analyze_file(path, hashlib.sha256(buf.getvalue()).hexdigest())
    level = r["candidates"][0]["hex"][1:3]
    assert abs(int(level, 16) - 30000 // 256) <= 1  # 约 117（#757575），而不是 255
    assert r["candidates"][0]["color_family"] == "gray"
