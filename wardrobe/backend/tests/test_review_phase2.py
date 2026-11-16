"""GPT Phase 2 审查（docs/REVIEW_PHASE2_2026-10-26.md）的独立复现测试，原样保留预期行为作为回归用例。"""

import pytest
from fastapi.testclient import TestClient

from wardrobe.config import Settings
from wardrobe.main import create_app

API = "/api/v1"
FORMAT = "wardrobe.import/v1"


@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=tmp_path / "data")
    app = create_app(s)
    c = TestClient(
        app, base_url="http://127.0.0.1:8765", headers={"X-Wardrobe-Client": "web-ui"}, raise_server_exceptions=False
    )
    yield s, app, c
    c.close()
    app.state.engine.dispose()


def post(c, path, data=None, expected=(200, 201)):
    r = c.post(API + path, json=data)
    assert r.status_code in expected, (r.status_code, r.text)
    return r.json()


def product(c, **extra):
    return post(c, "/products", {"name_ja": "QA item", **extra})


def run(c, payload):
    job = post(c, "/imports", payload)
    assert job["can_commit"], job
    return post(c, f"/imports/{job['job_id']}/commit")


def test_commit_rejects_stale_field_values_even_when_action_stays_update(env):
    _, _, c = env
    p = product(c, notes="preview original")
    preview = post(c, "/imports", {"format": FORMAT, "products": [{"id": p["id"], "notes": "import value"}]})
    r = c.patch(API + f"/products/{p['id']}", json={"version": 1, "notes": "human changed after preview"})
    assert r.status_code == 200, r.text
    commit = c.post(API + f"/imports/{preview['job_id']}/commit")
    after = c.get(API + f"/products/{p['id']}").json()
    assert commit.status_code == 409 and after["notes"] == "human changed after preview", {
        "commit_http": commit.status_code,
        "notes_after": after["notes"],
    }


def test_no_order_purchase_preview_accepts_valid_mixed_optional_line_fields(env):
    _, _, c = env
    p = product(c)
    body = {
        "format": FORMAT,
        "purchases": [
            {
                "purchased_on": "2026-01-01",
                "store_name": "QA store",
                "lines": [{"product_id": p["id"], "color_name": "BLACK"}, {"product_id": p["id"]}],
            }
        ],
    }
    r = c.post(API + "/imports", json=body)
    assert r.status_code == 201, (r.status_code, r.text)
    assert r.json()["can_commit"], r.text


def test_no_order_matching_does_not_overwrite_different_discount_purchase(env):
    _, _, c = env
    p = product(c)
    original = post(
        c,
        "/purchases",
        {
            "purchased_on": "2026-01-01",
            "store_name": "QA store",
            "lines": [{"product_id": p["id"], "quantity": 1, "unit_price": 1000, "discount_amount": 0}],
        },
    )
    run(
        c,
        {
            "format": FORMAT,
            "purchases": [
                {
                    "purchased_on": "2026-01-01",
                    "store_name": "QA store",
                    "lines": [{"product_id": p["id"], "quantity": 1, "unit_price": 1000, "discount_amount": 100}],
                }
            ],
        },
    )
    after = c.get(API + f"/purchases/{original['id']}").json()
    count = c.get(API + "/purchases").json()["total"]
    assert after["lines"][0]["discount_amount"] == 0 and count == 2, {
        "original_discount": after["lines"][0]["discount_amount"],
        "purchase_count": count,
    }


def test_import_existing_item_applies_explicit_new_purchase_line_id(env):
    _, _, c = env
    p = product(c)

    def purchase():
        return post(c, "/purchases", {"purchased_on": "2026-01-01", "lines": [{"product_id": p["id"], "quantity": 1}]})

    a, b = purchase(), purchase()
    la, lb = a["lines"][0]["id"], b["lines"][0]["id"]
    item = post(c, "/items", {"product_id": p["id"], "purchase_line_id": la})
    run(c, {"format": FORMAT, "items": [{"id": item["id"], "purchase_line_id": lb}]})
    after = c.get(API + f"/items/{item['id']}").json()
    assert after["purchase_line_id"] == lb, {"requested_line": lb, "actual_line": after["purchase_line_id"]}


def test_import_revert_does_not_delete_later_added_purchase_lines(env):
    _, _, c = env
    p = product(c)
    job = run(
        c,
        {
            "format": FORMAT,
            "purchases": [{"purchased_on": "2026-01-01", "order_no": "QA-1", "lines": [{"product_id": p["id"]}]}],
        },
    )
    pur = c.get(API + "/purchases").json()["items"][0]
    post(
        c,
        f"/purchases/{pur['id']}/lines",
        {"version": pur["version"], "product_id": p["id"], "name_raw": "later human line"},
    )
    r = c.post(API + f"/imports/{job['job_id']}/revert")
    assert r.status_code == 409, r.text
    assert len(c.get(API + f"/purchases/{pur['id']}").json()["lines"]) == 2


def test_verified_proposal_and_nonprotected_field_contract(env):
    _, _, c = env
    p = product(c)
    verified = post(c, f"/products/{p['id']}/verify", {"version": 1})
    r = c.patch(
        API + f"/products/{p['id']}",
        headers={"X-Wardrobe-Client": "ai:qa"},
        json={"version": verified["version"], "name_ja": "AI proposed", "notes": "AI note"},
    )
    assert r.status_code == 202, r.text
    after = c.get(API + f"/products/{p['id']}").json()
    assert after["name_ja"] == "QA item" and after["notes"] == "AI note"
    prop = r.json()["proposed"][0]
    post(c, f"/proposals/{prop['proposal_id']}/accept")
    assert c.get(API + f"/products/{p['id']}").json()["name_ja"] == "AI proposed"


def test_import_proposes_all_identifier_additions_together(env):
    _, _, c = env
    p = product(c)
    post(c, f"/products/{p['id']}/verify", {"version": 1})
    wanted = [{"scheme": "item_no", "value": "QA-111"}, {"scheme": "sku", "value": "QA-222"}]
    job = run(c, {"format": FORMAT, "products": [{"id": p["id"], "identifiers": wanted}]})
    props = c.get(API + "/proposals", params={"import_job_id": job["job_id"], "status": "pending"}).json()["items"]
    for prop in props:
        post(c, f"/proposals/{prop['proposal_id']}/accept")
    actual = c.get(API + f"/products/{p['id']}").json()["identifiers"]
    assert {(x["scheme"], x["value"]) for x in actual} == {(x["scheme"], x["value"]) for x in wanted}, {
        "wanted": wanted,
        "actual": actual,
        "pending_proposal_count": len(props),
    }
