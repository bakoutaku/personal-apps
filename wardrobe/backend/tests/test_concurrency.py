"""R6：乐观锁与聚合根版本。"""

import threading

from fastapi.testclient import TestClient
from helpers import API, err, get, make_product, make_purchase, ok


def test_missing_version_is_rejected(client):
    p = make_product(client)
    e = err(client.patch(f"{API}/products/{p['id']}", json={"notes": "x"}), 422, "VALIDATION_ERROR")
    assert e["details"][0]["loc"] == ["version"]


def test_stale_version_conflict_reports_current(client):
    p = make_product(client)
    ok(client.patch(f"{API}/products/{p['id']}", json={"version": 1, "notes": "a"}))
    e = err(client.patch(f"{API}/products/{p['id']}", json={"version": 1, "notes": "b"}), 409, "VERSION_CONFLICT")
    assert e["details"][0]["current_version"] == 2
    assert get(client, f"/products/{p['id']}")["notes"] == "a"


def test_if_match_header_is_accepted(client):
    p = make_product(client)
    ok(client.patch(f"{API}/products/{p['id']}", json={"notes": "a"}, headers={"If-Match": '"1"'}))


def test_two_clients_same_version_only_one_wins(client, ai):
    p = make_product(client)
    r1 = client.patch(f"{API}/products/{p['id']}", json={"version": 1, "notes": "人"})
    r2 = ai.patch(f"{API}/products/{p['id']}", json={"version": 1, "notes": "AI"})
    assert sorted([r1.status_code, r2.status_code]) == [200, 409]


def test_concurrent_threads_same_version_only_one_wins(app):
    c = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Wardrobe-Client": "web-ui"})
    p = make_product(c)
    item_id = make_purchase(c, p["id"])["lines"][0]["item_ids"][0]
    results: list[int] = []
    barrier = threading.Barrier(6)

    def worker(n: int):
        cl = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Wardrobe-Client": f"ai:t{n}"})
        barrier.wait()
        results.append(cl.patch(f"{API}/items/{item_id}", json={"version": 1, "notes": f"t{n}"}).status_code)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200] + [409] * 5
    assert get(c, f"/items/{item_id}")["version"] == 2


def test_subcollection_changes_bump_parent_version(client):
    p = make_product(client)
    v = ok(client.put(f"{API}/products/{p['id']}/sizes", json={"version": 1, "sizes": [{"size_label": "S"}]}))
    assert v["version"] == 2
    err(client.put(f"{API}/products/{p['id']}/colors", json={"version": 1, "colors": []}), 409, "VERSION_CONFLICT")

    item_id = make_purchase(client, p["id"])["lines"][0]["item_ids"][0]
    tagged = ok(client.put(f"{API}/items/{item_id}/tags", json={"version": 1, "tags": ["秋冬"]}))
    assert tagged["version"] == 2
    err(client.put(f"{API}/items/{item_id}/tags", json={"version": 1, "tags": []}), 409, "VERSION_CONFLICT")


def test_adding_line_bumps_purchase_version_and_line_has_own_version(client):
    p = make_product(client)
    pur = make_purchase(client, p["id"], create_items=False)
    line = pur["lines"][0]
    added = ok(client.post(f"{API}/purchases/{pur['id']}/lines", json={"version": 1, "product_id": p["id"]}), 201)
    assert added["version"] == 2
    # 修改明细只用明细自己的 version
    ok(client.patch(f"{API}/purchase-lines/{line['id']}", json={"version": 1, "unit_price": 5000}))
    # 删除明细属于购买记录的变化，要用购买记录的 version
    err(client.delete(f"{API}/purchase-lines/{line['id']}", params={"version": 1}), 409, "VERSION_CONFLICT")
    ok(client.delete(f"{API}/purchase-lines/{line['id']}", params={"version": 2}), 204)
    assert get(client, f"/purchases/{pur['id']}")["version"] == 3


def test_outfit_items_replace_needs_outfit_version(client):
    p = make_product(client)
    item_id = make_purchase(client, p["id"])["lines"][0]["item_ids"][0]
    o = ok(client.post(f"{API}/outfits", json={"name": "A"}), 201)
    o2 = ok(client.put(f"{API}/outfits/{o['id']}/items", json={"version": 1, "items": [{"item_id": item_id}]}))
    assert o2["version"] == 2
    err(client.put(f"{API}/outfits/{o['id']}/items", json={"version": 1, "items": []}), 409, "VERSION_CONFLICT")
