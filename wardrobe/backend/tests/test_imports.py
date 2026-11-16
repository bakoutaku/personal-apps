"""批量导入：格式校验、预览不改数据、提交、匹配去重、核实保护、错误处理、预览过期。"""

import copy

import pytest
from helpers import API, err, get, make_product, make_purchase, ok
from import_helpers import BASE_PAYLOAD, actions, commit, counts, payload, preview, run_import

# ───────────── 格式与引用校验 ─────────────


def test_schema_endpoint(client):
    out = ok(client.get(f"{API}/imports/schema"))
    assert out["format"] == "wardrobe.import/v1"
    assert "products" in out["schema"]["properties"]


@pytest.mark.parametrize(
    ("mutate", "loc"),
    [
        (lambda p: p["purchases"][0]["lines"][0].update(color_hex="1f2a44"), ["purchases", 0, "lines", 0, "color_hex"]),
        (lambda p: p["products"][0].update(nmae_ja="typo"), ["products", 0, "nmae_ja"]),
        (lambda p: p.update(format="other/v9"), ["format"]),
        (lambda p: p["items"][0].update(purchase_line_ref="nope"), ["items", 0, "purchase_line_ref"]),
        (lambda p: p["outfits"][0]["items"][0].update(item_ref="nope"), ["outfits", 0, "items", 0, "item_ref"]),
        (lambda p: p["products"].append(copy.deepcopy(p["products"][0])), ["products", 1, "ref"]),
    ],
)
def test_payload_errors_point_to_field_and_create_no_job(client, mutate, loc):
    body = payload()
    mutate(body)
    e = err(client.post(f"{API}/imports", json=body), 422, "VALIDATION_ERROR")
    assert loc in [d["loc"][: len(loc)] for d in e["details"]], e["details"]
    assert ok(client.get(f"{API}/imports"))["total"] == 0


def test_empty_payload_rejected(client):
    err(client.post(f"{API}/imports", json={"format": "wardrobe.import/v1"}), 422, "VALIDATION_ERROR")


# ───────────── 预览与提交 ─────────────


def test_preview_changes_nothing(client, app):
    from sqlalchemy import func, select

    from wardrobe.models import ChangeLog

    before = counts(client)
    with app.state.sessionmaker() as s:
        logs_before = s.scalar(select(func.count()).select_from(ChangeLog))
    job = preview(client, payload())
    assert job["status"] == "previewed" and job["can_commit"]
    assert actions(job) == [
        ("product", "create"),
        ("purchase", "create"),
        ("purchase_line", "create"),
        ("wardrobe_item", "update"),  # 对应 create_items 生成的第一件
        ("outfit", "create"),
    ]
    assert all(r["target_id"] is None for r in job["rows"] if r["action"] == "create")
    assert counts(client) == before
    with app.state.sessionmaker() as s:
        assert s.scalar(select(func.count()).select_from(ChangeLog)) == logs_before
    assert ok(client.get(f"{API}/search", params={"q": "インポート"}))["items"] == []


def test_commit_creates_everything_and_tags_change_log(client, app, settings):
    from sqlalchemy import select

    from wardrobe.models import ChangeLog

    job = run_import(client, payload())
    assert job["status"] == "committed" and job["backup_file"].startswith("wardrobe-")
    assert (settings.backups_dir / job["backup_file"]).exists()
    items = ok(client.get(f"{API}/items"))["items"]
    assert len(items) == 2
    tagged = [i for i in items if i["tags"] == ["导入标签"]]
    assert len(tagged) == 1 and tagged[0]["resolved"]["color"]["name"] == "NAVY"
    assert ok(client.get(f"{API}/items", params={"q": "インポート"}))["total"] == 2
    outfit = ok(client.get(f"{API}/outfits"))["items"][0]
    assert outfit["items"][0]["item"]["id"] == tagged[0]["id"]
    with app.state.sessionmaker() as s:
        logs = s.scalars(select(ChangeLog).where(ChangeLog.import_job_id == job["job_id"])).all()
    assert {log.entity for log in logs} >= {"product", "purchase", "wardrobe_item", "outfit", "tag"}
    assert all(log.actor.startswith("import:") or log.actor == "system" for log in logs)


