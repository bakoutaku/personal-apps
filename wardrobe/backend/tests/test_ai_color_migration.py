"""迁移 0002（ai_suggestion_context）：全新库、0001 旧库升级、降级再升级、备份恢复与结构校验。

全部在 pytest 提供的临时目录中进行。
"""

import io
import sqlite3
import zipfile

import pytest
from alembic import command
from fastapi.testclient import TestClient
from helpers import API, get, make_product, make_purchase, ok, upload
from PIL import Image as PILImage
from test_backup import _rebuild, _recount

from wardrobe.config import Settings
from wardrobe.db import alembic_config, current_revision, expected_schema, head_revision, make_engine, run_migrations
from wardrobe.main import create_app, prepare_database
from wardrobe.storage.backup import BackupError, create_backup, restore_backup, verify_backup

CONTEXT_COLUMNS = {
    "proposal_id", "kind", "target_version", "image_id", "image_sha256", "region", "algorithm", "parameters",
    "candidate", "candidates", "created_at",
}  # fmt: skip
BASE_URL = "http://127.0.0.1:8765"


def web(app) -> TestClient:
    return TestClient(app, base_url=BASE_URL, headers={"X-Wardrobe-Client": "web-ui"})


def navy_png() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (20, 30), (0x1F, 0x2A, 0x44)).save(buf, "PNG")
    return buf.getvalue()


def make_suggestion(client, name: str = "迁移测试") -> dict:
    p = make_product(client, identifiers=[], name_ja=name)
    item_id = make_purchase(client, p["id"])["lines"][0]["item_ids"][0]
    resp = upload(client, navy_png())
    img = ok(resp, 200 if resp.status_code == 200 else 201)  # 同一内容再次上传时复用已有图片（200）
    item = ok(client.post(f"{API}/items/{item_id}/images", json={"version": 1, "image_id": img["id"]}), 201)
    body = {"version": item["version"], "image_id": img["id"], "candidate_hex": "#1F2A44"}
    return ok(client.post(f"{API}/items/{item_id}/color-suggestions", json=body), 201)["proposal"]


def build_0001_database(settings: Settings) -> None:
    """建一个只执行到 0001 的旧库，并写入一条历史（无上下文）提议。"""
    settings.ensure_dirs()
    engine = make_engine(settings.db_path)
    run_migrations(engine, "0001")
    engine.dispose()
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "INSERT INTO change_proposal (entity, entity_id, field, current_value, proposed_value, actor, status, created_at)"
        " VALUES ('wardrobe_item', 42, 'size', '{}', '{\"size_label\": \"XL\"}', 'ai:old', 'pending', '2026-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()


def test_head_is_0002_and_the_table_has_the_expected_columns_and_foreign_keys(app, settings):
    assert head_revision() == "0003"  # Phase 5C 新增 0003；0002 的结构断言如下保持不变
    assert expected_schema("0002")["ai_suggestion_context"] == CONTEXT_COLUMNS
    assert "ai_suggestion_context" not in expected_schema("0001")
    # 0001 的其余表结构不变
    assert {t: c for t, c in expected_schema("0002").items() if t != "ai_suggestion_context"} == expected_schema("0001")
    conn = sqlite3.connect(settings.db_path)
    fks = {(r[2], r[3], r[6]) for r in conn.execute("PRAGMA foreign_key_list(ai_suggestion_context)")}
    conn.close()
    assert fks == {("change_proposal", "proposal_id", "CASCADE"), ("image", "image_id", "SET NULL")}


def test_0001_database_is_backed_up_and_upgraded_and_old_proposals_keep_working(tmp_path):
    settings = Settings(data_dir=tmp_path / "old")
    build_0001_database(settings)
    app = create_app(settings)
    assert current_revision(app.state.engine) == head_revision()
    backups = list(settings.backups_dir.glob("*pre-migrate.zip"))
    assert len(backups) == 1
    with zipfile.ZipFile(backups[0]) as zf:
        assert b'"schema_revision": "0001"' in zf.read("manifest.json")
    c = web(app)
    old = get(c, "/proposals")["items"]
    assert len(old) == 1 and old[0]["ai_context"] is None and old[0]["actor"] == "ai:old"
    # 升级后的库可以正常生成新的 AI 建议
    assert make_suggestion(c)["ai_context"]["algorithm"] == "wardrobe-color/2"
    app.state.engine.dispose()


