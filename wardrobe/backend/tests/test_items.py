"""衣物：颜色/尺寸取值（R1）、退货（BUG-002 / R5）、购买记录生成衣物。"""

import pytest
from helpers import API, err, get, make_product, make_purchase, ok


def _item(client, item_id):
    return get(client, f"/items/{item_id}")


# ───────────── R1 取值优先级 ─────────────


def test_purchase_color_and_size_override_product_defaults(client):
    p = make_product(client)
    pur = make_purchase(client, p["id"], color_code="69", color_name="NAVY", color_hex="#1F2A44", size_label="L")
    item = _item(client, pur["lines"][0]["item_ids"][0])
    assert item["resolved"]["color"] == {"code": "69", "name": "NAVY", "hex": "#1F2A44", "family": "navy",
                                         "source": "purchase_line"}  # fmt: skip
    assert item["resolved"]["size"]["label"] == "L" and item["resolved"]["size"]["source"] == "purchase_line"


def test_falls_back_to_product_default_color_when_purchase_has_none(client):
    p = make_product(client, sizes=[{"size_label": "FREE", "size_system": "free"}])
    pur = make_purchase(client, p["id"])
    item = _item(client, pur["lines"][0]["item_ids"][0])
    assert item["resolved"]["color"]["name"] == "BLACK"
    assert item["resolved"]["color"]["source"] == "product_default"
    # 商品只有一个尺码时才回退为默认尺码
    assert item["resolved"]["size"] == {"label": "FREE", "system": "free", "source": "product_default"}


def test_multiple_sizes_do_not_produce_a_guessed_size(client):
    p = make_product(client)
    item = _item(client, make_purchase(client, p["id"])["lines"][0]["item_ids"][0])
    assert item["resolved"]["size"] == {"label": None, "system": None, "source": None}


def test_color_group_never_mixes_sources(client):
    p = make_product(client)
    # 购买明细只有颜色名、没有 HEX：不能从商品默认色借 HEX
    pur = make_purchase(client, p["id"], color_name="NAVY")
    item = _item(client, pur["lines"][0]["item_ids"][0])
    assert item["resolved"]["color"] == {"code": None, "name": "NAVY", "hex": None, "family": None,
                                         "source": "purchase_line"}  # fmt: skip


def test_item_manual_value_wins(client):
    p = make_product(client)
    pur = make_purchase(client, p["id"], color_code="69", color_name="NAVY", color_hex="#1F2A44")
    item_id = pur["lines"][0]["item_ids"][0]
    out = ok(
        client.patch(f"{API}/items/{item_id}", json={"version": 1, "color_name": "褪色藏青", "color_hex": "#3A4560"})
    )
    assert out["resolved"]["color"]["source"] == "item"
    assert out["resolved"]["color"]["code"] is None  # 整组取自衣物，不混用明细的 code


def test_upstream_default_change_recomputes_items_without_bumping_version(client, app):
    from sqlalchemy import select

    from wardrobe.models import ChangeLog

    p = make_product(client)
    item_id = make_purchase(client, p["id"])["lines"][0]["item_ids"][0]
    assert _item(client, item_id)["resolved"]["color"]["name"] == "BLACK"
    ok(client.put(f"{API}/products/{p['id']}/colors", json={"version": 1, "colors": [
        {"color_code": "09", "name_ja": "BLACK", "hex": "#1A1A1A"},
        {"color_code": "69", "name_ja": "NAVY", "hex": "#1F2A44", "is_default": True},
    ]}))  # fmt: skip
    item = _item(client, item_id)
    assert item["resolved"]["color"]["name"] == "NAVY" and item["resolved"]["color"]["family"] == "navy"
    assert item["version"] == 1
    with app.state.sessionmaker() as s:
        log = s.scalars(select(ChangeLog).where(ChangeLog.entity == "wardrobe_item", ChangeLog.actor == "system")).one()
    assert log.after["eff_color_name"] == "NAVY" and log.after["triggered_by"] == "web-ui"


