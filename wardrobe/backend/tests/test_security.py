"""ARCHITECTURE §4：本机安全中间件。"""

from fastapi.testclient import TestClient
from helpers import API, err, ok


def test_get_without_client_header_is_allowed(raw):
    ok(raw.get(f"{API}/health"))


def test_write_without_client_header_is_rejected(raw):
    err(raw.post(f"{API}/tags", json={"name": "x"}), 403, "CLIENT_HEADER_REQUIRED")


def test_invalid_client_header_is_rejected(app):
    c = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Wardrobe-Client": "web ui!"})
    err(c.post(f"{API}/tags", json={"name": "x"}), 403, "CLIENT_HEADER_INVALID")


def test_foreign_host_is_rejected_dns_rebinding(app):
    c = TestClient(app, base_url="http://evil.example:8765")
    err(c.get(f"{API}/health"), 421, "MISDIRECTED_HOST")


def test_localhost_host_is_accepted(app):
    ok(TestClient(app, base_url="http://localhost:8765").get(f"{API}/health"))


def test_wrong_port_host_is_rejected(app):
    err(TestClient(app, base_url="http://127.0.0.1:9999").get(f"{API}/health"), 421, "MISDIRECTED_HOST")


def test_foreign_origin_is_rejected_even_with_client_header(client):
    resp = client.post(f"{API}/tags", json={"name": "x"}, headers={"Origin": "https://evil.example"})
    err(resp, 403, "ORIGIN_FORBIDDEN")


def test_null_origin_is_rejected(client):
    err(client.post(f"{API}/tags", json={"name": "x"}, headers={"Origin": "null"}), 403, "ORIGIN_FORBIDDEN")


def test_foreign_origin_cannot_read_either(raw):
    err(raw.get(f"{API}/items", headers={"Origin": "https://evil.example"}), 403, "ORIGIN_FORBIDDEN")


def test_cross_site_fetch_metadata_is_rejected(client):
    resp = client.post(f"{API}/tags", json={"name": "x"}, headers={"Sec-Fetch-Site": "cross-site"})
    err(resp, 403, "ORIGIN_FORBIDDEN")


def test_same_origin_and_dev_origin_are_allowed(client):
    ok(client.post(f"{API}/tags", json={"name": "a"}, headers={"Origin": "http://127.0.0.1:8765"}), 201)
    ok(client.post(f"{API}/tags", json={"name": "b"}, headers={"Origin": "http://localhost:5173"}), 201)


def test_no_cors_headers_are_emitted(client):
    resp = client.options(
        f"{API}/tags", headers={"Origin": "http://127.0.0.1:8765", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in resp.headers


def test_rejected_write_has_no_side_effect(client, raw):
    raw.post(f"{API}/tags", json={"name": "未授权"})
    assert all(t["name"] != "未授权" for t in ok(client.get(f"{API}/tags"))["items"])
