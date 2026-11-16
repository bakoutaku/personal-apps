"""试用反馈：列表图片按购买颜色、快捷分组（T恤 / 衬衫 / 半袖 …）。全部为虚构数据。"""

import pytest
from helpers import API, err, get, make_product, ok, png_bytes, upload

# ───────────── 列表图片按颜色 ─────────────


def two_color_product(client):
    p = make_product(
        client,
        identifiers=[],
        name_ja="二色T",
        category="tops-tshirt-short",
        colors=[
            {"color_code": "09", "name_ja": "BLACK", "is_default": True},
            {"color_code": "30", "name_ja": "NATURAL"},
            {"color_code": "69", "name_ja": "NAVY"},
        ],
    )
    black = ok(upload(client, png_bytes((10, 10, 10))), 201)
    natural = ok(upload(client, png_bytes((230, 220, 200))), 201)
    ok(
        client.post(
            f"{API}/products/{p['id']}/images",
            json={"version": 1, "image_id": black["id"], "role": "main", "color_code": "09"},
        ),
        201,
    )
    ok(
        client.post(
            f"{API}/products/{p['id']}/images",
            json={"version": 2, "image_id": natural["id"], "role": "color", "color_code": "30"},
        ),
        201,
    )
    return p, black, natural


def thumbs(client):
    return {i["id"]: i["thumb_url"] for i in get(client, "/items?limit=100")["items"]}


def test_list_thumbnail_follows_the_item_colour(client):
    p, black, natural = two_color_product(client)
    a = ok(client.post(f"{API}/items", json={"product_id": p["id"], "color_code": "09"}), 201)
    b = ok(client.post(f"{API}/items", json={"product_id": p["id"], "color_code": "30"}), 201)
    c = ok(client.post(f"{API}/items", json={"product_id": p["id"], "color_code": "69"}), 201)  # 没有该色的图
    t = thumbs(client)
    assert t[a["id"]] == get(client, f"/images/{black['id']}")["thumb_url"]
    assert t[b["id"]] == get(client, f"/images/{natural['id']}")["thumb_url"]
    assert t[c["id"]] == t[a["id"]]  # 回退到商品主图


def test_own_photo_still_wins_over_product_images(client):
    p, _, _ = two_color_product(client)
    b = ok(client.post(f"{API}/items", json={"product_id": p["id"], "color_code": "30"}), 201)
    own = ok(upload(client, png_bytes((0, 200, 0))), 201)
    ok(client.post(f"{API}/items/{b['id']}/images", json={"version": b["version"], "image_id": own["id"]}), 201)
    assert thumbs(client)[b["id"]] == get(client, f"/images/{own['id']}")["thumb_url"]


# ───────────── 快捷分组 ─────────────


def item(client, name, category=None, tags=()):
    p = make_product(client, identifiers=[], name_ja=name, name_zh=None, category=category, colors=[])
    return ok(client.post(f"{API}/items", json={"product_id": p["id"], "tags": list(tags)}), 201)["id"]


@pytest.fixture
def wardrobe(client):
    return {
        "tee_short": item(client, "短T", "tops-tshirt-short"),
        "tee_long": item(client, "长T", "tops-tshirt-long"),
        "tee_level2": item(client, "只到T恤针织", "tops-tshirt"),
        "knit": item(client, "毛衣", "tops-knit"),
        "sweat": item(client, "帽衫", "tops-sweat"),
        "oxford": item(client, "牛津", "tops-shirt-oxford"),
        "polo": item(client, "Polo", "tops-polo"),
        "short_shirt": item(client, "短袖衬衫", "tops-shirt-other", ["短袖"]),
        "tank": item(client, "背心", None, ["无袖"]),
        "jeans": item(client, "牛仔", "bottoms-jeans"),
        "shorts": item(client, "短裤", "bottoms-shorts"),
        "socks": item(client, "袜子", "innerwear-socks"),
        "heattech": item(client, "保暖", "innerwear-heattech"),
        "inner_level1": item(client, "内衣一级", "innerwear"),
        "none": item(client, "未分类"),
    }


