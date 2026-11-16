"""颜色：HEX 规范化与颜色族计算（DATA_MODEL R7）。"""

import colorsys
import re
import unicodedata

COLOR_FAMILIES = (
    "black", "white", "gray", "beige", "brown", "red", "pink", "orange",
    "yellow", "green", "blue", "navy", "purple", "multi",
)  # fmt: skip

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def normalize_hex(value: str | None) -> str | None:
    """接受 #rrggbb / #RRGGBB，统一为大写；其他格式抛 ValueError。"""
    if value is None:
        return None
    value = value.strip()
    if not HEX_RE.match(value):
        raise ValueError(f"颜色值必须为 #RRGGBB 格式，收到 {value!r}")
    return value.upper()


def color_family(hex_value: str | None) -> str | None:
    if not hex_value:
        return None
    r, g, b = (int(hex_value[i : i + 2], 16) / 255 for i in (1, 3, 5))
    h, lightness, s = colorsys.rgb_to_hls(r, g, b)
    h *= 360

    if lightness <= 0.15:
        return "black"
    if lightness >= 0.9 and s < 0.35:
        return "white"
    if s < 0.12 or (s < 0.2 and 0.2 < lightness < 0.85 and not 20 <= h <= 65):
        return "gray"
    if 200 <= h < 250 and lightness < 0.32:
        return "navy"
    if 20 <= h <= 65:
        if lightness >= 0.7 or (s < 0.4 and lightness >= 0.45):
            return "beige"
        if lightness < 0.45 and h < 50:
            return "brown"
    if h < 15 or h >= 345:
        return "pink" if lightness >= 0.75 else ("brown" if lightness < 0.3 and s < 0.6 else "red")
    if h < 40:
        return "brown" if lightness < 0.35 else "orange"
    if h < 70:
        return "yellow"
    if h < 170:
        return "green"
    if h < 250:
        return "blue"
    if h < 290:
        return "purple"
    return "pink"


# ---- 没有颜色值时：按颜色名称（及优衣库 / GU 色号）给出圆点的示意色 ----
# 示意色只用于显示，不写入颜色值（color_hex），也不参与颜色族（颜色族仍只按 HEX 计算，R7）。
# 每条：(名称写法, 示意色, 所属色系, 是否按色号深浅调整)；色系只用于核对色号的十位
_NAMED: tuple[tuple[tuple[str, ...], str, str, bool], ...] = (
    (("WHITE", "ホワイト", "白", "白色"), "#FFFFFF", "white", False),
    (("OFF WHITE", "オフホワイト", "米白", "米白色"), "#F2EEE3", "white", False),
    (("IVORY", "アイボリー", "象牙白"), "#F3EDDC", "white", False),
    (("NATURAL", "ナチュラル", "自然色"), "#E8DCC6", "beige", False),
    (("CREAM", "クリーム", "奶油色"), "#F1E6C8", "beige", False),
    (("LIGHT GRAY", "LIGHT GREY", "ライトグレー", "浅灰", "浅灰色"), "#C8C8C8", "gray", False),
    (("GRAY", "GREY", "グレー", "灰", "灰色"), "#8C8C8C", "gray", True),
    (("DARK GRAY", "DARK GREY", "ダークグレー", "深灰", "深灰色"), "#4A4A4A", "gray", False),
    (("CHARCOAL", "チャコール", "炭灰"), "#3C3C3C", "gray", False),
    (("BLACK", "ブラック", "黑", "黑色"), "#1C1C1C", "black", False),
    (("BEIGE", "ベージュ", "米色"), "#D2BE9C", "beige", True),
    (("BROWN", "ブラウン", "棕", "棕色"), "#7A5534", "brown", True),
    (("DARK BROWN", "ダークブラウン", "深棕", "深棕色"), "#4A3224", "brown", False),
    (("CAMEL", "キャメル", "驼色"), "#B08452", "brown", False),
    (("PINK", "ピンク", "粉", "粉色"), "#E8B4C0", "pink", True),
    (("RED", "レッド", "红", "红色"), "#B3262E", "red", True),
    (("WINE", "ワイン", "酒红", "酒红色"), "#6E2232", "red", False),
    (("ORANGE", "オレンジ", "橙", "橙色"), "#E07B39", "orange", True),
    (("YELLOW", "イエロー", "黄", "黄色"), "#E8C547", "yellow", True),
    (("GREEN", "グリーン", "绿", "绿色"), "#4F7A4A", "green", True),
    (("DARK GREEN", "ダークグリーン", "深绿", "深绿色"), "#2F4A36", "green", False),
    (("OLIVE", "オリーブ", "橄榄绿", "橄榄色"), "#6B6A3A", "green", False),
    (("LIGHT BLUE", "ライトブルー", "浅蓝", "浅蓝色"), "#A9C4DF", "blue", False),
    (("BLUE", "ブルー", "蓝", "蓝色"), "#4B78B5", "blue", True),
    (("NAVY", "ネイビー", "藏青", "藏青色", "海军蓝"), "#1F2A44", "navy", False),
    (("PURPLE", "パープル", "紫", "紫色"), "#6A4C93", "purple", True),
)
_BY_NAME = {name: (hex_, family, shade) for names, hex_, family, shade in _NAMED for name in names}
# 优衣库 / GU 色号：十位表示色系，个位越大颜色越深（如 61 BLUE 偏浅、68 BLUE 偏深）
_CODE_DECADE = {"gray": 0, "pink": 1, "red": 1, "orange": 2, "beige": 3, "brown": 3, "yellow": 4,
                "green": 5, "blue": 6, "purple": 7}  # fmt: skip
CODE_SHADE_BRANDS = {"uniqlo", "gu"}
_CODE_RE = re.compile(r"[0-9]{2}")


def _name_key(name: str | None) -> str | None:
    if not name:
        return None
    return " ".join(unicodedata.normalize("NFKC", name).upper().split()) or None


def _shade(hex_value: str, digit: int) -> str:
    r, g, b = (int(hex_value[i : i + 2], 16) / 255 for i in (1, 3, 5))
    h, _lightness, s = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(h, min(0.85, max(0.2, 0.80 - 0.06 * digit)), s)
    return "#" + "".join(f"{round(v * 255):02X}" for v in (r, g, b))


def display_swatch(hex_value: str | None, name: str | None, code: str | None, brand_slug: str | None) -> dict:
    """圆点显示用的颜色：有颜色值用颜色值；否则按颜色名称给示意色，优衣库 / GU 再按色号调深浅。"""
    if hex_value:
        return {"hex": hex_value, "source": "hex"}
    hit = _BY_NAME.get(_name_key(name) or "")
    if hit is None:
        return {"hex": None, "source": None}
    base, family, shade = hit
    if (
        shade
        and brand_slug in CODE_SHADE_BRANDS
        and code
        and _CODE_RE.fullmatch(code)  # 只认 ASCII 两位数字；isdigit() 会把「²」等也当数字，int() 却转不了
        and int(code[0]) == _CODE_DECADE[family]
    ):
        return {"hex": _shade(base, int(code[1])), "source": "name_code"}
    return {"hex": base, "source": "name"}