def test_reimport_is_idempotent(client):
    run_import(client, payload())
    before = counts(client)
    job = preview(client, payload())
    assert {a for _, a in actions(job)} == {"skip"}
    assert job["summary"]["job_warnings"][0]["code"] == "duplicate_payload"
    commit(client, job["job_id"])
    assert counts(client) == before


def test_commit_only_once_and_discard(client):
    job = preview(client, payload())
    commit(client, job["job_id"])
    err(client.post(f"{API}/imports/{job['job_id']}/commit"), 409, "IMPORT_NOT_PREVIEWED")
    other = preview(client, payload(source_label="另一批"))
    assert ok(client.delete(f"{API}/imports/{other['job_id']}"))["status"] == "discarded"
    err(client.post(f"{API}/imports/{other['job_id']}/commit"), 409, "IMPORT_NOT_PREVIEWED")


def test_rows_endpoint_filters(client):
    job = preview(client, payload())
    rows = ok(client.get(f"{API}/imports/{job['job_id']}/rows", params={"entity": "product"}))["items"]
    assert [r["entity"] for r in rows] == ["product"]


# ───────────── 匹配与去重（R2） ─────────────


def test_matches_existing_product_by_same_scheme_identifier(client):
    existing = make_product(client, identifiers=[{"scheme": "detail_page_id", "value": "e888001-000"}])
    job = preview(client, payload(purchases=[], items=[], outfits=[]))
    (row,) = job["rows"]
    assert (row["action"], row["target_id"], row["match_reason"]) == (
        "update", existing["id"], "identifier:detail_page_id",
    )  # fmt: skip


def test_receipt_code_never_matches_detail_page_id(client):
    """小票商品番号 888001 看起来是详情页编号的一部分，但不同编号体系绝不自动等同。"""
    make_product(client, identifiers=[{"scheme": "detail_page_id", "value": "E888001-000"}])
    body = payload(products=[{"ref": "p1", "brand": "uniqlo", "name_ja": "別の名前",
                              "identifiers": [{"scheme": "item_no", "value": "888001"}]}],
                   purchases=[], items=[], outfits=[])  # fmt: skip
    assert actions(preview(client, body)) == [("product", "create")]


def test_same_identifier_other_brand_is_not_a_match(client):
    make_product(client, brand="gu", identifiers=[{"scheme": "detail_page_id", "value": "E888001-000"}])
    job = preview(client, payload(purchases=[], items=[], outfits=[]))
    assert actions(job) == [("product", "create")]


def test_name_match_without_identifiers_warns(client):
    existing = make_product(client, identifiers=[], name_ja="ｲﾝﾎﾟｰﾄﾀﾞｳﾝ")
    body = payload(products=[{"ref": "p1", "brand": "uniqlo", "name_ja": "インポートダウン"}],
                   purchases=[], items=[], outfits=[])  # fmt: skip
    (row,) = preview(client, body)["rows"]
    assert row["target_id"] == existing["id"] and row["match_reason"] == "name:name_ja"
    assert row["warnings"][0]["code"] == "matched_by_name"


def test_ambiguous_identifiers_are_an_error(client):
    make_product(client, identifiers=[{"scheme": "detail_page_id", "value": "E1-000"}], name_ja="A")
    make_product(client, identifiers=[{"scheme": "item_no", "value": "2"}], name_ja="B")
    body = payload(products=[{"ref": "p1", "brand": "uniqlo", "name_ja": "C", "identifiers": [
        {"scheme": "detail_page_id", "value": "E1-000"}, {"scheme": "item_no", "value": "2"}]}],
        purchases=[], items=[], outfits=[])  # fmt: skip
    (row,) = preview(client, body)["rows"]
    assert row["action"] == "error" and row["errors"][0]["code"] == "AMBIGUOUS_MATCH"


def test_purchase_without_order_no_is_matched_by_exact_content(client):
    body = payload(items=[], outfits=[])
    body["purchases"][0].pop("order_no")
    run_import(client, body)
    job = preview(client, body)
    assert actions(job)[1:3] == [("purchase", "skip"), ("purchase_line", "skip")]
    assert job["rows"][1]["match_reason"] == "exact_duplicate"


