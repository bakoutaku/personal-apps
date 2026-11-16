"""导入撤销（BUG-003 / DATA_MODEL 5.1）：整批、原子、冲突零修改、幂等、共享标签、批内多次修改、已接受提议。"""

from helpers import API, err, get, make_product, make_purchase, ok
from import_helpers import commit, counts, payload, preview, run_import


def _revert(client, job_id, status=200):
    return ok(client.post(f"{API}/imports/{job_id}/revert"), status)


def _search_ids(client, q):
    return {i["id"] for i in ok(client.get(f"{API}/items", params={"q": q, "status": "all"}))["items"]}


def test_revert_removes_everything_the_import_created(client, settings):
    before = counts(client)
    job = run_import(client, payload())
    out = _revert(client, job["job_id"])
    assert out["status"] == "reverted" and out["already_reverted"] is False
    assert out["revert"]["deleted"] == {"outfit": 1, "wardrobe_item": 2, "purchase": 1, "product": 1, "tag": 1}
    assert (settings.backups_dir / out["revert"]["backup_file"]).exists()
    assert counts(client) == before
    assert _search_ids(client, "インポート") == set()
    # 撤销后可以重新导入同样的内容（没有残留的编号、订单号、名额占用）
    again = run_import(client, payload())
    assert [r["action"] for r in again["rows"][:3]] == ["create", "create", "create"]


def test_revert_is_idempotent(client):
    job = run_import(client, payload())
    first = _revert(client, job["job_id"])
    second = _revert(client, job["job_id"])
    assert second["already_reverted"] is True and second["revert"] == first["revert"]


def test_cannot_revert_preview_or_discarded(client):
    job = preview(client, payload())
    err(client.post(f"{API}/imports/{job['job_id']}/revert"), 409, "IMPORT_NOT_COMMITTED")


def test_revert_restores_updates_to_existing_records(client):
    p = make_product(client, identifiers=[{"scheme": "detail_page_id", "value": "E888001-000"}], notes="原备注")
    line = make_purchase(client, p["id"], quantity=1)["lines"][0]
    item_id = line["item_ids"][0]
    ok(client.put(f"{API}/items/{item_id}/tags", json={"version": 1, "tags": ["原标签"]}))
    product_before = get(client, f"/products/{p['id']}")
    item_before = get(client, f"/items/{item_id}")

    body = payload(
        products=[{"ref": "p1", "brand": "uniqlo", "notes": "导入备注",
                   "identifiers": [{"scheme": "detail_page_id", "value": "E888001-000"},
                                   {"scheme": "item_no", "value": "888001"}],
                   "colors": [{"color_code": "01", "name_ja": "WHITE", "hex": "#FFFFFF"}],
                   "sizes": [{"size_label": "XL"}]}],
        purchases=[], outfits=[],
        items=[{"id": item_id, "location": "新位置", "tags": ["导入标签"]}],
    )  # fmt: skip
    job = run_import(client, body)
    changed = get(client, f"/products/{p['id']}")
    assert changed["notes"] == "导入备注" and len(changed["colors"]) == 3 and len(changed["identifiers"]) == 2

    out = _revert(client, job["job_id"])
    assert out["revert"]["deleted"] == {"tag": 1}
    after = get(client, f"/products/{p['id']}")

    def without_ids(rows):
        return [{k: v for k, v in r.items() if k != "id"} for r in rows]

    assert after["notes"] == product_before["notes"] == "原备注"
    for key in ("colors", "sizes", "materials"):
        assert without_ids(after[key]) == without_ids(product_before[key]), key
    assert [(i["scheme"], i["value"]) for i in after["identifiers"]] == [
        (i["scheme"], i["value"]) for i in product_before["identifiers"]
    ]
    item_after = get(client, f"/items/{item_id}")
    assert (item_after["location"], item_after["tags"]) == (item_before["location"], ["原标签"])
    assert item_after["resolved"] == item_before["resolved"]
    assert _search_ids(client, "导入标签") == set()


def test_multiple_updates_to_same_record_in_one_batch(client):
    """GPT 复查意见：同一批次多次修改同一记录，不能把批次自身的版本递增当作冲突。"""
    p = make_product(client)
    item_id = make_purchase(client, p["id"], quantity=1)["lines"][0]["item_ids"][0]
    body = payload(products=[], purchases=[], outfits=[], items=[
        {"id": item_id, "location": "第一次"},
        {"id": item_id, "notes": "第二次", "tags": ["批内"]},
    ])  # fmt: skip
    job = run_import(client, body)
    assert get(client, f"/items/{item_id}")["version"] == 4
    _revert(client, job["job_id"])
    item = get(client, f"/items/{item_id}")
    assert (item["location"], item["notes"], item["tags"]) == (None, None, [])


def test_conflict_when_imported_record_was_edited_later(client):
    job = run_import(client, payload())
    product = ok(client.get(f"{API}/products"))["items"][0]
    ok(client.patch(f"{API}/products/{product['id']}", json={"version": product["version"], "notes": "人工修改"}))
    before = counts(client)
    e = err(client.post(f"{API}/imports/{job['job_id']}/revert"), 409, "REVERT_CONFLICT")
    assert {"entity": "product", "entity_id": product["id"], "reason": "modified_after_import"}.items() <= e["details"][
        0
    ].items()
    assert counts(client) == before
    assert get(client, f"/imports/{job['job_id']}")["status"] == "committed"
    assert get(client, f"/products/{product['id']}")["notes"] == "人工修改"


