"""Phase 5C：基于现有资料的标签 / 分类建议（规则 wardrobe-tagcat/3）。

不使用模型或外部服务。只读计算候选；用户选择后才生成待确认提议（create_suggestions），接受仍走 /proposals。

标签（只追加，不删除已有标签）：
* 同一商品的其他衣物（未删除、任何状态）带有、而这件衣物没有的标签 → 建议；
* 或：同类相似衣物中至少 MIN_SIMILAR_SUPPORT 件、且占比至少 MIN_SIMILAR_RATIO 带有的标签 → 建议。
  同类相似衣物 = 按 5B 评分（services/similar.py 的 score，持有中）达到门槛、且分类完全相同或同属一个二级分类的衣物，
  按 5B 的顺序取前 SIMILAR_POOL 件；只靠同色、共有标签或同一级分类的衣物不作为标签证据（季节、用途不能跨品类传播）；
* 或：商品名称（日 / 中 / 英）含 NAME_TAGS 中的词 → 建议对应的中文常用叫法（如「パーカ」→ 帽衫、连帽卫衣）。
  每个词条有适用范围（分类 slug，多为一级分类；None 表示材质等不限品类的词）：衣物已有有效分类时只用范围包含该分类的词条；
  还没有分类时，命中的词条与名称中命中的分类名（同分类建议的关键词）合起来跨不同一级分类，就都不用
  （如「スウェットショートパンツ」），不限品类的词条照常使用；范围窄于一级分类的词条（ヒートテック → 保暖内衣）
  还要求名称中命中的分类都在其范围内或是其上级（「ヒートテックソックス」命中袜子，不建议保暖内衣）；
* 排序：同商品证据优先 → 商品名称 → 相似衣物中的件数降序 → 标签名；最多 MAX_TAGS 个。

分类（只给有效分类为空的衣物，写入衣物自身的分类）：
* 分类的中文名、日文名（按「・」「·」「/」拆开）规范化后长度 ≥ MIN_KEYWORD_LEN 作为关键词；
  另加 CATEGORY_ALIASES 中的商品名称常用词（如「UT」→ T恤·针织、「キャップ」→ 帽子），纯英文字母的词要求前后不是字母；
* 「保暖内衣」「清凉内衣」（ヒートテック / エアリズム 是技术系列名）是弱分类：名称还命中上衣以外、
  且不是其上级的分类时不计，如「ヒートテックソックス」→ 袜子、「ヒートテックリブビーニー」→ 帽子；
  与上衣同时命中（「エアリズム…Tシャツ」，可能是内衣也可能是 T 恤）仍按跨一级分类判为不明确；
* 商品的日 / 中 / 英文名规范化后包含关键词即命中（每个分类取命中的最长关键词）；
* 命中的分类属于不同的一级分类（如「スウェットショートパンツ」同时命中上衣和下装）→ 不明确，不建议；
* 否则取命中分类中层级最深的；最深一层有多个分类命中时，取命中关键词最长的那个；最长长度并列时视为不明确，不建议。

wardrobe-tagcat/1 → /2：分类增加跨一级分类判为不明确；相似衣物的标签证据只计同类 / 同二级分类。
wardrobe-tagcat/2 → /3：标签增加「商品名称中的常用叫法」来源；分类增加别名词与弱分类。
"""

import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..errors import validation
from ..models import Category, ChangeProposal, Product, RuleSuggestionContext, WardrobeItem
from .common import now_iso, require_version
from .proposals import create_proposal
from .similar import MIN_SCORE, score
from .text import normalize_tag, normalize_text

