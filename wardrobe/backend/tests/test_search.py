"""衣橱列表筛选与模糊搜索（ARCHITECTURE §6）。"""

import pytest
from helpers import API, err, make_product, make_purchase, ok


@pytest.fixture
def wardrobe(client):
    down = make_product(client)
    tee = make_product(
        client,
        brand="gu",
        category="tops-tshirt-short",
        name_ja="ドライカラークルーネックT",
        name_zh="速干圆领T恤",
        identifiers=[{"scheme": "item_no", "value": "123456"}],
        colors=[{"color_code": "01", "name_ja": "OFF WHITE", "hex": "#F7F7F5", "is_default": True}],
        sizes=[{"size_label": "M"}],
        material_text="綿60%・ポリエステル40%",
    )
    d = make_purchase(client, down["id"], color_code="69", color_name="NAVY", color_hex="#1F2A44", size_label="L")
    t = make_purchase(client, tee["id"])
    down_item, tee_item = d["lines"][0]["item_ids"][0], t["lines"][0]["item_ids"][0]
    ok(client.put(f"{API}/items/{down_item}/tags", json={"version": 1, "tags": ["通勤", "秋冬"]}))
    ok(client.put(f"{API}/items/{tee_item}/tags", json={"version": 1, "tags": ["通勤"]}))
    return {"down": down_item, "tee": tee_item}


def ids(client, **params):
    return {i["id"] for i in ok(client.get(f"{API}/items", params=params))["items"]}


@pytest.mark.parametrize("q", ["ダウン", "だうん", "ﾀﾞｳﾝ", "测试羽绒", "e999001", "ナイロン", "navy", "秋冬"])
def test_fuzzy_search_finds_down(client, wardrobe, q):
    assert ids(client, q=q) == {wardrobe["down"]}


def test_short_tokens_use_like(client, wardrobe):
    assert ids(client, q="gu") == {wardrobe["tee"]}
    assert ids(client, q="T") >= {wardrobe["tee"]}


def test_multiple_tokens_are_and(client, wardrobe):
    assert ids(client, q="通勤 ダウン") == {wardrobe["down"]}
    assert ids(client, q="通勤") == {wardrobe["down"], wardrobe["tee"]}


def test_structured_filters(client, wardrobe):
    assert ids(client, category="outer") == {wardrobe["down"]}  # 含子孙分类
    assert ids(client, category="tops-tshirt") == {wardrobe["tee"]}
    assert ids(client, brand="gu") == {wardrobe["tee"]}
    assert ids(client, color="navy") == {wardrobe["down"]}
    assert ids(client, color="white,navy") == {wardrobe["down"], wardrobe["tee"]}
    assert ids(client, size="M") == {wardrobe["tee"]}  # 单一尺码商品回退
    assert ids(client, material="cotton") == {wardrobe["tee"]}
    assert ids(client, tag="通勤,秋冬") == {wardrobe["down"]}
    assert ids(client, tag="通勤,秋冬", tag_mode="any") == {wardrobe["down"], wardrobe["tee"]}


def test_list_item_shape_for_grid(client, wardrobe):
    item = ok(client.get(f"{API}/items", params={"q": "ダウン"}))["items"][0]
    assert item["category"]["path"] == ["外套", "羽绒", "轻羽绒"]
    assert item["brand"] == "UNIQLO" and item["thumb_url"] is None
    assert set(item["resolved"]) == {"color", "size"}


def test_sort_and_paging(client, wardrobe):
    page = ok(client.get(f"{API}/items", params={"sort": "name", "limit": 1}))
    assert page["total"] == 2 and len(page["items"]) == 1
    names = [i["name"] for i in ok(client.get(f"{API}/items", params={"sort": "name"}))["items"]]
    assert names == sorted(names)
    err(client.get(f"{API}/items", params={"sort": "bogus"}), 422, "VALIDATION_ERROR")


def test_global_search_and_reindex(client, wardrobe):
    res = ok(client.get(f"{API}/search", params={"q": "ダウン"}))
    assert [i["id"] for i in res["items"]] == [wardrobe["down"]]
    assert ok(client.post(f"{API}/search/reindex"))["indexed"] == 2
    assert ids(client, q="ダウン") == {wardrobe["down"]}


def test_product_rename_updates_index(client, wardrobe):
    item = ok(client.get(f"{API}/items/{wardrobe['tee']}"))
    pid = item["product_id"]
    ok(client.patch(f"{API}/products/{pid}", json={"version": item["product"]["version"], "name_ja": "エアリズムT"}))
    assert ids(client, q="エアリズム") == {wardrobe["tee"]}
    assert ids(client, q="ドライカラー") == set()
