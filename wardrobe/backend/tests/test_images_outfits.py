"""图片上传/去重/缩略图/删除，以及穿搭。"""

import io

from helpers import API, err, get, make_product, make_purchase, ok, png_bytes, upload
from PIL import Image as PILImage

from wardrobe.config import Settings
from wardrobe.main import create_app


def test_upload_creates_original_and_3x4_thumbnail(client, settings):
    img = ok(upload(client, png_bytes(size=(1000, 500)), source_type="user_photo", source_note="自拍"), 201)
    assert (img["width"], img["height"], img["mime"], img["deduplicated"]) == (1000, 500, "image/png", False)
    original = settings.images_dir / img["url"].removeprefix("/media/")
    thumb = settings.images_dir / img["thumb_url"].removeprefix("/media/")
    assert original.read_bytes() == png_bytes(size=(1000, 500))
    with PILImage.open(thumb) as t:
        assert (t.format, t.size) == ("WEBP", (600, 800))
    assert client.get(img["thumb_url"]).status_code == 200


def test_same_content_is_deduplicated(client):
    a = ok(upload(client), 201)
    b = ok(upload(client))
    assert b["id"] == a["id"] and b["deduplicated"] is True


def test_rejects_non_images_and_oversize(client, tmp_path):
    err(upload(client, b"not an image"), 422, "INVALID_IMAGE")
    buf = io.BytesIO()
    PILImage.new("RGB", (10, 10)).save(buf, "GIF")
    err(upload(client, buf.getvalue()), 422, "INVALID_IMAGE")

    from fastapi.testclient import TestClient

    small = create_app(Settings(data_dir=tmp_path / "small", max_upload_bytes=1000))
    c = TestClient(small, base_url="http://127.0.0.1:8765", headers={"X-Wardrobe-Client": "web-ui"})
    err(upload(c, png_bytes(size=(800, 800), color=(1, 2, 3)) + b"\0" * 2000), 413, "PAYLOAD_TOO_LARGE")


def test_media_path_traversal_is_blocked(client):
    assert client.get("/media/../wardrobe.db").status_code == 404
    assert client.get("/media/%2e%2e/wardrobe.db").status_code == 404


def test_item_main_image_becomes_thumb(client):
    p = make_product(client)
    item_id = make_purchase(client, p["id"])["lines"][0]["item_ids"][0]
    prod_img = ok(upload(client, png_bytes(color=(0, 0, 0))), 201)
    ok(client.post(f"{API}/products/{p['id']}/images", json={"version": 1, "image_id": prod_img["id"], "role": "main"}),
       201)  # fmt: skip
    assert get(client, f"/items/{item_id}")["thumb_url"] == prod_img["thumb_url"]
    own = ok(upload(client, png_bytes(color=(9, 9, 9))), 201)
    out = ok(client.post(f"{API}/items/{item_id}/images", json={"version": 1, "image_id": own["id"], "role": "main"}),
             201)  # fmt: skip
    assert out["thumb_url"] == own["thumb_url"] and out["version"] == 2


def test_delete_image_in_use_then_free(client, settings):
    p = make_product(client)
    img = ok(upload(client), 201)
    ok(client.post(f"{API}/products/{p['id']}/images", json={"version": 1, "image_id": img["id"]}), 201)
    e = err(client.delete(f"{API}/images/{img['id']}"), 409, "IN_USE")
    assert e["details"][0]["products"] == [p["id"]]
    ok(client.delete(f"{API}/products/{p['id']}/images/{img['id']}", params={"version": 2}))
    ok(client.delete(f"{API}/images/{img['id']}"), 204)
    assert not (settings.images_dir / img["url"].removeprefix("/media/")).exists()
    assert not (settings.images_dir / img["thumb_url"].removeprefix("/media/")).exists()


def test_failed_db_write_never_deletes_files(client, settings, app):
    """数据库回滚时文件不受影响；孤儿文件由 gc 清理。"""
    from wardrobe.storage.images import gc_orphans, store_image

    stored = store_image(settings, png_bytes(color=(5, 6, 7)))  # 写了文件但没有记录（模拟提交失败）
    path = settings.images_dir / stored.storage_path
    assert path.exists()
    kept = ok(upload(client, png_bytes(color=(8, 8, 8))), 201)
    assert gc_orphans(settings, app.state.sessionmaker) == 2  # 原图 + 缩略图
    assert not path.exists()
    assert (settings.images_dir / kept["url"].removeprefix("/media/")).exists()


# ───────────── 穿搭 ─────────────


def test_outfit_crud_and_item_protection(client):
    p = make_product(client)
    ids = make_purchase(client, p["id"], quantity=2)["lines"][0]["item_ids"]
    o = ok(client.post(f"{API}/outfits", json={
        "name": "秋季通勤", "season": "autumn", "tags": ["通勤"],
        "items": [{"item_id": ids[0], "slot": "outer"}, {"item_id": ids[1], "slot": "top"}],
    }), 201)  # fmt: skip
    assert [i["slot"] for i in o["items"]] == ["outer", "top"] and o["tags"] == ["通勤"]
    err(client.delete(f"{API}/items/{ids[0]}", params={"version": 1}), 409, "IN_USE")
    assert get(client, f"/items/{ids[0]}")["outfits"] == [{"id": o["id"], "name": "秋季通勤"}]
    assert [x["id"] for x in ok(client.get(f"{API}/outfits", params={"contains_item": ids[1]}))["items"]] == [o["id"]]
    ok(client.delete(f"{API}/outfits/{o['id']}", params={"version": 1}), 204)
    ok(client.delete(f"{API}/items/{ids[0]}", params={"version": 1}), 204)


def test_outfit_rejects_duplicate_or_missing_items(client):
    p = make_product(client)
    item_id = make_purchase(client, p["id"])["lines"][0]["item_ids"][0]
    err(client.post(f"{API}/outfits", json={"name": "x", "items": [{"item_id": item_id}, {"item_id": item_id}]}), 422,
        "VALIDATION_ERROR")  # fmt: skip
    err(client.post(f"{API}/outfits", json={"name": "x", "items": [{"item_id": 999}]}), 422, "VALIDATION_ERROR")