ALGORITHM = "wardrobe-tagcat/3"
SIMILAR_POOL = 10
MIN_SIMILAR_SUPPORT = 2
MIN_SIMILAR_RATIO = 0.3
MAX_TAGS = 5
MIN_KEYWORD_LEN = 2
# 相似衣物要计入标签证据，5B 评分理由中必须有其一
TAG_EVIDENCE_KINDS = ("same_category", "same_group")
# 商品名称中的词 → 中文常用叫法。（词, 名称中出现时先去掉的长词, 叫法, 适用范围的分类 slug 或 None）
NAME_TAGS: tuple[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], str | None], ...] = (
    (("パーカ", "フーディ"), (), ("帽衫", "连帽卫衣"), "tops"),
    (("スウェット",), (), ("卫衣",), "tops"),
    (("セーター", "ニット"), (), ("毛衣", "针织衫"), "tops"),
    (("カーディガン",), (), ("开衫",), "tops"),
    (("Tシャツ",), (), ("T恤",), "tops"),
    (("シャツ",), ("Tシャツ", "ポロシャツ"), ("衬衫",), "tops"),
    (("ジャケット", "ブルゾン"), (), ("夹克",), "outer"),
    (("コート",), (), ("大衣",), "outer"),
    (("ダッフル",), (), ("牛角扣大衣",), "outer"),
    (("ダウン",), (), ("羽绒服",), "outer"),
    (("フリース",), (), ("抓绒", "摇粒绒"), "outer"),
    (("ジーンズ", "デニム"), (), ("牛仔",), None),
    (("スカート",), (), ("半身裙",), "bottoms"),
    (("ワンピース",), (), ("连衣裙",), "dresses"),
    (("キャミソール",), (), ("吊带",), None),
    (("ブーツ",), (), ("靴子",), "shoes"),
    (("ベルト",), (), ("腰带",), "accessories"),
    (("ソックス", "靴下"), (), ("袜子",), "innerwear"),
    # 技术系列名：只用于保暖内衣本身，HEATTECH 袜子、帽子、围巾不是「保暖内衣」
    (("ヒートテック",), (), ("保暖内衣",), "innerwear-heattech"),
    # 袖长（不限品类）：衣橱的「半袖」快捷分组按这两个标签筛选
    (("半袖", "5分袖", "ショートスリーブ"), (), ("短袖",), None),
    (("ノースリーブ", "タンクトップ"), (), ("无袖",), None),
)
# 分类名覆盖不到的商品名称常用词 → 分类 slug：[(词, 名称中出现时先去掉的长词)]
CATEGORY_ALIASES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "tops-tshirt": (
        ("UT", ()), ("クルーネックT", ()), ("VネックT", ()), ("タートルネックT", ()), ("タートルT", ()),
        ("スウェT", ()), ("タンクトップ", ()),
    ),
    "tops-shirt": (("ブラウス", ()),),
    "tops-knit": (("カーディガン", ()),),
    "bottoms-skirt": (("キュロット", ()), ("スコート", ())),
    "bottoms-shorts": (("ショーツ", ("シームレスショーツ",)),),
    "innerwear": (("タイツ", ()),),
    "innerwear-underwear": (("ブリーフ", ()), ("トランクス", ()), ("シームレスショーツ", ())),
    "innerwear-socks": (("ソックス", ()),),
    "accessories-hat": (("キャップ", ()), ("ハット", ()), ("ビーニー", ())),
    "bags": (("バックパック", ()), ("リュック", ())),
    "shoes": (("ブーツ", ()), ("スニーカー", ()), ("サンダル", ()), ("ローファー", ())),
    "accessories-scarf": (("グローブ", ()),),
    "accessories": (("ネクタイ", ()), ("アンブレラ", ())),
}  # fmt: skip
# 技术系列名对应的分类：名称还命中上衣以外、且不是其上级的分类时不计
WEAK_CATEGORIES = ("innerwear-heattech", "innerwear-airism")
REASONS = {
    "tags": "规则建议：根据同一商品的其他衣物、同类相似衣物的标签和商品名称中的常用叫法，不是图像识别",
    "category": "规则建议：根据商品名称中的分类名称，不是图像识别",
}


def rules() -> dict:
    return {
        "algorithm": ALGORITHM,
        "similar_pool": SIMILAR_POOL,
        "min_similar_support": MIN_SIMILAR_SUPPORT,
        "min_similar_ratio": MIN_SIMILAR_RATIO,
        "similar_evidence_kinds": list(TAG_EVIDENCE_KINDS),
        "max_tags": MAX_TAGS,
        "name_tag_entries": len(NAME_TAGS),
        "category_alias_words": sum(len(v) for v in CATEGORY_ALIASES.values()),
        "weak_categories": list(WEAK_CATEGORIES),
        "min_keyword_length": MIN_KEYWORD_LEN,
    }


def _effective_category(item: WardrobeItem) -> int | None:
    return item.category_id if item.category_id is not None else item.product.category_id


