"""Phase 5A-1：color-analysis（只读）与 color-suggestions（只生成 pending 提议），以及接受/拒绝/过期规则。"""

import io

import pytest
from helpers import API, err, get, make_product, make_purchase, ok, png_bytes, upload
from import_helpers import BASE_PAYLOAD
from PIL import Image as PILImage
from sqlalchemy import func, select, text

from wardrobe.models import AISuggestionContext, ChangeLog, ChangeProposal

NAVY, WHITE = "#1F2A44", "#FFFFFF"


def two_color_png() -> bytes:
    """上 75% 藏青、下 25% 白色（40x100）。"""
    img = PILImage.new("RGB", (40, 100), (255, 255, 255))
    img.paste((0x1F, 0x2A, 0x44), (0, 0, 40, 75))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def transparent_png() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGBA", (20, 20), (0, 0, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def ctx(client):
    p = make_product(client)
    pur = make_purchase(client, p["id"], color_code="69", color_name="NAVY", size_label="L")
    line = pur["lines"][0]
    item_id = line["item_ids"][0]
    img = ok(upload(client, two_color_png()), 201)
    ok(client.post(f"{API}/items/{item_id}/images", json={"version": 1, "image_id": img["id"], "role": "main"}), 201)
    return {"product": p["id"], "line": line["id"], "purchase": pur["id"], "item": item_id, "image": img["id"]}


def business_state(client, app, c) -> dict:
    """衣物、商品、购买明细的完整响应 + 审计日志与提议数量。"""
    with app.state.sessionmaker() as s:
        logs = s.scalar(select(func.count()).select_from(ChangeLog))
        props = s.scalar(select(func.count()).select_from(ChangeProposal))
    return {
        "item": get(client, f"/items/{c['item']}"),
        "product": get(client, f"/products/{c['product']}"),
        "line": get(client, f"/purchase-lines/{c['line']}"),
        "facets": get(client, "/items/facets")["color"],
        "logs": logs,
        "proposals": props,
    }


def analyze(client, c, **body):
    return client.post(f"{API}/items/{c['item']}/color-analysis", json={"image_id": c["image"], **body})


def suggest(client, c, version, hex_=WHITE, **extra):
    body = {"version": version, "image_id": c["image"], "candidate_hex": hex_, **extra}
    return client.post(f"{API}/items/{c['item']}/color-suggestions", json=body)


# ───────────── 分析 ─────────────


def test_analysis_returns_candidates_and_writes_nothing(client, app, ctx):
    before = business_state(client, app, ctx)
    out = ok(analyze(client, ctx))
    assert out["status"] == "ok" and out["algorithm"] == "wardrobe-color/2"
    assert [c["hex"] for c in out["candidates"]] == [NAVY, WHITE]
    assert [c["pixel_share"] for c in out["candidates"]] == [0.75, 0.25]
    assert out["item_version"] == before["item"]["version"] and out["image_id"] == ctx["image"]
    assert out["current_color"] == {"color_code": None, "color_name": None, "color_hex": None}
    assert out["resolved_color"]["source"] == "purchase_line"
    assert business_state(client, app, ctx) == before


def test_analysis_region_is_applied(client, ctx):
    out = ok(analyze(client, ctx, region={"x": 0, "y": 0.8, "w": 1, "h": 0.2}))
    assert [c["hex"] for c in out["candidates"]] == [WHITE]
    assert out["region"] == {"x": 0.0, "y": 0.8, "w": 1.0, "h": 0.2}


@pytest.mark.parametrize(
    "body",
    [
        {"region": {"x": 0.5, "y": 0, "w": 0.6, "h": 1}},  # 越界
        {"region": {"x": 0, "y": 0, "w": 0, "h": 1}},  # 空区域
        {"region": {"x": -0.1, "y": 0, "w": 0.5, "h": 1}},
        {"path": "/etc/passwd"},  # 不接受任意路径
        {"url": "https://example.com/a.png"},
    ],
)
def test_invalid_analysis_input_is_rejected(client, app, ctx, body):
    before = business_state(client, app, ctx)
    err(analyze(client, ctx, **body), 422, "VALIDATION_ERROR")
    assert business_state(client, app, ctx) == before


