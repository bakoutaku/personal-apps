"""Phase 1 审查（BUG-006 ~ BUG-009）补充回归：审查报告「建议回归测试」中列出的场景。

BUG-004 / BUG-005 的补充场景在 test_backup.py 中。
"""

import subprocess
import sys
import threading
from pathlib import Path

from fastapi.testclient import TestClient
from helpers import API, err, get, make_product, make_purchase, ok, png_bytes, upload

from wardrobe.models import Image
from wardrobe.storage.images import gc_orphans

BASE = "http://127.0.0.1:8765"


def _client(app, name="web-ui"):
    return TestClient(app, base_url=BASE, headers={"X-Wardrobe-Client": name})


# ───────────── BUG-006 购买明细容量 ─────────────


def test_quantity_two_allows_exactly_two_items(client):
    p = make_product(client)
    line = make_purchase(client, p["id"], quantity=2, create_items=False)["lines"][0]
    for _ in range(2):
        ok(client.post(f"{API}/items", json={"purchase_line_id": line["id"]}), 201)
    e = err(client.post(f"{API}/items", json={"purchase_line_id": line["id"]}), 409, "LINE_FULL")
    assert e["details"][0] == {"loc": ["purchase_line_id"], "quantity": 2, "linked": 2}
    assert len(get(client, f"/purchase-lines/{line['id']}")["item_ids"]) == 2


def test_returned_items_still_count_toward_capacity(client):
    p = make_product(client)
    line = make_purchase(client, p["id"])["lines"][0]
    ok(client.post(f"{API}/items/{line['item_ids'][0]}/return", json={"version": 1, "returned_on": "2025-11-10"}))
    err(client.post(f"{API}/items", json={"purchase_line_id": line["id"]}), 409, "LINE_FULL")


def test_relinking_to_full_line_is_rejected_without_change(client):
    p = make_product(client)
    full = make_purchase(client, p["id"])["lines"][0]
    loose = ok(client.post(f"{API}/items", json={"product_id": p["id"]}), 201)
    err(client.patch(f"{API}/items/{loose['id']}", json={"version": 1, "purchase_line_id": full["id"]}), 409,
        "LINE_FULL")  # fmt: skip
    after = get(client, f"/items/{loose['id']}")
    assert after["purchase_line_id"] is None and after["version"] == 1


def test_restore_is_rejected_when_slot_was_taken(client):
    p = make_product(client)
    line = make_purchase(client, p["id"])["lines"][0]
    first = line["item_ids"][0]
    ok(client.delete(f"{API}/items/{first}", params={"version": 1}), 204)
    ok(client.post(f"{API}/items", json={"purchase_line_id": line["id"]}), 201)  # 空出的名额被新衣物占用
    err(client.post(f"{API}/items/{first}/restore", json={"version": 2}), 409, "LINE_FULL")


def test_concurrent_creates_only_fill_remaining_capacity(app):
    c = _client(app)
    p = make_product(c)
    line = make_purchase(c, p["id"], quantity=3, create_items=False)["lines"][0]
    ok(c.post(f"{API}/items", json={"purchase_line_id": line["id"]}), 201)  # 剩余 2 个名额
    results: list[int] = []
    barrier = threading.Barrier(6)

    def worker():
        cl = _client(app, "ai:worker")
        barrier.wait()
        results.append(cl.post(f"{API}/items", json={"purchase_line_id": line["id"]}).status_code)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [201, 201, 409, 409, 409, 409]
    assert len(get(c, f"/purchase-lines/{line['id']}")["item_ids"]) == 3


# ───────────── BUG-007 恢复依赖 ─────────────


def test_failed_restore_does_not_bump_version_and_retry_after_dependency_restore(client):
    p = make_product(client)
    item = ok(client.post(f"{API}/items", json={"product_id": p["id"]}), 201)
    ok(client.delete(f"{API}/items/{item['id']}", params={"version": 1}), 204)
    ok(client.delete(f"{API}/products/{p['id']}", params={"version": 1}), 204)

    e = err(client.post(f"{API}/items/{item['id']}/restore", json={"version": 2}), 409, "DEPENDENCY_DELETED")
    assert e["details"][0]["product_id"] == p["id"]
    assert ok(client.get(f"{API}/items"))["total"] == 0

    restored = ok(client.post(f"{API}/products/{p['id']}/restore", json={"version": 2}))
    assert restored["version"] == 3
    out = ok(client.post(f"{API}/items/{item['id']}/restore", json={"version": 2}))  # 失败的那次没有增加 version
    assert out["version"] == 3 and out["product"]["id"] == p["id"]