def test_purchase_line_change_recomputes_items(client):
    p = make_product(client)
    line = make_purchase(client, p["id"], color_name="NAVY", size_label="L")["lines"][0]
    ok(client.patch(f"{API}/purchase-lines/{line['id']}", json={"version": 1, "size_label": "XL"}))
    assert _item(client, line["item_ids"][0])["resolved"]["size"]["label"] == "XL"


# ───────────── 购买 → 衣物 ─────────────


def test_quantity_two_creates_two_independent_items(client):
    p = make_product(client)
    pur = make_purchase(client, p["id"], quantity=2)
    ids = pur["lines"][0]["item_ids"]
    assert len(ids) == 2 and ids[0] != ids[1]
    assert _item(client, ids[0])["acquired_on"] == "2025-11-03"


def test_create_items_requires_product(client):
    resp = client.post(f"{API}/purchases", json={"purchased_on": "2025-11-03", "create_items": True,
                                                  "lines": [{"name_raw": "謎の服"}]})  # fmt: skip
    e = err(resp, 422, "VALIDATION_ERROR")
    assert e["details"][0]["loc"] == ["lines", 0, "product_id"]
    assert ok(client.get(f"{API}/purchases"))["total"] == 0


def test_unmatched_line_keeps_raw_code_and_can_be_matched_later(client):
    p = make_product(client)
    pur = make_purchase(client, None, create_items=False, item_code_raw="999001", name_raw="ﾃｽﾄﾀﾞｳﾝ")
    line = pur["lines"][0]
    assert line["product_match"] == "unmatched" and line["item_code_raw"] == "999001"
    matched = ok(client.post(f"{API}/purchase-lines/{line['id']}/match", json={"version": 1, "product_id": p["id"]}))
    assert matched["product_match"] == "confirmed" and matched["item_code_raw"] == "999001"


def test_duplicate_order_number(client):
    body = {"purchased_on": "2025-11-03", "store_name": "测试店", "order_no": "R-1"}
    ok(client.post(f"{API}/purchases", json=body), 201)
    err(client.post(f"{API}/purchases", json=body), 409, "DUPLICATE")
    ok(client.post(f"{API}/purchases", json={**body, "store_name": "别的店"}), 201)


def test_item_product_must_match_line_product(client):
    a = make_product(client)
    b = make_product(client, identifiers=[], name_ja="別")
    line = make_purchase(client, a["id"], create_items=False)["lines"][0]
    resp = client.post(f"{API}/items", json={"product_id": b["id"], "purchase_line_id": line["id"]})
    assert err(resp, 422, "VALIDATION_ERROR")["details"][0]["code"] == "product_mismatch"


def test_inline_product_creates_manual_product(client):
    out = ok(client.post(f"{API}/items", json={"product": {"name_zh": "旧T恤", "category": "tops-tshirt-short"},
                                                 "color_name": "白", "color_hex": "#FFFFFF", "tags": ["家居"]}), 201)  # fmt: skip
    assert out["product"]["origin"] == "manual"
    assert out["resolved"]["color"]["family"] == "white" and out["tags"] == ["家居"]


# ───────────── BUG-002 退货 ─────────────


def test_return_one_of_two_keeps_purchase_history(client):
    p = make_product(client)
    pur = make_purchase(client, p["id"], quantity=2, color_name="NAVY")
    line = pur["lines"][0]
    first, second = line["item_ids"]
    out = ok(client.post(f"{API}/items/{first}/return",
                         json={"version": 1, "returned_on": "2025-11-10", "refund_amount": 7990}))  # fmt: skip
    assert (out["status"], out["retired_on"], out["refund_amount"]) == ("returned", "2025-11-10", 7990)
    assert _item(client, second)["status"] == "owned"

    after = get(client, f"/purchases/{pur['id']}")
    assert after["version"] == pur["version"]
    assert after["lines"][0]["quantity"] == 2 and after["lines"][0]["returned_quantity"] == 1
    assert after["lines"][0]["unit_price"] == 7990

    owned = ok(client.get(f"{API}/items"))
    assert [i["id"] for i in owned["items"]] == [second]
    assert {i["id"] for i in ok(client.get(f"{API}/items", params={"status": "all"}))["items"]} == {first, second}


