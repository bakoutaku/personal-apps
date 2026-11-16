"""Phase 2 审查（BUG-011 ~ BUG-015）补充回归：审查报告「建议回归测试」中列出的场景。"""

import pytest
from helpers import API, err, get, make_product, make_purchase, ok
from import_helpers import commit, counts, preview, run_import

FMT = "wardrobe.import/v1"


def _changes(client):
    return ok(client.get(f"{API}/changes", params={"limit": 1}))["total"]


# ───────────── BUG-011 预览之后的修改 ─────────────


def test_stale_when_subcollection_changed_after_preview(client):
    p = make_product(client)
    job = preview(client, {"format": FMT, "products": [{"id": p["id"], "notes": "导入"}]})
    ok(client.put(f"{API}/products/{p['id']}/sizes", json={"version": 1, "sizes": [{"size_label": "XS"}]}))
    before, logs = counts(client), _changes(client)
    e = err(client.post(f"{API}/imports/{job['job_id']}/commit"), 409, "PREVIEW_STALE")
    assert e["details"][0]["changed_rows"] == [0]
    assert counts(client) == before and _changes(client) == logs
    assert get(client, f"/products/{p['id']}")["notes"] is None


def test_stale_when_verified_record_changed_before_proposal_commit(client, ai):
    p = make_product(client)
    ok(client.post(f"{API}/products/{p['id']}/verify", json={"version": 1}))
    job = preview(ai, {"format": FMT, "products": [{"id": p["id"], "name_zh": "AI 提议"}]})
    assert job["rows"][0]["action"] == "propose"
    ok(client.patch(f"{API}/products/{p['id']}", json={"version": 2, "name_zh": "人工"}))
    err(ai.post(f"{API}/imports/{job['job_id']}/commit"), 409, "PREVIEW_STALE")
    assert ok(client.get(f"{API}/proposals"))["total"] == 0


def test_any_row_stale_blocks_whole_commit(client):
    a = make_product(client, identifiers=[], name_ja="A")
    b = make_product(client, identifiers=[], name_ja="B")
    job = preview(client, {"format": FMT, "products": [{"id": a["id"], "notes": "a"}, {"id": b["id"], "notes": "b"}]})
    ok(client.patch(f"{API}/products/{b['id']}", json={"version": 1, "description": "人工"}))
    e = err(client.post(f"{API}/imports/{job['job_id']}/commit"), 409, "PREVIEW_STALE")
    assert e["details"][0]["changed_rows"] == [1]
    assert get(client, f"/products/{a['id']}")["notes"] is None  # 第一行也没有写入


def test_repreview_after_stale_commits(client):
    p = make_product(client)
    body = {"format": FMT, "products": [{"id": p["id"], "notes": "导入"}]}
    stale = preview(client, body)
    ok(client.patch(f"{API}/products/{p['id']}", json={"version": 1, "description": "人工"}))
    err(client.post(f"{API}/imports/{stale['job_id']}/commit"), 409, "PREVIEW_STALE")
    run_import(client, body)
    after = get(client, f"/products/{p['id']}")
    assert (after["notes"], after["description"]) == ("导入", "人工")


def test_unrelated_changes_do_not_make_preview_stale(client):
    p = make_product(client)
    other = make_product(client, identifiers=[], name_ja="无关")
    job = preview(client, {"format": FMT, "products": [{"id": p["id"], "notes": "导入"}]})
    ok(client.patch(f"{API}/products/{other['id']}", json={"version": 1, "notes": "无关修改"}))
    commit(client, job["job_id"])


# ───────────── BUG-012 / 013 无订单号购买的匹配 ─────────────


def _purchase(lines, **header):
    return {"format": FMT, "purchases": [{"purchased_on": "2026-01-01", "store_name": "店", **header, "lines": lines}]}


def test_mixed_missing_fields_and_reordered_lines_are_idempotent(client):
    p = make_product(client)
    lines = [
        {"product_id": p["id"], "color_name": "BLACK"},
        {"product_id": p["id"], "item_code_raw": "1", "size_label": "M", "unit_price": 990},
        {"product_id": p["id"]},
        {"product_id": p["id"]},  # 完全相同的两行按数量计
    ]
    run_import(client, _purchase(lines))
    job = preview(client, _purchase(list(reversed(lines))))
    assert job["rows"][0]["action"] == "skip" and job["rows"][0]["match_reason"] == "exact_duplicate"
    assert counts(client)["purchase"] == 1


def test_one_extra_identical_line_is_a_different_purchase(client):
    p = make_product(client)
    run_import(client, _purchase([{"product_id": p["id"]}]))
    run_import(client, _purchase([{"product_id": p["id"]}, {"product_id": p["id"]}]))
    assert counts(client)["purchase"] == 2


