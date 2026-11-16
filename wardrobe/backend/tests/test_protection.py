"""R4（Phase 2）：受限请求方修改已核实记录的受保护字段 → 202 + 修改提议；记录本身的受保护字段不变。

删除、恢复、删除编号这类破坏性操作不能提议，仍然 409。
"""

import pytest
from fastapi.testclient import TestClient
from helpers import API, err, get, make_product, make_purchase, ok


@pytest.fixture
def verified(client):
    """已核实的商品、购买明细、衣物各一。"""
    p = make_product(client)
    pur = make_purchase(client, p["id"], color_code="69", color_name="NAVY", size_label="L")
    line = pur["lines"][0]
    item_id = line["item_ids"][0]
    ok(client.post(f"{API}/products/{p['id']}/verify", json={"version": 1}))
    ok(client.post(f"{API}/purchase-lines/{line['id']}/verify", json={"version": 1}))
    ok(client.post(f"{API}/items/{item_id}/verify", json={"version": 1}))
    return {"product": p["id"], "purchase": pur["id"], "line": line["id"], "item": item_id}


def _snapshot(client, v):
    return {
        "p": get(client, f"/products/{v['product']}"),
        "l": get(client, f"/purchase-lines/{v['line']}"),
        "i": get(client, f"/items/{v['item']}"),
    }


def test_ai_patch_mixing_protected_and_free_fields(ai, client, verified):
    pid = verified["product"]
    body = ok(
        ai.patch(f"{API}/products/{pid}", json={"version": 2, "material_text": "綿100%", "notes": "AI 备注"}), 202
    )
    assert body["applied"] == ["notes"]
    (prop,) = body["proposed"]
    assert (prop["field"], prop["proposed_value"], prop["status"], prop["actor"]) == (
        "material_text", "綿100%", "pending", "ai:codex",
    )  # fmt: skip
    after = get(client, f"/products/{pid}")
    assert after["notes"] == "AI 备注" and after["material_text"] != "綿100%"
    assert body["record"]["version"] == after["version"] == 3


def test_ai_patch_only_protected_does_not_bump_version(ai, client, verified):
    body = ok(ai.patch(f"{API}/products/{verified['product']}", json={"version": 2, "name_zh": "AI 改名"}), 202)
    assert body["applied"] == [] and body["record"]["version"] == 2


def test_ai_can_edit_unprotected_fields_directly(ai, verified):
    out = ok(ai.patch(f"{API}/products/{verified['product']}", json={"version": 2, "notes": "AI 备注"}))
    assert out["notes"] == "AI 备注" and out["version"] == 3


def test_ai_resending_same_protected_value_is_not_a_change(ai, client, verified):
    current = get(client, f"/products/{verified['product']}")
    ok(ai.patch(f"{API}/products/{verified['product']}", json={"version": 2, "name_ja": current["name_ja"]}))
    assert ok(client.get(f"{API}/proposals"))["total"] == 0


def test_web_ui_and_cli_edit_protected_fields_directly(client, app, verified):
    ok(client.patch(f"{API}/products/{verified['product']}", json={"version": 2, "name_zh": "改名"}))
    cli = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Wardrobe-Client": "cli"})
    ok(cli.patch(f"{API}/products/{verified['product']}", json={"version": 3, "name_zh": "再改"}))
    assert ok(client.get(f"{API}/proposals"))["total"] == 0


def test_unknown_client_name_is_restricted(app, verified):
    other = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Wardrobe-Client": "webui"})
    ok(other.patch(f"{API}/products/{verified['product']}", json={"version": 2, "name_zh": "x"}), 202)


