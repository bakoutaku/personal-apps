"""备份与恢复（ARCHITECTURE §8）。全部在临时目录中进行。"""

import json
import zipfile

import pytest
from helpers import API, make_product, ok, png_bytes, upload

from wardrobe.main import prepare_database
from wardrobe.storage.backup import BackupError, create_backup, restore_backup, verify_backup


def _rewrite_zip(src, dest, *, mutate=None, extra: dict[str, bytes] | None = None):
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if mutate:
                data = mutate(info.filename, data)
            zout.writestr(info.filename, data)
        for name, data in (extra or {}).items():
            zout.writestr(name, data)


def test_backup_contents_and_manifest(client, settings):
    make_product(client)
    img = ok(upload(client), 201)
    path = create_backup(settings, "manual")
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        names = set(zf.namelist())
    assert manifest["schema_revision"] == "0003"  # 当前 head（0003：规则建议上下文）
    assert manifest["table_counts"]["product"] == 1
    assert f"images/{img['url'].removeprefix('/media/')}" in names
    assert set(manifest["files"]) | {"manifest.json"} == names


def test_full_restore_cycle(client, settings, app):
    p = make_product(client)
    img = ok(upload(client), 201)
    backup = create_backup(settings, "manual")

    # 备份之后的修改：新商品、新图片、删除旧图片
    make_product(client, identifiers=[], name_ja="备份之后")
    ok(upload(client, png_bytes(color=(1, 1, 1))), 201)
    app.state.engine.dispose()

    result = restore_backup(settings, backup)
    assert result["pre_restore_backup"].endswith("pre-restore.zip")

    engine, _ = prepare_database(settings)
    from fastapi.testclient import TestClient

    from wardrobe.main import create_app

    c = TestClient(create_app(settings), base_url="http://127.0.0.1:8765", headers={"X-Wardrobe-Client": "web-ui"})
    products = ok(c.get(f"{API}/products"))["items"]
    assert [x["id"] for x in products] == [p["id"]]
    assert ok(c.get(f"{API}/images"))["total"] == 1
    assert c.get(img["thumb_url"]).status_code == 200
    engine.dispose()


def test_tampered_backup_is_rejected_and_data_untouched(client, settings, tmp_path):
    make_product(client)
    good = create_backup(settings, "manual")
    bad = tmp_path / "bad.zip"
    _rewrite_zip(good, bad, mutate=lambda n, d: d + b"x" if n == "wardrobe.db" else d)
    before = settings.db_path.read_bytes()
    with pytest.raises(BackupError, match="校验失败"):
        restore_backup(settings, bad)
    assert settings.db_path.read_bytes() == before


