from itertools import product

from fastapi.testclient import TestClient
from helpers import API, make_product, ok

from wardrobe.config import Settings
from wardrobe.main import create_app


def test_facet_counts_against_independent_detail_oracle(client):
    rows = []
    for n, (brand, color, size, status) in enumerate(
        product(["uniqlo", "gu"], ["black", "navy"], ["M", "L"], ["owned", "returned"])
    ):
        p = make_product(
            client,
            brand=brand,
            name_ja=f"QA架空{n}",
            identifiers=[],
            category="tops-tshirt-short" if brand == "gu" else "outer-light-down",
            material_text="綿100%" if brand == "gu" else "毛100%",
        )
        i = ok(
            client.post(
                API + "/items",
                json={
                    "product_id": p["id"],
                    "color_hex": "#111111" if color == "black" else "#1F2A44",
                    "size_label": size,
                    "tags": ["QA偶数" if n % 2 == 0 else "QA奇数"],
                },
            ),
            201,
        )
        if status == "returned":
            i = ok(
                client.post(
                    f"{API}/items/{i['id']}/return", json={"version": i["version"], "returned_on": "2026-10-26"}
                )
            )
        rows.append(
            {
                "brand": brand,
                "color": color,
                "size": size,
                "status": status,
                "tag": i["tags"][0],
                "material": "cotton" if brand == "gu" else "wool",
            }
        )
    cases = [
        {},
        {"brand": "gu"},
        {"color": "navy,black", "size": "L"},
        {"material": "wool", "status": "all"},
        {"tag": "QA偶数", "brand": "gu"},
        {"status": "returned", "color": "navy", "size": "M"},
        {"brand": "gu", "material": "wool"},
    ]
    for case in cases:
        f = {"status": "owned", **case}
        facets = ok(client.get(API + "/items/facets", params=f))

        def matches(row, skip=None, f=f):
            return all(k == skip or v == "all" or row[k] in v.split(",") for k, v in f.items())

        assert facets["total"] == sum(matches(r) for r in rows) == ok(client.get(API + "/items", params=f))["total"]
        for dim in ["brand", "color", "size", "status", "tag", "material"]:
            expected = {}
            for row in rows:
                if matches(row, dim):
                    expected[row[dim]] = expected.get(row[dim], 0) + 1
            assert facets[dim] == expected, (case, dim, facets[dim], expected)


def test_direct_index_keeps_ui_csp(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<div id=app></div>")
    c = TestClient(
        create_app(Settings(data_dir=tmp_path / "data", frontend_dist=dist)), base_url="http://127.0.0.1:8765"
    )
    assert c.get("/").headers.get("content-security-policy")
    assert c.get("/index.html").headers.get("content-security-policy"), "direct index loses UI CSP"


def test_selected_comma_tag_finds_own_item(client):
    # 原审查复现使用旧 CSV；新版完整值协议显式使用 tag_exact，保留原返回断言。
    p = make_product(client)
    i = ok(client.post(API + "/items", json={"product_id": p["id"], "tags": ["QA,逗号"]}), 201)
    assert ok(client.get(API + "/items/facets"))["tag"] == {"QA,逗号": 1}
    found = ok(client.get(API + "/items", params={"tag_exact": "QA,逗号"}))
    assert [r["id"] for r in found["items"]] == [i["id"]], found


def test_purchase_currency_and_refund_remain_separate(client):
    p = make_product(client, currency="JPY", list_price=999)
    buy = ok(
        client.post(
            API + "/purchases",
            json={
                "purchased_on": "2026-10-26",
                "currency": "USD",
                "create_items": True,
                "lines": [{"product_id": p["id"], "quantity": 1, "unit_price": 50, "discount_amount": 5}],
            },
        ),
        201,
    )
    iid = buy["lines"][0]["item_ids"][0]
    returned = ok(
        client.post(f"{API}/items/{iid}/return", json={"version": 1, "returned_on": "2026-10-26", "refund_amount": 45})
    )
    assert (
        returned["purchase"]["currency"] == "USD"
        and returned["product"]["currency"] == "JPY"
        and returned["refund_amount"] == 45
    )


def test_rejected_response_has_documented_security_headers(client):
    r = client.get(API + "/health", headers={"Origin": "null"})
    assert r.status_code == 403
    assert r.headers.get("x-content-type-options") == "nosniff"