def test_any_differing_fact_creates_separate_purchase(client):
    p = make_product(client)
    base = [{"product_id": p["id"], "unit_price": 1000}]
    run_import(client, _purchase(base))
    variants = [
        _purchase(base, channel="online"),
        _purchase(base, currency="USD"),
        _purchase(base, total_amount=1000),
        _purchase([{**base[0], "color_hex": "#000000"}]),
        _purchase([{**base[0], "name_raw": "小票名称"}]),
    ]
    for v in variants:
        assert preview(client, v)["rows"][0]["action"] == "create"
    original = ok(client.get(f"{API}/purchases"))["items"][0]
    assert original["channel"] == "store" and original["lines"][0]["discount_amount"] is None


def test_two_identical_purchases_in_one_import_stay_two(client):
    p = make_product(client)
    body = _purchase([{"product_id": p["id"]}])
    body["purchases"].append(dict(body["purchases"][0]))
    run_import(client, body)
    assert counts(client)["purchase"] == 2
    again = preview(client, body)  # 重复导入：两笔分别对应已有的两笔
    assert [r["action"] for r in again["rows"] if r["entity"] == "purchase"] == ["skip", "skip"]
    assert len({r["target_id"] for r in again["rows"] if r["entity"] == "purchase"}) == 2


def test_explicit_id_still_updates_purchase(client):
    p = make_product(client)
    pur = make_purchase(client, p["id"], create_items=False)
    run_import(client, {"format": FMT, "purchases": [{"id": pur["id"], "notes": "按 id 修改"}]})
    assert get(client, f"/purchases/{pur['id']}")["notes"] == "按 id 修改"


# ───────────── BUG-014 已有衣物的关联修改 ─────────────


def _two_lines(client):
    p = make_product(client)
    la = make_purchase(client, p["id"], create_items=False)["lines"][0]["id"]
    lb = make_purchase(client, p["id"], create_items=False)["lines"][0]["id"]
    item = ok(client.post(f"{API}/items", json={"product_id": p["id"], "purchase_line_id": la}), 201)
    return p, la, lb, item


def test_relink_by_ref_unlink_with_null_and_omit_keeps(client):
    p, la, _, item = _two_lines(client)
    body = {"format": FMT, "purchases": [{"purchased_on": "2026-02-02", "lines": [{"ref": "new", "product_id": p["id"]}]}],
            "items": [{"id": item["id"], "purchase_line_ref": "new"}]}  # fmt: skip
    run_import(client, body)
    new_line = ok(client.get(f"{API}/purchases", params={"date_from": "2026-02-02"}))["items"][0]["lines"][0]["id"]
    assert get(client, f"/items/{item['id']}")["purchase_line_id"] == new_line
    run_import(client, {"format": FMT, "items": [{"id": item["id"], "notes": "不改关联"}]})
    assert get(client, f"/items/{item['id']}")["purchase_line_id"] == new_line
    run_import(client, {"format": FMT, "items": [{"id": item["id"], "purchase_line_id": None}]})
    assert get(client, f"/items/{item['id']}")["purchase_line_id"] is None


def test_relink_to_full_or_mismatched_line_is_row_error(client):
    p, la, lb, item = _two_lines(client)
    ok(client.post(f"{API}/items", json={"product_id": p["id"], "purchase_line_id": lb}), 201)  # lb 已满
    job = preview(client, {"format": FMT, "items": [{"id": item["id"], "purchase_line_id": lb}]})
    assert job["rows"][0]["errors"][0]["code"] == "LINE_FULL"
    other = make_product(client, identifiers=[], name_ja="别的商品")
    lo = make_purchase(client, other["id"], create_items=False)["lines"][0]["id"]
    job = preview(client, {"format": FMT, "items": [{"id": item["id"], "purchase_line_id": lo}]})
    assert job["rows"][0]["errors"][0]["details"][0]["code"] == "product_mismatch"


def test_relink_verified_item_becomes_proposal(client, ai):
    _, la, lb, item = _two_lines(client)
    ok(client.post(f"{API}/items/{item['id']}/verify", json={"version": 1}))
    job = commit(ai, preview(ai, {"format": FMT, "items": [{"id": item["id"], "purchase_line_id": lb}]})["job_id"])
    assert job["rows"][0]["action"] == "propose"
    assert get(client, f"/items/{item['id']}")["purchase_line_id"] == la


