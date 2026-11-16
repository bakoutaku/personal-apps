"""GPT Phase 1 修复复查（docs/REVIEW_PHASE1_REGRESSION_2026-10-26.md）的独立边界测试，原样保留预期行为作为回归用例。"""

import hashlib
import json
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

from wardrobe.config import Settings
from wardrobe.main import create_app
from wardrobe.storage.backup import BackupError, create_backup, verify_backup

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


def test_restore_revalidates_line_product_after_reassignment(env):
    _, _, c = env
    a = post(c, "/products", {"name_ja": "QA coat A"})
    b = post(c, "/products", {"name_ja": "QA coat B"})
    purchase = post(
        c,
        "/purchases",
        {
            "purchased_on": "2026-01-01",
            "create_items": True,
            "lines": [{"product_id": a["id"], "quantity": 1, "color_name": "BLACK"}],
        },
    )
    line = purchase["lines"][0]
    item_id = line["item_ids"][0]
    assert c.delete(API + f"/items/{item_id}?version=1").status_code == 204
    update = c.patch(
        API + f"/purchase-lines/{line['id']}", json={"version": 1, "product_id": b["id"], "color_name": "NAVY"}
    )
    assert update.status_code == 200, update.text
    restored = c.post(API + f"/items/{item_id}/restore", json={"version": 2})
    current = c.get(API + f"/purchase-lines/{line['id']}").json()
    if restored.status_code in (409, 422):
        assert c.get(API + f"/items/{item_id}").status_code == 404
        return
    assert restored.status_code == 200, restored.text
    result = restored.json()
    assert result["product"]["id"] == current["product_id"], {
        "restore_http": restored.status_code,
        "item_product_id": result["product"]["id"],
        "line_product_id": current["product_id"],
        "resolved_color": result["resolved"]["color"],
    }


def test_same_product_line_edits_still_allow_restore(env):
    _, _, c = env
    p = post(c, "/products", {"name_ja": "QA control"})
    purchase = post(
        c,
        "/purchases",
        {"purchased_on": "2026-01-01", "create_items": True, "lines": [{"product_id": p["id"], "quantity": 1}]},
    )
    line = purchase["lines"][0]
    item = line["item_ids"][0]
    assert c.delete(API + f"/items/{item}?version=1").status_code == 204
    assert c.patch(API + f"/purchase-lines/{line['id']}", json={"version": 1, "color_name": "NAVY"}).status_code == 200
    r = c.post(API + f"/items/{item}/restore", json={"version": 2})
    assert r.status_code == 200, r.text
    assert r.json()["resolved"]["color"]["name"] == "NAVY"


@pytest.mark.parametrize("missing_table", ["import_row", "change_proposal"])
def test_backup_rejects_missing_migration_table(env, tmp_path, missing_table):
    s, _, c = env
    post(c, "/products", {"name_ja": "QA backup"})
    good = create_backup(s)
    with zipfile.ZipFile(good) as z:
        entries = {name: z.read(name) for name in z.namelist()}
    db = tmp_path / "edited.db"
    db.write_bytes(entries["wardrobe.db"])
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE " + missing_table)
    entries["wardrobe.db"] = db.read_bytes()
    manifest = json.loads(entries["manifest.json"])
    manifest["files"]["wardrobe.db"] = hashlib.sha256(entries["wardrobe.db"]).hexdigest()
    manifest["table_counts"].pop(missing_table, None)
    entries["manifest.json"] = json.dumps(manifest).encode()
    bad = tmp_path / (missing_table + ".zip")
    with zipfile.ZipFile(bad, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    with pytest.raises(BackupError):
        verify_backup(bad, tmp_path / ("verify-" + missing_table))
