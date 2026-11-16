"""文本规范化：搜索、标签去重、编号查重共用。"""

import re
import unicodedata

_SPACE = re.compile(r"\s+")
_KATA_START, _KATA_END = 0x30A1, 0x30F6  # ァ..ヶ
_KATA_TO_HIRA = {c: c - 0x60 for c in range(_KATA_START, _KATA_END + 1)}


def normalize_text(s: str | None) -> str:
    """NFKC（全角→半角、半角片假名→全角）→ 小写 → 片假名转平假名 → 压缩空白。"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower().translate(_KATA_TO_HIRA)
    return _SPACE.sub(" ", s).strip()


def normalize_identifier(value: str) -> str:
    """编号查重用：NFKC、大写、去掉空白。不做任何跨体系推断。"""
    return _SPACE.sub("", unicodedata.normalize("NFKC", value)).upper()


def normalize_tag(name: str) -> str:
    return normalize_text(name)


def clean_str(s: str | None) -> str | None:
    """去首尾空白，空字符串视为 None。"""
    if s is None:
        return None
    s = s.strip()
    return s or None