def test_only_the_items_own_linked_images_can_be_analyzed(client, ctx):
    other = ok(upload(client, png_bytes(color=(10, 200, 10))), 201)  # 未关联
    e = err(
        client.post(f"{API}/items/{ctx['item']}/color-analysis", json={"image_id": other["id"]}),
        422,
        "VALIDATION_ERROR",
    )
    assert e["details"][0]["code"] == "not_linked"
    # 商品图（可能是其他色款）也不能用
    prod = get(client, f"/products/{ctx['product']}")
    ok(
        client.post(
            f"{API}/products/{ctx['product']}/images", json={"version": prod["version"], "image_id": other["id"]}
        ),
        201,
    )
    err(
        client.post(f"{API}/items/{ctx['item']}/color-analysis", json={"image_id": other["id"]}),
        422,
        "VALIDATION_ERROR",
    )
    err(client.post(f"{API}/items/{ctx['item']}/color-analysis", json={"image_id": 99999}), 422, "VALIDATION_ERROR")


def test_deleted_item_cannot_be_analyzed(client, ctx):
    v = get(client, f"/items/{ctx['item']}")["version"]
    ok(client.delete(f"{API}/items/{ctx['item']}", params={"version": v}), 204)
    err(analyze(client, ctx), 404, "NOT_FOUND")


def test_fully_transparent_photo_gives_no_suggestion_and_no_proposal(client, app, ctx):
    img = ok(upload(client, transparent_png()), 201)
    v = get(client, f"/items/{ctx['item']}")["version"]
    ok(client.post(f"{API}/items/{ctx['item']}/images", json={"version": v, "image_id": img["id"]}), 201)
    c = {**ctx, "image": img["id"]}
    out = ok(analyze(client, c))
    assert out["status"] == "no_suggestion" and out["reason"] == "no_opaque_pixels" and out["candidates"] == []
    e = err(suggest(client, c, v + 1, "#000000"), 422, "VALIDATION_ERROR")
    assert e["details"][0]["code"] == "no_suggestion"
    assert business_state(client, app, c)["proposals"] == 0


def test_missing_or_tampered_original_file_is_reported(client, settings, ctx):
    img = get(client, f"/images/{ctx['image']}")
    path = settings.images_dir / img["url"].removeprefix("/media/")
    path.write_bytes(b"tampered")
    err(analyze(client, ctx), 409, "IMAGE_UNAVAILABLE")
    path.unlink()
    err(analyze(client, ctx), 409, "IMAGE_UNAVAILABLE")


# ───────────── 生成建议 ─────────────


@pytest.mark.parametrize("verified", [False, True])
def test_suggestion_creates_only_a_pending_proposal(client, app, ctx, verified):
    if verified:
        v = get(client, f"/items/{ctx['item']}")["version"]
        ok(client.post(f"{API}/items/{ctx['item']}/verify", json={"version": v}))
    before = business_state(client, app, ctx)
    version = before["item"]["version"]
    out = ok(suggest(client, ctx, version, WHITE), 201)
    p = out["proposal"]
    assert p["status"] == "pending" and p["entity"] == "wardrobe_item" and p["field"] == "color"
    assert p["current_value"] == {"color_code": None, "color_name": None, "color_hex": None}
    assert p["proposed_value"] == {"color_code": None, "color_name": None, "color_hex": WHITE}
    a = p["ai_context"]
    assert a["source"] == "local_image_analysis" and a["algorithm"] == "wardrobe-color/2"
    assert a["target_version"] == version and a["image_id"] == ctx["image"]
    assert a["image_sha256"] == get(client, f"/images/{ctx['image']}")["sha256"]
    assert a["candidate"]["hex"] == WHITE and [c["hex"] for c in a["candidates"]] == [NAVY, WHITE]
    assert "wardrobe-color" not in (p["reason"] or "")  # 机器上下文不藏在 reason 里
    after = business_state(client, app, ctx)
    assert after["proposals"] == before["proposals"] + 1
    # 衣物（含 version、有效颜色）、商品、购买明细、筛选计数、审计日志都不变
    assert {k: after[k] for k in ("item", "product", "line", "facets", "logs")} == {
        k: before[k] for k in ("item", "product", "line", "facets", "logs")
    }


