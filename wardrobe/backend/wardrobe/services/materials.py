"""材质原文解析（DATA_MODEL R3）。

支持形如：
  本体:綿100%／リブ:綿98%・ポリウレタン2%
  表地:ナイロン100%/裏地:ナイロン100%/詰め物:ダウン90%・フェザー10%
  綿60%, ポリエステル40%
解析失败时返回空列表和 warning，原文始终保留。
"""

import re
import unicodedata
from dataclasses import dataclass

FIBERS = {
    "cotton": ["綿", "コットン", "棉", "纯棉", "cotton"],
    "polyester": ["ポリエステル", "聚酯纤维", "涤纶", "polyester"],
    "nylon": ["ナイロン", "锦纶", "尼龙", "nylon", "polyamide"],
    "polyurethane": ["ポリウレタン", "氨纶", "polyurethane", "elastane", "spandex"],
    "wool": ["毛", "ウール", "羊毛", "wool"],
    "cashmere": ["カシミヤ", "カシミア", "羊绒", "cashmere"],
    "rayon": ["レーヨン", "人造丝", "粘纤", "粘胶纤维", "rayon", "viscose"],
    "linen": ["麻", "リネン", "亚麻", "linen"],
    "acrylic": ["アクリル", "腈纶", "acrylic"],
    "silk": ["絹", "シルク", "真丝", "桑蚕丝", "silk"],
    "cupro": ["キュプラ", "铜氨纤维", "cupro"],
    "modal": ["モダール", "莫代尔", "modal"],
    "lyocell": ["リヨセル", "テンセル", "莱赛尔", "lyocell", "tencel"],
    "down": ["ダウン", "羽绒", "down"],
    "feather": ["フェザー", "羽毛", "feather"],
    "polypropylene": ["ポリプロピレン", "丙纶", "polypropylene"],
}
PARTS = {
    "body": ["本体", "身生地", "身頃", "主体", "body"],
    "shell": ["表地", "表面", "面料", "shell"],
    "lining": ["裏地", "里料", "lining"],
    "rib": ["リブ", "罗纹", "rib"],
    "fill": ["詰め物", "中わた", "中綿", "填充物", "fill"],
    "pocket": ["ポケット袋布", "袋布", "口袋布", "pocket"],
}

_FIBER_LOOKUP = {alias.lower(): key for key, aliases in FIBERS.items() for alias in aliases}
_PART_LOOKUP = {alias.lower(): key for key, aliases in PARTS.items() for alias in aliases}
_PART_SPLIT = re.compile(r"[／/\n;；]")
_FIBER_SPLIT = re.compile(r"[・、,，]")
_FIBER_RE = re.compile(r"^(?P<name>.+?)\s*(?P<pct>\d+(?:\.\d+)?)\s*%$")


@dataclass
class ParsedMaterial:
    part: str
    part_raw: str | None
    fiber: str
    fiber_raw: str
    percent: float | None


def fiber_key(raw: str) -> str:
    raw = raw.strip().lower()
    if raw in _FIBER_LOOKUP:
        return _FIBER_LOOKUP[raw]
    # 「指定外繊維(テンセル)」之类：括号内再查一次
    m = re.search(r"[(（](.+?)[)）]", raw)
    if m and m.group(1).strip() in _FIBER_LOOKUP:
        return _FIBER_LOOKUP[m.group(1).strip()]
    return "other"


def parse_material_text(text: str) -> tuple[list[ParsedMaterial], list[dict]]:
    warnings: list[dict] = []
    result: list[ParsedMaterial] = []
    norm = unicodedata.normalize("NFKC", text)
    for chunk in _PART_SPLIT.split(norm):
        chunk = chunk.strip()
        if not chunk:
            continue
        part_raw = None
        if ":" in chunk:
            part_raw, chunk = (s.strip() for s in chunk.split(":", 1))
        part = _PART_LOOKUP.get(part_raw.lower(), part_raw) if part_raw else "body"
        part_total = 0.0
        for piece in _FIBER_SPLIT.split(chunk):
            piece = piece.strip()
            if not piece:
                continue
            m = _FIBER_RE.match(piece)
            if not m:
                warnings.append({"code": "material_parse_failed", "message": f"无法解析材质片段 {piece!r}"})
                return [], warnings
            pct = float(m.group("pct"))
            part_total += pct
            result.append(ParsedMaterial(part, part_raw, fiber_key(m.group("name")), m.group("name").strip(), pct))
        if part_total and abs(part_total - 100) > 0.01:
            warnings.append(
                {"code": "percent_sum_not_100", "message": f"部位 {part_raw or part} 百分比合计为 {part_total:g}%"}
            )
    if not result:
        warnings.append({"code": "material_parse_failed", "message": "材质原文中没有识别到成分"})
    return result, warnings