def test_return_validation(client):
    p = make_product(client)
    item_id = make_purchase(client, p["id"])["lines"][0]["item_ids"][0]
    e = err(client.post(f"{API}/items/{item_id}/return", json={"version": 1, "returned_on": "2025-10-01"}), 422,
            "VALIDATION_ERROR")  # fmt: skip
    assert e["details"][0]["code"] == "before_acquired"
    err(client.post(f"{API}/items/{item_id}/return", json={"version": 1, "returned_on": "2025-13-40"}), 422,
        "VALIDATION_ERROR")  # fmt: skip
    err(client.post(f"{API}/items/{item_id}/return", json={"version": 1, "returned_on": "2025-11-10",
                                                           "refund_amount": -1}), 422, "VALIDATION_ERROR")  # fmt: skip
    ok(client.post(f"{API}/items/{item_id}/return", json={"version": 1, "returned_on": "2025-11-10"}))
    err(client.post(f"{API}/items/{item_id}/return", json={"version": 2, "returned_on": "2025-11-10"}), 409,
        "ALREADY_RETURNED")  # fmt: skip


def test_refund_requires_returned_status(client):
    p = make_product(client)
    item_id = make_purchase(client, p["id"])["lines"][0]["item_ids"][0]
    e = err(client.patch(f"{API}/items/{item_id}", json={"version": 1, "refund_amount": 100}), 422, "VALIDATION_ERROR")
    assert e["details"][0]["code"] == "requires_returned"
    ok(
        client.post(
            f"{API}/items/{item_id}/return", json={"version": 1, "returned_on": "2025-11-10", "refund_amount": 1}
        )
    )
    # 改回 owned 必须同时清空退款
    err(client.patch(f"{API}/items/{item_id}", json={"version": 2, "status": "owned"}), 422, "VALIDATION_ERROR")
    out = ok(client.patch(f"{API}/items/{item_id}", json={"version": 2, "status": "owned", "refund_amount": None}))
    assert out["status"] == "owned" and out["refund_amount"] is None


def test_returned_item_stays_in_outfit_history(client):
    p = make_product(client)
    item_id = make_purchase(client, p["id"])["lines"][0]["item_ids"][0]
    outfit = ok(client.post(f"{API}/outfits", json={"name": "通勤", "items": [{"item_id": item_id, "slot": "outer"}]}),
                201)  # fmt: skip
    ok(client.post(f"{API}/items/{item_id}/return", json={"version": 1, "returned_on": "2025-11-10"}))
    after = get(client, f"/outfits/{outfit['id']}")
    assert after["items"][0]["item"]["status"] == "returned"


def test_new_item_cannot_start_as_returned(client):
    p = make_product(client)
    err(client.post(f"{API}/items", json={"product_id": p["id"], "status": "returned"}), 422, "VALIDATION_ERROR")


# ───────────── 删除与恢复 ─────────────


def test_soft_delete_and_restore(client):
    p = make_product(client)
    item_id = make_purchase(client, p["id"])["lines"][0]["item_ids"][0]
    ok(client.delete(f"{API}/items/{item_id}", params={"version": 1}), 204)
    err(client.get(f"{API}/items/{item_id}"), 404, "NOT_FOUND")
    assert ok(client.get(f"{API}/items", params={"q": "テスト"}))["total"] == 0
    out = ok(client.post(f"{API}/items/{item_id}/restore", json={"version": 2}))
    assert out["version"] == 3
    assert ok(client.get(f"{API}/items", params={"q": "テスト"}))["total"] == 1


@pytest.mark.parametrize("status", ["disposed", "sold", "given_away", "lost"])
def test_status_changes_keep_item(client, status):
    p = make_product(client)
    item_id = make_purchase(client, p["id"])["lines"][0]["item_ids"][0]
    ok(client.patch(f"{API}/items/{item_id}", json={"version": 1, "status": status, "retired_on": "2026-01-01"}))
    assert ok(client.get(f"{API}/items", params={"status": status}))["total"] == 1
