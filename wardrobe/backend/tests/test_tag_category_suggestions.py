"""Phase 5C：标签 / 分类规则建议（wardrobe-tagcat/3）。全部为虚构数据；预期结果由规则直接推出。"""

import sqlite3

import pytest
from helpers import API, err, get, make_product, ok
from sqlalchemy import event, func, select
from test_similar_items import NAVY, RED, new_item

from wardrobe.db import expected_schema, head_revision
from wardrobe.models import ChangeLog, ChangeProposal


def bare_item(client, name_ja, category=None):
    """只有日文名的衣物（共用的 make_product 默认带中文名「测试羽绒茄克」，会干扰名称关键词）。"""
    p = make_product(client, identifiers=[], name_ja=name_ja, name_zh=None, category=category, colors=[])
    return ok(client.post(f"{API}/items", json={"product_id": p["id"]}), 201)


def preview(client, item_id):
    return ok(client.get(f"{API}/items/{item_id}/tag-suggestions"))


def create(client, item_id, version, tags=(), category_id=None):
    return client.post(
        f"{API}/items/{item_id}/tag-suggestions",
        json={"version": version, "tags": list(tags), "category_id": category_id},
    )


def counts(app):
    with app.state.sessionmaker() as s:
        return (
            s.scalar(select(func.count()).select_from(ChangeLog)),
            s.scalar(select(func.count()).select_from(ChangeProposal)),
        )


# ───────────── 标签 ─────────────


def test_tags_from_other_items_of_the_same_product(client):
    p = make_product(client, identifiers=[], name_ja="同商品", category="outer-coat", colors=[])
    a = ok(client.post(f"{API}/items", json={"product_id": p["id"], "tags": ["通勤", "黑色系"]}), 201)
    b = ok(client.post(f"{API}/items", json={"product_id": p["id"], "tags": ["通勤"]}), 201)
    out = preview(client, b["id"])
    assert out["algorithm"] == "wardrobe-tagcat/3"
    assert [t["name"] for t in out["tags"]] == ["黑色系"]  # 已有的「通勤」不再建议
    assert out["tags"][0]["reasons"][0] == {
        "kind": "same_product",
        "label": f"同一商品的其他衣物有此标签（#{a['id']}）",
    }
    assert out["tags"][0]["evidence"]["same_product_item_ids"] == [a["id"]]


def test_tags_from_similar_items_need_two_supporting_items_and_30_percent(client):
    t = new_item(client, "目标", "outer-coat", NAVY)
    new_item(client, "相似1", "outer-coat", NAVY, ["冬", "雨天"])
    new_item(client, "相似2", "outer-coat", NAVY, ["冬"])
    new_item(client, "相似3", "outer-coat", NAVY)
    new_item(client, "不相似", "tops-polo", RED, ["冬", "雨天"])  # 不在相似衣物中，不计入
    out = preview(client, t["id"])
    assert [x["name"] for x in out["tags"]] == ["冬"]  # 冬：2/3；雨天：1/3 不足 2 件
    assert out["tags"][0]["reasons"] == [{"kind": "similar_items", "label": "相似衣物中 2/3 件有此标签"}]


def test_at_most_five_tags_and_same_product_evidence_first(client):
    p = make_product(
        client, identifiers=[], name_ja="同商品", category="outer-coat", colors=[{"hex": NAVY, "is_default": True}]
    )
    ok(client.post(f"{API}/items", json={"product_id": p["id"], "tags": ["Z同商品"]}), 201)
    t = ok(client.post(f"{API}/items", json={"product_id": p["id"]}), 201)
    many = ["甲", "乙", "丙", "丁", "戊", "己"]
    for i in range(2):
        new_item(client, f"相似{i}", "outer-coat", NAVY, many)
    names = [x["name"] for x in preview(client, t["id"])["tags"]]
    assert len(names) == 5 and names[0] == "Z同商品"


# ───────────── 分类 ─────────────


