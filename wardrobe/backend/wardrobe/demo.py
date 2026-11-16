"""演示数据：通过正在运行的服务的 HTTP API 写入（上传生成的示意图 → 导入预览 → 提交）。

所有商品、编号、订单号均为虚构；图片是程序生成的纯色剪影，不使用任何网站的素材。
只能在没有任何商品的数据库中执行，避免混入真实数据。
"""

import io
import json
import urllib.error
import urllib.request
import uuid

from PIL import Image, ImageDraw

CLIENT = {"X-Wardrobe-Client": "cli"}

# (ref, 品牌, 分类, 日文名, 中文名, 颜色代码, 颜色名, HEX, 尺码, 材质, 剪影, 标签, 状态)
ITEMS = [
    ("tee-w", "uniqlo", "tops-tshirt-short", "クルーネックT（半袖）", "圆领T恤（短袖）", "00", "WHITE", "#F4F4F2", "M",
     "綿100%", "tee", ["基础款", "夏"], "owned"),
    ("tee-k", "uniqlo", "tops-tshirt-short", "クルーネックT（半袖）", "圆领T恤（短袖）", "09", "BLACK", "#1C1C1C", "M",
     "綿100%", "tee", ["基础款", "夏"], "owned"),
    ("ls-n", "uniqlo", "tops-tshirt-long", "ワッフルクルーネックT", "华夫格圆领T恤", "69", "NAVY", "#24304A", "L",
     "綿60%・ポリエステル40%", "tee", ["秋冬"], "owned"),
    ("knit-b", "uniqlo", "tops-knit", "メリノクルーネックセーター", "美利奴圆领毛衣", "32", "BEIGE", "#D8C7A8", "M",
     "毛100%", "knit", ["秋冬", "通勤"], "owned"),
    ("knit-g", "gu", "tops-knit", "ワッフルクルーネックセーター", "华夫格毛衣", "56", "OLIVE", "#5E6B3A", "L",
     "アクリル70%・ナイロン30%", "knit", ["秋冬"], "owned"),
    ("sweat", "gu", "tops-sweat", "スウェットパーカ", "连帽卫衣", "03", "GRAY", "#9A9A9A", "L",
     "綿80%・ポリエステル20%", "hoodie", ["休闲"], "owned"),
    ("oxford", "uniqlo", "tops-shirt-oxford", "オックスフォードシャツ", "牛津纺衬衫", "61", "BLUE", "#8FAACC", "M",
     "綿100%", "shirt", ["通勤"], "owned"),
    ("flannel", "uniqlo", "tops-shirt-flannel", "フランネルチェックシャツ", "法兰绒格子衬衫", "15", "RED", "#9E2B2B", "L",
     "綿100%", "shirt", ["秋冬", "休闲"], "owned"),
    ("uld", "uniqlo", "outer-light-down", "ウルトラライトダウンジャケット", "高级轻型羽绒茄克", "69", "NAVY", "#1F2A44",
     "L", "表地:ナイロン100%／詰め物:ダウン90%・フェザー10%", "coat", ["秋冬", "通勤"], "owned"),
    ("fleece", "uniqlo", "outer-fleece", "ファーリーフリースジャケット", "摇粒绒茄克", "31", "CREAM", "#EFE6D2", "L",
     "ポリエステル100%", "coat", ["秋冬", "家居"], "owned"),
    ("coat", "uniqlo", "outer-coat", "ウールブレンドチェスターコート", "羊毛混纺切斯特大衣", "08", "DARK GRAY", "#3A3A3C",
     "L", "表地:ポリエステル52%・毛40%・その他8%", "coat", ["秋冬", "通勤"], "owned"),
    ("jeans", "uniqlo", "bottoms-jeans", "ストレートジーンズ", "直筒牛仔裤", "67", "BLUE", "#3D5A80", "76cm",
     "綿99%・ポリウレタン1%", "pants", ["基础款"], "owned"),
    ("chino", "gu", "bottoms-chino", "スリムチノパンツ", "修身休闲裤", "32", "BEIGE", "#C9B48A", "M",
     "綿98%・ポリウレタン2%", "pants", ["通勤"], "owned"),
    ("slacks", "uniqlo", "bottoms-slacks", "スマートアンクルパンツ", "九分西裤", "08", "DARK GRAY", "#45474D", "M",
     "ポリエステル68%・レーヨン27%・ポリウレタン5%", "pants", ["通勤"], "owned"),
    ("shorts", "gu", "bottoms-shorts", "リネンブレンドショーツ", "亚麻混纺短裤", "57", "OLIVE", "#7A7F4E", "M",
     "麻55%・綿45%", "shorts", ["夏"], "owned"),
    ("heat", "uniqlo", "innerwear-heattech", "ヒートテッククルーネックT", "保暖圆领T恤", "09", "BLACK", "#202020", "M",
     "ポリエステル34%・アクリル30%・レーヨン30%・ポリウレタン6%", "tee", ["秋冬"], "owned"),
    ("tee-r", "gu", "tops-tshirt-short", "ドライクルーネックT", "速干圆领T恤", "19", "PINK", "#E9B4C0", "S",
     "ポリエステル100%", "tee", ["夏"], "returned"),
    ("polo", "uniqlo", "tops-polo", "ドライカノコポロシャツ", "速干珠地网眼POLO衫", "00", "WHITE", "#F7F7F5", "M",
     "綿70%・ポリエステル30%", "tee", ["夏", "通勤"], "owned"),
]  # fmt: skip