def test_restore_blocked_by_deleted_purchase(client):
    p = make_product(client)
    pur = make_purchase(client, p["id"])
    item_id = pur["lines"][0]["item_ids"][0]
    ok(client.delete(f"{API}/items/{item_id}", params={"version": 1}), 204)
    ok(client.delete(f"{API}/purchases/{pur['id']}", params={"version": 1}), 204)
    err(client.post(f"{API}/items/{item_id}/restore", json={"version": 2}), 409, "DEPENDENCY_DELETED")
    ok(client.post(f"{API}/purchases/{pur['id']}/restore", json={"version": 2}))
    ok(client.post(f"{API}/items/{item_id}/restore", json={"version": 2}))


def test_cannot_link_new_item_to_deleted_purchase(client):
    p = make_product(client)
    pur = make_purchase(client, p["id"], create_items=False)
    ok(client.delete(f"{API}/purchases/{pur['id']}", params={"version": 1}), 204)
    err(client.post(f"{API}/items", json={"purchase_line_id": pur["lines"][0]["id"]}), 409, "DEPENDENCY_DELETED")


def test_product_restore_rechecks_identifier_uniqueness(client):
    p = make_product(client)
    ok(client.delete(f"{API}/products/{p['id']}", params={"version": 1}), 204)
    make_product(client)  # 同品牌同编号的新商品
    err(client.post(f"{API}/products/{p['id']}/restore", json={"version": 2}), 409, "DUPLICATE")


def test_ai_cannot_restore_verified_records(client, ai):
    p = make_product(client)
    ok(client.post(f"{API}/products/{p['id']}/verify", json={"version": 1}))
    ok(client.delete(f"{API}/products/{p['id']}", params={"version": 2}), 204)
    err(ai.post(f"{API}/products/{p['id']}/restore", json={"version": 3}), 409, "VERIFIED_PROTECTED")


def test_every_active_item_has_active_dependencies(client, app):
    """不变量：所有活动衣物的商品与购买记录都未删除。"""
    p = make_product(client)
    pur = make_purchase(client, p["id"], quantity=2)
    a, b = pur["lines"][0]["item_ids"]
    ok(client.delete(f"{API}/items/{a}", params={"version": 1}), 204)
    err(client.delete(f"{API}/purchases/{pur['id']}", params={"version": 1}), 409, "IN_USE")
    ok(client.delete(f"{API}/items/{b}", params={"version": 1}), 204)
    ok(client.delete(f"{API}/purchases/{pur['id']}", params={"version": 1}), 204)
    for item_id in (a, b):
        client.post(f"{API}/items/{item_id}/restore", json={"version": 2})
    from sqlalchemy import select

    from wardrobe.models import Product, Purchase, PurchaseLine, WardrobeItem

    with app.state.sessionmaker() as s:
        bad = s.execute(
            select(WardrobeItem.id)
            .join(Product, Product.id == WardrobeItem.product_id)
            .outerjoin(PurchaseLine, PurchaseLine.id == WardrobeItem.purchase_line_id)
            .outerjoin(Purchase, Purchase.id == PurchaseLine.purchase_id)
            .where(
                WardrobeItem.deleted_at.is_(None),
                (Product.deleted_at.is_not(None)) | (Purchase.deleted_at.is_not(None)),
            )
        ).all()
    assert bad == []


# ───────────── BUG-008 字典改名后的索引 ─────────────


def _ids(client, q):
    return {i["id"] for i in ok(client.get(f"{API}/items", params={"q": q}))["items"]}


def test_shared_tag_rename_updates_all_items_with_normalization(client):
    p = make_product(client)
    ids = make_purchase(client, p["id"], quantity=2)["lines"][0]["item_ids"]
    for item_id in ids:
        ok(client.put(f"{API}/items/{item_id}/tags", json={"version": 1, "tags": ["きれいめ"]}))
    tag = next(t for t in ok(client.get(f"{API}/tags"))["items"] if t["name"] == "きれいめ")
    ok(client.patch(f"{API}/tags/{tag['id']}", json={"name": "ﾜｰｸｽﾀｲﾙ"}))
    assert _ids(client, "ワークスタイル") == set(ids)
    assert _ids(client, "きれいめ") == set()