def test_ai_clients_may_generate_but_not_decide(client, ai, ctx):
    v = get(client, f"/items/{ctx['item']}")["version"]
    p = ok(suggest(ai, ctx, v), 201)["proposal"]
    assert p["actor"] == "ai:codex"
    err(ai.post(f"{API}/proposals/{p['proposal_id']}/accept"), 403, "PRIVILEGED_ONLY")
    err(ai.post(f"{API}/proposals/{p['proposal_id']}/reject"), 403, "PRIVILEGED_ONLY")


def test_candidate_must_come_from_the_servers_own_analysis(client, app, ctx):
    v = get(client, f"/items/{ctx['item']}")["version"]
    first = ok(suggest(client, ctx, v, NAVY), 201)["proposal"]
    for bad in ("#123456", "#FFFFFE"):
        e = err(suggest(client, ctx, v, bad), 422, "VALIDATION_ERROR")
        assert e["details"][0]["code"] == "not_a_candidate"
    err(suggest(client, ctx, v, "white"), 422, "VALIDATION_ERROR")  # 非法 HEX
    # 区域内没有藏青：同一个 HEX 在该区域不是候选
    e = err(suggest(client, ctx, v, NAVY, region={"x": 0, "y": 0.8, "w": 1, "h": 0.2}), 422, "VALIDATION_ERROR")
    assert e["details"][0]["code"] == "not_a_candidate"
    # 失败的请求不会取代已有的 pending 提议
    assert get(client, f"/proposals/{first['proposal_id']}")["status"] == "pending"
    assert business_state(client, app, ctx)["proposals"] == 1


def test_stale_version_and_lowercase_hex(client, ctx):
    v = get(client, f"/items/{ctx['item']}")["version"]
    err(suggest(client, ctx, v - 1), 409, "VERSION_CONFLICT")
    p = ok(suggest(client, ctx, v, "#1f2a44"), 201)["proposal"]  # HEX 按现有规范统一为大写
    assert p["proposed_value"]["color_hex"] == NAVY


def test_whole_group_is_written_and_missing_code_or_name_clears_the_override(client, ctx):
    item = get(client, f"/items/{ctx['item']}")
    item = ok(
        client.patch(
            f"{API}/items/{ctx['item']}",
            json={"version": item["version"], "color_code": "69", "color_name": "NAVY", "color_hex": "#202A40"},
        )
    )
    cleared = ok(suggest(client, ctx, item["version"], WHITE), 201)["proposal"]
    assert cleared["current_value"] == {"color_code": "69", "color_name": "NAVY", "color_hex": "#202A40"}
    assert cleared["proposed_value"] == {"color_code": None, "color_name": None, "color_hex": WHITE}
    named = ok(suggest(client, ctx, item["version"], WHITE, color_name="OFF WHITE", color_code="01"), 201)["proposal"]
    assert named["proposed_value"] == {"color_code": "01", "color_name": "OFF WHITE", "color_hex": WHITE}
    # 新建同字段提议按原规则取代旧 pending
    assert get(client, f"/proposals/{cleared['proposal_id']}")["status"] == "superseded"


def test_identical_proposal_is_rejected_without_superseding(client, ctx):
    item = get(client, f"/items/{ctx['item']}")
    item = ok(client.patch(f"{API}/items/{ctx['item']}", json={"version": item["version"], "color_hex": WHITE}))
    pending = ok(suggest(client, ctx, item["version"], NAVY), 201)["proposal"]
    e = err(suggest(client, ctx, item["version"], WHITE), 422, "VALIDATION_ERROR")
    assert e["details"][0]["code"] == "no_change"
    assert get(client, f"/proposals/{pending['proposal_id']}")["status"] == "pending"


# ───────────── 接受 / 拒绝 ─────────────


