"""品牌、分类（R8 移动校验）、标签。"""

import pytest
from helpers import API, err, make_product, ok


def _cat(client, slug, parent=None, **kw):
    return ok(client.post(f"{API}/categories", json={"slug": slug, "name_zh": slug, "parent": parent, **kw}), 201)


@pytest.fixture
def tree(client):
    """a(1) > b(2) > c(3)；x(1) > y(2)"""
    a = _cat(client, "a")
    b = _cat(client, "b", "a")
    c = _cat(client, "c", "b")
    x = _cat(client, "x")
    y = _cat(client, "y", "x")
    return {n: v for n, v in zip("abcxy", (a, b, c, x, y), strict=True)}


def test_levels_are_computed_from_parent(tree):
    assert [tree[k]["level"] for k in "abcxy"] == [1, 2, 3, 1, 2]


def test_fourth_level_is_rejected(client, tree):
    e = err(
        client.post(f"{API}/categories", json={"slug": "d", "name_zh": "d", "parent": "c"}), 422, "VALIDATION_ERROR"
    )
    assert e["details"][0]["code"] == "too_deep"


def test_move_into_own_descendant_is_rejected(client, tree):
    e = err(client.patch(f"{API}/categories/{tree['a']['id']}", json={"parent": "c"}), 422, "VALIDATION_ERROR")
    assert e["details"][0]["code"] == "cycle"
    err(client.patch(f"{API}/categories/{tree['a']['id']}", json={"parent": "a"}), 422, "VALIDATION_ERROR")


def test_move_that_would_exceed_depth_is_rejected(client, tree):
    # b 子树高 2，放到 y(2) 下面会变成 3、4 级
    e = err(client.patch(f"{API}/categories/{tree['b']['id']}", json={"parent": "y"}), 422, "VALIDATION_ERROR")
    assert e["details"][0]["code"] == "too_deep"


def test_move_recomputes_subtree_levels(client, tree):
    ok(client.patch(f"{API}/categories/{tree['b']['id']}", json={"parent": None}))
    flat = {c["slug"]: c for c in ok(client.get(f"{API}/categories", params={"format": "flat"}))["items"]}
    assert (flat["b"]["level"], flat["b"]["parent_id"], flat["c"]["level"]) == (1, None, 2)
    ok(client.patch(f"{API}/categories/{tree['b']['id']}", json={"parent": "x"}))
    flat = {c["slug"]: c for c in ok(client.get(f"{API}/categories", params={"format": "flat"}))["items"]}
    assert (flat["b"]["level"], flat["c"]["level"]) == (2, 3)


def test_delete_category_rules(client, tree):
    err(client.delete(f"{API}/categories/{tree['a']['id']}"), 409, "IN_USE")
    make_product(client, identifiers=[], category="y")
    err(client.delete(f"{API}/categories/{tree['y']['id']}"), 409, "IN_USE")
    ok(client.delete(f"{API}/categories/{tree['c']['id']}"), 204)


def test_tags_deduplicate_by_normalized_name(client):
    first = ok(client.post(f"{API}/tags", json={"name": "通勤"}), 201)
    again = ok(client.post(f"{API}/tags", json={"name": " 通勤 "}))
    assert again["id"] == first["id"] and again["existing"] is True
    kana = ok(client.post(f"{API}/tags", json={"name": "ｶｼﾞｭｱﾙ"}), 201)
    assert ok(client.post(f"{API}/tags", json={"name": "カジュアル"}))["id"] == kana["id"]


def test_brand_crud(client):
    b = ok(client.post(f"{API}/brands", json={"slug": "muji", "name": "無印良品", "name_zh": "无印良品"}), 201)
    err(client.post(f"{API}/brands", json={"slug": "muji", "name": "x"}), 409, "DUPLICATE")
    assert ok(client.patch(f"{API}/brands/{b['id']}", json={"name_ja": "むじるしりょうひん"}))["name_ja"]
    make_product(client, brand="muji", identifiers=[])