def test_brand_rename_updates_items_of_all_products(client):
    b = ok(client.post(f"{API}/brands", json={"slug": "acme", "name": "旧ブランド名"}), 201)
    p1 = make_product(client, brand="acme", identifiers=[], name_ja="一")
    p2 = make_product(client, brand="acme", identifiers=[], name_ja="二")
    i1 = make_purchase(client, p1["id"])["lines"][0]["item_ids"][0]
    i2 = make_purchase(client, p2["id"])["lines"][0]["item_ids"][0]
    ok(client.patch(f"{API}/brands/{b['id']}", json={"name": "新しい名前", "name_zh": "新品牌"}))
    assert _ids(client, "新しい名前") == {i1, i2}
    assert _ids(client, "新品牌") == {i1, i2}
    assert _ids(client, "旧ブランド名") == set()


def test_rename_without_references_is_fine(client):
    t = ok(client.post(f"{API}/tags", json={"name": "未使用"}), 201)
    ok(client.patch(f"{API}/tags/{t['id']}", json={"name": "仍未使用"}))


def test_index_matches_reindex_after_upstream_changes(client):
    """不变量：增量维护的索引与全量重建的结果一致。"""
    b = ok(client.post(f"{API}/brands", json={"slug": "acme", "name": "Alpha"}), 201)
    p = make_product(client, brand="acme", identifiers=[])
    item_id = make_purchase(client, p["id"])["lines"][0]["item_ids"][0]
    ok(client.put(f"{API}/items/{item_id}/tags", json={"version": 1, "tags": ["Gamma"]}))
    ok(client.patch(f"{API}/brands/{b['id']}", json={"name": "Beta"}))
    tag = next(t for t in ok(client.get(f"{API}/tags"))["items"] if t["name"] == "Gamma")
    ok(client.patch(f"{API}/tags/{tag['id']}", json={"name": "Delta"}))
    queries = ["alpha", "beta", "gamma", "delta"]
    before = {q: _ids(client, q) for q in queries}
    ok(client.post(f"{API}/search/reindex"))
    assert before == {q: _ids(client, q) for q in queries}


# ───────────── BUG-009 图片 GC 与上传并发 ─────────────


def _all_image_files_exist(app, settings) -> list[str]:
    with app.state.sessionmaker() as s:
        rows = s.query(Image.storage_path, Image.thumb_path).all()
    return [p for pair in rows for p in pair if not (settings.images_dir / p).exists()]