def test_category_from_the_deepest_name_keyword(client):
    t = bare_item(client, "テストダウンジャケット")
    cat = preview(client, t["id"])["category"]
    # 「ダウン」(羽绒，二级)、「ジャケット」(夹克，二级)、「ダウンジャケット」(羽绒服，三级)：取最深的一级
    assert cat["slug"] == "outer-down-jacket" and cat["path"] == ["外套", "羽绒", "羽绒服"]
    assert cat["reasons"] == [{"kind": "name_keyword", "label": "商品名称含「だうんじゃけっと」"}]


def test_same_level_hits_prefer_the_strictly_longest_keyword(client):
    # 「ウルトラライトダウン」(轻羽绒，三级，10 字) 与「ダウンジャケット」(羽绒服，三级，8 字) 都命中：取更长的
    t = bare_item(client, "ウルトラライトダウンジャケット")
    cat = preview(client, t["id"])["category"]
    assert cat["slug"] == "outer-light-down"
    assert cat["reasons"] == [{"kind": "name_keyword", "label": "商品名称含「うるとららいとだうん」"}]


def test_category_not_suggested_when_ambiguous_missing_or_already_categorized(client):
    ok(client.post(f"{API}/categories", json={"slug": "qa-aaa", "name_zh": "测试甲类"}), 201)
    ok(client.post(f"{API}/categories", json={"slug": "qa-bbb", "name_zh": "测试乙类"}), 201)
    amb = bare_item(client, "测试甲类与测试乙类")
    out = preview(client, amb["id"])
    assert out["category"] is None and out["category_note"] == "ambiguous"
    none = bare_item(client, "XYZ-001")
    assert preview(client, none["id"])["category_note"] == "no_keyword_match"
    done = bare_item(client, "テストダウンジャケット", "outer-coat")
    assert preview(client, done["id"])["category_note"] == "already_categorized"


# ───────────── 生成提议 ─────────────


def test_create_only_adds_pending_proposals_and_validates_the_choice(client, app):
    t = bare_item(client, "テストダウンジャケット")
    sib = ok(client.post(f"{API}/items", json={"product_id": t["product_id"], "tags": ["冬"]}), 201)
    assert sib["product_id"] == t["product_id"]
    pv = preview(client, t["id"])
    cid = pv["category"]["category_id"]
    before_item = get(client, f"/items/{t['id']}")
    logs_before, props_before = counts(app)
    err(create(client, t["id"], t["version"]), 422, "VALIDATION_ERROR")  # 什么都没选
    e = err(create(client, t["id"], t["version"], ["不在建议中"]), 422, "VALIDATION_ERROR")
    assert e["details"][0]["code"] == "not_a_suggestion"
    err(create(client, t["id"], t["version"], category_id=cid + 999), 422, "VALIDATION_ERROR")
    err(create(client, t["id"], t["version"] - 1, ["冬"]), 409, "VERSION_CONFLICT")
    assert counts(app) == (logs_before, props_before)
    out = ok(create(client, t["id"], t["version"], ["冬"], cid), 201)
    fields = {p["field"]: p for p in out["proposals"]}
    assert fields["tags_add"]["proposed_value"] == ["冬"] and fields["tags_add"]["current_value"] == []
    assert fields["category_id"]["proposed_value"] == cid and fields["category_id"]["current_value"] is None
    ctx = fields["category_id"]["rule_context"]
    assert ctx["source"] == "rule_based" and ctx["algorithm"] == "wardrobe-tagcat/3" and ctx["kind"] == "category"
    assert fields["tags_add"]["rule_context"]["evidence"]["tags"][0]["evidence"]["same_product_item_ids"] == [sib["id"]]
    assert all(p["status"] == "pending" and p["ai_context"] is None for p in out["proposals"])
    assert get(client, f"/items/{t['id']}") == before_item  # 衣物（含 version、标签、分类）不变
    assert counts(app)[0] == logs_before  # 生成提议不写审计日志（与既有提议一致）


