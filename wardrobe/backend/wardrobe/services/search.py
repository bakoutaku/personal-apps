"""模糊搜索（ARCHITECTURE §6）：FTS5 trigram + 文本规范化；1–2 字符的词退化为 LIKE。"""

from sqlalchemy import ColumnElement, and_, column, text

from ..models import WardrobeItem
from .text import normalize_text

_ALL_COLS = "names || ' ' || brand || ' ' || codes || ' ' || colors || ' ' || materials || ' ' || tags || ' ' || notes"


def tokens(q: str) -> list[str]:
    return [t for t in normalize_text(q).split(" ") if t]


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def item_search_clause(q: str) -> ColumnElement[bool] | None:
    """返回「衣物 id 命中全部词」的条件（词之间 AND）。"""
    clauses = []
    for i, tok in enumerate(tokens(q)):
        name = f"q{i}"
        if len(tok) >= 3:
            sub = text(f"SELECT rowid FROM search_index WHERE search_index MATCH :{name}").bindparams(
                **{name: '"' + tok.replace('"', '""') + '"'}
            )
        else:
            sub = text(f"SELECT rowid FROM search_index WHERE ({_ALL_COLS}) LIKE :{name} ESCAPE '\\'").bindparams(
                **{name: f"%{_like_escape(tok)}%"}
            )
        clauses.append(WardrobeItem.id.in_(sub.columns(column("rowid"))))
    return and_(*clauses) if clauses else None