class Library:
    """一次请求共用的资料：全部分类与未删除衣物（含标签、商品）只读一次，批量预览 / 生成不再逐件查询整库。"""

    def __init__(self, session: Session):
        self.cats = list(session.scalars(select(Category)))
        self.cat_by_id = {c.id: c for c in self.cats}
        items = session.scalars(
            select(WardrobeItem)
            .where(WardrobeItem.deleted_at.is_(None))
            .options(selectinload(WardrobeItem.tags), selectinload(WardrobeItem.product).selectinload(Product.category))
        ).all()
        self.by_product: dict[int, list[WardrobeItem]] = defaultdict(list)
        for it in items:
            self.by_product[it.product_id].append(it)
        self.owned = [it for it in items if it.status == "owned"]


def evidence_pool(item: WardrobeItem, lib: Library) -> list[WardrobeItem]:
    """同类相似衣物：沿用 5B 的评分、门槛与顺序，先过滤出同类 / 同二级分类的，再取前 SIMILAR_POOL 件。"""
    ranked = []
    for other in lib.owned:
        if other.id == item.id:
            continue
        total, reasons, n_tags = score(item, other, lib.cat_by_id)
        if total >= MIN_SCORE and any(r["kind"] in TAG_EVIDENCE_KINDS for r in reasons):
            ranked.append((total, n_tags, other))
    ranked.sort(key=lambda r: (-r[0], -r[1], -r[2].id))
    return [r[2] for r in ranked[:SIMILAR_POOL]]


def name_tags(item: WardrobeItem, lib: Library) -> list[tuple[str, str]]:
    """商品名称中的常用叫法：返回 [(叫法, 命中的词)]，按 NAME_TAGS 顺序。"""
    text = _name_text(item)
    hits = []
    by_id = lib.cat_by_id
    by_slug = {c.slug: c for c in lib.cats}
    for words, excludes, names, scope in NAME_TAGS:
        t = text
        for x in excludes:
            t = t.replace(normalize_text(x), " ")
        word = next((w for w in words if normalize_text(w) in t), None)
        if word is not None and (scope is None or scope in by_slug):
            hits.append((word, names, by_slug.get(scope) if scope else None))

    def within(c: Category, root: Category) -> bool:
        while c is not None:
            if c.id == root.id:
                return True
            c = by_id.get(c.parent_id) if c.parent_id else None
        return False

    cat = by_id.get(_effective_category(item))
    if cat is not None:
        hits = [h for h in hits if h[2] is None or within(cat, h[2])]
    else:
        named = _keyword_hits(text, lib.cats)
        tops = {_top(h[2], by_id) for h in hits if h[2] is not None} | {_top(c, by_id) for c, _ in named}
        if len(tops) > 1:
            hits = [h for h in hits if h[2] is None]  # 跨一级分类：名称里的修饰词不能决定是哪类衣物
        # 范围窄于一级分类的词条：名称中命中的分类都要在其范围内，或是其上级
        hits = [
            h for h in hits
            if h[2] is None or h[2].parent_id is None or all(within(c, h[2]) or within(h[2], c) for c, _ in named)
        ]  # fmt: skip
    return [(name, word) for word, names, _ in hits for name in names]


