"""GPT Phase 1 审查（docs/REVIEW_PHASE1_2026-10-26.md）的独立复现测试，原样保留预期行为作为回归用例。"""

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from wardrobe.config import Settings
from wardrobe.main import create_app
from wardrobe.storage.backup import BackupError, create_backup, restore_backup, verify_backup

API = "/api/v1"


@pytest.fixture
def env(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings)
    client = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Wardrobe-Client": "web-ui"})
    yield settings, app, client
    client.close()
    app.state.engine.dispose()


def post(c, path, data):
    r = c.post(API + path, json=data)
    assert r.status_code in (200, 201), r.text
    return r.json()


def product(c):
    return post(c, "/products", {"name_ja": "QA fictional jacket"})


def test_purchase_quantity_limits_item_creation(env):
    _, _, c = env
    p = product(c)
    purchase = post(
        c,
        "/purchases",
        {"purchased_on": "2026-01-01", "create_items": True, "lines": [{"product_id": p["id"], "quantity": 1}]},
    )
    line = purchase["lines"][0]
    r = c.post(API + "/items", json={"product_id": p["id"], "purchase_line_id": line["id"]})
    if r.status_code == 201:
        for item_id in [*line["item_ids"], r.json()["id"]]:
            result = c.post(API + f"/items/{item_id}/return", json={"version": 1, "returned_on": "2026-01-02"})
            assert result.status_code == 200, result.text
    current = c.get(API + f"/purchase-lines/{line['id']}").json()
    assert r.status_code in (409, 422), {
        "status": r.status_code,
        "quantity": current["quantity"],
        "item_ids": current["item_ids"],
        "returned_quantity": current["returned_quantity"],
    }


def test_restoring_item_cannot_reactivate_deleted_product(env):
    _, _, c = env
    p = product(c)
    item = post(c, "/items", {"product_id": p["id"]})
    assert c.delete(API + f"/items/{item['id']}?version=1").status_code == 204
    assert c.delete(API + f"/products/{p['id']}?version=1").status_code == 204
    r = c.post(API + f"/items/{item['id']}/restore", json={"version": 2})
    parent = c.get(API + f"/products/{p['id']}")
    assert r.status_code == 409 or parent.status_code == 200, {
        "restore": r.status_code,
        "product_get": parent.status_code,
        "visible_items": c.get(API + "/items").json()["total"],
    }


def test_rename_tag_updates_search(env):
    _, _, c = env
    p = product(c)
    post(c, "/items", {"product_id": p["id"], "tags": ["oldmarker"]})
    tag = c.get(API + "/tags").json()["items"][0]
    assert c.patch(API + f"/tags/{tag['id']}", json={"name": "newmarker"}).status_code == 200
    new = c.get(API + "/items", params={"q": "newmarker"}).json()["total"]
    old = c.get(API + "/items", params={"q": "oldmarker"}).json()["total"]
    assert (new, old) == (1, 0), {"new_hits": new, "old_hits": old}


def test_incomplete_image_backup_is_rejected(env, tmp_path):
    import io

    from PIL import Image

    s, app, c = env
    buf = io.BytesIO()
    Image.new("RGB", (30, 40), "red").save(buf, "PNG")
    r = c.post(API + "/images", files={"file": ("qa.png", buf.getvalue(), "image/png")})
    assert r.status_code == 201
    img = r.json()
    good = create_backup(s)
    missing = "images/" + img["url"].removeprefix("/media/")
    bad = tmp_path / "incomplete.zip"
    with zipfile.ZipFile(good) as src, zipfile.ZipFile(bad, "w") as dst:
        for name in src.namelist():
            if name == missing:
                continue
            data = src.read(name)
            if name == "manifest.json":
                manifest = json.loads(data)
                del manifest["files"][missing]
                data = json.dumps(manifest).encode()
            dst.writestr(name, data)
    try:
        verify_backup(bad, tmp_path / "verification")
    except BackupError:
        return
    app.state.engine.dispose()
    restored = restore_backup(s, bad)
    new_app = create_app(s)
    with TestClient(new_app, base_url="http://127.0.0.1:8765") as after:
        media = after.get(img["url"]).status_code
    new_app.state.engine.dispose()
    assert False, {
        "verification": "accepted incomplete archive",
        "restore": restored["restored_from"],
        "missing_original_http": media,
    }


def test_restore_move_failure_keeps_current_data(env):
    s, app, c = env
    product(c)
    backup = create_backup(s)
    app.state.engine.dispose()
    before = s.db_path.read_bytes()
    original_replace = Path.replace

    def injected(source, target):
        if source == s.images_dir and Path(target).name == "images":
            raise OSError("QA simulated failure moving old images")
        return original_replace(source, target)

    with patch.object(Path, "replace", injected), pytest.raises(OSError):
        restore_backup(s, backup)
    assert s.db_path.exists() and s.db_path.read_bytes() == before, {
        "db_exists": s.db_path.exists(),
        "moved_old_dirs": [p.name for p in s.data_dir.glob(".restore-old-*")],
    }