def _shape(kind: str, w: int, h: int) -> list[tuple[float, float]]:
    """简单的服装剪影（相对坐标 → 像素）。"""
    shapes = {
        "tee": [(.30, .18), (.42, .14), (.58, .14), (.70, .18), (.86, .32), (.77, .40), (.70, .35), (.70, .82),
                (.30, .82), (.30, .35), (.23, .40), (.14, .32)],
        "knit": [(.30, .16), (.42, .13), (.58, .13), (.70, .16), (.84, .70), (.75, .72), (.70, .40), (.70, .84),
                 (.30, .84), (.30, .40), (.25, .72), (.16, .70)],
        "hoodie": [(.36, .14), (.50, .08), (.64, .14), (.72, .20), (.86, .70), (.76, .72), (.70, .42), (.70, .84),
                   (.30, .84), (.30, .42), (.24, .72), (.14, .70), (.28, .20)],
        "shirt": [(.32, .15), (.45, .12), (.50, .18), (.55, .12), (.68, .15), (.84, .72), (.75, .74), (.70, .40),
                  (.71, .86), (.29, .86), (.30, .40), (.25, .74), (.16, .72)],
        "coat": [(.33, .12), (.45, .10), (.50, .16), (.55, .10), (.67, .12), (.84, .78), (.75, .80), (.72, .42),
                 (.73, .92), (.27, .92), (.28, .42), (.25, .80), (.16, .78)],
        "pants": [(.30, .10), (.70, .10), (.74, .92), (.56, .92), (.50, .30), (.44, .92), (.26, .92)],
        "shorts": [(.28, .22), (.72, .22), (.78, .66), (.56, .68), (.50, .40), (.44, .68), (.22, .66)],
    }  # fmt: skip
    return [(x * w, y * h) for x, y in shapes[kind]]