def tag_suggestions(item: WardrobeItem, lib: Library) -> list[dict]:
    have = {t.name_norm for t in item.tags}
    found: dict[str, dict] = {}

    def entry(tag) -> dict:
        return found.setdefault(tag.name_norm, {"name": tag.name, "same_product": [], "similar": [], "name_words": []})

    for other in lib.by_product.get(item.product_id, []):
        if other.id == item.id:
            continue
        for t in other.tags:
            if t.name_norm not in have:
                entry(t)["same_product"].append(other.id)

    for name, word in name_tags(item, lib):
        norm = normalize_tag(name)
        if norm not in have:
            e = found.setdefault(norm, {"name": name, "same_product": [], "similar": [], "name_words": []})
            if word not in e["name_words"]:
                e["name_words"].append(word)

    pool = evidence_pool(item, lib)
    for other in pool:
        for t in other.tags:
            if t.name_norm not in have:
                entry(t)["similar"].append(other.id)

    out = []
    for norm, e in found.items():
        n = len(e["similar"])
        by_similar = n >= MIN_SIMILAR_SUPPORT and pool and n / len(pool) >= MIN_SIMILAR_RATIO
        if not (e["same_product"] or e["name_words"] or by_similar):
            continue
        reasons = []
        if e["same_product"]:
            ids = "、".join(f"#{i}" for i in sorted(e["same_product"]))
            reasons.append({"kind": "same_product", "label": f"同一商品的其他衣物有此标签（{ids}）"})
        if e["name_words"]:
            words = "」「".join(e["name_words"])
            reasons.append({"kind": "name_alias", "label": f"商品名称含「{words}」（常用叫法）"})
        if n:
            reasons.append({"kind": "similar_items", "label": f"相似衣物中 {n}/{len(pool)} 件有此标签"})
        out.append(
            {
                "name": e["name"],
                "norm": norm,
                "reasons": reasons,
                "evidence": {
                    "same_product_item_ids": sorted(e["same_product"]),
                    "name_words": e["name_words"],
                    "similar_item_ids": e["similar"],
                    "similar_pool": len(pool),
                },
            }
        )
    out.sort(
        key=lambda s: (
            not s["evidence"]["same_product_item_ids"],
            not s["evidence"]["name_words"],
            -len(s["evidence"]["similar_item_ids"]),
            s["norm"],
        )
    )
    return out[:MAX_TAGS]


def _keywords(c: Category) -> list[str]:
    raw = [c.name_zh, *(re.split(r"[・·/／]", c.name_ja) if c.name_ja else []), *re.split(r"[・·/／]", c.name_zh)]
    seen, out = set(), []
    for k in raw:
        n = normalize_text(k)
        if len(n) >= MIN_KEYWORD_LEN and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _name_text(item: WardrobeItem) -> str:
    p = item.product
    return normalize_text(" ".join(n for n in (p.name_ja, p.name_zh, p.name_en) if n))


def _contains(text: str, word: str) -> bool:
    if re.fullmatch(r"[a-z0-9]+", word):  # 纯英文字母 / 数字：不能是更长单词的一部分（如 UT 不匹配 OUTER）
        return re.search(rf"(?<![a-z0-9]){word}(?![a-z0-9])", text) is not None
    return word in text


def _alias_hits(text: str, slug: str) -> list[str]:
    out = []
    for word, excludes in CATEGORY_ALIASES.get(slug, ()):
        t = text
        for x in excludes:
            t = t.replace(normalize_text(x), " ")
        w = normalize_text(word)
        if len(w) >= MIN_KEYWORD_LEN and _contains(t, w):
            out.append(w)
    return out


def _keyword_hits(text: str, cats: list[Category]) -> list[tuple[Category, str]]:
    """名称中命中的分类：[(分类, 命中的最长关键词)]。弱分类按 WEAK_CATEGORIES 的规则去掉。"""
    hits = []
    for c in cats:
        kws = [k for k in _keywords(c) if k in text] + _alias_hits(text, c.slug)
        if kws:
            hits.append((c, max(kws, key=len)))
    by_id = {c.id: c for c in cats}

    def ancestors(c: Category) -> set[int]:
        out = set()
        while c.parent_id is not None and c.parent_id in by_id:
            c = by_id[c.parent_id]
            out.add(c.id)
        return out

    def overridden(weak: Category) -> bool:
        above = ancestors(weak)
        return any(
            c.slug not in WEAK_CATEGORIES and by_id[_top(c, by_id)].slug != "tops" and c.id not in above
            for c, _ in hits
        )

    return [(c, kw) for c, kw in hits if not (c.slug in WEAK_CATEGORIES and overridden(c))]


