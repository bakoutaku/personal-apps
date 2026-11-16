"""导出往返、变更历史、穿着记录、匹配候选。"""

from fastapi.testclient import TestClient
from helpers import API, err, get, make_product, make_purchase, ok
from import_helpers import counts, payload, run_import

from wardrobe.config import Settings
from wardrobe.main import create_app


def _populate(client):
    run_import(client, payload())
    item = ok(client.get(f"{API}/items"))["items"][0]
    ok(client.post(f"{API}/items/{item['id']}/return", json={"version": item["version"], "returned_on": "2025-11-10",
                                                              "refund_amount": 100}))  # fmt: skip


def test_export_reimport_same_db_is_noop(client):
    _populate(client)
    exported = ok(client.get(f"{API}/export"))
    before = counts(client)
    job = run_import(client, exported)
    assert {r["action"] for r in job["rows"]} == {"skip"}, [r for r in job["rows"] if r["action"] != "skip"]
    assert counts(client) == before


def test_portable_export_into_fresh_database(client, tmp_path):
    _populate(client)
    exported = ok(client.get(f"{API}/export", params={"include_ids": False}))
    assert "id" not in exported["products"][0]
    fresh = TestClient(create_app(Settings(data_dir=tmp_path / "fresh")), base_url="http://127.0.0.1:8765",
                       headers={"X-Wardrobe-Client": "cli"})  # fmt: skip
    run_import(fresh, exported)
    keys = ("product", "purchase", "purchase_line", "wardrobe_item", "outfit", "tag")
    assert {k: counts(fresh)[k] for k in keys} == {k: counts(client)[k] for k in keys}

    def shape(c):
        items = ok(c.get(f"{API}/items", params={"status": "all", "sort": "id"}))["items"]
        return sorted((i["name"], i["status"], i["resolved"]["color"]["name"], tuple(i["tags"])) for i in items)

    assert shape(fresh) == shape(client)


def test_changes_endpoint_filters(client):
    p = make_product(client)
    ok(client.patch(f"{API}/products/{p['id']}", json={"version": 1, "notes": "x"}))
    logs = ok(client.get(f"{API}/changes", params={"entity": "product", "entity_id": p["id"]}))
    assert [c["op"] for c in logs["items"]] == ["update", "create"]
    assert logs["items"][0]["after"] == {"notes": "x"}


def test_wear_logging(client, ai):
    p = make_product(client)
    item_id = make_purchase(client, p["id"])["lines"][0]["item_ids"][0]
    ok(client.post(f"{API}/items/{item_id}/verify", json={"version": 1}))
    out = ok(ai.post(f"{API}/items/{item_id}/wear", json={"version": 2, "worn_on": "2025-12-01"}))  # 不受保护
    assert (out["wear_count"], out["last_worn_on"], out["version"]) == (1, "2025-12-01", 3)
    out = ok(ai.post(f"{API}/items/{item_id}/wear", json={"version": 3, "worn_on": "2025-11-20"}))
    assert (out["wear_count"], out["last_worn_on"]) == (2, "2025-12-01")
    err(ai.post(f"{API}/items/{item_id}/wear", json={"version": 4, "worn_on": "2020-01-01"}), 422, "VALIDATION_ERROR")
    sorted_ids = [i["id"] for i in ok(client.get(f"{API}/items", params={"sort": "-wear_count"}))["items"]]
    assert sorted_ids[0] == item_id


def test_match_candidates_same_scheme_and_name(client):
    by_code = make_product(client, identifiers=[{"scheme": "item_no", "value": "777001"}], name_ja="無関係な名前")
    detail_only = make_product(client, identifiers=[{"scheme": "detail_page_id", "value": "E777001-000"}],
                               name_ja="ﾃｽﾄﾀﾞｳﾝｼﾞｬｹｯﾄ")  # fmt: skip
    line = make_purchase(client, None, create_items=False, item_code_raw="777001", name_raw="テストダウンジャケット")[
        "lines"
    ][0]
    out = ok(client.get(f"{API}/purchase-lines/{line['id']}/match-candidates"))
    by_id = {c["product"]["id"]: c for c in out["candidates"]}
    assert by_id[by_code["id"]]["reasons"] == ["identifier:item_no"]
    # 详情页编号 E777001-000 不会因为包含 777001 而被当成编号匹配，只按名称相似出现
    assert by_id[detail_only["id"]]["reasons"][0].startswith("name_similarity:")
    assert get(client, f"/purchase-lines/{line['id']}")["product_match"] == "unmatched"  # 只读