@pytest.mark.parametrize("verified", [False, True])
def test_accept_changes_only_the_items_color_group(client, app, ctx, verified):
    if verified:
        v = get(client, f"/items/{ctx['item']}")["version"]
        ok(client.post(f"{API}/items/{ctx['item']}/verify", json={"version": v}))
    before = business_state(client, app, ctx)
    v = before["item"]["version"]
    p = ok(suggest(client, ctx, v, WHITE, color_name="WHITE"), 201)["proposal"]
    out = ok(client.post(f"{API}/proposals/{p['proposal_id']}/accept"))
    assert out["status"] == "accepted" and out["ai_context"]["candidate"]["hex"] == WHITE
    item = get(client, f"/items/{ctx['item']}")
    assert item["version"] == v + 1
    assert (item["color_code"], item["color_name"], item["color_hex"]) == (None, "WHITE", WHITE)
    assert item["resolved"]["color"] == {
        "code": None,
        "name": "WHITE",
        "hex": WHITE,
        "family": "white",
        "source": "item",
    }
    # 购买事实与商品资料不变
    assert get(client, f"/purchase-lines/{ctx['line']}") == before["line"]
    assert get(client, f"/products/{ctx['product']}") == before["product"]
    # 筛选按新的有效颜色
    ids = [x["id"] for x in get(client, "/items?color=white")["items"]]
    assert ctx["item"] in ids
    logs = get(client, f"/changes?entity=wardrobe_item&entity_id={ctx['item']}&proposal_id={p['proposal_id']}")["items"]
    assert len(logs) == 1 and logs[0]["after"]["color_hex"] == WHITE and logs[0]["version_after"] == v + 1
    err(client.post(f"{API}/proposals/{p['proposal_id']}/accept"), 409, "PROPOSAL_NOT_PENDING")


def test_reject_changes_nothing(client, app, ctx):
    v = get(client, f"/items/{ctx['item']}")["version"]
    p = ok(suggest(client, ctx, v), 201)["proposal"]
    before = business_state(client, app, ctx)
    assert ok(client.post(f"{API}/proposals/{p['proposal_id']}/reject"))["status"] == "rejected"
    after = business_state(client, app, ctx)
    assert {k: after[k] for k in ("item", "product", "line", "facets", "logs")} == {
        k: before[k] for k in ("item", "product", "line", "facets", "logs")
    }


def _assert_stale(client, app, ctx, proposal_id):
    before = business_state(client, app, ctx)
    e = err(client.post(f"{API}/proposals/{proposal_id}/accept"), 409, "PROPOSAL_STALE")
    assert get(client, f"/proposals/{proposal_id}")["status"] == "pending"
    assert business_state(client, app, ctx) == before
    return e


def test_any_change_to_the_item_after_generation_makes_it_stale(client, app, ctx):
    v = get(client, f"/items/{ctx['item']}")["version"]
    p = ok(suggest(client, ctx, v), 201)["proposal"]
    ok(client.post(f"{API}/items/{ctx['item']}/wear", json={"version": v}))  # 与颜色无关的修改
    e = _assert_stale(client, app, ctx, p["proposal_id"])
    assert "version" in e["message"]


def test_unlinked_source_image_makes_it_stale(client, app, ctx):
    v = get(client, f"/items/{ctx['item']}")["version"]
    p = ok(suggest(client, ctx, v), 201)["proposal"]
    item = ok(client.delete(f"{API}/items/{ctx['item']}/images/{ctx['image']}", params={"version": v}))
    # 重新关联同一张图片也不行：version 已变
    ok(
        client.post(f"{API}/items/{ctx['item']}/images", json={"version": item["version"], "image_id": ctx["image"]}),
        201,
    )
    _assert_stale(client, app, ctx, p["proposal_id"])


def test_deleting_the_source_image_is_not_blocked_and_keeps_the_sha(client, app, ctx):
    v = get(client, f"/items/{ctx['item']}")["version"]
    p = ok(suggest(client, ctx, v), 201)["proposal"]
    sha = p["ai_context"]["image_sha256"]
    ok(client.delete(f"{API}/items/{ctx['item']}/images/{ctx['image']}", params={"version": v}))
    ok(client.delete(f"{API}/images/{ctx['image']}"), 204)  # 历史分析上下文不是业务引用
    ctx_out = get(client, f"/proposals/{p['proposal_id']}")["ai_context"]
    assert ctx_out["image_id"] is None and ctx_out["image_sha256"] == sha
    _assert_stale(client, app, ctx, p["proposal_id"])