def test_revert_restores_link_or_reports_conflict(client):
    p, la, lb, item = _two_lines(client)
    job = run_import(client, {"format": FMT, "items": [{"id": item["id"], "purchase_line_id": lb}]})
    ok(client.post(f"{API}/imports/{job['job_id']}/revert"))
    assert get(client, f"/items/{item['id']}")["purchase_line_id"] == la

    job = run_import(client, {"format": FMT, "items": [{"id": item["id"], "purchase_line_id": lb}]})
    ok(client.post(f"{API}/items", json={"product_id": p["id"], "purchase_line_id": la}), 201)  # 原明细被占满
    e = err(client.post(f"{API}/imports/{job['job_id']}/revert"), 409, "REVERT_CONFLICT")
    assert e["details"][0]["reason"] == "link_no_longer_valid"
    assert get(client, f"/items/{item['id']}")["purchase_line_id"] == lb


# ───────────── BUG-015 多个编号 ─────────────


def _verified_product(client, **kw):
    p = make_product(client, **kw)
    return ok(client.post(f"{API}/products/{p['id']}/verify", json={"version": 1}))


def _idents(client, pid):
    return {(i["scheme"], i["value"]) for i in get(client, f"/products/{pid}")["identifiers"]}


def test_existing_plus_several_new_identifiers_one_proposal(client, ai):
    p = _verified_product(client)
    wanted = [{"scheme": "item_no", "value": "A-1"}, {"scheme": "sku", "value": "B-2"}, {"scheme": "jan", "value": "4"}]
    job = commit(ai, preview(ai, {"format": FMT, "products": [{"id": p["id"], "identifiers": wanted}]})["job_id"])
    (prop,) = ok(client.get(f"{API}/proposals", params={"import_job_id": job["job_id"]}))["items"]
    assert len(prop["proposed_value"]) == 4  # 原有 1 个 + 新增 3 个
    ok(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"))
    assert _idents(client, p["id"]) == {("detail_page_id", "E999001-000"), ("item_no", "A-1"), ("sku", "B-2"),
                                        ("jan", "4")}  # fmt: skip


def test_same_value_in_two_schemes_is_kept_separate(client, ai):
    p = _verified_product(client, identifiers=[])
    wanted = [{"scheme": "item_no", "value": "777"}, {"scheme": "sku", "value": "777"}]
    job = commit(ai, preview(ai, {"format": FMT, "products": [{"id": p["id"], "identifiers": wanted}]})["job_id"])
    (prop,) = ok(client.get(f"{API}/proposals", params={"import_job_id": job["job_id"]}))["items"]
    ok(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"))
    assert _idents(client, p["id"]) == {("item_no", "777"), ("sku", "777")}


def test_one_invalid_identifier_fails_row_atomically(client, ai):
    make_product(client, identifiers=[{"scheme": "sku", "value": "TAKEN"}], name_ja="占用者")
    p = _verified_product(client, identifiers=[], name_ja="目标")
    wanted = [{"scheme": "item_no", "value": "OK-1"}, {"scheme": "sku", "value": "TAKEN"}]
    job = preview(ai, {"format": FMT, "products": [{"id": p["id"], "identifiers": wanted}]})
    assert job["rows"][0]["action"] == "error" and job["rows"][0]["errors"][0]["code"] == "DUPLICATE"


def test_two_rows_for_same_product_merge_identifier_proposals(client, ai):
    p = _verified_product(client, identifiers=[])
    body = {"format": FMT, "products": [
        {"id": p["id"], "identifiers": [{"scheme": "item_no", "value": "R1"}]},
        {"id": p["id"], "identifiers": [{"scheme": "sku", "value": "R2"}]},
    ]}  # fmt: skip
    job = commit(ai, preview(ai, body)["job_id"])
    pending = ok(client.get(f"{API}/proposals", params={"import_job_id": job["job_id"]}))["items"]
    assert len(pending) == 1 and {i["value"] for i in pending[0]["proposed_value"]} == {"R1", "R2"}


def test_unverified_product_gets_all_identifiers_directly(client):
    p = make_product(client, identifiers=[])
    wanted = [{"scheme": "item_no", "value": "U1"}, {"scheme": "sku", "value": "U2"}]
    run_import(client, {"format": FMT, "products": [{"id": p["id"], "identifiers": wanted}]})
    assert _idents(client, p["id"]) == {("item_no", "U1"), ("sku", "U2")}


def test_revert_withdraws_identifier_proposal_and_reject_leaves_product(client, ai):
    p = _verified_product(client, identifiers=[])
    body = {"format": FMT, "products": [{"id": p["id"], "identifiers": [{"scheme": "item_no", "value": "W1"}]}]}
    job = commit(ai, preview(ai, body)["job_id"])
    out = ok(client.post(f"{API}/imports/{job['job_id']}/revert"))
    assert out["revert"]["proposals_withdrawn"] == 1
    job2 = commit(ai, preview(ai, body)["job_id"])
    (prop,) = ok(client.get(f"{API}/proposals", params={"import_job_id": job2["job_id"]}))["items"]
    ok(client.post(f"{API}/proposals/{prop['proposal_id']}/reject"))
    assert _idents(client, p["id"]) == set()


# ───────────── BUG-011 复查：所有实体类型、穿搭的各种修改 ─────────────


def _setup_targets(client):
    p = make_product(client)
    pur = make_purchase(client, p["id"], quantity=2)
    line = pur["lines"][0]
    item_id = line["item_ids"][0]
    outfit = ok(client.post(f"{API}/outfits", json={"name": "原穿搭", "items": [{"item_id": item_id}]}), 201)
    return {"product": p["id"], "purchase": pur["id"], "line": line["id"], "item": item_id, "outfit": outfit["id"]}


# (导入内容, 预览之后的人工修改)
ENTITY_CASES = {
    "product": (lambda t: {"products": [{"id": t["product"], "notes": "导入"}]},
                lambda c, t: c.patch(f"{API}/products/{t['product']}", json={"version": 1, "description": "人工"})),
    "purchase": (lambda t: {"purchases": [{"id": t["purchase"], "notes": "导入"}]},
                 lambda c, t: c.patch(f"{API}/purchases/{t['purchase']}", json={"version": 1, "total_amount": 1})),
    "purchase_line": (lambda t: {"purchases": [{"id": t["purchase"], "lines": [{"id": t["line"], "notes": "导入"}]}]},
                      lambda c, t: c.patch(f"{API}/purchase-lines/{t['line']}", json={"version": 1, "unit_price": 1})),
    "wardrobe_item": (lambda t: {"items": [{"id": t["item"], "notes": "导入"}]},
                      lambda c, t: c.patch(f"{API}/items/{t['item']}", json={"version": 1, "location": "人工"})),
    "outfit": (lambda t: {"outfits": [{"id": t["outfit"], "description": "导入"}]},
               lambda c, t: c.patch(f"{API}/outfits/{t['outfit']}", json={"version": 1, "occasion": "人工"})),
}  # fmt: skip


@pytest.mark.parametrize("entity", list(ENTITY_CASES))
def test_every_entity_type_detects_changes_after_preview(client, entity):
    targets = _setup_targets(client)
    build, human_edit = ENTITY_CASES[entity]
    job = preview(client, {"format": FMT, **build(targets)})
    row = next(r for r in job["rows"] if r["entity"] == entity)
    assert row["action"] == "update" and isinstance(row["diff"]["basis_version"], int)
    ok(human_edit(client, targets))
    before, logs = counts(client), _changes(client)
    err(client.post(f"{API}/imports/{job['job_id']}/commit"), 409, "PREVIEW_STALE")
    assert counts(client) == before and _changes(client) == logs


def test_outfit_matched_by_name_tags_and_cover_changes_are_detected(client):
    from helpers import upload

    t = _setup_targets(client)
    img = ok(upload(client), 201)
    body = {"format": FMT, "outfits": [{"name": "原穿搭", "description": "导入"}]}  # 按名称匹配
    for edit in (
        lambda v: client.put(f"{API}/outfits/{t['outfit']}/tags", json={"version": v, "tags": ["人工"]}),
        lambda v: client.patch(f"{API}/outfits/{t['outfit']}", json={"version": v, "cover_image_id": img["id"]}),
    ):
        job = preview(client, body)
        assert job["rows"][0]["match_reason"] == "name"
        ok(edit(get(client, f"/outfits/{t['outfit']}")["version"]))
        err(client.post(f"{API}/imports/{job['job_id']}/commit"), 409, "PREVIEW_STALE")
    assert get(client, f"/outfits/{t['outfit']}")["description"] is None


def test_one_stale_outfit_in_mixed_batch_blocks_everything(client):
    t = _setup_targets(client)
    body = {"format": FMT, "products": [{"id": t["product"], "notes": "导入"}],
            "outfits": [{"id": t["outfit"], "description": "导入"}]}  # fmt: skip
    job = preview(client, body)
    ok(client.put(f"{API}/outfits/{t['outfit']}/items", json={"version": 1, "items": []}))
    err(client.post(f"{API}/imports/{job['job_id']}/commit"), 409, "PREVIEW_STALE")
    assert get(client, f"/products/{t['product']}")["notes"] is None


def test_missing_basis_version_fails_loudly(client, monkeypatch):
    """防回归：若某个分支漏记版本，整个请求失败且零修改，而不是静默允许覆盖。"""
    from wardrobe.api.import_executor import ImportExecutor

    t = _setup_targets(client)
    monkeypatch.setattr(ImportExecutor, "_basis", staticmethod(lambda row, obj: None))
    before = counts(client)
    err(client.post(f"{API}/imports", json={"format": FMT, "outfits": [{"id": t["outfit"], "description": "x"}]}),
        500, "INTERNAL_INVARIANT")  # fmt: skip
    assert counts(client) == before