@pytest.mark.parametrize(
    ("method", "path", "body", "field"),
    [
        ("put", "/products/{product}/colors", {"version": 2, "colors": [{"name_ja": "RED"}]}, "colors"),
        ("put", "/products/{product}/sizes", {"version": 2, "sizes": [{"size_label": "XL"}]}, "sizes"),
        ("put", "/products/{product}/materials", {"version": 2, "materials": [{"fiber": "cotton", "percent": 100}]},
         "materials"),
        ("post", "/products/{product}/identifiers", {"version": 2, "scheme": "item_no", "value": "1"}, "identifiers"),
        ("patch", "/purchase-lines/{line}", {"version": 2, "size_label": "M"}, "size"),
        ("patch", "/items/{item}", {"version": 2, "status": "disposed"}, "status"),
        ("post", "/items/{item}/return", {"version": 2, "returned_on": "2025-11-10"}, "status"),
    ],
)  # fmt: skip
def test_proposable_entries_create_proposals_without_change(ai, client, verified, method, path, body, field):
    before = _snapshot(client, verified)
    resp = ok(ai.request(method.upper(), API + path.format(**verified), json=body), 202)
    assert [p["field"] for p in resp["proposed"]] == [field]
    assert _snapshot(client, verified) == before


def test_partial_item_patch_applies_free_fields(ai, client, verified):
    resp = ok(ai.patch(f"{API}/items/{verified['item']}", json={"version": 2, "color_name": "BLACK", "location": "衣柜"}),
              202)  # fmt: skip
    assert resp["applied"] == ["location"]
    (prop,) = resp["proposed"]
    assert prop["field"] == "color"  # 颜色组整体提议
    assert prop["current_value"] == {"color_code": None, "color_name": None, "color_hex": None}
    assert prop["proposed_value"] == {"color_code": None, "color_name": "BLACK", "color_hex": None}
    item = get(client, f"/items/{verified['item']}")
    assert item["location"] == "衣柜" and item["resolved"]["color"]["name"] == "NAVY"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("delete", "/products/{product}?version=2"),
        ("delete", "/purchase-lines/{line}?version=1"),
        ("delete", "/items/{item}?version=2"),
    ],
)
def test_destructive_operations_stay_forbidden(ai, client, verified, method, path):
    before = _snapshot(client, verified)
    err(ai.request(method.upper(), API + path.format(**verified)), 409, "VERIFIED_PROTECTED")
    assert _snapshot(client, verified) == before
    assert ok(client.get(f"{API}/proposals"))["total"] == 0


def test_identifier_delete_stays_forbidden(ai, client, verified):
    ident = get(client, f"/products/{verified['product']}")["identifiers"][0]
    err(ai.delete(f"{API}/products/{verified['product']}/identifiers/{ident['id']}", params={"version": 2}), 409,
        "VERIFIED_PROTECTED")  # fmt: skip


def test_match_to_other_product_becomes_proposal(ai, client, verified):
    other = make_product(client, identifiers=[], name_ja="別商品")
    resp = ok(ai.post(f"{API}/purchase-lines/{verified['line']}/match",
                      json={"version": 2, "product_id": other["id"]}), 202)  # fmt: skip
    assert resp["proposed"][0]["field"] == "match"
    assert get(client, f"/purchase-lines/{verified['line']}")["product_id"] == verified["product"]


def test_ai_can_tag_and_annotate_verified_item(ai, verified):
    out = ok(ai.put(f"{API}/items/{verified['item']}/tags", json={"version": 2, "tags": ["通勤"]}))
    out = ok(ai.patch(f"{API}/items/{verified['item']}", json={"version": out["version"], "location": "卧室衣柜"}))
    assert out["tags"] == ["通勤"] and out["location"] == "卧室衣柜"


def test_ai_cannot_verify_or_unverify(ai, client):
    p = make_product(client)
    err(ai.post(f"{API}/products/{p['id']}/verify", json={"version": 1}), 403, "PRIVILEGED_ONLY")
    ok(client.post(f"{API}/products/{p['id']}/verify", json={"version": 1}))
    err(ai.post(f"{API}/products/{p['id']}/unverify", json={"version": 2}), 403, "PRIVILEGED_ONLY")


def test_unverified_records_are_freely_editable_by_ai(ai, client):
    p = make_product(client)
    ok(ai.patch(f"{API}/products/{p['id']}", json={"version": 1, "material_text": "綿100%"}))
    assert ok(client.get(f"{API}/proposals"))["total"] == 0