def test_zip_slip_is_rejected(client, settings, tmp_path):
    make_product(client)
    good = create_backup(settings, "manual")
    evil = tmp_path / "evil.zip"
    _rewrite_zip(good, evil, extra={"../escape.txt": b"x"})
    with pytest.raises(BackupError, match="不安全的路径"):
        verify_backup(evil, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def _rebuild(src, dest, tmp_path, *, edit_db=None, drop=(), manifest_edit=None):
    """解压 → 修改数据库/删除文件 → 重新计算 manifest 哈希 → 打包。得到「哈希自洽」但内容有问题的备份。"""
    import hashlib
    import sqlite3

    work = tmp_path / f"rebuild-{dest.stem}"
    with zipfile.ZipFile(src) as zf:
        zf.extractall(work)
    if edit_db:
        conn = sqlite3.connect(work / "wardrobe.db")
        edit_db(conn)
        conn.commit()
        conn.close()
    for rel in drop:
        (work / rel).unlink()
    manifest = json.loads((work / "manifest.json").read_text())
    manifest["files"] = {
        p.relative_to(work).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(work.rglob("*"))
        if p.is_file() and p.name != "manifest.json"
    }
    if manifest_edit:
        manifest_edit(manifest)
    (work / "manifest.json").write_text(json.dumps(manifest))
    with zipfile.ZipFile(dest, "w") as zf:
        for p in sorted(work.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(work).as_posix())
    return dest


def test_unknown_newer_schema_is_rejected(client, settings, tmp_path):
    make_product(client)
    good = create_backup(settings, "manual")

    def bump(conn):
        conn.execute("UPDATE alembic_version SET version_num = '9999'")

    newer = _rebuild(good, tmp_path / "newer.zip", tmp_path, edit_db=bump,
                     manifest_edit=lambda m: m.update(schema_revision="9999"))  # fmt: skip
    with pytest.raises(BackupError, match="比当前程序新"):
        verify_backup(newer, tmp_path / "out")


def test_manifest_revision_must_match_database(client, settings, tmp_path):
    make_product(client)
    good = create_backup(settings, "manual")
    lying = _rebuild(good, tmp_path / "lying.zip", tmp_path, manifest_edit=lambda m: m.update(schema_revision="x"))
    with pytest.raises(BackupError, match="不一致"):
        verify_backup(lying, tmp_path / "out")


def test_empty_database_file_is_rejected(client, settings, tmp_path):
    make_product(client)
    good = create_backup(settings, "manual")

    def wipe(conn):
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            if not t.startswith("search_index_"):
                conn.execute(f'DROP TABLE IF EXISTS "{t}"')

    empty = _rebuild(good, tmp_path / "empty.zip", tmp_path, edit_db=wipe)
    with pytest.raises(BackupError, match="缺少必要的表|schema"):
        verify_backup(empty, tmp_path / "out")


def test_missing_required_table_is_rejected(client, settings, tmp_path):
    make_product(client)
    good = create_backup(settings, "manual")
    bad = _rebuild(good, tmp_path / "notable.zip", tmp_path, edit_db=lambda c: c.execute("DROP TABLE outfit_tag"))
    with pytest.raises(BackupError, match="outfit_tag"):
        verify_backup(bad, tmp_path / "out")


def test_missing_thumbnail_is_rejected(client, settings, tmp_path):
    img = ok(upload(client), 201)
    good = create_backup(settings, "manual")
    thumb = "images/" + img["thumb_url"].removeprefix("/media/")
    bad = _rebuild(good, tmp_path / "nothumb.zip", tmp_path, drop=[thumb])
    with pytest.raises(BackupError, match="缩略图"):
        verify_backup(bad, tmp_path / "out")


def test_image_content_must_match_database_sha(client, settings, tmp_path):
    img = ok(upload(client), 201)
    good = create_backup(settings, "manual")
    original = "images/" + img["url"].removeprefix("/media/")

    def swap(conn):
        conn.execute("UPDATE image SET sha256 = 'f' || substr(sha256, 2)")

    bad = _rebuild(good, tmp_path / "swap.zip", tmp_path, edit_db=swap)
    with pytest.raises(BackupError, match="sha256"):
        verify_backup(bad, tmp_path / "out")
    assert original  # 路径本身仍在清单中，靠内容核对发现问题


def test_rejected_restore_leaves_current_data_untouched(client, settings, tmp_path, app):
    make_product(client)
    img = ok(upload(client), 201)
    good = create_backup(settings, "manual")
    bad = _rebuild(good, tmp_path / "nodb.zip", tmp_path, drop=["wardrobe.db"])
    app.state.engine.dispose()
    db_before = settings.db_path.read_bytes()
    with pytest.raises(BackupError, match="wardrobe.db"):
        restore_backup(settings, bad)
    assert settings.db_path.read_bytes() == db_before
    assert (settings.images_dir / img["url"].removeprefix("/media/")).exists()
    assert not list(settings.data_dir.glob(".restore*"))


@pytest.mark.parametrize("fail_on", ["wardrobe.db", "images-old", "db-install", "images-install"])
def test_restore_rolls_back_at_every_step(client, settings, app, fail_on, monkeypatch):
    """任何一次 rename 失败，数据目录都回到恢复前的状态，且可以正常启动。"""
    from pathlib import Path

    make_product(client)
    img = ok(upload(client), 201)
    backup = create_backup(settings, "manual")
    make_product(client, identifiers=[], name_ja="恢复前的新数据")
    app.state.engine.dispose()
    db_before = settings.db_path.read_bytes()
    original_replace = Path.replace
    failed: list[int] = []

    def failing(src, dst):
        src, dst = Path(src), Path(dst)
        hit = {
            "wardrobe.db": src == settings.db_path,
            "images-old": src == settings.images_dir,
            "db-install": dst == settings.db_path,
            "images-install": dst == settings.images_dir,
        }[fail_on]
        if hit and not failed:
            failed.append(1)  # 只失败一次，回滚自身的 rename 正常执行
            raise OSError(f"模拟失败：{src} -> {dst}")
        return original_replace(src, dst)

    monkeypatch.setattr(Path, "replace", failing)
    with pytest.raises(OSError, match="模拟失败"):
        restore_backup(settings, backup)
    monkeypatch.setattr(Path, "replace", original_replace)

    assert failed
    assert settings.db_path.read_bytes() == db_before
    assert (settings.images_dir / img["url"].removeprefix("/media/")).exists()
    assert not list(settings.data_dir.glob(".restore*"))
    from fastapi.testclient import TestClient

    from wardrobe.main import create_app

    c = TestClient(create_app(settings), base_url="http://127.0.0.1:8765")
    assert ok(c.get(f"{API}/products"))["total"] == 2


def test_interrupted_restore_blocks_startup(settings, client, app):
    from wardrobe.main import create_app
    from wardrobe.storage.backup import RESTORE_MARKER

    app.state.engine.dispose()
    (settings.data_dir / RESTORE_MARKER).write_text("{}")
    with pytest.raises(BackupError, match="未完成的恢复"):
        create_app(settings)
    (settings.data_dir / RESTORE_MARKER).unlink()

    old = settings.data_dir / ".restore-old-test"
    old.mkdir()
    settings.db_path.replace(old / "wardrobe.db")
    with pytest.raises(BackupError, match="未完成的恢复"):
        create_app(settings)
    assert not settings.db_path.exists()  # 没有静默新建空库


def test_not_a_zip(settings, tmp_path):
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"hello")
    with pytest.raises(BackupError):
        restore_backup(settings, junk)


