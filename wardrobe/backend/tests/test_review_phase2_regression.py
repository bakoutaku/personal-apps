"""GPT Phase 2 修复复查（docs/REVIEW_PHASE2_REGRESSION_2026-10-26.md）的独立测试，原样保留预期行为作为回归用例。"""

import pytest
from fastapi.testclient import TestClient

from wardrobe.config import Settings
from wardrobe.main import create_app

API = "/api/v1"
FMT = "wardrobe.import/v1"


@pytest.fixture
def env(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data"))
    c = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Wardrobe-Client": "web-ui"})
    yield c
    c.close()
    app.state.engine.dispose()


def post(c, path, body=None):
    r = c.post(API + path, json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_outfit_scalar_edit_after_preview_rejects_commit(env):
    c = env
    outfit = post(c, "/outfits", {"name": "QA outfit", "description": "original"})
    preview = post(c, "/imports", {"format": FMT, "outfits": [{"id": outfit["id"], "description": "imported"}]})
    assert preview["can_commit"], preview
    r = c.patch(API + f"/outfits/{outfit['id']}", json={"version": 1, "description": "human after preview"})
    assert r.status_code == 200, r.text
    response = c.post(API + f"/imports/{preview['job_id']}/commit")
    after = c.get(API + f"/outfits/{outfit['id']}").json()
    assert response.status_code == 409 and after["description"] == "human after preview", {
        "commit_http": response.status_code,
        "description": after["description"],
        "preview_diff": preview["rows"][0]["diff"],
    }


def test_outfit_items_edit_after_preview_rejects_commit(env):
    c = env
    product = post(c, "/products", {"name_ja": "QA product"})
    ids = [post(c, "/items", {"product_id": product["id"]})["id"] for _ in range(3)]
    outfit = post(c, "/outfits", {"name": "QA outfit", "items": [{"item_id": ids[0], "slot": "top"}]})
    job = post(
        c, "/imports", {"format": FMT, "outfits": [{"id": outfit["id"], "items": [{"item_id": ids[1], "slot": "top"}]}]}
    )
    assert job["can_commit"], job
    manual = c.put(
        API + f"/outfits/{outfit['id']}/items", json={"version": 1, "items": [{"item_id": ids[2], "slot": "top"}]}
    )
    assert manual.status_code == 200, manual.text
    response = c.post(API + f"/imports/{job['job_id']}/commit")
    after = c.get(API + f"/outfits/{outfit['id']}").json()
    final_ids = [x["item_id"] if "item_id" in x else x["item"]["id"] for x in after["items"]]
    assert response.status_code == 409 and final_ids == [ids[2]], {
        "commit_http": response.status_code,
        "expected_item_ids": [ids[2]],
        "actual_item_ids": final_ids,
    }


def test_unchanged_outfit_can_commit(env):
    c = env
    outfit = post(c, "/outfits", {"name": "QA control", "description": "original"})
    job = post(c, "/imports", {"format": FMT, "outfits": [{"id": outfit["id"], "description": "imported"}]})
    post(c, f"/imports/{job['job_id']}/commit")
    assert c.get(API + f"/outfits/{outfit['id']}").json()["description"] == "imported"