def category_suggestion(item: WardrobeItem, cats: list[Category]) -> tuple[dict | None, str | None]:
    """返回（建议, 没有建议时的原因代码）。"""
    if _effective_category(item) is not None:
        return None, "already_categorized"
    hits = _keyword_hits(_name_text(item), cats)
    if not hits:
        return None, "no_keyword_match"
    by_id = {x.id: x for x in cats}
    if len({_top(c, by_id) for c, _ in hits}) > 1:
        return None, "ambiguous"  # 跨一级分类：名称里的修饰词不能决定品类
    deepest = max(c.level for c, _ in hits)
    top = [(c, kw) for c, kw in hits if c.level == deepest]
    longest = max(len(kw) for _, kw in top)
    top = [(c, kw) for c, kw in top if len(kw) == longest]
    if len({c.id for c, _ in top}) > 1:
        return None, "ambiguous"
    c, kw = top[0]
    path, node = [], c
    while node is not None:
        path.append(node.name_zh)
        node = by_id.get(node.parent_id) if node.parent_id else None
    return {
        "category_id": c.id,
        "slug": c.slug,
        "path": list(reversed(path)),
        "reasons": [{"kind": "name_keyword", "label": f"商品名称含「{kw}」"}],
        "evidence": {"keyword": kw, "matched_category_ids": sorted({x.id for x, _ in hits})},
    }, None


def _top(c: Category, by_id: dict[int, Category]) -> int:
    while c.parent_id is not None and c.parent_id in by_id:
        c = by_id[c.parent_id]
    return c.id


def suggestions_for(session: Session, item: WardrobeItem, lib: Library | None = None) -> dict:
    lib = lib if lib is not None else Library(session)
    category, note = category_suggestion(item, lib.cats)
    return {
        "item_id": item.id,
        "item_version": item.version,
        "tags": tag_suggestions(item, lib),
        "category": category,
        "category_note": note,
    }


def create_suggestions(
    session: Session,
    *,
    actor: str,
    item: WardrobeItem,
    version: int,
    tags: list[str],
    category_id: int | None,
    lib: Library | None = None,
) -> list[ChangeProposal]:
    """按用户选择生成提议。服务端重新计算，只接受仍在本次计算结果中的标签 / 分类。"""
    require_version(item, version)
    if not tags and category_id is None:
        raise validation(["tags"], "empty", "请至少选择一个标签或分类建议")
    current = suggestions_for(session, item, lib)
    by_norm = {s["norm"]: s for s in current["tags"]}
    chosen = []
    for i, name in enumerate(tags):
        s = by_norm.get(normalize_tag(name))
        if s is None:
            raise validation(["tags", i], "not_a_suggestion", f"「{name}」不在当前的标签建议中")
        if s not in chosen:
            chosen.append(s)
    cat = current["category"]
    if category_id is not None and (cat is None or cat["category_id"] != category_id):
        raise validation(["category_id"], "not_a_suggestion", "该分类不在当前的分类建议中")
    out = []
    if chosen:
        p = create_proposal(
            session, actor=actor, entity="wardrobe_item", entity_id=item.id, field="tags_add",
            current=[t.name for t in item.tags], proposed=[s["name"] for s in chosen], reason=REASONS["tags"],
        )  # fmt: skip
        _context(
            session,
            p,
            "tags",
            item.version,
            {"tags": [{k: s[k] for k in ("name", "reasons", "evidence")} for s in chosen]},
        )
        out.append(p)
    if category_id is not None:
        p = create_proposal(
            session, actor=actor, entity="wardrobe_item", entity_id=item.id, field="category_id",
            current=item.category_id, proposed=category_id, reason=REASONS["category"],
        )  # fmt: skip
        _context(session, p, "category", item.version, {k: cat[k] for k in ("slug", "path", "reasons", "evidence")})
        out.append(p)
    session.flush()
    for p in out:
        session.refresh(p, ["rule_context"])
    return out


def _context(session: Session, p: ChangeProposal, kind: str, version: int, evidence: dict) -> None:
    session.add(
        RuleSuggestionContext(
            proposal_id=p.id,
            kind=kind,
            target_version=version,
            algorithm=ALGORITHM,
            evidence=evidence,
            created_at=now_iso(),
        )  # fmt: skip
    )


def rule_context_stale_reason(p: ChangeProposal, obj: WardrobeItem) -> str | None:
    """分类建议：接受前衣物（含商品）必须仍然没有有效分类。标签是只追加，不需要额外核对。"""
    ctx = p.rule_context
    if ctx is not None and ctx.kind == "category" and _effective_category(obj) is not None:
        return "衣物已经有分类了"
    return None


def missing_tags(obj: WardrobeItem, names: list[str]) -> list[str]:
    have = {t.name_norm for t in obj.tags}
    return [n for n in names if normalize_tag(n) not in have]