# ───────────── on_existing 模式 ─────────────


@pytest.fixture
def existing(client):
    return make_product(client, identifiers=[{"scheme": "detail_page_id", "value": "E888001-000"}],
                        name_zh=None, notes="原备注", colors=[], sizes=[])  # fmt: skip


def _product_only(**fields):
    return payload(products=[{"ref": "p1", "brand": "uniqlo", "identifiers": [
        {"scheme": "detail_page_id", "value": "E888001-000"}], **fields}], purchases=[], items=[], outfits=[])  # fmt: skip


def test_update_unverified_overwrites_and_appends_collections(client, existing):
    body = _product_only(name_zh="新中文名", notes="新备注",
                         colors=[{"color_code": "09", "name_ja": "BLACK", "is_default": True}],
                         identifiers=[{"scheme": "detail_page_id", "value": "E888001-000"},
                                      {"scheme": "item_no", "value": "888001"}])  # fmt: skip
    run_import(client, body)
    p = get(client, f"/products/{existing['id']}")
    assert (p["name_zh"], p["notes"]) == ("新中文名", "新备注")
    assert [c["name_ja"] for c in p["colors"]] == ["BLACK"]
    assert {i["scheme"] for i in p["identifiers"]} == {"detail_page_id", "item_no"}


def test_fill_empty_keeps_existing_values(client, existing):
    body = _product_only(name_zh="新中文名", notes="新备注")
    body["options"] = {"on_existing": "fill_empty"}
    run_import(client, body)
    p = get(client, f"/products/{existing['id']}")
    assert (p["name_zh"], p["notes"]) == ("新中文名", "原备注")


def test_skip_mode_changes_nothing(client, existing):
    body = _product_only(notes="新备注")
    body["options"] = {"on_existing": "skip"}
    job = run_import(client, body)
    assert actions(job) == [("product", "skip")]
    assert get(client, f"/products/{existing['id']}")["notes"] == "原备注"


def test_existing_default_color_is_kept(client):
    p = make_product(client, identifiers=[{"scheme": "detail_page_id", "value": "E888001-000"}])
    body = _product_only(colors=[{"color_code": "01", "name_ja": "WHITE", "is_default": True}])
    job = run_import(client, body)
    assert job["rows"][0]["warnings"][0]["code"] == "default_color_kept"
    colors = get(client, f"/products/{p['id']}")["colors"]
    assert [c["name_ja"] for c in colors if c["is_default"]] == ["BLACK"]


# ───────────── 已核实记录 → 修改提议 ─────────────


def test_import_never_overwrites_verified_data(client, ai):
    p = make_product(client, identifiers=[{"scheme": "detail_page_id", "value": "E888001-000"}])
    ok(client.post(f"{API}/products/{p['id']}/verify", json={"version": 1}))
    body = _product_only(name_ja="AI 认为的名字", notes="AI 备注", material_text="綿100%")
    job = preview(ai, body)
    assert job["rows"][0]["action"] == "update"  # notes 不受保护，直接生效
    committed = commit(ai, job["job_id"])
    after = get(client, f"/products/{p['id']}")
    assert after["name_ja"] == p["name_ja"] and after["material_text"] == p["material_text"]
    assert after["notes"] == "AI 备注"
    props = ok(client.get(f"{API}/proposals", params={"import_job_id": committed["job_id"]}))["items"]
    assert sorted(x["field"] for x in props) == ["material_text", "name_ja"]
    assert {x["actor"] for x in props} == {"import:ai:codex"}
    assert committed["summary"]["proposals"] == 2


def test_web_ui_import_also_proposes_for_verified(client):
    p = make_product(client, identifiers=[{"scheme": "detail_page_id", "value": "E888001-000"}])
    ok(client.post(f"{API}/products/{p['id']}/verify", json={"version": 1}))
    job = run_import(client, _product_only(name_ja="新名字"))
    assert actions(job) == [("product", "propose")]
    assert get(client, f"/products/{p['id']}")["name_ja"] == p["name_ja"]


# ───────────── 行级错误、部分提交、依赖 ─────────────


def _with_bad_category():
    body = payload()
    body["products"][0]["category"] = "no-such-category"
    return body


