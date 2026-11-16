import pytest
from fastapi.testclient import TestClient
from helpers import API, make_product, ok

from wardrobe.config import Settings
from wardrobe.main import create_app


@pytest.fixture
def ui(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=app></div>")
    (dist / "assets/app.js").write_text("console.log(1)")
    with TestClient(
        create_app(Settings(data_dir=tmp_path / "data", frontend_dist=dist)), base_url="http://127.0.0.1:8765"
    ) as client:
        yield client


def test_exact_tag_and_legacy_csv_are_unambiguous(client):
    p = make_product(client)

    def add(tags, size):
        return ok(client.post(f"{API}/items", json={"product_id": p["id"], "tags": tags, "size_label": size}), 201)[
            "id"
        ]

    literal = add(["QA,逗号", "通勤"], "M,L")
    separate = add(["QA", "逗号", "通勤"], "M")
    other = add(["通勤"], "L")

    def found(params):
        return {i["id"] for i in ok(client.get(f"{API}/items", params=params))["items"]}

    assert found({"tag": "QA,逗号"}) == {separate}  # 旧 CSV 保持 AND 语义
    assert found([("tag_exact", "QA,逗号"), ("tag_exact", "通勤")]) == {literal}
    assert found([("tag_exact", "QA,逗号"), ("tag_exact", "通勤"), ("tag_mode", "any")]) == {literal, separate, other}
    assert found({"tag": "通勤", "tag_exact": "QA,逗号"}) == {literal}
    assert found({"size_exact": "M,L"}) == {literal}
    assert found({"size": "M,L"}) == {separate, other}
    facets = ok(client.get(f"{API}/items/facets", params={"tag_exact": "QA,逗号", "size_exact": "M,L"}))
    assert facets["total"] == 1
    assert facets["tag"]["QA,逗号"] == 1
    assert facets["size"] == {"M,L": 1}


def test_exact_filters_are_documented_as_repeatable_query_values(client):
    parameters = ok(client.get("/api/openapi.json"))["paths"][f"{API}/items"]["get"]["parameters"]
    for name in ("tag_exact", "size_exact"):
        param = next(p for p in parameters if p["name"] == name)
        assert param["in"] == "query"
        assert any(s.get("type") == "array" for s in param["schema"]["anyOf"])


@pytest.mark.parametrize(
    "method,path,headers,status",
    [
        ("GET", "/health", {}, 200),
        ("GET", "/no-such-api", {}, 404),
        ("GET", "/health", {"Host": "evil.example"}, 421),
        ("GET", "/health", {"Origin": "null"}, 403),
        ("GET", "/health", {"Sec-Fetch-Site": "cross-site"}, 403),
        ("POST", "/items", {"X-Wardrobe-Client": ""}, 403),
        ("POST", "/items", {"X-Wardrobe-Client": "invalid value"}, 403),
    ],
)
def test_security_headers_on_normal_and_rejected_responses(client, method, path, headers, status):
    response = client.request(method, f"{API}{path}", headers=headers)
    assert response.status_code == status
    for header, value in {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "no-referrer",
    }.items():
        assert response.headers[header] == value


def test_all_html_entrypoints_share_csp_and_cache(ui):
    headers = [ui.get(path).headers for path in ("/", "/index.html", "/items/9")]
    assert len({h["content-security-policy"] for h in headers}) == 1
    assert all(h["cache-control"] == "no-cache" for h in headers)
    asset = ui.get("/assets/app.js")
    assert "immutable" in asset.headers["cache-control"]
    assert "javascript" in asset.headers["content-type"]
    for path in ("/assets/missing.js", "/wardrobe.db", "/backup.zip", "/missing.css"):
        assert ui.get(path).status_code == 404
