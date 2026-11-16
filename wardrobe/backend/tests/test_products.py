"""商品：创建、编号不混同（R2）、默认色（BUG-001）、子集合版本（R6）。"""

from helpers import API, err, get, make_product, ok


def test_create_product_with_parsed_materials(client):
    p = make_product(client)
    assert p["version"] == 1
    assert p["brand"]["slug"] == "uniqlo"
    assert p["category"]["path"] == ["外套", "羽绒", "轻羽绒"]
    assert [(m["part"], m["fiber"], m["percent"]) for m in p["materials"]] == [
        ("shell", "nylon", 100),
        ("fill", "down", 90),
        ("fill", "feather", 10),
    ]
    assert p["colors"][1]["color_family"] == "navy"
    assert p["warnings"] == []


def test_create_requires_a_name_and_rejects_unknown_fields(client):
    err(client.post(f"{API}/products", json={"brand": "uniqlo"}), 422, "VALIDATION_ERROR")
    e = err(client.post(f"{API}/products", json={"name_ja": "x", "nmae_zh": "typo"}), 422, "VALIDATION_ERROR")
    assert e["details"][0]["loc"] == ["nmae_zh"]


def test_unknown_category_gives_hint(client):
    e = err(client.post(f"{API}/products", json={"name_ja": "x", "category": "nope"}), 422, "VALIDATION_ERROR")
    assert "hint" in e["details"][0]


def test_invalid_hex_error_points_to_field(client):
    body = {"name_ja": "x", "colors": [{"name_ja": "N", "hex": "1f2a44"}]}
    e = err(client.post(f"{API}/products", json=body), 422, "VALIDATION_ERROR")
    assert e["details"][0]["loc"] == ["colors", 0, "hex"]


def test_material_parse_warning_is_returned_not_fatal(client):
    p = make_product(client, identifiers=[], material_text="ふわふわ素材")
    assert p["materials"] == []
    assert p["material_text"] == "ふわふわ素材"
    assert p["warnings"][0]["code"] == "material_parse_failed"


# ───────────── R2 编号不混同 ─────────────


def test_same_identifier_in_same_brand_is_duplicate(client):
    first = make_product(client)
    e = err(
        client.post(
            f"{API}/products",
            json={
                "brand": "uniqlo",
                "name_ja": "別",
                "identifiers": [{"scheme": "detail_page_id", "value": "e999001-000"}],
            },
        ),
        409,
        "DUPLICATE",
    )
    assert e["details"][0]["existing_id"] == first["id"]


def test_same_identifier_other_brand_or_other_scheme_is_allowed(client):
    make_product(client)
    make_product(client, brand="gu")
    # 同一品牌、同一个值，但 scheme 不同：不是同一个编号
    make_product(client, identifiers=[{"scheme": "item_no", "value": "E999001-000"}])


def test_lookup_only_matches_same_scheme(client):
    p = make_product(client, identifiers=[{"scheme": "detail_page_id", "value": "E999001-000"}])
    # 小票上的商品番号 999001 看起来是详情页编号的一部分，但绝不能自动匹配
    hits = ok(client.post(f"{API}/products/lookup", json={"scheme": "item_no", "value": "999001"}))["items"]
    assert hits == []
    hits = ok(client.post(f"{API}/products/lookup", json={"scheme": "detail_page_id", "value": " e999001-000"}))
    assert [h["id"] for h in hits["items"]] == [p["id"]]
    listed = ok(client.get(f"{API}/products", params={"identifier": "item_no:999001"}))
    assert listed["total"] == 0