def ids(client, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return {i["id"] for i in get(client, f"/items?limit=100&{q}")["items"]}


@pytest.mark.parametrize(
    ("group", "expected"),
    [
        ("tshirt", {"tee_short", "tee_long", "tee_level2"}),
        ("shirt", {"oxford", "polo", "short_shirt"}),
        ("short_sleeve", {"tee_short", "short_shirt", "tank"}),
        ("knit", {"knit"}),
        ("hoodie", {"sweat"}),
        ("pants", {"jeans"}),
        ("shorts", {"shorts"}),
        ("socks", {"socks"}),
        ("inner", {"heattech", "inner_level1"}),
        ("skirt", set()),
    ],
)
def test_group_filter(client, wardrobe, group, expected):
    assert ids(client, group=group) == {wardrobe[k] for k in expected}


def test_unknown_group_is_rejected(client, wardrobe):
    err(client.get(f"{API}/items?group=nope"), 422, "VALIDATION_ERROR")


def test_group_combines_with_other_filters_and_facets_count_every_group(client, wardrobe):
    assert ids(client, group="tshirt", q="短T") == {wardrobe["tee_short"]}
    groups = {g["key"]: g for g in get(client, "/items/facets?group=tshirt")["groups"]}
    # 分组计数不受当前所选分组影响，但受其他条件影响
    assert groups["tshirt"]["count"] == 3 and groups["shirt"]["count"] == 3 and groups["short_sleeve"]["count"] == 3
    assert groups["skirt"]["count"] == 0
    assert groups["socks"]["more"] is True and groups["tshirt"]["more"] is False
    assert [g["label"] for g in get(client, "/items/facets")["groups"]][:4] == ["T恤", "衬衫", "半袖", "毛衣"]
    narrowed = {g["key"]: g["count"] for g in get(client, "/items/facets?q=短")["groups"]}
    assert narrowed["tshirt"] == 1 and narrowed["shirt"] == 1


def test_short_sleeve_tags_come_from_the_name(client):
    a = item(client, "ユーティリティオーバーサイズシャツ/半袖", "tops-shirt-other")
    b = item(client, "ドライオープンカラーシャツ(5分袖)", "tops-shirt-other")
    c = item(client, "エアリズムタンクトップ", None)
    names = {i: [t["name"] for t in get(client, f"/items/{i}/tag-suggestions")["tags"]] for i in (a, b, c)}
    assert "短袖" in names[a] and "短袖" in names[b] and "无袖" in names[c]
    assert "短袖" not in names[c]


# GPT 独立审查 TRIAL-TAG-QA-001 的复现测试（docs/独立审查_试用分组与名称标签_2026-10-28.md），原样加入（仅格式化）
from test_tag_category_suggestions import bare_item, preview  # noqa: E402


@pytest.mark.parametrize("category", [None, "innerwear-socks"])
def test_heattech_socks_do_not_suggest_underwear_label(client, category):
    it = bare_item(client, "ヒートテックソックス/パイル", category)
    out = preview(client, it["id"])
    assert "袜子" in [t["name"] for t in out["tags"]]
    assert "保暖内衣" not in [t["name"] for t in out["tags"]], out


def test_heattech_underwear_tag_can_be_accepted_for_socks(client):
    it = bare_item(client, "ヒートテックソックス/パイル", "innerwear-socks")
    r = client.post(f"{API}/items/{it['id']}/tag-suggestions", json={"version": it["version"], "tags": ["保暖内衣"]})
    if r.status_code == 201:
        p = r.json()["proposals"][0]["proposal_id"]
        ok(client.post(f"{API}/proposals/{p}/accept"))
    assert "保暖内衣" not in get(client, f"/items/{it['id']}")["tags"]


def name_tag_names(client, name, category=None):
    return [t["name"] for t in preview(client, bare_item(client, name, category)["id"])["tags"]]


@pytest.mark.parametrize(
    ("name", "category", "expected"),
    [
        # 真正的保暖内衣仍建议
        ("ヒートテックインナー", None, True),  # 「インナー」是保暖内衣的上级
        ("ヒートテックタイツ/前開き", None, True),
        ("ヒートテックVネックT", "innerwear-heattech", True),
        ("極暖ヒートテックコットンタイツ/前開き", "innerwear-heattech", True),
        # 其他品类的 HEATTECH 不建议
        ("ヒートテックリブビーニー", None, False),
        ("ヒートテックリブビーニー", "accessories-hat", False),
        ("ヒートテックマフラー", None, False),
        ("ヒートテックライニンググローブスウェードタッチ", "accessories-scarf", False),
        ("ヒートテックVネックT", "tops-tshirt-long", False),
        ("ヒートテックVネックT", None, False),  # 未分类且跨上衣 / 内衣：保守不建议
    ],
)
def test_heattech_label_only_for_heattech_innerwear(client, name, category, expected):
    assert ("保暖内衣" in name_tag_names(client, name, category)) is expected


def test_other_entries_still_use_the_top_level_scope(client):
    # 一级范围的词条行为不变：分类在该一级分类的子分类下时仍适用
    assert "半身裙" in name_tag_names(client, "デニムスカート", "bottoms-skirt")
    assert "卫衣" in name_tag_names(client, "スムーススウェットパーカ", "tops-sweat")
