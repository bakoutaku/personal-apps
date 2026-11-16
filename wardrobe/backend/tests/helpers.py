"""测试数据构造。所有商品、编号、订单均为虚构。"""

import io

from PIL import Image as PILImage

API = "/api/v1"


def ok(resp, status: int = 200):
    assert resp.status_code == status, f"{resp.status_code}: {resp.text}"
    return resp.json() if resp.content else None


def err(resp, status: int, code: str):
    assert resp.status_code == status, f"{resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["error"]["code"] == code, body
    return body["error"]


def make_product(client, **overrides) -> dict:
    body = {
        "brand": "uniqlo",
        "category": "outer-light-down",
        "name_ja": "テストダウンジャケット",
        "name_zh": "测试羽绒茄克",
        "identifiers": [{"scheme": "detail_page_id", "value": "E999001-000"}],
        "colors": [
            {"color_code": "09", "name_ja": "BLACK", "hex": "#1A1A1A", "is_default": True},
            {"color_code": "69", "name_ja": "NAVY", "hex": "#1F2A44"},
        ],
        "sizes": [{"size_label": "M"}, {"size_label": "L"}],
        "material_text": "表地:ナイロン100%／詰め物:ダウン90%・フェザー10%",
    }
    body.update(overrides)
    return ok(client.post(f"{API}/products", json=body), 201)


def make_purchase(client, product_id: int | None, *, quantity: int = 1, create_items: bool = True, **line) -> dict:
    line_body = {"product_id": product_id, "quantity": quantity, "unit_price": 7990, **line}
    if product_id is None:
        line_body.pop("product_id")
    return ok(
        client.post(
            f"{API}/purchases",
            json={
                "purchased_on": "2025-11-03",
                "store_name": "测试店",
                "lines": [line_body],
                "create_items": create_items,
            },
        ),
        201,
    )


def get(client, path: str) -> dict:
    return ok(client.get(f"{API}{path}"))


def png_bytes(color=(200, 30, 30), size=(300, 400)) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def upload(client, data: bytes | None = None, **form):
    return client.post(
        f"{API}/images",
        files={"file": ("photo.png", data if data is not None else png_bytes(), "image/png")},
        data=form,
    )