def garment_png(hex_color: str, kind: str) -> bytes:
    w, h = 600, 800
    img = Image.new("RGB", (w, h), (240, 239, 236))
    draw = ImageDraw.Draw(img)
    rgb = tuple(int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    outline = tuple(max(0, c - 40) for c in rgb)
    draw.polygon(_shape(kind, w, h), fill=rgb, outline=outline)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _request(base: str, method: str, path: str, body=None, headers=None, raw: bytes | None = None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hdrs = {**CLIENT, **(headers or {})}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {path} 失败：{exc.code} {exc.read().decode(errors='replace')}") from exc


def _upload(base: str, png: bytes, note: str) -> int:
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="source_type"\r\n\r\nother\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="source_note"\r\n\r\n{note}\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="demo.png"\r\n'
        f"Content-Type: image/png\r\n\r\n".encode()
        + png
        + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    out = _request(base, "POST", "/api/v1/images", raw=b"".join(parts),
                   headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})  # fmt: skip
    return out["id"]


def build_payload(image_ids: dict[str, int]) -> dict:
    products, purchases, items = [], [], []
    for i, (ref, brand, cat, ja, zh, code, cname, hex_, size, material, _kind, tags, status) in enumerate(ITEMS):
        products.append(
            {
                "ref": f"p-{ref}", "brand": brand, "category": cat, "name_ja": ja, "name_zh": zh,
                "identifiers": [{"scheme": "item_no", "value": f"DEMO-{i + 1:03d}"}],
                "colors": [{"color_code": code, "name_ja": cname, "hex": hex_, "is_default": True}],
                "sizes": [{"size_label": size}], "material_text": material,
                "images": [{"image_id": image_ids[ref], "role": "main"}],
            }
        )  # fmt: skip
        month = 1 + i % 10
        purchases.append(
            {
                "purchased_on": f"2025-{month:02d}-{10 + i % 15:02d}",
                "store_name": "示例店（虚构）", "order_no": f"DEMO-ORDER-{i + 1:03d}", "create_items": True,
                "lines": [{"ref": f"l-{ref}", "product_ref": f"p-{ref}", "item_code_raw": f"DEMO-{i + 1:03d}",
                           "color_code": code, "color_name": cname, "color_hex": hex_, "size_label": size,
                           "quantity": 1, "unit_price": 990 + (i % 6) * 1000}],
            }
        )  # fmt: skip
        item = {"ref": f"i-{ref}", "purchase_line_ref": f"l-{ref}", "tags": tags, "location": "衣柜"}
        if status == "returned":
            item.update(status="returned", retired_on=f"2025-{month:02d}-28", refund_amount=990)
        items.append(item)
    outfits = [
        {"name": "秋季通勤", "season": "autumn", "tags": ["通勤"],
         "items": [{"item_ref": "i-uld", "slot": "outer"}, {"item_ref": "i-oxford", "slot": "top"},
                   {"item_ref": "i-slacks", "slot": "bottom"}]},
        {"name": "周末休闲", "season": "all", "tags": ["休闲"],
         "items": [{"item_ref": "i-sweat", "slot": "top"}, {"item_ref": "i-jeans", "slot": "bottom"}]},
    ]  # fmt: skip
    return {"format": "wardrobe.import/v1", "source_label": "演示数据（虚构）", "products": products,
            "purchases": purchases, "items": items, "outfits": outfits}  # fmt: skip


def seed_demo(base: str) -> dict:
    meta = _request(base, "GET", "/api/v1/meta")
    if meta["counts"]["product"]:
        raise RuntimeError("数据库中已有商品。演示数据只能写入空数据库（可用 WARDROBE_DATA_DIR 指定另一个目录）")
    image_ids = {ref: _upload(base, garment_png(hex_, kind), f"演示用示意图 {ref}")
                 for ref, *_, hex_, _s, _m, kind, _t, _st in ITEMS}  # fmt: skip
    job = _request(base, "POST", "/api/v1/imports", build_payload(image_ids))
    if not job["can_commit"]:
        raise RuntimeError(f"演示数据预览有错误：{json.dumps(job['summary'], ensure_ascii=False)}")
    done = _request(base, "POST", f"/api/v1/imports/{job['job_id']}/commit")
    return {"job_id": done["job_id"], "summary": done["summary"], "images": len(image_ids)}
