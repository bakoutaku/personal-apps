"""Phase 4 上传路径遗留问题：像素上限在解码前检查；缩略图正确处理 16 位灰度。全部为程序生成的图片。"""

import io

import pytest
from helpers import API, err, ok, upload
from PIL import Image as PILImage

from wardrobe.storage import images as image_storage


def png(img: PILImage.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_images_between_one_and_two_times_the_limit_are_rejected(client):
    # 8000 × 7600 = 6080 万像素：Pillow 自己只会给警告（2 倍以上才报错），上传必须拒绝
    data = png(PILImage.new("1", (8000, 7600)))
    e = err(upload(client, data), 422, "INVALID_IMAGE")
    assert "超过上限" in e["message"]
    assert ok(client.get(f"{API}/images"))["total"] == 0


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_pixel_limit_boundary(client, monkeypatch):
    monkeypatch.setattr(image_storage.PILImage, "MAX_IMAGE_PIXELS", 1200)
    assert ok(upload(client, png(PILImage.new("RGB", (30, 40), (1, 2, 3)))), 201)["width"] == 30  # 正好 1200
    err(upload(client, png(PILImage.new("RGB", (31, 40), (1, 2, 3)))), 422, "INVALID_IMAGE")  # 1240


def test_sixteen_bit_greyscale_thumbnail_is_not_clipped_to_white(client, settings):
    img = ok(upload(client, png(PILImage.new("I;16", (60, 80), 30000))), 201)
    thumb = settings.images_dir / img["thumb_url"].removeprefix("/media/")
    with PILImage.open(thumb) as t:
        r, g, b = t.convert("RGB").getpixel((t.width // 2, t.height // 2))
    assert abs(r - 30000 // 256) <= 2 and r == g == b  # 约 117，而不是 255


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_oversized_image_is_rejected_before_any_decoding(client, settings, monkeypatch):
    """GPT 审查建议：只检查 422 抓不到「先解码再拒绝」的退化；解码一旦被调用就让测试失败。"""
    data = png(PILImage.new("1", (8000, 7600)))

    def no_decode(self, *args, **kwargs):
        raise AssertionError("超限图片不应被解码")

    monkeypatch.setattr(PILImage.Image, "load", no_decode)
    monkeypatch.setattr(PILImage.Image, "verify", no_decode)
    err(upload(client, data), 422, "INVALID_IMAGE")
    assert ok(client.get(f"{API}/images"))["total"] == 0
    assert not list(settings.images_dir.glob("*/*/*"))
