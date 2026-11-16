"""初始品牌与默认三级分类。仅在对应表为空时写入，用户之后可自由修改。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Brand, Category
from .services.common import now_iso

BRANDS = [
    ("uniqlo", "UNIQLO", "ユニクロ", "优衣库", "https://www.uniqlo.com/jp/ja/"),
    ("gu", "GU", "ジーユー", "GU", "https://www.gu-global.com/jp/ja/"),
]

# (slug, 中文, 日文, 子分类)
CATEGORIES = [
    ("tops", "上衣", "トップス", [
        ("tops-tshirt", "T恤·针织", "Tシャツ・ニット", [
            ("tops-tshirt-short", "短袖T恤", "半袖Tシャツ"),
            ("tops-tshirt-long", "长袖T恤", "長袖Tシャツ"),
            ("tops-knit", "针织衫", "ニット・セーター"),
            ("tops-sweat", "卫衣", "スウェット・パーカー"),
        ]),
        ("tops-shirt", "衬衫", "シャツ", [
            ("tops-shirt-oxford", "牛津纺衬衫", "オックスフォードシャツ"),
            ("tops-shirt-flannel", "法兰绒衬衫", "フランネルシャツ"),
            ("tops-shirt-linen", "亚麻衬衫", "リネンシャツ"),
            ("tops-shirt-other", "其他衬衫", "その他シャツ"),
        ]),
        ("tops-polo", "Polo衫", "ポロシャツ", []),
    ]),
    ("outer", "外套", "アウター", [
        ("outer-down", "羽绒", "ダウン", [
            ("outer-light-down", "轻羽绒", "ウルトラライトダウン"),
            ("outer-down-jacket", "羽绒服", "ダウンジャケット"),
        ]),
        ("outer-jacket", "夹克", "ジャケット・ブルゾン", []),
        ("outer-coat", "大衣", "コート", []),
        ("outer-fleece", "抓绒", "フリース", []),
        ("outer-blazer", "西装外套", "テーラードジャケット", []),
    ]),
    ("bottoms", "下装", "ボトムス", [
        ("bottoms-pants", "裤子", "パンツ", [
            ("bottoms-jeans", "牛仔裤", "ジーンズ"),
            ("bottoms-chino", "休闲裤", "チノ・カジュアルパンツ"),
            ("bottoms-slacks", "西裤", "スラックス"),
            ("bottoms-sweatpants", "运动裤", "スウェットパンツ"),
        ]),
        ("bottoms-shorts", "短裤", "ショートパンツ", []),
        ("bottoms-skirt", "裙子", "スカート", []),
    ]),
    ("dresses", "连衣裙", "ワンピース", []),
    ("innerwear", "内衣·家居", "インナー・ルームウェア", [
        ("innerwear-heattech", "保暖内衣", "ヒートテック", []),
        ("innerwear-airism", "清凉内衣", "エアリズム", []),
        ("innerwear-underwear", "内裤", "下着", []),
        ("innerwear-socks", "袜子", "靴下", []),
        ("innerwear-loungewear", "家居服", "ルームウェア", []),
    ]),
    ("shoes", "鞋", "シューズ", []),
    ("bags", "包", "バッグ", []),
    ("accessories", "配饰", "小物", [
        ("accessories-hat", "帽子", "帽子", []),
        ("accessories-belt", "腰带", "ベルト", []),
        ("accessories-scarf", "围巾·手套", "マフラー・手袋", []),
    ]),
]  # fmt: skip


def seed_defaults(session: Session) -> None:
    now = now_iso()
    if not session.scalar(select(func.count()).select_from(Brand)):
        for slug, name, ja, zh, url in BRANDS:
            session.add(
                Brand(slug=slug, name=name, name_ja=ja, name_zh=zh, website=url, created_at=now, updated_at=now)
            )

    if not session.scalar(select(func.count()).select_from(Category)):

        def add(nodes, parent: Category | None, level: int):
            for order, node in enumerate(nodes):
                slug, zh, ja, *rest = node
                cat = Category(
                    slug=slug,
                    name_zh=zh,
                    name_ja=ja,
                    level=level,
                    parent_id=parent.id if parent else None,
                    sort_order=order,
                    created_at=now,
                    updated_at=now,
                )
                session.add(cat)
                session.flush()
                if rest and rest[0]:
                    add(rest[0], cat, level + 1)

        add(CATEGORIES, None, 1)
    session.commit()
