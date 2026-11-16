"""修改提议的接受、拒绝、过期、取代与批量处理。"""

import pytest
from helpers import API, err, get, make_product, make_purchase, ok


@pytest.fixture
def verified(client):
    p = make_product(client)
    pur = make_purchase(client, p["id"], quantity=2, color_code="69", color_name="NAVY", size_label="L")
    line = pur["lines"][0]
    item_id = line["item_ids"][0]
    ok(client.post(f"{API}/products/{p['id']}/verify", json={"version": 1}))
    ok(client.post(f"{API}/purchase-lines/{line['id']}/verify", json={"version": 1}))
    ok(client.post(f"{API}/items/{item_id}/verify", json={"version": 1}))
    return {"product": p["id"], "line": line["id"], "item": item_id}


def _propose(ai, path, body):
    return ok(ai.request("PATCH" if "proposals" not in path else "POST", API + path, json=body), 202)["proposed"][0]


def test_accept_applies_change_and_logs_proposal_id(ai, client, app, verified):
    prop = _propose(ai, f"/products/{verified['product']}", {"version": 2, "material_text": "綿100%"})
    out = ok(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"))
    assert out["status"] == "accepted" and out["decided_at"]
    product = get(client, f"/products/{verified['product']}")
    assert product["material_text"] == "綿100%"
    assert [(m["fiber"], m["percent"]) for m in product["materials"]] != []  # 材质原文更新，结构保持原样
    from sqlalchemy import select

    from wardrobe.models import ChangeLog

    with app.state.sessionmaker() as s:
        log = s.scalars(select(ChangeLog).where(ChangeLog.proposal_id == prop["proposal_id"])).one()
    assert (log.actor, log.after) == ("web-ui", {"material_text": "綿100%"})


def test_reject_changes_nothing(ai, client, verified):
    prop = _propose(ai, f"/products/{verified['product']}", {"version": 2, "name_zh": "AI 改名"})
    before = get(client, f"/products/{verified['product']}")
    assert ok(client.post(f"{API}/proposals/{prop['proposal_id']}/reject"))["status"] == "rejected"
    assert get(client, f"/products/{verified['product']}") == before
    err(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"), 409, "PROPOSAL_NOT_PENDING")


def test_ai_cannot_decide(ai, verified):
    prop = _propose(ai, f"/products/{verified['product']}", {"version": 2, "name_zh": "AI 改名"})
    err(ai.post(f"{API}/proposals/{prop['proposal_id']}/accept"), 403, "PRIVILEGED_ONLY")
    err(ai.post(f"{API}/proposals/{prop['proposal_id']}/reject"), 403, "PRIVILEGED_ONLY")


def test_stale_proposal_is_not_applied(ai, client, verified):
    prop = _propose(ai, f"/products/{verified['product']}", {"version": 2, "name_zh": "AI 改名"})
    ok(client.patch(f"{API}/products/{verified['product']}", json={"version": 2, "name_zh": "人工改名"}))
    err(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"), 409, "PROPOSAL_STALE")
    assert get(client, f"/products/{verified['product']}")["name_zh"] == "人工改名"
    assert get(client, f"/proposals/{prop['proposal_id']}")["status"] == "pending"


def test_newer_proposal_supersedes_older(ai, client, verified):
    first = _propose(ai, f"/products/{verified['product']}", {"version": 2, "name_zh": "一"})
    second = _propose(ai, f"/products/{verified['product']}", {"version": 2, "name_zh": "二"})
    assert get(client, f"/proposals/{first['proposal_id']}")["status"] == "superseded"
    assert get(client, f"/proposals/{second['proposal_id']}")["status"] == "pending"
    assert [p["proposal_id"] for p in ok(client.get(f"{API}/proposals"))["items"]] == [second["proposal_id"]]


def test_group_proposal_applies_whole_group(ai, client, verified):
    prop = _propose(ai, f"/items/{verified['item']}", {"version": 2, "color_name": "OLIVE", "color_hex": "#556B2F"})
    ok(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"))
    item = get(client, f"/items/{verified['item']}")
    assert item["resolved"]["color"] == {"code": None, "name": "OLIVE", "hex": "#556B2F", "family": "green",
                                         "source": "item"}  # fmt: skip


def test_collection_and_identifier_proposals(ai, client, verified):
    pid = verified["product"]
    colors = ok(ai.put(f"{API}/products/{pid}/colors", json={"version": 2, "colors": [
        {"color_code": "09", "name_ja": "BLACK", "hex": "#1A1A1A"},
        {"color_code": "69", "name_ja": "NAVY", "hex": "#1F2A44", "is_default": True},
    ]}), 202)["proposed"][0]  # fmt: skip
    ident = ok(ai.post(f"{API}/products/{pid}/identifiers", json={"version": 2, "scheme": "item_no", "value": "999001"}),
               202)["proposed"][0]  # fmt: skip
    ok(client.post(f"{API}/proposals/{colors['proposal_id']}/accept"))
    ok(client.post(f"{API}/proposals/{ident['proposal_id']}/accept"))
    product = get(client, f"/products/{pid}")
    assert [c["is_default"] for c in product["colors"]] == [False, True]
    assert ("item_no", "999001") in {(i["scheme"], i["value"]) for i in product["identifiers"]}


def test_invalid_collection_is_rejected_before_proposing(ai, client, verified):
    body = {"version": 2, "colors": [{"name_ja": "A", "is_default": True}, {"name_ja": "B", "is_default": True}]}
    err(ai.put(f"{API}/products/{verified['product']}/colors", json=body), 422, "VALIDATION_ERROR")
    assert ok(client.get(f"{API}/proposals"))["total"] == 0


def test_return_proposal_accept_returns_item(ai, client, verified):
    prop = ok(ai.post(f"{API}/items/{verified['item']}/return",
                      json={"version": 2, "returned_on": "2025-11-10", "refund_amount": 7990}), 202)["proposed"][0]  # fmt: skip
    assert prop["proposed_value"] == {"status": "returned", "retired_on": "2025-11-10", "refund_amount": 7990}
    ok(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"))
    item = get(client, f"/items/{verified['item']}")
    assert (item["status"], item["refund_amount"]) == ("returned", 7990)


def test_accept_reruns_validation(ai, client, verified):
    """接受时重新执行全部校验：明细数量已被占满时，改关联的提议不能生效。"""
    other_line = make_purchase(client, verified["product"], quantity=1)["lines"][0]  # 已有 1 件，满
    prop = _propose(ai, f"/items/{verified['item']}", {"version": 2, "purchase_line_id": other_line["id"]})
    err(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"), 409, "LINE_FULL")
    assert get(client, f"/proposals/{prop['proposal_id']}")["status"] == "pending"
    assert get(client, f"/items/{verified['item']}")["purchase_line_id"] == verified["line"]


def test_bulk_decisions_are_independent(ai, client, verified):
    a = _propose(ai, f"/products/{verified['product']}", {"version": 2, "name_zh": "批量一"})
    b = _propose(ai, f"/products/{verified['product']}", {"version": 2, "material_text": "綿100%"})
    c = _propose(ai, f"/items/{verified['item']}", {"version": 2, "size_label": "XL"})
    ok(client.patch(f"{API}/items/{verified['item']}", json={"version": 2, "size_label": "S"}))  # 使 c 过期
    res = ok(client.post(f"{API}/proposals/bulk",
                         json={"ids": [a["proposal_id"], b["proposal_id"], c["proposal_id"]], "decision": "accept"}))  # fmt: skip
    assert (res["succeeded"], res["failed"]) == (2, 1)
    assert res["results"][2]["error"]["code"] == "PROPOSAL_STALE"
    product = get(client, f"/products/{verified['product']}")
    assert (product["name_zh"], product["material_text"]) == ("批量一", "綿100%")
    assert get(client, f"/items/{verified['item']}")["resolved"]["size"]["label"] == "S"


def test_line_match_proposal(ai, client, verified):
    other = make_product(client, identifiers=[], name_ja="別商品")
    # 明细已生成衣物（属于原商品），接受改配会因为衣物商品不一致被拒绝
    prop = ok(ai.post(f"{API}/purchase-lines/{verified['line']}/match",
                      json={"version": 2, "product_id": other["id"]}), 202)["proposed"][0]  # fmt: skip
    err(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"), 409, "IN_USE")
