"""试用反馈：颜色圆点按颜色名称 / 色号显示示意色，衣橱总览一次列出全部衣物。全部为虚构数据。"""

import pytest
from fastapi.testclient import TestClient
from helpers import API, get, make_product, ok

from wardrobe.services.colors import display_swatch

# ───────────── 颜色名称 → 颜色族、示意色 ─────────────


@pytest.mark.parametrize(
    ("name", "hex_"),
    [
        ("BLACK", "#1C1C1C"),
        ("off  white", "#F2EEE3"),
        ("ＮＡＴＵＲＡＬ", "#E8DCC6"),
        ("DARK GRAY", "#4A4A4A"),
        ("ネイビー", "#1F2A44"),
        ("藏青", "#1F2A44"),
    ],
)
def test_swatch_from_colour_name_in_any_writing(name, hex_):
    assert display_swatch(None, name, None, None) == {"hex": hex_, "source": "name"}


def test_swatch_prefers_a_real_hex_value():
    assert display_swatch("#123456", "BLACK", "09", "uniqlo") == {"hex": "#123456", "source": "hex"}


def test_swatch_from_name_and_uniqlo_code_shade():
    light, dark = (display_swatch(None, "BLUE", code, "uniqlo") for code in ("61", "68"))
    assert light["source"] == dark["source"] == "name_code"
    assert light["hex"] != dark["hex"]
    lum = [sum(int(s["hex"][i : i + 2], 16) for i in (1, 3, 5)) for s in (light, dark)]
    assert lum[0] > lum[1]  # 个位越大越深
    assert display_swatch(None, "BLACK", "09", "uniqlo") == {"hex": "#1C1C1C", "source": "name"}  # 固定色不调


@pytest.mark.parametrize(
    ("code", "brand"),
    [("61", "other-brand"), ("61", None), ("31", "uniqlo"), ("6", "uniqlo"), ("6A", "gu"), (None, "gu")],
)
def test_code_shade_only_for_uniqlo_gu_codes_of_the_same_colour_group(code, brand):
    # 其他品牌、色号与颜色名不在同一色系（31 是米色系）、色号不是两位数字：只用名称的基准色
    assert display_swatch(None, "BLUE", code, brand) == {"hex": "#4B78B5", "source": "name"}


def test_unknown_name_has_no_swatch():
    assert display_swatch(None, "91", "91", "uniqlo") == {"hex": None, "source": None}


# ───────────── 衣物：颜色族与示意色 ─────────────


def no_hex_item(client, color_code, color_name, **product):
    p = make_product(client, identifiers=[], colors=[], **product)
    return ok(
        client.post(f"{API}/items", json={"product_id": p["id"], "color_code": color_code, "color_name": color_name}),
        201,
    )


def test_item_without_hex_gets_a_display_swatch_but_no_hex_or_family(client):
    item = no_hex_item(client, "08", "DARK GRAY")
    detail = get(client, f"/items/{item['id']}")
    # 颜色值、颜色族都不由名称推算（R7 不变），只多一个显示用的示意色
    assert detail["resolved"]["color"] == {
        "code": "08", "name": "DARK GRAY", "hex": None, "family": None, "source": "item",
    }  # fmt: skip
    assert detail["color_swatch"] == {"hex": "#4A4A4A", "source": "name"}
    assert get(client, "/items")["items"][0]["color_swatch"] == {"hex": "#4A4A4A", "source": "name"}
    assert get(client, "/items/facets")["color"] == {}


def test_real_hex_wins_for_the_swatch(client):
    p = make_product(client, identifiers=[], colors=[])
    a = ok(
        client.post(f"{API}/items", json={"product_id": p["id"], "color_name": "BLACK", "color_hex": "#F5F5F5"}), 201
    )
    assert a["resolved"]["color"]["family"] == "white"
    assert a["color_swatch"] == {"hex": "#F5F5F5", "source": "hex"}


def test_other_brand_uses_the_base_colour_without_code_shade(client):
    ok(client.post(f"{API}/brands", json={"slug": "other-brand", "name": "Other"}), 201)
    item = no_hex_item(client, "61", "BLUE", brand="other-brand")
    assert get(client, f"/items/{item['id']}")["color_swatch"] == {"hex": "#4B78B5", "source": "name"}


# ───────────── 衣橱总览 ─────────────


