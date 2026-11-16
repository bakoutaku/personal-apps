"""迁移与数据库层约束（含 Phase 0 审查 BUG-001 / BUG-002 的回归）。"""

import sqlite3

import pytest
from alembic import command

from wardrobe.db import alembic_config, current_revision, head_revision, make_engine, run_migrations
from wardrobe.models import Base

NOW = "2026-10-26T00:00:00Z"


@pytest.fixture
def conn(settings, app):
    c = sqlite3.connect(settings.db_path)
    c.execute("PRAGMA foreign_keys = ON")
    yield c
    c.close()


def test_migration_is_at_head(app, settings):
    assert current_revision(app.state.engine) == head_revision()


def test_orm_columns_match_migration(conn):
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'search_index%' "
            "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
        )
    ]
    assert set(tables) == set(Base.metadata.tables)
    for t in tables:
        db_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        assert db_cols == {c.name for c in Base.metadata.tables[t].columns}, t


def test_integrity_and_foreign_keys(conn):
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_downgrade_then_upgrade_roundtrip(tmp_path):
    engine = make_engine(tmp_path / "rt.db")
    run_migrations(engine)
    cfg = alembic_config()
    with engine.begin() as c:
        cfg.attributes["connection"] = c
        command.downgrade(cfg, "base")
    assert current_revision(engine) is None
    run_migrations(engine)
    assert current_revision(engine) == head_revision()


def _product(conn) -> int:
    conn.execute(
        "INSERT INTO product(id, brand_id, name_ja, created_at, updated_at) VALUES (100, 1, 'テスト', ?, ?)", (NOW, NOW)
    )
    return 100


def test_bug001_second_default_color_rejected_by_insert_and_update(conn):
    pid = _product(conn)
    conn.execute(
        "INSERT INTO product_color(product_id, color_code, name_ja, is_default) VALUES (?, '09', 'B', 1)", (pid,)
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO product_color(product_id, color_code, name_ja, is_default) VALUES (?, '69', 'N', 1)", (pid,)
        )
    conn.execute(
        "INSERT INTO product_color(product_id, color_code, name_ja, is_default) VALUES (?, '69', 'N', 0)", (pid,)
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE product_color SET is_default = 1 WHERE color_code = '69'")


def test_bug001_default_is_per_product_and_zero_allowed(conn):
    _product(conn)
    conn.execute("INSERT INTO product(id, name_ja, created_at, updated_at) VALUES (101, 'B', ?, ?)", (NOW, NOW))
    conn.execute("INSERT INTO product_color(product_id, color_code, is_default) VALUES (100, '09', 1)")
    conn.execute("INSERT INTO product_color(product_id, color_code, is_default) VALUES (101, '09', 1)")
    conn.execute("UPDATE product_color SET is_default = 0")
    assert conn.execute("SELECT count(*) FROM product_color WHERE is_default = 1").fetchone()[0] == 0


def test_bug002_refund_only_when_returned(conn):
    pid = _product(conn)
    conn.execute(
        "INSERT INTO wardrobe_item(id, product_id, created_at, updated_at) VALUES (1, ?, ?, ?)", (pid, NOW, NOW)
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE wardrobe_item SET refund_amount = 100 WHERE id = 1")
    conn.execute("UPDATE wardrobe_item SET status = 'returned', refund_amount = 100 WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE wardrobe_item SET status = 'owned' WHERE id = 1")


def test_purchase_line_match_requires_product(conn):
    conn.execute(
        "INSERT INTO purchase(id, purchased_on, created_at, updated_at) VALUES (1, '2025-01-01', ?, ?)", (NOW, NOW)
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO purchase_line(purchase_id, product_match, created_at, updated_at) "
            "VALUES (1, 'confirmed', ?, ?)",
            (NOW, NOW),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO purchase_line(purchase_id, product_id, product_match, created_at, updated_at) "
            "VALUES (1, NULL, 'suggested', ?, ?)",
            (NOW, NOW),
        )


def test_review_enums_withdrawn_and_revert(conn):
    conn.execute(
        "INSERT INTO change_proposal(entity, entity_id, field, actor, status, created_at) "
        "VALUES ('product', 1, 'x', 'ai:t', 'withdrawn', ?)",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO change_log(occurred_at, actor, entity, entity_id, op) VALUES (?, 'cli', 'product', 1, 'revert')",
        (NOW,),
    )


def test_seed_data(client):
    from helpers import API, ok

    brands = {b["slug"] for b in ok(client.get(f"{API}/brands"))["items"]}
    assert {"uniqlo", "gu"} <= brands
    flat = ok(client.get(f"{API}/categories", params={"format": "flat"}))["items"]
    assert {c["level"] for c in flat} == {1, 2, 3}
