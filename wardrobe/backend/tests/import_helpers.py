"""导入测试的数据构造。所有商品、编号、订单均为虚构。"""

import copy

from helpers import API, ok

BASE_PAYLOAD = {
    "format": "wardrobe.import/v1",
    "source_label": "测试导入",
    "products": [
        {
            "ref": "p1",
            "brand": "uniqlo",
            "category": "outer-light-down",
            "name_ja": "インポートダウン",
            "name_zh": "导入羽绒",
            "identifiers": [{"scheme": "detail_page_id", "value": "E888001-000"}],
            "colors": [{"color_code": "69", "name_ja": "NAVY", "hex": "#1F2A44", "is_default": True}],
            "sizes": [{"size_label": "M"}, {"size_label": "L"}],
            "material_text": "表地:ナイロン100%",
        }
    ],
    "purchases": [
        {
            "ref": "o1",
            "purchased_on": "2025-11-03",
            "store_name": "导入测试店",
            "order_no": "IMP-1",
            "create_items": True,
            "lines": [
                {
                    "ref": "l1",
                    "product_ref": "p1",
                    "item_code_raw": "888001",
                    "color_name": "NAVY",
                    "size_label": "L",
                    "quantity": 2,
                    "unit_price": 7990,
                }
            ],
        }
    ],
    "items": [{"ref": "i1", "purchase_line_ref": "l1", "tags": ["导入标签"], "location": "衣柜"}],
    "outfits": [
        {"ref": "f1", "name": "导入穿搭", "items": [{"item_ref": "i1", "slot": "outer"}], "tags": ["导入标签"]}
    ],
}


def payload(**overrides) -> dict:
    p = copy.deepcopy(BASE_PAYLOAD)
    p.update(overrides)
    return p


def preview(client, body, status=201) -> dict:
    return ok(client.post(f"{API}/imports", json=body), status)


def commit(client, job_id, status=200, **body) -> dict:
    return ok(client.post(f"{API}/imports/{job_id}/commit", json=body or None), status)


def run_import(client, body) -> dict:
    job = preview(client, body)
    assert job["can_commit"], job
    return commit(client, job["job_id"])


def counts(client) -> dict:
    return ok(client.get(f"{API}/meta"))["counts"]


def actions(job) -> list[tuple]:
    return [(r["entity"], r["action"]) for r in job["rows"]]
