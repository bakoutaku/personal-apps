"""Phase 5B：相似衣物（wardrobe-similar/1）。全部为虚构数据；预期分值由规则表直接算出。"""

import pytest
from helpers import API, err, get, make_product, ok
from sqlalchemy import func, select

from wardrobe.models import ChangeLog, ChangeProposal

NAVY, BLACK, RED = "#1F2A44", "#1A1A1A", "#C81E1E"


def new_item(client, name, category, hex_=None, tags=()):
    colors = [{"color_code": "01", "name_ja": "C", "hex": hex_, "is_default": True}] if hex_ else []
    p = make_product(client, identifiers=[], name_ja=name, category=category, colors=colors)
    return ok(client.post(f"{API}/items", json={"product_id": p["id"], "tags": list(tags)}), 201)


def similar(client, item_id, **params):
    return ok(client.get(f"{API}/items/{item_id}/similar", params=params))


def test_scores_reasons_threshold_and_order(client):
    t = new_item(client, "目标T", "tops-tshirt-short", NAVY, ["通勤", "秋冬"])
    a = new_item(client, "A 同类同色同标签", "tops-tshirt-short", NAVY, ["通勤"])  # 4 + 3 + 2 = 9
    b = new_item(client, "B 同二级分类", "tops-tshirt-long", RED)  # 3
    new_item(client, "C 只同一级分类", "tops-shirt-oxford", RED)  # 1，不推荐
    d = new_item(client, "D 只同色", "outer-coat", NAVY)  # 3
    new_item(client, "E 只一个标签", "outer-coat", RED, ["通勤"])  # 2，不推荐
    f = new_item(client, "F 一级+同色+标签", "tops-shirt-oxford", NAVY, ["秋冬"])  # 1 + 3 + 2 = 6
    out = similar(client, t["id"])
    assert out["algorithm"] == "wardrobe-similar/1" and out["min_score"] == 3 and out["status"] == "owned"
    assert [(x["item"]["id"], x["score"]) for x in out["items"]] == [
        (a["id"], 9),
        (f["id"], 6),
        (d["id"], 3),
        (b["id"], 3),
    ]
    by_id = {x["item"]["id"]: x for x in out["items"]}
    assert [r["label"] for r in by_id[a["id"]]["reasons"]] == [
        "同类衣物（短袖T恤）",
        "颜色相近（藏青）",
        "共有标签：#通勤",
    ]
    assert [r["label"] for r in by_id[f["id"]]["reasons"]] == ["同属「上衣」", "颜色相近（藏青）", "共有标签：#秋冬"]
    assert [r["label"] for r in by_id[b["id"]]["reasons"]] == ["同属「T恤·针织」"]
    assert [r["points"] for r in by_id[a["id"]]["reasons"]] == [4, 3, 2]
    assert by_id[a["id"]]["item"]["name"] == "A 同类同色同标签"  # 列表项与衣橱网格同一结构


def test_missing_data_never_counts_as_a_match(client):
    t = new_item(client, "无资料目标", None)
    new_item(client, "也无资料", None)
    new_item(client, "有资料", "tops-tshirt-short", NAVY, ["通勤"])
    assert similar(client, t["id"])["items"] == []
    # 反方向：目标有资料，候选缺少对应资料
    t2 = new_item(client, "有资料目标", "outer-coat", BLACK, ["雨天"])
    assert similar(client, t2["id"])["items"] == []


def test_shared_tags_count_at_most_three(client):
    tags = ["甲", "乙", "丙", "丁"]
    t = new_item(client, "目标", None, None, tags)
    o = new_item(client, "四个共有标签", None, None, tags)
    (x,) = similar(client, t["id"])["items"]
    assert x["item"]["id"] == o["id"] and x["score"] == 6
    assert x["reasons"] == [{"kind": "shared_tags", "label": "共有标签：#丁、#丙、#乙、#甲", "points": 6}]


def test_excludes_self_deleted_and_non_owned_by_default(client):
    t = new_item(client, "目标", "outer-coat", NAVY)
    gone = new_item(client, "已删除", "outer-coat", NAVY)
    ok(client.delete(f"{API}/items/{gone['id']}", params={"version": gone["version"]}), 204)
    ret = new_item(client, "已退货", "outer-coat", NAVY)
    ok(client.post(f"{API}/items/{ret['id']}/return", json={"version": ret["version"], "returned_on": "2026-01-02"}))
    keep = new_item(client, "持有", "outer-coat", NAVY)
    assert [x["item"]["id"] for x in similar(client, t["id"])["items"]] == [keep["id"]]
    ids = [x["item"]["id"] for x in similar(client, t["id"], status="all")["items"]]
    assert ids == [keep["id"], ret["id"]] and t["id"] not in ids and gone["id"] not in ids


def test_read_only_and_errors(client, app):
    t = new_item(client, "目标", "outer-coat", NAVY, ["通勤"])
    new_item(client, "候选", "outer-coat", NAVY, ["通勤"])
    with app.state.sessionmaker() as s:
        before = (
            s.scalar(select(func.count()).select_from(ChangeLog)),
            s.scalar(select(func.count()).select_from(ChangeProposal)),
        )
    v = get(client, f"/items/{t['id']}")["version"]
    assert len(similar(client, t["id"])["items"]) == 1
    with app.state.sessionmaker() as s:
        after = (
            s.scalar(select(func.count()).select_from(ChangeLog)),
            s.scalar(select(func.count()).select_from(ChangeProposal)),
        )
    assert after == before and get(client, f"/items/{t['id']}")["version"] == v
    err(client.get(f"{API}/items/99999/similar"), 404, "NOT_FOUND")
    for bad in ({"limit": 0}, {"limit": 25}, {"status": "returned"}):
        err(client.get(f"{API}/items/{t['id']}/similar", params=bad), 422, "VALIDATION_ERROR")


@pytest.mark.parametrize("limit", [1, 2])
def test_limit(client, limit):
    t = new_item(client, "目标", "outer-coat", NAVY)
    for i in range(3):
        new_item(client, f"候选{i}", "outer-coat", NAVY)
    assert len(similar(client, t["id"], limit=limit)["items"]) == limit