def test_overview_lists_every_owned_item_with_all_fields_unpaged(client):
    p = make_product(
        client,
        identifiers=[{"scheme": "item_no", "value": "470001"}],
        name_ja="テストダウン",
        name_zh="测试羽绒",
        category="outer-light-down",
        colors=[],
    )
    season = ok(client.post(f"{API}/tags", json={"name": "冬", "kind": "season"}), 201)
    first = ok(
        client.post(
            f"{API}/items",
            json={"product_id": p["id"], "color_code": "69", "color_name": "NAVY", "size_label": "M",
                  "tags": [season["name"], "通勤"]},
        ),
        201,
    )  # fmt: skip
    for _ in range(60):  # 超过列表默认的每页件数
        ok(client.post(f"{API}/items", json={"product_id": p["id"]}), 201)
    ok(client.post(f"{API}/items", json={"product_id": p["id"], "status": "wishlist"}), 201)

    data = get(client, "/items/overview")
    assert data["total"] == len(data["items"]) == 61  # 只含持有中，不分页
    row = next(r for r in data["items"] if r["id"] == first["id"])
    assert row["name_ja"] == "テストダウン"
    assert row["name_zh"] == "测试羽绒"
    assert row["brand"] == "UNIQLO"
    assert row["item_no"] == "470001"
    assert row["category"]["path"][-1] == "轻羽绒"
    assert (row["color"]["name"], row["color"]["code"], row["color"]["swatch"]) == ("NAVY", "69", "#1F2A44")
    assert row["size"]["label"] == "M"
    assert row["material_text"] == "表地:ナイロン100%／詰め物:ダウン90%・フェザー10%"
    assert [(m["part"], m["fiber"], m["percent"]) for m in row["materials"]] == [
        ("shell", "nylon", 100),
        ("fill", "down", 90),
        ("fill", "feather", 10),
    ]
    assert row["seasons"] == ["冬"]
    assert set(row["tags"]) == {"通勤", "冬"}
    assert get(client, "/items/overview?status=all")["total"] == 62


def test_overview_is_sorted_by_category_tree_then_name_with_uncategorized_last(client):
    def item(name, category):
        p = make_product(client, identifiers=[], name_ja=name, name_zh=None, category=category, colors=[])
        return ok(client.post(f"{API}/items", json={"product_id": p["id"]}), 201)["id"]

    loose = item("あ未分類", None)
    pants = item("パンツ", "bottoms")
    tee_b = item("Tシャツ B", "tops-tshirt-short")
    tee_a = item("Tシャツ A", "tops-tshirt-short")
    assert [r["id"] for r in get(client, "/items/overview")["items"]] == [tee_a, tee_b, pants, loose]


def test_overview_accepts_the_list_filters(client):
    p = make_product(client, identifiers=[], colors=[])
    m = ok(client.post(f"{API}/items", json={"product_id": p["id"], "size_label": "M"}), 201)
    ok(client.post(f"{API}/items", json={"product_id": p["id"], "size_label": "L"}), 201)
    assert [r["id"] for r in get(client, "/items/overview?size=M")["items"]] == [m["id"]]


# ───────────── GPT 独立审查复现（OVERVIEW-COLOR-QA-001，原样收录，仅格式调整） ─────────────


@pytest.mark.parametrize("code", ["6²", "²1"])
def test_non_decimal_digit_code_falls_back_to_name(code):
    assert display_swatch(None, "BLUE", code, "uniqlo") == {"hex": "#4B78B5", "source": "name"}


def test_accepted_colour_code_cannot_break_item_creation_and_whole_library(app):
    client = TestClient(
        app, base_url="http://127.0.0.1:8765", headers={"X-Wardrobe-Client": "web-ui"}, raise_server_exceptions=False
    )
    p = make_product(client, identifiers=[], colors=[])
    r = client.post(f"{API}/items", json={"product_id": p["id"], "color_code": "6²", "color_name": "BLUE"})
    listing = client.get(f"{API}/items")
    overview = client.get(f"{API}/items/overview")
    print("POST item:", r.status_code, "GET list:", listing.status_code, "GET overview:", overview.status_code)
    assert r.status_code == 201
    assert listing.status_code == overview.status_code == 200


@pytest.mark.parametrize("code", ["６１", "61 ", "+6", "6"])
def test_other_non_ascii_or_malformed_codes_use_the_base_colour(code):
    assert display_swatch(None, "BLUE", code, "uniqlo") == {"hex": "#4B78B5", "source": "name"}