def test_add_and_remove_identifier_bumps_version(client):
    p = make_product(client)
    p2 = ok(client.post(f"{API}/products/{p['id']}/identifiers",
                        json={"version": 1, "scheme": "item_no", "value": "999001", "source": "receipt"}), 201)  # fmt: skip
    assert p2["version"] == 2
    assert {(i["scheme"], i["value"]) for i in p2["identifiers"]} == {
        ("detail_page_id", "E999001-000"),
        ("item_no", "999001"),
    }
    ident = next(i for i in p2["identifiers"] if i["scheme"] == "item_no")
    p3 = ok(client.delete(f"{API}/products/{p['id']}/identifiers/{ident['id']}", params={"version": 2}))
    assert p3["version"] == 3 and len(p3["identifiers"]) == 1


def test_changing_brand_rechecks_identifier_uniqueness(client):
    make_product(client, brand="gu")
    p = make_product(client)
    err(client.patch(f"{API}/products/{p['id']}", json={"version": 1, "brand": "gu"}), 409, "DUPLICATE")


# ───────────── BUG-001 默认色 ─────────────


def test_put_colors_rejects_multiple_defaults_and_changes_nothing(client):
    p = make_product(client)
    body = {
        "version": 1,
        "colors": [
            {"color_code": "09", "name_ja": "BLACK", "is_default": True},
            {"color_code": "69", "name_ja": "NAVY", "is_default": True},
        ],
    }
    e = err(client.put(f"{API}/products/{p['id']}/colors", json=body), 422, "VALIDATION_ERROR")
    assert [d["loc"] for d in e["details"]] == [["colors", 0, "is_default"], ["colors", 1, "is_default"]]
    after = get(client, f"/products/{p['id']}")
    assert after["version"] == 1
    assert after["colors"] == p["colors"]


def test_put_colors_switch_default_and_allow_zero(client):
    p = make_product(client)
    switched = ok(client.put(f"{API}/products/{p['id']}/colors", json={"version": 1, "colors": [
        {"color_code": "09", "name_ja": "BLACK", "hex": "#1A1A1A"},
        {"color_code": "69", "name_ja": "NAVY", "hex": "#1F2A44", "is_default": True},
    ]}))  # fmt: skip
    assert [c["is_default"] for c in switched["colors"]] == [False, True]
    assert switched["version"] == 2
    none = ok(client.put(f"{API}/products/{p['id']}/colors", json={"version": 2, "colors": [{"name_ja": "BLACK"}]}))
    assert [c["is_default"] for c in none["colors"]] == [False]


def test_put_colors_duplicate_entry_rolls_back(client):
    p = make_product(client)
    body = {"version": 1, "colors": [{"color_code": "09", "name_ja": "B"}, {"color_code": "09", "name_ja": "B"}]}
    err(client.put(f"{API}/products/{p['id']}/colors", json=body), 422, "VALIDATION_ERROR")
    assert get(client, f"/products/{p['id']}")["colors"] == p["colors"]


def test_put_materials_reparses_text_when_omitted(client):
    p = make_product(client)
    ok(client.patch(f"{API}/products/{p['id']}", json={"version": 1, "material_text": "綿100%"}))
    out = ok(client.put(f"{API}/products/{p['id']}/materials", json={"version": 2}))
    assert [(m["fiber"], m["percent"]) for m in out["materials"]] == [("cotton", 100)]


def test_product_delete_blocked_while_items_exist(client):
    from helpers import make_purchase

    p = make_product(client)
    make_purchase(client, p["id"])
    err(client.delete(f"{API}/products/{p['id']}", params={"version": 1}), 409, "IN_USE")


def test_change_log_records_product_update(client, app):
    from sqlalchemy import select

    from wardrobe.models import ChangeLog

    p = make_product(client)
    ok(client.patch(f"{API}/products/{p['id']}", json={"version": 1, "notes": "备注"}))
    with app.state.sessionmaker() as s:
        logs = s.scalars(select(ChangeLog).where(ChangeLog.entity == "product").order_by(ChangeLog.id)).all()
    assert [(log.op, log.actor) for log in logs] == [("create", "web-ui"), ("update", "web-ui")]
    assert logs[1].before == {"notes": None} and logs[1].after == {"notes": "备注"} and logs[1].version_after == 2