def test_backup_missing_database_is_rejected(env, tmp_path):
    s, app, c = env
    product(c)
    good = create_backup(s)
    bad = tmp_path / "no-database.zip"
    with zipfile.ZipFile(good) as src, zipfile.ZipFile(bad, "w") as dst:
        for name in src.namelist():
            if name == "wardrobe.db":
                continue
            data = src.read(name)
            if name == "manifest.json":
                manifest = json.loads(data)
                del manifest["files"]["wardrobe.db"]
                data = json.dumps(manifest).encode()
            dst.writestr(name, data)
    try:
        verify_backup(bad, tmp_path / "verify-no-db")
    except BackupError:
        return
    app.state.engine.dispose()
    restored = restore_backup(s, bad)
    new_app = create_app(s)
    with TestClient(new_app, base_url="http://127.0.0.1:8765") as after:
        products_after = after.get(API + "/products").json()["total"]
    new_app.state.engine.dispose()
    assert False, {
        "verification": "accepted missing DB",
        "restore": restored["restored_from"],
        "product_count_before": 1,
        "product_count_after_restart": products_after,
    }


def test_updated_brand_is_searchable(env):
    _, _, c = env
    brand = post(c, "/brands", {"slug": "qa-brand", "name": "oldbrandmarker"})
    p = post(c, "/products", {"name_ja": "QA coat", "brand_id": brand["id"]})
    post(c, "/items", {"product_id": p["id"]})
    assert c.patch(API + f"/brands/{brand['id']}", json={"name": "newbrandmarker"}).status_code == 200
    assert c.get(API + "/items", params={"q": "newbrandmarker"}).json()["total"] == 1


def test_image_gc_does_not_delete_concurrently_reuploaded_files(env):
    import io

    from PIL import Image

    s, app, c = env
    buf = io.BytesIO()
    Image.new("RGB", (30, 40), "blue").save(buf, "PNG")
    data = buf.getvalue()
    first = c.post(API + "/images", files={"file": ("qa.png", data, "image/png")}).json()
    original_glob = Path.glob
    uploaded = []

    def interleave(path, pattern, **kw):
        # gc_orphans has already read its referenced SHA set at this point.
        if path == s.images_dir / "original" and not uploaded:
            with TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Wardrobe-Client": "web-ui"}) as other:
                r = other.post(API + "/images", files={"file": ("qa.png", data, "image/png")})
                assert r.status_code == 201, r.text
                uploaded.append(r.json())
        return original_glob(path, pattern, **kw)

    with patch.object(Path, "glob", interleave):
        deleted = c.delete(API + f"/images/{first['id']}")
    assert deleted.status_code == 204, deleted.text
    image = uploaded[0]
    meta_status = c.get(API + f"/images/{image['id']}").status_code
    file_status = c.get(image["url"]).status_code
    thumb_status = c.get(image["thumb_url"]).status_code
    assert (meta_status, file_status, thumb_status) == (200, 200, 200), {
        "metadata": meta_status,
        "original": file_status,
        "thumbnail": thumb_status,
    }


def test_atomic_default_color_and_version_contract(env):
    _, _, c = env
    p = product(c)
    item = post(c, "/items", {"product_id": p["id"]})
    good = {"version": 1, "colors": [{"name_ja": "NAVY", "hex": "#001144", "is_default": True}]}
    r = c.put(API + f"/products/{p['id']}/colors", json=good)
    assert r.status_code == 200, r.text
    assert c.get(API + f"/items/{item['id']}").json()["resolved"]["color"]["name"] == "NAVY"
    assert c.put(API + f"/products/{p['id']}/colors", json=good).status_code == 409
    bad = {"version": 2, "colors": [{"name_ja": "BLACK", "is_default": True}, {"name_ja": "WHITE", "is_default": True}]}
    assert c.put(API + f"/products/{p['id']}/colors", json=bad).status_code == 422
    assert c.get(API + f"/products/{p['id']}").json()["colors"][0]["name_ja"] == "NAVY"


def test_partial_return_and_unknown_actor_protection(env):
    _, _, c = env
    p = product(c)
    purchase = post(
        c,
        "/purchases",
        {
            "purchased_on": "2026-01-01",
            "create_items": True,
            "lines": [{"product_id": p["id"], "quantity": 2, "color_name": "NAVY", "size_label": "L"}],
        },
    )
    line = purchase["lines"][0]
    i = line["item_ids"][0]
    r = c.post(API + f"/items/{i}/return", json={"version": 1, "returned_on": "2026-01-03", "refund_amount": 10})
    assert r.status_code == 200
    current = c.get(API + f"/purchase-lines/{line['id']}").json()
    assert current["quantity"] == 2 and current["returned_quantity"] == 1
    post(c, f"/products/{p['id']}/verify", {"version": 1})
    r = c.patch(
        API + f"/products/{p['id']}",
        headers={"X-Wardrobe-Client": "unknown-client"},
        json={"version": 2, "name_ja": "changed", "notes": "must not apply"},
    )
    # Phase 2 契约变更（API §1.5，Phase 0 设计即已约定）：受保护字段转为提议并返回 202，
    # 不受保护的 notes 照常生效。原断言为 409 + notes 不变；数据安全断言（受保护字段不变）保持不变并加强。
    assert r.status_code == 202
    assert [x["field"] for x in r.json()["proposed"]] == ["name_ja"]
    after = c.get(API + f"/products/{p['id']}").json()
    assert after["name_ja"] == "QA fictional jacket"
    pending = c.get(API + "/proposals").json()["items"]
    assert [(x["field"], x["actor"], x["status"]) for x in pending] == [("name_ja", "unknown-client", "pending")]