def test_conflict_when_created_record_is_referenced_outside(client):
    job = run_import(client, payload(purchases=[], items=[], outfits=[]))
    product = ok(client.get(f"{API}/products"))["items"][0]
    ok(client.post(f"{API}/items", json={"product_id": product["id"]}), 201)  # 批次外的新衣物引用导入的商品
    e = err(client.post(f"{API}/imports/{job['job_id']}/revert"), 409, "REVERT_CONFLICT")
    assert e["details"][0]["reason"] == "used_by_item_outside_import"
    assert counts(client)["product"] == 1


def test_conflict_when_imported_item_used_in_outside_outfit(client):
    job = run_import(client, payload(outfits=[]))
    item = ok(client.get(f"{API}/items"))["items"][0]
    ok(client.post(f"{API}/outfits", json={"name": "人工穿搭", "items": [{"item_id": item["id"]}]}), 201)
    e = err(client.post(f"{API}/imports/{job['job_id']}/revert"), 409, "REVERT_CONFLICT")
    assert e["details"][0]["reason"] == "used_by_outfit_outside_import"


def test_shared_tag_created_by_import_is_kept(client):
    p = make_product(client, identifiers=[], name_ja="批次外")
    outside = ok(client.post(f"{API}/items", json={"product_id": p["id"]}), 201)
    job = run_import(client, payload())
    ok(client.put(f"{API}/items/{outside['id']}/tags", json={"version": 1, "tags": ["导入标签"]}))
    out = _revert(client, job["job_id"])
    assert out["revert"]["tags_kept"] == ["导入标签"]
    assert get(client, f"/items/{outside['id']}")["tags"] == ["导入标签"]


def test_accepted_proposals_are_kept_pending_withdrawn(client, ai):
    p = make_product(client, identifiers=[{"scheme": "detail_page_id", "value": "E888001-000"}])
    ok(client.post(f"{API}/products/{p['id']}/verify", json={"version": 1}))
    body = payload(products=[{"ref": "p1", "brand": "uniqlo", "name_zh": "AI 中文名", "material_text": "綿100%",
                              "identifiers": [{"scheme": "detail_page_id", "value": "E888001-000"}]}],
                   purchases=[], items=[], outfits=[])  # fmt: skip
    job = commit(ai, preview(ai, body)["job_id"])
    props = {
        x["field"]: x for x in ok(client.get(f"{API}/proposals", params={"import_job_id": job["job_id"]}))["items"]
    }
    ok(client.post(f"{API}/proposals/{props['name_zh']['proposal_id']}/accept"))  # 人接受了其中一条

    out = _revert(client, job["job_id"])  # 接受提议产生的修改不算冲突
    assert out["revert"]["proposals_withdrawn"] == 1
    assert out["revert"]["proposals_kept"] == [{"proposal_id": props["name_zh"]["proposal_id"], "status": "accepted"}]
    assert get(client, f"/products/{p['id']}")["name_zh"] == "AI 中文名"
    assert get(client, f"/proposals/{props['material_text']['proposal_id']}")["status"] == "withdrawn"


def test_revert_of_lines_added_to_existing_purchase(client):
    p = make_product(client)
    pur = ok(client.post(f"{API}/purchases", json={"purchased_on": "2025-11-03", "store_name": "导入测试店",
                                                    "order_no": "IMP-1"}), 201)  # fmt: skip
    body = payload(products=[], items=[], outfits=[])
    body["purchases"][0]["lines"][0].pop("product_ref")
    body["purchases"][0]["lines"][0]["product_id"] = p["id"]
    job = run_import(client, body)
    assert len(get(client, f"/purchases/{pur['id']}")["lines"]) == 1
    assert ok(client.get(f"{API}/items"))["total"] == 2
    _revert(client, job["job_id"])
    after = get(client, f"/purchases/{pur['id']}")
    assert after["lines"] == [] and ok(client.get(f"{API}/items"))["total"] == 0


def test_revert_keeps_index_and_files_consistent(client, app, settings):
    from helpers import upload

    img = ok(upload(client), 201)
    body = payload()
    body["products"][0]["images"] = [{"image_id": img["id"], "role": "main"}]
    job = run_import(client, body)
    _revert(client, job["job_id"])
    queries = ["インポート", "导入标签", "navy"]
    before = {q: _search_ids(client, q) for q in queries}
    ok(client.post(f"{API}/search/reindex"))
    assert before == {q: _search_ids(client, q) for q in queries}
    assert get(client, f"/images/{img['id']}")["references"] == {"products": [], "items": [], "outfits": []}
    assert (settings.images_dir / img["url"].removeprefix("/media/")).exists()


def test_revert_writes_audit_entries(client):
    job = run_import(client, payload())
    _revert(client, job["job_id"])
    logs = ok(client.get(f"{API}/changes", params={"import_job_id": job["job_id"], "op": "revert", "limit": 200}))
    assert logs["total"] >= 6
