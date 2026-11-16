"""Phase 3 后端支持：筛选统计、网页界面托管（SPA 回退、CSP）、安全头、演示数据。"""

import pytest
from fastapi.testclient import TestClient
from helpers import API, make_product, make_purchase, ok, png_bytes, upload

from wardrobe.config import Settings
from wardrobe.main import create_app

BASE = "http://127.0.0.1:8765"

# ───────────── 筛选统计 ─────────────


@pytest.fixture
def wardrobe(client):
    down = make_product(client)  # 外套 > 羽绒 > 轻羽绒，默认色 BLACK
    tee = make_product(client, brand="gu", category="tops-tshirt-short", name_ja="T", identifiers=[],
                       colors=[{"name_ja": "WHITE", "hex": "#FFFFFF", "is_default": True}], sizes=[{"size_label": "M"}],
                       material_text="綿100%")  # fmt: skip
    a = make_purchase(client, down["id"], color_name="NAVY", color_hex="#1F2A44", size_label="L")["lines"][0][
        "item_ids"
    ][0]
    b = make_purchase(client, down["id"])["lines"][0]["item_ids"][0]  # 默认色 BLACK
    c = make_purchase(client, tee["id"])["lines"][0]["item_ids"][0]
    ok(client.put(f"{API}/items/{a}/tags", json={"version": 1, "tags": ["通勤"]}))
    ok(client.post(f"{API}/items/{c}/return", json={"version": 1, "returned_on": "2025-12-01"}))
    return {"a": a, "b": b, "c": c}


def _category_id(client, slug):
    return next(c["id"] for c in ok(client.get(f"{API}/categories", params={"format": "flat"}))["items"]
                if c["slug"] == slug)  # fmt: skip


def test_facets_count_owned_items_by_default(client, wardrobe):
    f = ok(client.get(f"{API}/items/facets"))
    assert f["total"] == 2
    assert f["color"] == {"navy": 1, "black": 1}
    assert f["brand"] == {"uniqlo": 2}
    assert f["size"] == {"L": 1}
    assert f["tag"] == {"通勤": 1}
    assert f["material"] == {"nylon": 2, "down": 2, "feather": 2}
    assert f["status"] == {"owned": 2, "returned": 1}  # 状态维度不应用自身筛选


def test_facets_include_ancestor_categories(client, wardrobe):
    f = ok(client.get(f"{API}/items/facets", params={"status": "all"}))
    assert f["category"][str(_category_id(client, "outer"))] == 2
    assert f["category"][str(_category_id(client, "outer-down"))] == 2
    assert f["category"][str(_category_id(client, "outer-light-down"))] == 2
    assert f["category"][str(_category_id(client, "tops"))] == 1


def test_facet_dimension_ignores_its_own_filter(client, wardrobe):
    f = ok(client.get(f"{API}/items/facets", params={"color": "navy"}))
    assert f["total"] == 1
    assert f["color"] == {"navy": 1, "black": 1}  # 选了藏青，颜色维度仍显示其他颜色
    assert f["tag"] == {"通勤": 1}  # 其他维度按藏青过滤
    assert f["size"] == {"L": 1}


def test_facets_match_list_totals(client, wardrobe):
    for params in ({}, {"color": "black"}, {"q": "テスト"}, {"brand": "uniqlo", "tag": "通勤"}, {"status": "all"}):
        assert (
            ok(client.get(f"{API}/items/facets", params=params))["total"]
            == ok(client.get(f"{API}/items", params=params))["total"]
        ), params


# ───────────── 网页界面托管 ─────────────


@pytest.fixture
def ui(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>UI</title><div id=app></div>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    app = create_app(Settings(data_dir=tmp_path / "data", frontend_dist=dist))
    return TestClient(app, base_url=BASE)


def test_spa_serves_index_for_client_routes_with_csp(ui):
    for path in ("/", "/items/12", "/outfits", "/some/deep/link"):
        r = ui.get(path)
        assert r.status_code == 200 and "<div id=app>" in r.text, path
        assert "default-src 'self'" in r.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_spa_serves_assets_with_long_cache(ui):
    r = ui.get("/assets/app.js")
    assert r.text == "console.log(1)" and "immutable" in r.headers["cache-control"]


def test_spa_never_swallows_api_or_media_404(ui):
    r = ui.get("/api/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    assert ui.get("/api").status_code == 404
    assert ui.get("/media/thumb/none.webp").status_code == 404


def test_spa_path_traversal_returns_index_not_file(ui):
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
        r = ui.get(path)
        assert "secret" not in r.text, path


def test_without_build_root_shows_hint(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", frontend_dist=tmp_path / "missing"))
    r = TestClient(app, base_url=BASE).get("/")
    assert r.status_code == 200 and "/api/docs" in r.text


def test_security_headers_on_all_responses(client, raw):
    for resp in (client.get(f"{API}/health"), raw.get(f"{API}/items/999999"), client.get("/api/docs")):
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["referrer-policy"] == "no-referrer"
    assert "content-security-policy" not in client.get("/api/docs").headers  # Swagger 需要 CDN 资源


# ───────────── 演示数据 ─────────────


def test_demo_payload_imports_cleanly(client):
    from wardrobe.demo import ITEMS, build_payload, garment_png

    ids = {}
    for ref, *_, hex_, _s, _m, kind, _t, _st in ITEMS:
        ids[ref] = ok(upload(client, garment_png(hex_, kind)), 201)["id"]
    job = ok(client.post(f"{API}/imports", json=build_payload(ids)), 201)
    assert job["can_commit"], [r for r in job["rows"] if r["errors"]]
    ok(client.post(f"{API}/imports/{job['job_id']}/commit"))
    counts = ok(client.get(f"{API}/meta"))["counts"]
    assert counts["wardrobe_item"] == len(ITEMS) and counts["outfit"] == 2
    assert ok(client.get(f"{API}/items", params={"status": "returned"}))["total"] == 1
    # 示意图是 3:4、宽 600
    import io

    from PIL import Image as PILImage

    with PILImage.open(io.BytesIO(garment_png("#1F2A44", "coat"))) as im:
        assert im.size == (600, 800)


def test_demo_refuses_non_empty_database(client, monkeypatch):
    from wardrobe import demo

    make_product(client)
    monkeypatch.setattr(demo, "_request", lambda base, method, path, *a, **k: client.request(method, path).json())
    with pytest.raises(RuntimeError, match="已有商品"):
        demo.seed_demo("")
    assert png_bytes()  # helpers 可用


def test_item_detail_exposes_purchase_currency(client):
    product = make_product(client)
    purchase = ok(
        client.post(
            f"{API}/purchases",
            json={
                "purchased_on": "2026-10-26",
                "currency": "USD",
                "create_items": True,
                "lines": [{"product_id": product["id"], "quantity": 1, "unit_price": 50}],
            },
        ),
        201,
    )
    item_id = purchase["lines"][0]["item_ids"][0]
    item = ok(client.get(f"{API}/items/{item_id}"))
    assert item["purchase"]["currency"] == "USD"
    assert item["product"]["currency"] == "JPY"
