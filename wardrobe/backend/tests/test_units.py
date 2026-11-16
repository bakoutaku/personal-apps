"""纯函数：文本规范化、颜色族、材质解析。"""

import pytest

from wardrobe.services.colors import color_family, normalize_hex
from wardrobe.services.materials import parse_material_text
from wardrobe.services.text import normalize_identifier, normalize_text


def test_normalize_text_folds_width_case_and_kana():
    assert normalize_text("ｳﾙﾄﾗﾗｲﾄﾀﾞｳﾝ") == normalize_text("ウルトラライトダウン") == "うるとららいとだうん"
    assert normalize_text("ＵＮＩＱＬＯ　エアリズム") == "uniqlo えありずむ"


def test_normalize_identifier_keeps_scheme_semantics():
    assert normalize_identifier(" e465185-000 ") == "E465185-000"
    assert normalize_identifier("４６５１８５") == "465185"


@pytest.mark.parametrize(
    ("hex_value", "family"),
    [
        ("#1A1A1A", "black"),
        ("#000000", "black"),
        ("#FFFFFF", "white"),
        ("#F7F7F5", "white"),
        ("#808080", "gray"),
        ("#1F2A44", "navy"),
        ("#2F5DA8", "blue"),
        ("#F5F5DC", "beige"),
        ("#C3B091", "beige"),
        ("#6B4226", "brown"),
        ("#C8102E", "red"),
        ("#F4B6C2", "pink"),
        ("#F28C28", "orange"),
        ("#F2D21B", "yellow"),
        ("#3B7A3B", "green"),
        ("#556B2F", "green"),
        ("#6A3D9A", "purple"),
    ],
)
def test_color_family(hex_value, family):
    assert color_family(hex_value) == family


def test_normalize_hex():
    assert normalize_hex("#1f2a44") == "#1F2A44"
    with pytest.raises(ValueError):
        normalize_hex("1f2a44")
    with pytest.raises(ValueError):
        normalize_hex("#abc")


def test_parse_uniqlo_style_material():
    parsed, warnings = parse_material_text("本体:綿100%／リブ:綿98%・ポリウレタン2%")
    assert warnings == []
    assert [(m.part, m.fiber, m.percent) for m in parsed] == [
        ("body", "cotton", 100),
        ("rib", "cotton", 98),
        ("rib", "polyurethane", 2),
    ]
    assert parsed[1].fiber_raw == "綿" and parsed[1].part_raw == "リブ"


def test_parse_material_without_part_and_fullwidth():
    parsed, warnings = parse_material_text("綿６０％、ポリエステル４０％")
    assert warnings == []
    assert [(m.part, m.fiber, m.percent) for m in parsed] == [("body", "cotton", 60), ("body", "polyester", 40)]


def test_parse_material_unknown_fiber_and_bad_sum():
    parsed, warnings = parse_material_text("指定外繊維(テンセル)50%・謎素材30%")
    assert [m.fiber for m in parsed] == ["lyocell", "other"]
    assert [w["code"] for w in warnings] == ["percent_sum_not_100"]


def test_parse_material_failure_keeps_nothing():
    parsed, warnings = parse_material_text("やわらかい素材")
    assert parsed == []
    assert warnings[0]["code"] == "material_parse_failed"