def test_row_errors_block_commit_and_cascade_to_dependents(client):
    job = preview(client, _with_bad_category())
    assert job["can_commit"] is False and job["summary"]["error"] == 5
    product_row = job["rows"][0]
    assert product_row["errors"][0]["details"][0]["loc"] == ["category"]
    assert all(r["errors"][0]["code"] == "dependency_failed" for r in job["rows"][1:])
    err(client.post(f"{API}/imports/{job['job_id']}/commit"), 409, "IMPORT_HAS_ERRORS")
    assert counts(client)["product"] == 0


def test_allow_partial_commits_good_rows_only(client):
    body = _with_bad_category()
    body["products"].append({"ref": "p2", "name_ja": "独立商品"})
    job = preview(client, body)
    done = commit(client, job["job_id"], allow_partial=True)
    assert done["status"] == "committed"
    assert [p["name_ja"] for p in ok(client.get(f"{API}/products"))["items"]] == ["独立商品"]


def test_capacity_is_enforced_for_imported_items(client):
    body = payload(outfits=[])
    body["purchases"][0]["create_items"] = False
    body["purchases"][0]["lines"][0]["quantity"] = 1
    body["items"] = [{"ref": "a", "purchase_line_ref": "l1"}, {"ref": "b", "purchase_line_ref": "l1"}]
    job = preview(client, body)
    assert [r["action"] for r in job["rows"][3:]] == ["create", "error"]
    assert job["rows"][4]["errors"][0]["code"] == "LINE_FULL"


def test_import_returned_item(client):
    p = make_product(client)
    body = payload(products=[], purchases=[], outfits=[],
                   items=[{"product_id": p["id"], "status": "returned", "acquired_on": "2025-01-01",
                           "retired_on": "2025-01-10", "refund_amount": 1000}])  # fmt: skip
    run_import(client, body)
    item = ok(client.get(f"{API}/items", params={"status": "returned"}))["items"][0]
    detail = get(client, f"/items/{item['id']}")
    assert (detail["retired_on"], detail["refund_amount"]) == ("2025-01-10", 1000)


def test_existing_item_by_line_slot_gets_tags(client):
    p = make_product(client)
    line = make_purchase(client, p["id"], quantity=1)["lines"][0]
    body = payload(products=[], purchases=[], outfits=[],
                   items=[{"purchase_line_id": line["id"], "tags": ["补标签"]}])  # fmt: skip
    job = run_import(client, body)
    assert job["rows"][0]["match_reason"] == "purchase_line_slot"
    assert get(client, f"/items/{line['item_ids'][0]}")["tags"] == ["补标签"]


def test_image_links(client):
    from helpers import upload

    img = ok(upload(client), 201)
    body = payload(purchases=[], items=[], outfits=[])
    body["products"][0]["images"] = [{"image_id": img["id"], "role": "main"}]
    run_import(client, body)
    product = ok(client.get(f"{API}/products"))["items"][0]
    assert [i["id"] for i in product["images"]] == [img["id"]]


# ───────────── 预览过期 ─────────────


def test_commit_rejects_stale_preview(client):
    job = preview(client, payload())
    assert job["rows"][0]["action"] == "create"
    make_product(client, identifiers=[{"scheme": "detail_page_id", "value": "E888001-000"}])  # 预览后才出现
    before = counts(client)
    e = err(client.post(f"{API}/imports/{job['job_id']}/commit"), 409, "PREVIEW_STALE")
    assert 0 in e["details"][0]["changed_rows"]
    assert counts(client) == before
    assert get(client, f"/imports/{job['job_id']}")["status"] == "previewed"


def test_payload_keys_are_preserved_for_audit(client):
    job = preview(client, BASE_PAYLOAD)
    assert job["payload_sha256"] and len(job["payload_sha256"]) == 64


def test_new_product_without_name_is_row_error(client):
    body = payload(products=[{"ref": "p1", "brand": "uniqlo", "identifiers": [{"scheme": "item_no", "value": "1"}]}],
                   purchases=[], items=[], outfits=[])  # fmt: skip
    (row,) = preview(client, body)["rows"]
    assert row["action"] == "error" and row["errors"][0]["code"] == "VALIDATION_ERROR"