def test_accept_tags_only_appends_and_keeps_tags_added_later(client):
    p = make_product(client, identifiers=[], name_ja="同商品", category="outer-coat", colors=[])
    ok(client.post(f"{API}/items", json={"product_id": p["id"], "tags": ["冬"]}), 201)
    t = ok(client.post(f"{API}/items", json={"product_id": p["id"], "tags": ["旧"]}), 201)
    prop = ok(create(client, t["id"], t["version"], ["冬"]), 201)["proposals"][0]
    # 生成后用户又加了一个标签：只追加的提议仍可接受，且不会丢掉后加的标签
    item = ok(client.put(f"{API}/items/{t['id']}/tags", json={"version": t["version"], "tags": ["旧", "后加"]}))
    ok(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"))
    after = get(client, f"/items/{t['id']}")
    assert set(after["tags"]) == {"旧", "后加", "冬"} and len(after["tags"]) == 3
    assert after["version"] == item["version"] + 1


def test_accept_tags_that_already_exist_changes_nothing(client):
    p = make_product(client, identifiers=[], name_ja="同商品", category="outer-coat", colors=[])
    ok(client.post(f"{API}/items", json={"product_id": p["id"], "tags": ["冬"]}), 201)
    t = ok(client.post(f"{API}/items", json={"product_id": p["id"]}), 201)
    prop = ok(create(client, t["id"], t["version"], ["冬"]), 201)["proposals"][0]
    item = ok(client.put(f"{API}/items/{t['id']}/tags", json={"version": t["version"], "tags": ["冬"]}))
    assert ok(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"))["status"] == "accepted"
    assert get(client, f"/items/{t['id']}")["version"] == item["version"]


def test_accept_category_writes_the_item_category(client):
    t = bare_item(client, "テストダウンジャケット")
    cid = preview(client, t["id"])["category"]["category_id"]
    prop = ok(create(client, t["id"], t["version"], category_id=cid), 201)["proposals"][0]
    ok(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"))
    after = get(client, f"/items/{t['id']}")
    assert after["category"]["slug"] == "outer-down-jacket" and after["version"] == t["version"] + 1


def test_category_proposal_is_stale_once_the_item_or_its_product_has_a_category(client):
    t = bare_item(client, "テストダウンジャケット")
    cid = preview(client, t["id"])["category"]["category_id"]
    prop = ok(create(client, t["id"], t["version"], category_id=cid), 201)["proposals"][0]
    prod = get(client, f"/products/{t['product_id']}")
    ok(client.patch(f"{API}/products/{prod['id']}", json={"version": prod["version"], "category": "outer-coat"}))
    e = err(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"), 409, "PROPOSAL_STALE")
    assert "已经有分类" in e["message"]
    assert get(client, f"/items/{t['id']}")["category"]["slug"] == "outer-coat"


def test_ai_clients_may_create_but_not_decide(client, ai):
    t = bare_item(client, "テストダウンジャケット")
    cid = preview(client, t["id"])["category"]["category_id"]
    prop = ok(create(ai, t["id"], t["version"], category_id=cid), 201)["proposals"][0]
    assert prop["actor"] == "ai:codex"
    err(ai.post(f"{API}/proposals/{prop['proposal_id']}/accept"), 403, "PRIVILEGED_ONLY")


# ───────────── 批量 ─────────────


def test_batch_preview_is_read_only_and_lists_only_items_with_suggestions(client, app):
    a = bare_item(client, "テストダウンジャケット")  # 有分类建议
    bare_item(client, "XYZ-002", "outer-coat")  # 没有任何建议
    logs, props = counts(app)
    out = ok(client.get(f"{API}/tag-suggestions"))
    assert out["total"] == 1 and [x["item"]["id"] for x in out["items"]] == [a["id"]]
    assert out["items"][0]["category"]["slug"] == "outer-down-jacket"
    assert counts(app) == (logs, props)


def test_batch_create_reports_each_item(client):
    a = bare_item(client, "テストダウンジャケット")
    b = bare_item(client, "テストダウンジャケット二号")
    ca = preview(client, a["id"])["category"]["category_id"]
    body = {
        "items": [
            {"item_id": a["id"], "version": a["version"], "category_id": ca},
            {"item_id": b["id"], "version": b["version"] + 5, "category_id": ca},  # 旧 version
            {"item_id": 99999, "version": 1, "tags": ["x"]},
        ]
    }
    out = ok(client.post(f"{API}/tag-suggestions/batch", json=body), 201)
    assert (out["succeeded"], out["failed"]) == (1, 2)
    codes = [r.get("error", {}).get("code") for r in out["results"]]
    assert codes == [None, "VERSION_CONFLICT", "NOT_FOUND"]
    pending = get(client, "/proposals")["items"]
    assert [p["entity_id"] for p in pending] == [a["id"]]


def test_batch_size_is_limited(client):
    body = {"items": [{"item_id": 1, "version": 1, "tags": ["x"]}] * 101}
    err(client.post(f"{API}/tag-suggestions/batch", json=body), 422, "VALIDATION_ERROR")


# ───────────── 迁移 0003 ─────────────


def test_migration_0003_adds_only_the_rule_context_table(app, settings):
    assert head_revision() == "0003"
    new = {t: c for t, c in expected_schema("0003").items() if t != "rule_suggestion_context"}
    assert new == expected_schema("0002")
    assert expected_schema("0003")["rule_suggestion_context"] == {
        "proposal_id", "kind", "target_version", "algorithm", "evidence", "created_at",
    }  # fmt: skip
    conn = sqlite3.connect(settings.db_path)
    fks = {(r[2], r[3], r[6]) for r in conn.execute("PRAGMA foreign_key_list(rule_suggestion_context)")}
    conn.close()
    assert fks == {("change_proposal", "proposal_id", "CASCADE")}


@pytest.mark.parametrize("kind", ["tags", "category"])
def test_rule_context_kind_is_constrained(app, settings, kind):
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "INSERT INTO change_proposal (entity, entity_id, field, actor, status, created_at) VALUES ('wardrobe_item', 1, 'x', 'cli', 'pending', 't')"
    )
    pid = conn.execute("SELECT max(id) FROM change_proposal").fetchone()[0]
    conn.execute("INSERT INTO rule_suggestion_context VALUES (?, ?, 1, 'a', '{}', 't')", (pid, kind))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO rule_suggestion_context VALUES (?, 'colour', 1, 'a', '{}', 't')", (pid + 1,))
    conn.close()


# ───────────── GPT 独立审查复现（REVIEW_PHASE5C_GPT_INDEPENDENT_2026-10-28.md，原样加入） ─────────────


@pytest.mark.parametrize(
    "name",
    ["スウェットショートパンツ", "ニットスカート", "Tシャツワンピース", "エアリズムコットンオーバーサイズTシャツ"],
)
def test_cross_group_names_do_not_choose_the_wrong_major_category(client, name):
    out = preview(client, bare_item(client, name)["id"])
    assert out["category"] is None, (name, out["category"])
    assert out["category_note"] == "ambiguous"


def test_color_only_evidence_does_not_transfer_season_tags(client):
    target = new_item(client, "藏青大衣", "outer-coat", NAVY)
    new_item(client, "藏青短袖甲", "tops-tshirt-short", NAVY, ["夏"])
    new_item(client, "藏青短袖乙", "tops-tshirt-short", NAVY, ["夏"])
    assert "夏" not in [r["name"] for r in preview(client, target["id"])["tags"]]


def test_batch_duplicate_ids_rejected_before_writing(client):
    item = bare_item(client, "テストダウンジャケット")
    category = preview(client, item["id"])["category"]["category_id"]
    entry = {"item_id": item["id"], "version": item["version"], "category_id": category}
    response = client.post(f"{API}/tag-suggestions/batch", json={"items": [entry, entry]})
    assert response.status_code == 422, response.text
    assert get(client, "/proposals")["total"] == 0


def test_preview_and_creation_protect_original_rows(client, settings):
    target = bare_item(client, "テストダウンジャケット")

    def dump():
        with sqlite3.connect(settings.db_path) as db:
            return "\n".join(db.iterdump())

    original = dump()
    out = preview(client, target["id"])
    ok(client.get(f"{API}/tag-suggestions"))
    assert dump() == original
    before = get(client, f"/items/{target['id']}")
    p = ok(create(client, target["id"], target["version"], category_id=out["category"]["category_id"]), 201)
    assert get(client, f"/items/{target['id']}") == before
    assert p["proposals"][0]["status"] == "pending"


# ───────────── 修复回归（PHASE5C_FIXES_2026-10-28.md） ─────────────


def tag_names(client, item_id):
    return [t["name"] for t in preview(client, item_id)["tags"]]


def test_tag_evidence_ignores_shared_tags_or_same_top_level_only(client):
    # 目标：短袖T恤（上衣 / T恤·针织 / 短袖T恤），带「通勤」「周末」
    t = new_item(client, "目标", "tops-tshirt-short", None, ["通勤", "周末"])
    for i in range(3):  # 只共有 2 个标签（4 分），分类不同大类：5B 会推荐，但不是标签证据
        new_item(client, f"共有标签{i}", "bottoms-jeans", None, ["通勤", "周末", "夏"])
    for i in range(3):  # 只同属一级分类「上衣」（1 分）+ 共有 2 个标签：5 分，仍不是标签证据
        new_item(client, f"同一级{i}", "tops-shirt-oxford", None, ["通勤", "周末", "秋"])
    assert len(ok(client.get(f"{API}/items/{t['id']}/similar"))["items"]) == 6  # 5B 的展示规则不变
    assert tag_names(client, t["id"]) == []


def test_tag_evidence_counts_same_group_items(client):
    t = new_item(client, "目标", "tops-tshirt-short", None)
    a = new_item(client, "长袖1", "tops-tshirt-long", None, ["冬"])  # 同属「T恤·针织」：same_group
    b = new_item(client, "长袖2", "tops-tshirt-long", None, ["冬"])
    out = preview(client, t["id"])
    assert [x["name"] for x in out["tags"]] == ["冬"]
    assert out["tags"][0]["evidence"]["similar_item_ids"] == [b["id"], a["id"]]
    assert out["tags"][0]["evidence"]["similar_pool"] == 2
    assert out["similar_evidence_kinds"] == ["same_category", "same_group"]


def test_tag_evidence_pool_is_filtered_before_taking_the_top_ten(client):
    # 12 件不同品类、同色且共有标签的衣物在 5B 中得分更高（3 + 2 = 5），但不是标签证据；
    # 先过滤再取前 10，两件同类衣物（4 分）仍构成 2/2
    t = new_item(client, "目标", "outer-coat", NAVY, ["通勤"])
    for i in range(12):
        new_item(client, f"同色{i}", "bottoms-jeans", NAVY, ["通勤", "夏"])
    new_item(client, "同类1", "outer-coat", None, ["冬"])
    new_item(client, "同类2", "outer-coat", None, ["冬"])
    out = preview(client, t["id"])
    assert [x["name"] for x in out["tags"]] == ["冬"]
    assert out["tags"][0]["reasons"] == [{"kind": "similar_items", "label": "相似衣物中 2/2 件有此标签"}]


def test_tag_evidence_ratio_boundary(client):
    # 7 件同类：2/7 ≈ 28.6% < 30% 不建议；再加一件带标签的变成 3/8 = 37.5% 建议
    t = new_item(client, "目标", "outer-coat", None)
    for i in range(2):
        new_item(client, f"有{i}", "outer-coat", None, ["冬"])
    for i in range(5):
        new_item(client, f"无{i}", "outer-coat", None)
    assert tag_names(client, t["id"]) == []
    new_item(client, "有2", "outer-coat", None, ["冬"])
    assert tag_names(client, t["id"]) == ["冬"]


def test_tag_evidence_excludes_deleted_and_returned_items(client):
    t = new_item(client, "目标", "outer-coat", None)
    keep = new_item(client, "持有", "outer-coat", None, ["冬"])
    gone = new_item(client, "已删除", "outer-coat", None, ["冬"])
    ok(client.delete(f"{API}/items/{gone['id']}", params={"version": gone["version"]}), 204)
    ret = new_item(client, "已退货", "outer-coat", None, ["冬"])
    ok(client.post(f"{API}/items/{ret['id']}/return", json={"version": ret["version"], "returned_on": "2026-01-02"}))
    assert tag_names(client, t["id"]) == []  # 只有 1 件持有中的同类衣物，不足 2 件
    new_item(client, "持有2", "outer-coat", None, ["冬"])
    out = preview(client, t["id"])
    assert sorted(out["tags"][0]["evidence"]["similar_item_ids"])[0] == keep["id"]
    assert gone["id"] not in out["tags"][0]["evidence"]["similar_item_ids"]
    assert ret["id"] not in out["tags"][0]["evidence"]["similar_item_ids"]


@pytest.mark.parametrize(
    ("name", "slug"),
    [("ヒートテックインナー", "innerwear-heattech"), ("アウターダウンジャケット", "outer-down-jacket")],
)
def test_hits_within_one_top_level_category_still_pick_the_deepest(client, name, slug):
    # 「インナー」「アウター」本身也命中（同一个一级分类，不算跨大类）
    out = preview(client, bare_item(client, name)["id"])
    assert out["category"]["slug"] == slug and out["category_note"] is None


def test_batch_preview_matches_single_item_results(client):
    bare_item(client, "テストダウンジャケット")
    bare_item(client, "スウェットショートパンツ")
    t = new_item(client, "目标", "outer-coat", None)
    new_item(client, "同类1", "outer-coat", None, ["冬"])
    new_item(client, "同类2", "outer-coat", None, ["冬", "通勤"])
    p = make_product(client, identifiers=[], name_ja="同商品", category="outer-coat", colors=[])
    ok(client.post(f"{API}/items", json={"product_id": p["id"], "tags": ["雨天"]}), 201)
    ok(client.post(f"{API}/items", json={"product_id": p["id"]}), 201)
    batch = ok(client.get(f"{API}/tag-suggestions"))
    assert batch["total"] >= 4 and t["id"] in [x["item_id"] for x in batch["items"]]
    for row in batch["items"]:
        single = preview(client, row["item_id"])
        assert {k: v for k, v in row.items() if k != "item"} == {k: single[k] for k in row if k != "item"}


def test_duplicate_ids_rejected_but_distinct_items_still_work(client):
    a = bare_item(client, "テストダウンジャケット")
    b = bare_item(client, "テストダウンジャケット二号")
    ca = preview(client, a["id"])["category"]["category_id"]
    e = {"item_id": a["id"], "version": a["version"], "category_id": ca}
    f = {"item_id": b["id"], "version": b["version"], "category_id": ca}
    bad = err(client.post(f"{API}/tag-suggestions/batch", json={"items": [e, f, e]}), 422, "VALIDATION_ERROR")
    assert f"#{a['id']}" in str(bad)
    assert get(client, "/proposals")["total"] == 0
    out = ok(client.post(f"{API}/tag-suggestions/batch", json={"items": [e, f]}), 201)
    assert (out["succeeded"], out["failed"]) == (2, 0)


def _statements(app, fn):
    n = [0]

    def count(*_):
        n[0] += 1

    event.listen(app.state.engine, "before_cursor_execute", count)
    try:
        fn()
    finally:
        event.remove(app.state.engine, "before_cursor_execute", count)
    return n[0]


def test_batch_preview_reads_the_library_once_not_per_item(client, app):
    p = make_product(client, identifiers=[], name_ja="テストダウンジャケット", name_zh=None, category=None, colors=[])

    def grow(n):
        for _ in range(n):
            ok(client.post(f"{API}/items", json={"product_id": p["id"], "tags": []}), 201)

    def page():
        out = ok(client.get(f"{API}/tag-suggestions", params={"limit": 2}))
        assert len(out["items"]) == 2

    grow(5)
    small = _statements(app, page)
    grow(25)
    large = _statements(app, page)
    assert large == small  # 30 件与 5 件的 SQL 次数相同：只随页大小而非衣物总数变化


# ───────────── 商品名称中的常用叫法（wardrobe-tagcat/3） ─────────────


def reasons_of(client, item_id, name):
    return next(t["reasons"] for t in preview(client, item_id)["tags"] if t["name"] == name)


@pytest.mark.parametrize("category", [None, "tops-sweat"])
def test_name_gives_several_common_names(client, category):
    item = bare_item(client, "スムーススウェットパーカ", category)
    assert tag_names(client, item["id"]) == ["卫衣", "帽衫", "连帽卫衣"]
    assert reasons_of(client, item["id"], "帽衫") == [
        {"kind": "name_alias", "label": "商品名称含「パーカ」（常用叫法）"}
    ]
    assert reasons_of(client, item["id"], "卫衣") == [
        {"kind": "name_alias", "label": "商品名称含「スウェット」（常用叫法）"}
    ]


def test_name_words_are_normalized(client):
    item = bare_item(client, "ｽｳｪｯﾄﾌｰﾃﾞｨ")  # 半角片假名
    assert tag_names(client, item["id"]) == ["卫衣", "帽衫", "连帽卫衣"]


@pytest.mark.parametrize(
    ("name", "category", "expected"),
    [
        # 已有分类：只用同一级分类的词条
        ("スウェットショートパンツ", "bottoms-shorts", []),
        ("Tシャツワンピース", "dresses", ["连衣裙"]),
        ("ニットスカート", "bottoms-skirt", ["半身裙"]),
        # 还没有分类：命中的词条跨一级分类就都不用
        ("スウェットショートパンツ", None, []),
        ("ニットスカート", None, []),
        # 不限品类的词条（材质）照常使用
        ("デニムジャケット", "outer-jacket", ["夹克", "牛仔"]),
        ("デニムスカート", None, ["半身裙", "牛仔"]),
        # 长词先去掉：Tシャツ 不是衬衫
        ("クルーネックTシャツ", None, ["T恤"]),
        # 名称中的分类名也参与判断：未分类时「ダウン」（外套）与「シャツ」（上衣）跨一级分类；分类后按所属分类
        ("ボタンダウンシャツ", None, []),
        ("ボタンダウンシャツ", "tops-shirt-oxford", ["衬衫"]),
        ("テストダウンジャケット", None, ["夹克", "羽绒服"]),
        ("同商品", None, []),
    ],
)
def test_name_tags_respect_the_top_level_category(client, name, category, expected):
    item = bare_item(client, name, category)
    assert sorted(tag_names(client, item["id"])) == sorted(expected)


def test_name_tags_skip_tags_the_item_already_has(client):
    p = make_product(client, identifiers=[], name_ja="スムーススウェットパーカ", name_zh=None, category=None, colors=[])
    item = ok(client.post(f"{API}/items", json={"product_id": p["id"], "tags": ["帽衫"]}), 201)
    assert tag_names(client, item["id"]) == ["卫衣", "连帽卫衣"]


def test_name_and_similar_evidence_merge_and_same_product_comes_first(client):
    p = make_product(
        client, identifiers=[], name_ja="スムーススウェットパーカ", name_zh=None, category="tops-sweat", colors=[]
    )
    target = ok(client.post(f"{API}/items", json={"product_id": p["id"], "color_code": None}), 201)
    ok(client.post(f"{API}/items", json={"product_id": p["id"], "tags": ["运动"]}), 201)
    new_item(client, "同类1", "tops-sweat", None, ["卫衣"])
    new_item(client, "同类2", "tops-sweat", None, ["卫衣"])
    tags = preview(client, target["id"])["tags"]
    assert [t["name"] for t in tags] == ["运动", "卫衣", "帽衫", "连帽卫衣"]
    kinds = [r["kind"] for r in tags[1]["reasons"]]
    assert kinds == ["name_alias", "similar_items"]
    assert tags[1]["evidence"]["name_words"] == ["スウェット"]


def test_name_tags_count_towards_the_limit(client):
    item = bare_item(client, "フリースパーカスウェットセーター", "tops-sweat")
    # 命中 パーカ / スウェット / セーター（上衣），フリース 属于外套被排除；共 5 个叫法，正好是上限
    assert tag_names(client, item["id"]) == ["卫衣", "帽衫", "毛衣", "连帽卫衣", "针织衫"]
    assert preview(client, item["id"])["max_tags"] == 5


def test_name_tag_proposal_creates_the_new_tag_on_accept(client):
    item = bare_item(client, "スムーススウェットパーカ", "tops-sweat")
    out = ok(create(client, item["id"], item["version"], ["帽衫"]), 201)
    prop = out["proposals"][0]
    assert prop["proposed_value"] == ["帽衫"]
    ctx = prop["rule_context"]
    assert ctx["algorithm"] == "wardrobe-tagcat/3"
    assert ctx["evidence"]["tags"][0]["evidence"]["name_words"] == ["パーカ"]
    ok(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"))
    assert get(client, f"/items/{item['id']}")["tags"] == ["帽衫"]
    assert "帽衫" not in tag_names(client, item["id"])


def test_batch_lists_items_with_only_name_suggestions(client):
    item = bare_item(client, "スムーススウェットパーカ", "tops-sweat")
    rows = ok(client.get(f"{API}/tag-suggestions"))["items"]
    row = next(r for r in rows if r["item_id"] == item["id"])
    assert [t["name"] for t in row["tags"]] == ["卫衣", "帽衫", "连帽卫衣"]


# ───────────── 分类别名与弱分类（wardrobe-tagcat/3） ─────────────


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("ポケモン UT", "tops-tshirt"),
        ("マンガUT 集英社創業100周年", "tops-tshirt"),
        ("ドライEXクルーネックT", "tops-tshirt"),
        ("エアリズムシームレスショーツ/ジャストウエスト", "innerwear-underwear"),  # 长词先去掉，不算短裤
        ("ウルトラストレッチアクティブショーツ", "bottoms-shorts"),
        ("ナイロンキュロット", "bottoms-skirt"),
        ("コットンボクサーブリーフ/前開き", "innerwear-underwear"),
        ("50色ソックス", "innerwear-socks"),
        ("UVカットシェードキャップ", "accessories-hat"),
        ("ファンクショナルバックパック", "bags"),
        ("レースアップブーツ", "shoes"),
        ("シルクネクタイ", "accessories"),
        # 弱分类：命中上衣以外、且不是其上级的分类时让位
        ("ヒートテックソックス/パイル", "innerwear-socks"),
        ("ヒートテックリブビーニー", "accessories-hat"),
        ("ヒートテックマフラー", "accessories-scarf"),
        ("ヒートテックタイツ/前開き", "innerwear-heattech"),  # 「タイツ」→ 内衣，是上级，保留更细的
        ("ヒートテックインナー", "innerwear-heattech"),  # 「インナー」是上级，保留更细的保暖内衣
        ("エアリズムキャミソール", "innerwear-airism"),  # 只有弱分类时照常
    ],
)
def test_category_aliases_and_weak_categories(client, name, slug):
    out = preview(client, bare_item(client, name)["id"])
    assert out["category"] is not None and out["category"]["slug"] == slug, (
        name,
        out["category"],
        out["category_note"],
    )


@pytest.mark.parametrize(
    "name",
    [
        "ヒートテックVネックT",  # 系列名与上衣：可能是内衣，也可能是 T 恤
        "エアリズムクルーネックT",
        "UTILITY OUTER",  # UT 不能是更长英文单词的一部分
    ],
)
def test_weak_category_with_tops_or_embedded_alias_gives_no_category(client, name):
    out = preview(client, bare_item(client, name)["id"])
    if name.startswith("UTILITY"):
        assert out["category"] is None or out["category"]["slug"] != "tops-tshirt"
    else:
        assert out["category"] is None and out["category_note"] == "ambiguous"


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("エアリズムコットンカノコポロシャツ", None),
        ("ドライカノコポロシャツ", "tops-polo"),
    ],
)
def test_polo_shirts_are_not_tagged_as_shirts(client, name, category):
    assert "衬衫" not in tag_names(client, bare_item(client, name, category)["id"])


def test_a_real_shirt_next_to_polo_wording_is_still_a_shirt(client):
    # 只去掉「ポロシャツ」这个词，名称里另有「シャツ」时仍建议衬衫
    assert "衬衫" in tag_names(client, bare_item(client, "ポロシャツ風オープンカラーシャツ", "tops-shirt")["id"])