def test_deleted_target_item_makes_it_stale(client, ctx):
    v = get(client, f"/items/{ctx['item']}")["version"]
    p = ok(suggest(client, ctx, v), 201)["proposal"]
    ok(client.delete(f"{API}/items/{ctx['item']}", params={"version": v}), 204)
    err(client.post(f"{API}/proposals/{p['proposal_id']}/accept"), 409, "PROPOSAL_STALE")


def test_bulk_accept_reports_stale_ai_suggestions_individually(client, ai, ctx):
    # 另一件已核实衣物上的普通（无上下文）提议
    p2 = make_product(client, identifiers=[], name_ja="另一件")
    other = make_purchase(client, p2["id"], color_code="09")["lines"][0]["item_ids"][0]
    ok(client.post(f"{API}/items/{other}/verify", json={"version": 1}))
    normal = ok(ai.patch(f"{API}/items/{other}", json={"version": 2, "size_label": "XL"}), 202)["proposed"][0]
    assert normal["ai_context"] is None
    v = get(client, f"/items/{ctx['item']}")["version"]
    sug = ok(suggest(client, ctx, v), 201)["proposal"]
    ok(client.post(f"{API}/items/{ctx['item']}/wear", json={"version": v}))
    out = ok(
        client.post(
            f"{API}/proposals/bulk", json={"ids": [normal["proposal_id"], sug["proposal_id"]], "decision": "accept"}
        )
    )
    by_id = {r["proposal_id"]: r for r in out["results"]}
    assert by_id[normal["proposal_id"]]["ok"] is True
    assert by_id[sug["proposal_id"]]["error"]["code"] == "PROPOSAL_STALE"


def test_ordinary_proposals_keep_their_original_rules(client, ai, ctx):
    """无上下文的普通提议：不相关字段修改后仍可接受（Phase 2 规则），不受新 AI 规则影响。"""
    v = get(client, f"/items/{ctx['item']}")["version"]
    ok(client.post(f"{API}/items/{ctx['item']}/verify", json={"version": v}))
    prop = ok(ai.patch(f"{API}/items/{ctx['item']}", json={"version": v + 1, "size_label": "XL"}), 202)["proposed"][0]
    ok(client.post(f"{API}/items/{ctx['item']}/wear", json={"version": v + 1}))
    assert ok(client.post(f"{API}/proposals/{prop['proposal_id']}/accept"))["status"] == "accepted"


def test_ai_patch_on_verified_item_supersedes_an_ai_suggestion_as_before(client, ai, ctx):
    v = get(client, f"/items/{ctx['item']}")["version"]
    ok(client.post(f"{API}/items/{ctx['item']}/verify", json={"version": v}))
    sug = ok(suggest(client, ctx, v + 1), 201)["proposal"]
    ok(ai.patch(f"{API}/items/{ctx['item']}", json={"version": v + 1, "color_hex": "#123456"}), 202)
    assert get(client, f"/proposals/{sug['proposal_id']}")["status"] == "superseded"


def test_import_revert_leaves_ai_suggestions_alone(client, app, ctx):
    v = get(client, f"/items/{ctx['item']}")["version"]
    sug = ok(suggest(client, ctx, v), 201)["proposal"]
    job = ok(client.post(f"{API}/imports", json=BASE_PAYLOAD), 201)
    ok(client.post(f"{API}/imports/{job['job_id']}/commit"))
    ok(client.post(f"{API}/imports/{job['job_id']}/revert"))
    assert get(client, f"/proposals/{sug['proposal_id']}")["status"] == "pending"
    assert ok(client.post(f"{API}/proposals/{sug['proposal_id']}/accept"))["status"] == "accepted"


def test_context_rows_are_one_per_suggestion(client, app, ctx):
    v = get(client, f"/items/{ctx['item']}")["version"]
    ok(suggest(client, ctx, v, NAVY), 201)
    ok(suggest(client, ctx, v, WHITE), 201)
    with app.state.sessionmaker() as s:
        rows = s.scalars(select(AISuggestionContext).order_by(AISuggestionContext.proposal_id)).all()
        assert [r.candidate["hex"] for r in rows] == [NAVY, WHITE]
        assert all(r.kind == "color" and r.target_version == v for r in rows)