def test_old_backups_are_pruned(client, tmp_path):
    from wardrobe.config import Settings

    s = Settings(data_dir=tmp_path / "prune", backup_keep=3)
    prepare_database(s)
    for _ in range(5):
        create_backup(s, "manual")
    assert len(list(s.backups_dir.glob("*.zip"))) == 3


def test_backup_api(client):
    made = ok(client.post(f"{API}/backups"), 201)
    assert made["name"] in [b["name"] for b in ok(client.get(f"{API}/backups"))["items"]]


def test_failed_rollback_leaves_marker_and_blocks_startup(client, settings, app, monkeypatch):
    """连回滚都失败时（例如磁盘问题持续存在），保留标记并拒绝启动，而不是静默新建空库。"""
    from pathlib import Path

    from wardrobe.main import create_app

    make_product(client)
    backup = create_backup(settings, "manual")
    app.state.engine.dispose()
    original_replace = Path.replace

    def always_fail_into_db(src, dst):
        if Path(dst) == settings.db_path:
            raise OSError("模拟持续失败")
        return original_replace(src, dst)

    monkeypatch.setattr(Path, "replace", always_fail_into_db)
    with pytest.raises(OSError):
        restore_backup(settings, backup)
    monkeypatch.setattr(Path, "replace", original_replace)
    assert list(settings.data_dir.glob(".restore-old-*/wardrobe.db"))  # 旧数据库仍在暂存目录中
    with pytest.raises(BackupError, match="未完成的恢复"):
        create_app(settings)


def _recount(dest_manifest_db):
    """按数据库实际内容重算 table_counts，让 manifest 完全自洽，只留下结构问题。"""
    import sqlite3

    conn = sqlite3.connect(dest_manifest_db)
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "AND name NOT LIKE 'search_index_%'"
        )
    ]
    counts = {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
    conn.close()
    return counts


@pytest.mark.parametrize("table", ["import_job", "import_row", "change_proposal", "outfit_tag", "search_index"])
def test_any_table_created_by_migrations_is_required(client, settings, tmp_path, table):
    """复查补充：必要表由迁移推导；manifest 与数据库完全自洽时也能发现缺表。"""
    make_product(client)
    good = create_backup(settings, "manual")
    holder = {}

    def drop(conn):
        conn.execute(f'DROP TABLE "{table}"')

    def fix_counts(m):
        m["table_counts"] = holder["counts"]

    # 先删表并关闭连接（写入主文件），再按实际内容重算行数
    work = tmp_path / "pre"
    with zipfile.ZipFile(good) as zf:
        zf.extractall(work)
    import sqlite3

    conn = sqlite3.connect(work / "wardrobe.db")
    drop(conn)
    conn.commit()
    conn.close()
    holder["counts"] = _recount(work / "wardrobe.db")
    bad = _rebuild(good, tmp_path / f"no-{table}.zip", tmp_path, edit_db=drop, manifest_edit=fix_counts)
    with pytest.raises(BackupError, match=f"缺少 schema 0003 的必要表.*{table}"):
        verify_backup(bad, tmp_path / "out")


def test_changed_columns_are_rejected(client, settings, tmp_path):
    make_product(client)
    good = create_backup(settings, "manual")
    bad = _rebuild(good, tmp_path / "cols.zip", tmp_path,
                   edit_db=lambda c: c.execute("ALTER TABLE tag ADD COLUMN surprise TEXT"))  # fmt: skip
    with pytest.raises(BackupError, match="列与 schema 0003 不一致.*tag"):
        verify_backup(bad, tmp_path / "out")


def test_manifest_table_counts_must_match(client, settings, tmp_path):
    make_product(client)
    good = create_backup(settings, "manual")

    def lie(m):
        m["table_counts"]["product"] = 99

    bad = _rebuild(good, tmp_path / "counts.zip", tmp_path, manifest_edit=lie)
    with pytest.raises(BackupError, match="表行数与数据库不一致.*product"):
        verify_backup(bad, tmp_path / "out")


def test_expected_schema_matches_live_database(app, settings):
    """推导出的必要结构与应用实际使用的数据库完全一致（防止推导逻辑与迁移脱节）。"""
    import sqlite3

    from wardrobe.db import expected_schema, head_revision, table_columns

    conn = sqlite3.connect(settings.db_path)
    try:
        assert table_columns(conn) == expected_schema(head_revision())
    finally:
        conn.close()


def test_backup_database_is_self_contained(client, settings, tmp_path):
    """备份中的数据库不是 WAL 模式：对它的修改直接写入文件本身。"""
    make_product(client)
    with zipfile.ZipFile(create_backup(settings, "manual")) as zf:
        data = zf.read("wardrobe.db")
    assert (data[18], data[19]) == (1, 1)  # 1 = 回滚日志模式，2 = WAL