def test_threaded_delete_reupload_and_gc_keep_referenced_files(app, settings):
    data = png_bytes(color=(10, 20, 30))
    stop = threading.Event()
    errors: list[str] = []

    def churn():
        c = _client(app)
        for _ in range(15):
            r = upload(c, data)
            if r.status_code not in (200, 201):
                errors.append(r.text)
                continue
            c.delete(f"{API}/images/{r.json()['id']}")
            r = upload(c, data)
            if r.status_code not in (200, 201):
                errors.append(r.text)
        stop.set()

    def collector():
        while not stop.is_set():
            gc_orphans(settings, app.state.sessionmaker)

    threads = [threading.Thread(target=churn), threading.Thread(target=collector), threading.Thread(target=collector)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert _all_image_files_exist(app, settings) == []
    final = _client(app).get(f"{API}/images").json()["items"]
    assert len(final) == 1
    assert _client(app).get(final[0]["thumb_url"]).status_code == 200


def test_cross_process_gc_does_not_delete_referenced_files(app, settings):
    """独立进程反复执行 GC（相当于 ./wardrobe gc-images），同时本进程删除并重新上传。"""
    backend = Path(__file__).resolve().parents[1]
    script = (
        "import sys; from pathlib import Path; from wardrobe.config import Settings; "
        "from wardrobe.db import make_engine, make_sessionmaker; from wardrobe.storage.images import gc_orphans; "
        "s = Settings(data_dir=Path(sys.argv[1])); f = make_sessionmaker(make_engine(s.db_path)); "
        "[gc_orphans(s, f) for _ in range(200)]"
    )
    proc = subprocess.Popen([sys.executable, "-c", script, str(settings.data_dir)], cwd=backend,
                            env={"PYTHONPATH": str(backend), "PATH": "/usr/bin:/bin"})  # fmt: skip
    c = _client(app)
    data = png_bytes(color=(40, 50, 60))
    try:
        while proc.poll() is None:
            r = upload(c, data)
            assert r.status_code in (200, 201), r.text
            c.delete(f"{API}/images/{r.json()['id']}")
            ok(upload(c, data), 201)
            assert _all_image_files_exist(app, settings) == []
    finally:
        proc.wait(timeout=60)
    assert proc.returncode == 0
    assert _all_image_files_exist(app, settings) == []


def test_backup_holds_image_lock(app, settings, client):
    """备份打包期间 GC 不能删除快照引用的文件：备份与 GC 交替进行时备份始终成功。"""
    from wardrobe.storage.backup import create_backup

    ok(upload(client), 201)
    done = threading.Event()

    def collector():
        while not done.is_set():
            gc_orphans(settings, app.state.sessionmaker)

    t = threading.Thread(target=collector)
    t.start()
    try:
        for _ in range(5):
            create_backup(settings, "manual")
    finally:
        done.set()
        t.join()


# ───────────── BUG-010 恢复时重新核对明细商品 ─────────────


def _deleted_item_then_line_reassigned(client, via: str):
    a = make_product(client, identifiers=[], name_ja="商品A")
    b = make_product(client, identifiers=[], name_ja="商品B")
    line = make_purchase(client, a["id"], color_name="BLACK")["lines"][0]
    item_id = line["item_ids"][0]
    ok(client.delete(f"{API}/items/{item_id}", params={"version": 1}), 204)
    if via == "patch":
        ok(client.patch(f"{API}/purchase-lines/{line['id']}", json={"version": 1, "product_id": b["id"],
                                                                     "color_name": "NAVY"}))  # fmt: skip
    else:
        ok(client.post(f"{API}/purchase-lines/{line['id']}/match", json={"version": 1, "product_id": b["id"]}))
    return a, b, line, item_id


def test_restore_rejected_after_line_reassigned_via_patch_or_match(client, app):
    from sqlalchemy import func, select, text

    from wardrobe.models import ChangeLog

    for via in ("patch", "match"):
        _, _, _, item_id = _deleted_item_then_line_reassigned(client, via)
        with app.state.sessionmaker() as s:
            logs_before = s.scalar(select(func.count()).select_from(ChangeLog))
        e = err(client.post(f"{API}/items/{item_id}/restore", json={"version": 2}), 422, "VALIDATION_ERROR")
        assert e["details"][0]["code"] == "product_mismatch"
        err(client.get(f"{API}/items/{item_id}"), 404, "NOT_FOUND")  # 仍是删除状态
        with app.state.sessionmaker() as s:
            assert s.scalar(select(func.count()).select_from(ChangeLog)) == logs_before
            assert s.execute(text("SELECT count(*) FROM search_index WHERE rowid = :i"), {"i": item_id}).scalar() == 0


def test_restore_succeeds_after_line_is_matched_back(client):
    a, _, line, item_id = _deleted_item_then_line_reassigned(client, "patch")
    err(client.post(f"{API}/items/{item_id}/restore", json={"version": 2}), 422, "VALIDATION_ERROR")
    ok(client.patch(f"{API}/purchase-lines/{line['id']}", json={"version": 2, "product_id": a["id"]}))
    out = ok(client.post(f"{API}/items/{item_id}/restore", json={"version": 2}))  # 原 version 仍有效
    assert out["product"]["id"] == a["id"] and out["version"] == 3
    assert out["resolved"]["color"]["name"] == "NAVY" and out["resolved"]["color"]["source"] == "purchase_line"


def test_active_items_always_match_their_line_product(client, app):
    """不变量：活动衣物若关联已匹配的购买明细，两端的商品必须相同。"""
    from sqlalchemy import select

    from wardrobe.models import PurchaseLine, WardrobeItem

    for via in ("patch", "match"):
        _, _, _, item_id = _deleted_item_then_line_reassigned(client, via)
        client.post(f"{API}/items/{item_id}/restore", json={"version": 2})
    p = make_product(client, identifiers=[], name_ja="正常")
    make_purchase(client, p["id"], quantity=2)
    with app.state.sessionmaker() as s:
        bad = s.execute(
            select(WardrobeItem.id)
            .join(PurchaseLine, PurchaseLine.id == WardrobeItem.purchase_line_id)
            .where(
                WardrobeItem.deleted_at.is_(None),
                PurchaseLine.product_id.is_not(None),
                PurchaseLine.product_id != WardrobeItem.product_id,
            )
        ).all()
    assert bad == []