# Claude 独立审查（docs/REVIEW_PHASE5A_CLAUDE_2026-10-27.md）P2-3 的复现，原样加入
def test_item_changed_during_computation_is_409_and_creates_nothing(client, app, ctx, monkeypatch):
    import wardrobe.api.suggestions as sug_api

    real = sug_api.run_analysis

    def slow(settings, source, region):
        out = real(settings, source, region)
        v = get(client, f"/items/{ctx['item']}")["version"]
        ok(client.post(f"{API}/items/{ctx['item']}/wear", json={"version": v}))
        return out

    monkeypatch.setattr(sug_api, "run_analysis", slow)
    v = get(client, f"/items/{ctx['item']}")["version"]
    err(suggest(client, ctx, v), 409, "VERSION_CONFLICT")
    assert business_state(client, app, ctx)["proposals"] == 0


# ───────────── 审查修复补充（P3-1 / P3-2 / P3-3） ─────────────


def test_analysis_response_is_one_consistent_snapshot(client, ctx, monkeypatch):
    """计算期间衣物颜色被修改：响应中的 version 与当前颜色都来自计算开始前的同一时刻。"""
    import wardrobe.api.suggestions as sug_api

    real = sug_api.run_analysis

    def slow(settings, source, region):
        out = real(settings, source, region)
        v = get(client, f"/items/{ctx['item']}")["version"]
        ok(client.patch(f"{API}/items/{ctx['item']}", json={"version": v, "color_hex": "#123456"}))
        return out

    monkeypatch.setattr(sug_api, "run_analysis", slow)
    before = get(client, f"/items/{ctx['item']}")
    out = ok(analyze(client, ctx))
    assert out["item_version"] == before["version"]
    assert out["current_color"] == {"color_code": None, "color_name": None, "color_hex": None}
    assert out["resolved_color"]["hex"] == before["resolved"]["color"]["hex"]


def test_image_unlinked_during_computation_is_409_and_creates_nothing(client, app, ctx, monkeypatch):
    import wardrobe.api.suggestions as sug_api

    real = sug_api.run_analysis

    def slow(settings, source, region):
        out = real(settings, source, region)
        # 直接删除关联行（不经 API，因此 version 不变），只测试关联核对本身
        with app.state.sessionmaker() as s:
            s.execute(
                text("DELETE FROM item_image WHERE item_id = :i AND image_id = :g"),
                {"i": ctx["item"], "g": ctx["image"]},
            )
            s.commit()
        return out

    monkeypatch.setattr(sug_api, "run_analysis", slow)
    v = get(client, f"/items/{ctx['item']}")["version"]
    e = err(suggest(client, ctx, v), 409, "VERSION_CONFLICT")
    assert "不再关联" in e["message"]
    assert business_state(client, app, ctx)["proposals"] == 0


@pytest.mark.parametrize(
    ("tamper", "reason"),
    [
        ("DELETE FROM item_image WHERE item_id = :i AND image_id = :g", "（来源图片已不再关联到这件衣物）"),
        (
            "UPDATE ai_suggestion_context SET image_sha256 = 'x' WHERE proposal_id = :p",
            "（来源图片已被删除或内容不同）",
        ),
        ("UPDATE ai_suggestion_context SET image_id = NULL WHERE proposal_id = :p", "（来源图片已被删除）"),
    ],
)
def test_each_source_check_rejects_acceptance_even_when_the_version_is_unchanged(client, app, ctx, tamper, reason):
    """version 核对之外的三项来源核对分别有效（审查 P3-3：此前都被 version 核对先拦下）。"""
    v = get(client, f"/items/{ctx['item']}")["version"]
    p = ok(suggest(client, ctx, v), 201)["proposal"]
    with app.state.sessionmaker() as s:
        s.execute(text(tamper), {"i": ctx["item"], "g": ctx["image"], "p": p["proposal_id"]})
        s.commit()
    assert get(client, f"/items/{ctx['item']}")["version"] == v
    e = err(client.post(f"{API}/proposals/{p['proposal_id']}/accept"), 409, "PROPOSAL_STALE")
    assert reason in e["message"]
    assert get(client, f"/proposals/{p['proposal_id']}")["status"] == "pending"
    assert get(client, f"/items/{ctx['item']}")["color_hex"] is None