def test_downgrade_then_upgrade_keeps_other_data(client, app, settings):
    make_suggestion(client)
    app.state.engine.dispose()
    engine = make_engine(settings.db_path)
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0001")
    assert current_revision(engine) == "0001"
    raw = sqlite3.connect(settings.db_path)
    tables = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "ai_suggestion_context" not in tables
    assert raw.execute("SELECT count(*) FROM change_proposal").fetchone()[0] == 1
    raw.close()
    run_migrations(engine)
    assert current_revision(engine) == head_revision()
    engine.dispose()
    app2 = create_app(settings)
    props = get(web(app2), "/proposals")["items"]
    assert len(props) == 1 and props[0]["ai_context"] is None  # 降级时上下文随表删除，提议本身保留
    app2.state.engine.dispose()


def test_0001_backup_restores_and_is_upgraded(tmp_path):
    old = Settings(data_dir=tmp_path / "old")
    build_0001_database(old)
    backup = create_backup(old, "manual")
    assert verify_backup(backup, tmp_path / "check")["schema_revision"] == "0001"
    target = Settings(data_dir=tmp_path / "new")
    app = create_app(target)
    make_product(web(app))
    app.state.engine.dispose()
    restore_backup(target, backup)
    engine, _ = prepare_database(target)
    assert current_revision(engine) == head_revision()
    engine.dispose()
    app2 = create_app(target)
    c = web(app2)
    assert get(c, "/products")["total"] == 0  # 恢复的是旧备份的内容
    assert [p["actor"] for p in get(c, "/proposals")["items"]] == ["ai:old"]
    app2.state.engine.dispose()


def test_backup_with_ai_context_round_trips(client, app, settings, tmp_path):
    prop = make_suggestion(client)
    backup = create_backup(settings, "manual")
    with zipfile.ZipFile(backup) as zf:
        manifest = zf.read("manifest.json").decode()
    assert '"ai_suggestion_context": 1' in manifest
    make_suggestion(client, "备份之后")  # 备份之后的新建议
    app.state.engine.dispose()
    restore_backup(settings, backup)
    app2 = create_app(settings)
    props = get(web(app2), "/proposals")["items"]
    assert [p["proposal_id"] for p in props] == [prop["proposal_id"]]
    assert props[0]["ai_context"] == prop["ai_context"]
    app2.state.engine.dispose()


def test_0002_backup_missing_the_context_table_is_rejected(client, settings, tmp_path):
    make_suggestion(client)
    good = create_backup(settings, "manual")
    holder = {}
    work = tmp_path / "pre"
    with zipfile.ZipFile(good) as zf:
        zf.extractall(work)
    conn = sqlite3.connect(work / "wardrobe.db")
    conn.execute("DROP TABLE ai_suggestion_context")
    conn.commit()
    conn.close()
    holder["counts"] = _recount(work / "wardrobe.db")
    bad = _rebuild(
        good, tmp_path / "no-ctx.zip", tmp_path,
        edit_db=lambda c: c.execute("DROP TABLE ai_suggestion_context"),
        manifest_edit=lambda m: m.update(table_counts=holder["counts"]),
    )  # fmt: skip
    with pytest.raises(BackupError, match="缺少 schema 0003 的必要表.*ai_suggestion_context"):
        verify_backup(bad, tmp_path / "out")


def test_image_gc_ignores_analysis_context(client, app, settings):
    prop = make_suggestion(client)
    item_id = prop["entity_id"]
    image_id = prop["ai_context"]["image_id"]
    item = get(client, f"/items/{item_id}")
    ok(client.delete(f"{API}/items/{item_id}/images/{image_id}", params={"version": item["version"]}))
    ok(client.delete(f"{API}/images/{image_id}"), 204)
    sha = prop["ai_context"]["image_sha256"]
    assert not list(settings.images_dir.glob(f"*/*/{sha}.*"))  # 文件已按原规则清理
