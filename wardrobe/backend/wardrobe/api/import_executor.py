"""导入执行器：把 wardrobe.import/v1 的每一行变成对现有 API 写函数的调用。

* 预览与提交使用同一段代码：预览时在保存点内执行后整体回滚，提交时重新执行并与预览比对。
* 每一行在自己的保存点内执行；出错只回滚该行，依赖它的行标为 dependency_failed。
* 请求方固定为 "import:<发起者>"（受限请求方），因此已核实记录的受保护字段一律转为修改提议。
* API 写函数在 defer_commit 下只 flush，整个导入是一个事务。
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..import_schema import ImportItem, ImportLine, ImportOutfit, ImportPayload, ImportProduct, ImportPurchase
from ..models import (
    ChangeProposal,
    Outfit,
    Product,
    ProductIdentifier,
    Purchase,
    PurchaseLine,
    WardrobeItem,
)
from ..schemas import (
    ColorIn,
    ColorsPut,
    IdentifierAdd,
    ItemCreate,
    ItemImageLink,
    ItemPatch,
    LineAdd,
    LinePatch,
    MaterialsPut,
    OutfitCreate,
    OutfitItemIn,
    OutfitItemsPut,
    OutfitPatch,
    ProductCreate,
    ProductImageLink,
    ProductPatch,
    PurchaseCreate,
    PurchasePatch,
    SizeIn,
    SizesPut,
    TagsPut,
)
from ..services import products as product_svc
from ..services.categories import resolve_category
from ..services.proposals import blocked_fields, create_proposal
from ..services.text import normalize_identifier, normalize_text
from . import items as items_api
from . import outfits as outfits_api
from . import products as products_api
from . import purchases as purchases_api

PRODUCT_SCALARS = product_svc.SCALAR_FIELDS
PURCHASE_FIELDS = ("purchased_on", "channel", "store_name", "order_no", "total_amount", "currency", "notes")
LINE_FIELDS = (
    "product_id", "product_match", "item_code_raw", "name_raw", "color_code", "color_name", "color_hex",
    "size_label", "size_system", "quantity", "unit_price", "discount_amount", "notes", "attributes",
)  # fmt: skip
ITEM_FIELDS = (
    "category_id", "color_code", "color_name", "color_hex", "size_label", "size_system", "condition",
    "acquired_on", "location", "alterations", "favorite", "notes", "attributes", "status", "retired_on",
    "refund_amount", "wear_count", "last_worn_on",
)  # fmt: skip
# 新建衣物时这些字段先不写，创建后再用 PATCH 写入（与 API 相同：新衣物先是 owned，退货等状态随后变更）
ITEM_AFTER_CREATE = ("status", "retired_on", "refund_amount", "wear_count", "last_worn_on")
OUTFIT_FIELDS = ("name", "description", "season", "occasion", "rating", "cover_image_id", "attributes")
# 判断「无订单号的购买是否与已有记录完全相同」时比较的明细事实（第一个必须是 product_id）
LINE_FACTS = (
    "product_id", "item_code_raw", "name_raw", "color_code", "color_name", "color_hex", "size_label",
    "size_system", "quantity", "unit_price", "discount_amount",
)  # fmt: skip


@dataclass
class Row:
    index: int
    entity: str
    ref: str | None
    action: str = "skip"
    target_id: int | None = None
    match_reason: str | None = None
    normalized: dict | None = None
    diff: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def plan_key(self) -> tuple:
        """预览与提交比对用（BUG-011）。

        新建记录的 id 在预览中没有意义，不参与比对。会修改已有记录的行（update / propose）还比对
        「匹配时目标记录的 version」：预览之后该记录只要被改过（字段、子集合、标签、关联都会增加 version），
        提交就会因 PREVIEW_STALE 被拒绝，不会覆盖预览之后的人工修改。
        """
        basis = self.diff.get("basis_version") if self.action in ("update", "propose") else None
        return (self.entity, self.ref, self.action, self.match_reason,
                None if self.action == "create" else self.target_id, basis)  # fmt: skip


class DependencyFailed(Exception):
    pass


def _empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _api_error(exc: ApiError) -> dict:
    return {"code": exc.code, "message": exc.message, "details": exc.details}


def _validation_error(exc: ValidationError) -> dict:
    details = [{"loc": list(e["loc"]), "code": e["type"], "message": e["msg"]} for e in exc.errors()]
    return {"code": "VALIDATION_ERROR", "message": f"{len(details)} 个字段校验失败", "details": details}


class ImportExecutor:
    def __init__(self, session: Session, payload: ImportPayload, *, actor: str):
        self.session = session
        self.payload = payload
        self.actor = f"import:{actor}"
        self.options = payload.options
        self.rows: list[Row] = []
        self.refs: dict[str, dict[str, int]] = {"product": {}, "purchase": {}, "line": {}, "item": {}, "outfit": {}}
        self.failed: dict[str, set[str]] = {k: set() for k in self.refs}
        self.claimed_items: set[int] = set()
        self.claimed_purchases: set[int] = set()  # 本批次已匹配或新建的购买，不能再被后面的行匹配

    # ───────────── 通用 ─────────────

    def _row(self, entity: str, ref: str | None, normalized: dict | None) -> Row:
        row = Row(index=len(self.rows), entity=entity, ref=ref, normalized=normalized)
        self.rows.append(row)
        return row

    def _ref(self, kind: str, ref: str | None, given_id: int | None) -> int | None:
        if ref is None:
            return given_id
        if ref in self.failed[kind]:
            raise DependencyFailed(f"依赖的 {kind} ref {ref!r} 导入失败")
        return self.refs[kind][ref]

    def _run(self, row: Row, fn) -> None:
        """在保存点内执行一行；失败时回滚该行并记录错误。"""
        proposals_before = len(self.session.info.get("proposals_created", []))
        try:
            with self.session.begin_nested():
                fn(row)
        except DependencyFailed as exc:
            row.action, row.target_id = "error", None
            row.errors.append({"code": "dependency_failed", "message": str(exc)})
        except ApiError as exc:
            row.action, row.target_id = "error", None
            row.errors.append(_api_error(exc))
        except ValidationError as exc:
            row.action, row.target_id = "error", None
            row.errors.append(_validation_error(exc))
        except IntegrityError as exc:
            row.action, row.target_id = "error", None
            row.errors.append({"code": "CONSTRAINT_VIOLATION", "message": str(exc.orig), "details": []})
        if row.action == "error":
            del self.session.info.setdefault("proposals_created", [])[proposals_before:]

    def _proposals_since(self, start: int) -> list[int]:
        return self.session.info.get("proposals_created", [])[start:]

    @staticmethod
    def _basis(row: Row, obj) -> None:
        """记录匹配到已有记录时它的 version（在本行做任何修改之前）。"""
        row.diff["basis_version"] = obj.version

    def _settle(self, row: Row, obj, version_before: int, proposals_start: int, extra_changed: bool = False) -> None:
        """根据版本变化与新提议决定已有记录这一行的动作。"""
        self.session.refresh(obj)
        proposals = self._proposals_since(proposals_start)
        changed = obj.version != version_before or extra_changed
        if proposals:
            row.diff["proposals"] = proposals
        row.action = "update" if changed else ("propose" if proposals else "skip")
        if changed and proposals:
            row.warnings.append(
                {"code": "partially_proposed", "message": f"已核实字段生成了 {len(proposals)} 条修改提议"}
            )

    def _pick(self, obj, desired: dict) -> dict:
        """按 on_existing 选出需要写入的字段。"""
        mode = self.options.on_existing
        out = {}
        for k, v in desired.items():
            cur = getattr(obj, k)
            if mode == "fill_empty":
                if _empty(cur) and not _empty(v):
                    out[k] = v
            elif cur != v:
                out[k] = v
        return out

    # ───────────── 商品 ─────────────

    def _match_product(self, p: ImportProduct, brand_id: int | None, row: Row) -> Product | None:
        s = self.session
        if p.id is not None:
            obj = s.get(Product, p.id)
            if obj is None or obj.deleted_at is not None:
                raise ApiError(404, "NOT_FOUND", f"商品 {p.id} 不存在")
            row.match_reason = "id"
            return obj
        found: dict[int, str] = {}
        for ident in p.identifiers:
            q = (
                select(Product.id)
                .join(ProductIdentifier, ProductIdentifier.product_id == Product.id)
                .where(
                    ProductIdentifier.scheme == ident.scheme,
                    ProductIdentifier.value_norm == normalize_identifier(ident.value),
                    Product.deleted_at.is_(None),
                    Product.brand_id.is_(None) if brand_id is None else Product.brand_id == brand_id,
                )
            )
            for pid in s.scalars(q):
                found.setdefault(pid, f"identifier:{ident.scheme}")
        if len(found) > 1:
            raise ApiError(
                409, "AMBIGUOUS_MATCH", f"编号同时匹配到多个商品 {sorted(found)}", [{"product_ids": sorted(found)}]
            )
        if found:
            ((pid, reason),) = found.items()
            row.match_reason = reason
            return s.get(Product, pid)
        if not p.identifiers:
            for name_field in ("name_ja", "name_zh", "name_en"):
                name = getattr(p, name_field)
                if not name:
                    continue
                q = select(Product).where(
                    Product.deleted_at.is_(None),
                    Product.brand_id.is_(None) if brand_id is None else Product.brand_id == brand_id,
                )
                hits = [x for x in s.scalars(q) if normalize_text(getattr(x, name_field)) == normalize_text(name)]
                if len(hits) == 1:
                    row.match_reason = f"name:{name_field}"
                    row.warnings.append({"code": "matched_by_name",
                                         "message": f"没有编号，按同品牌同名匹配到已有商品 {hits[0].id}"})  # fmt: skip
                    return hits[0]
        return None

    def import_product(self, p: ImportProduct) -> None:
        row = self._row("product", p.ref, p.model_dump(mode="json", exclude_unset=True))

        def run(row: Row) -> None:
            s = self.session
            brand = (
                product_svc.resolve_brand(s, p.brand, p.brand_id)
                if {"brand", "brand_id"} & p.model_fields_set
                else None
            )
            obj = self._match_product(p, brand.id if brand else None, row)
            if obj is None:
                body = ProductCreate(
                    **p.model_dump(exclude={"ref", "id", "images"}, exclude_unset=True, exclude_none=True)
                )
                out = products_api.create_product(body, s, self.actor)
                obj = s.get(Product, out["id"])
                obj.import_job_id = s.info.get("import_job_id")
                row.action, row.target_id = "create", obj.id
                row.warnings.extend(out.get("warnings", []))
                self._link_product_images(obj, p)
                return
            row.target_id = obj.id
            self._basis(row, obj)
            if self.options.on_existing == "skip":
                row.action = "skip"
                return
            self._update_product(obj, p, row)

        self._run(row, run)
        if row.action == "error":
            if p.ref:
                self.failed["product"].add(p.ref)
        elif p.ref:
            self.refs["product"][p.ref] = row.target_id

    def _update_product(self, obj: Product, p: ImportProduct, row: Row) -> None:
        s = self.session
        version_before, start = obj.version, len(self.session.info.get("proposals_created", []))
        desired = {f: getattr(p, f) for f in PRODUCT_SCALARS if f in p.model_fields_set}
        refs = product_svc.resolve_refs(s, ProductPatch(**p.model_dump(include={"brand", "brand_id", "category",
                                                                                 "category_id"}, exclude_unset=True)))  # fmt: skip
        desired.update(refs)
        fields = self._pick(obj, desired)
        if fields:
            row.diff["fields"] = {k: [getattr(obj, k), v] for k, v in fields.items()}
            products_api.patch_product(obj.id, ProductPatch(version=obj.version, **fields), s, self.actor)
            s.refresh(obj)

        # 子集合只追加，不删除
        self._add_identifiers(obj, p, row)

        snapshot = product_svc.collection_snapshot(obj, "colors")
        have = {(c["color_code"], c["name_ja"]) for c in snapshot}
        has_default = any(c["is_default"] for c in snapshot)
        new_colors = []
        for c in p.colors:
            if (c.color_code, c.name_ja) in have:
                continue
            data = c.model_dump(mode="json")
            if data["is_default"] and has_default:
                data["is_default"] = False
                row.warnings.append({"code": "default_color_kept",
                                     "message": f"已有默认颜色，{c.name_ja or c.color_code} 不设为默认"})  # fmt: skip
            has_default = has_default or data["is_default"]
            new_colors.append(data)
        if new_colors:
            s.refresh(obj)
            merged = [ColorIn(**c) for c in snapshot + new_colors]
            products_api.put_colors(obj.id, ColorsPut(version=obj.version, colors=merged), s, self.actor)
            row.diff["colors_added"] = new_colors

        sizes = product_svc.collection_snapshot(obj, "sizes")
        new_sizes = [
            sz.model_dump(mode="json") for sz in p.sizes if sz.size_label not in {x["size_label"] for x in sizes}
        ]
        if new_sizes:
            s.refresh(obj)
            merged = [SizeIn(**x) for x in sizes + new_sizes]
            products_api.put_sizes(obj.id, SizesPut(version=obj.version, sizes=merged), s, self.actor)
            row.diff["sizes_added"] = new_sizes

        if not obj.materials and (p.materials or ("material_text" in fields and fields["material_text"])):
            s.refresh(obj)
            products_api.put_materials(obj.id, MaterialsPut(version=obj.version, materials=p.materials), s, self.actor)
            row.diff["materials_set"] = True

        self._link_product_images(obj, p)
        self._settle(row, obj, version_before, start)

    def _add_identifiers(self, obj: Product, p: ImportProduct, row: Row) -> None:
        """一行中的全部新编号作为一个整体处理（BUG-015）。

        先逐个做唯一性校验（任何一个非法，整行失败、不留部分结果）；已核实商品生成**一条**包含全部新编号的
        提议（同一批次已有的待处理编号提议会被合并，而不是被取代）；未核实商品直接逐个添加。
        """
        s = self.session
        s.refresh(obj)
        seen = {(i.scheme, i.value_norm) for i in obj.identifiers}
        new = []
        for ident in p.identifiers:
            key = (ident.scheme, normalize_identifier(ident.value))
            if key in seen:
                continue
            seen.add(key)
            product_svc.build_identifier(s, obj, ident)  # 唯一性校验（同品牌、同 scheme）
            new.append({"scheme": ident.scheme, "value": ident.value, "source": ident.source})
        if not new:
            return
        row.diff["identifiers_added"] = new
        if blocked_fields(self.actor, "product", obj, {"identifiers"}):
            pending = s.scalar(
                select(ChangeProposal).where(
                    ChangeProposal.entity == "product",
                    ChangeProposal.entity_id == obj.id,
                    ChangeProposal.field == "identifiers",
                    ChangeProposal.status == "pending",
                    ChangeProposal.import_job_id == s.info.get("import_job_id"),
                )
            )
            base = pending.proposed_value if pending else product_svc.collection_snapshot(obj, "identifiers")
            have = {(i["scheme"], normalize_identifier(i["value"])) for i in base}
            merged = base + [i for i in new if (i["scheme"], normalize_identifier(i["value"])) not in have]
            create_proposal(
                s, actor=self.actor, entity="product", entity_id=obj.id, field="identifiers",
                current=product_svc.collection_snapshot(obj, "identifiers"), proposed=merged,
            )  # fmt: skip
            return
        for ident in new:
            s.refresh(obj)
            products_api.add_identifier(obj.id, IdentifierAdd(version=obj.version, **ident), s, self.actor)

    def _link_product_images(self, obj: Product, p: ImportProduct) -> None:
        for img in p.images:
            self.session.refresh(obj)
            if any(pi.image_id == img.image_id for pi in obj.images):
                continue
            body = ProductImageLink(version=obj.version, **img.model_dump())
            products_api.add_product_image(obj.id, body, self.session, self.actor)

    # ───────────── 购买 ─────────────

    @staticmethod
    def _line_sig(product_id, item_code_raw, color_code, color_name, size_label) -> tuple:
        """购买记录内定位明细用的签名（已按订单号或 id 确定是同一笔购买之后）。"""
        return (product_id, item_code_raw, color_code, color_name, size_label)

    def _payload_facts(self, pur: ImportPurchase) -> tuple:
        """这笔购买若被新建，会写入的全部购买事实（缺省值按 API 的默认值计算）。"""
        header = (pur.channel or "store", pur.currency or "JPY", pur.total_amount)
        lines = Counter(
            (self._ref("product", ln.product_ref, ln.product_id), *(getattr(ln, f) for f in LINE_FACTS[1:]))
            for ln in pur.lines
        )
        return header, lines

    @staticmethod
    def _record_facts(purchase: Purchase) -> tuple:
        header = (purchase.channel, purchase.currency, purchase.total_amount)
        lines = Counter(tuple(getattr(ln, f) for f in LINE_FACTS) for ln in purchase.lines)
        return header, lines

    def _match_purchase(self, pur: ImportPurchase, row: Row) -> Purchase | None:
        s = self.session
        if pur.id is not None:
            obj = s.get(Purchase, pur.id)
            if obj is None or obj.deleted_at is not None:
                raise ApiError(404, "NOT_FOUND", f"购买记录 {pur.id} 不存在")
            row.match_reason = "id"
            return obj
        if pur.order_no:
            obj = s.scalar(
                select(Purchase).where(
                    Purchase.order_no == pur.order_no,
                    Purchase.deleted_at.is_(None),
                    Purchase.store_name.is_(None) if pur.store_name is None else Purchase.store_name == pur.store_name,
                )
            )
            if obj is not None:
                row.match_reason = "order_no"
            return obj
        # 没有订单号（BUG-012 / 013）：只有当「这笔购买若被新建将写入的全部事实」与已有记录完全一致时，
        # 才视为同一笔（保证重复导入幂等）；任何事实不同（折扣、单价、渠道、币种、总额、颜色……）都新建。
        # 用多重集比较，可哈希、不排序，None 与字符串混合也不会出错；重复的明细按数量计。
        want = self._payload_facts(pur)
        candidates = s.scalars(
            select(Purchase)
            .where(
                Purchase.purchased_on == pur.purchased_on.isoformat(),
                Purchase.deleted_at.is_(None),
                Purchase.store_name.is_(None) if pur.store_name is None else Purchase.store_name == pur.store_name,
                Purchase.order_no.is_(None),
            )
            .order_by(Purchase.id)
        )
        for c in candidates:
            if c.id not in self.claimed_purchases and self._record_facts(c) == want:
                row.match_reason = "exact_duplicate"
                return c
        return None

    def import_purchase(self, pur: ImportPurchase) -> None:
        row = self._row("purchase", pur.ref, pur.model_dump(mode="json", exclude_unset=True, exclude={"lines"}))
        line_rows = [
            self._row("purchase_line", ln.ref, ln.model_dump(mode="json", exclude_unset=True)) for ln in pur.lines
        ]
        state: dict = {}

        def run(row: Row) -> None:
            s = self.session
            obj = self._match_purchase(pur, row)
            if obj is None:
                lines = []
                for ln in pur.lines:
                    data = ln.model_dump(exclude={"ref", "id", "product_ref"}, exclude_unset=True)
                    data["product_id"] = self._ref("product", ln.product_ref, ln.product_id)
                    lines.append(data)
                body = PurchaseCreate(
                    **pur.model_dump(include=set(PURCHASE_FIELDS), exclude_unset=True, exclude_none=True),
                    lines=lines,
                    create_items=pur.create_items,
                )
                out = purchases_api.create_purchase(body, s, self.actor)
                row.action, row.target_id = "create", out["id"]
                self.claimed_purchases.add(out["id"])
                s.get(Purchase, out["id"]).import_job_id = s.info.get("import_job_id")
                for lr, ln_out in zip(line_rows, out["lines"], strict=True):
                    lr.action, lr.target_id = "create", ln_out["id"]
                    if ln_out["item_ids"]:
                        lr.diff["items_created"] = ln_out["item_ids"]
                state["created"] = True
                return
            row.target_id = obj.id
            self.claimed_purchases.add(obj.id)
            self._basis(row, obj)
            state["obj"] = obj
            if self.options.on_existing == "skip":
                row.action = "skip"
                return
            version_before = obj.version
            desired = pur.model_dump(include=set(PURCHASE_FIELDS), exclude_unset=True, mode="json")
            fields = self._pick(obj, desired)
            if fields:
                row.diff["fields"] = {k: [getattr(obj, k), v] for k, v in fields.items()}
                purchases_api.patch_purchase(obj.id, PurchasePatch(version=obj.version, **fields), s, self.actor)
            s.refresh(obj)
            row.action = "update" if obj.version != version_before else "skip"

        self._run(row, run)
        if row.action == "error":
            for lr in line_rows:
                lr.action = "error"
                lr.errors.append({"code": "dependency_failed", "message": "所属购买记录导入失败"})
        elif not state.get("created"):
            obj = state["obj"]
            used: set[int] = set()
            for lr, ln in zip(line_rows, pur.lines, strict=True):
                self._run(lr, lambda lr, ln=ln: self._import_line(obj, ln, lr, used, pur.create_items))
        if row.action != "error" and pur.ref:
            self.refs["purchase"][pur.ref] = row.target_id
        for lr, ln in zip(line_rows, pur.lines, strict=True):
            if ln.ref:
                if lr.action == "error":
                    self.failed["line"].add(ln.ref)
                else:
                    self.refs["line"][ln.ref] = lr.target_id

    def _import_line(self, purchase: Purchase, ln: ImportLine, row: Row, used: set[int], create_items: bool) -> None:
        s = self.session
        pid = self._ref("product", ln.product_ref, ln.product_id)
        target = None
        if ln.id is not None:
            target = s.get(PurchaseLine, ln.id)
            if target is None or target.purchase_id != purchase.id:
                raise ApiError(404, "NOT_FOUND", f"购买记录 {purchase.id} 中没有明细 {ln.id}")
            row.match_reason = "id"
        else:
            sig = self._line_sig(pid, ln.item_code_raw, ln.color_code, ln.color_name, ln.size_label)
            for x in purchase.lines:
                if x.id not in used and self._line_sig(x.product_id, x.item_code_raw, x.color_code, x.color_name,
                                                       x.size_label) == sig:  # fmt: skip
                    target = x
                    row.match_reason = "line_signature"
                    break
        if target is None:
            s.refresh(purchase)
            data = ln.model_dump(exclude={"ref", "id", "product_ref"}, exclude_unset=True)
            data["product_id"] = pid
            before_ids = {x.id for x in purchase.lines}
            purchases_api.add_line(purchase.id, LineAdd(version=purchase.version, create_items=create_items, **data),
                                   s, self.actor)  # fmt: skip
            s.refresh(purchase)
            target = next(x for x in purchase.lines if x.id not in before_ids)
            row.action, row.target_id = "create", target.id
            used.add(target.id)
            return
        used.add(target.id)
        row.target_id = target.id
        self._basis(row, target)
        if self.options.on_existing == "skip":
            row.action = "skip"
            return
        version_before, start = target.version, len(s.info.get("proposals_created", []))
        desired = ln.model_dump(include=set(LINE_FIELDS), exclude_unset=True, mode="json")
        if ln.product_ref is not None:
            desired["product_id"] = pid
        fields = self._pick(target, desired)
        if fields:
            row.diff["fields"] = {k: [getattr(target, k), v] for k, v in fields.items()}
            purchases_api.patch_line(target.id, LinePatch(version=target.version, **fields), s, self.actor)
        created = []
        if create_items and target.product_id is not None:
            s.refresh(target)
            active = s.scalar(
                select(func.count())
                .select_from(WardrobeItem)
                .where(WardrobeItem.purchase_line_id == target.id, WardrobeItem.deleted_at.is_(None))
            )
            for _ in range(target.quantity - active):
                created.append(items_api.create_item_route(ItemCreate(purchase_line_id=target.id), s, self.actor)["id"])
        if created:
            row.diff["items_created"] = created
        self._settle(row, target, version_before, start, extra_changed=bool(created))

    # ───────────── 衣物 ─────────────

    def import_item(self, it: ImportItem) -> None:
        row = self._row("wardrobe_item", it.ref, it.model_dump(mode="json", exclude_unset=True))

        def run(row: Row) -> None:
            s = self.session
            product_id = self._ref("product", it.product_ref, it.product_id)
            line_id = self._ref("line", it.purchase_line_ref, it.purchase_line_id)
            obj = None
            if it.id is not None:
                obj = s.get(WardrobeItem, it.id)
                if obj is None or obj.deleted_at is not None:
                    raise ApiError(404, "NOT_FOUND", f"衣物 {it.id} 不存在")
                row.match_reason = "id"
            elif line_id is not None:
                # 同一购买明细下已有的衣物按顺序对应（重复导入不会超出数量）
                for cand in s.scalars(
                    select(WardrobeItem)
                    .where(WardrobeItem.purchase_line_id == line_id, WardrobeItem.deleted_at.is_(None))
                    .order_by(WardrobeItem.id)
                ):
                    if cand.id not in self.claimed_items:
                        obj = cand
                        row.match_reason = "purchase_line_slot"
                        break
            fields = it.model_dump(include=set(ITEM_FIELDS), exclude_unset=True, mode="json")
            if {"category", "category_id"} & it.model_fields_set:
                cat = resolve_category(s, it.category if it.category is not None else it.category_id)
                fields["category_id"] = cat.id if cat else None
            if obj is None:
                later = {k: fields.pop(k) for k in ITEM_AFTER_CREATE if k in fields}
                if later.get("status") == "owned":
                    later.pop("status")
                body = ItemCreate(product_id=product_id, purchase_line_id=line_id, tags=it.tags, **fields)
                out = items_api.create_item_route(body, s, self.actor)
                obj = s.get(WardrobeItem, out["id"])
                obj.import_job_id = s.info.get("import_job_id")
                if later:
                    items_api.patch_item(obj.id, ItemPatch(version=obj.version, **later), s, self.actor)
                row.action, row.target_id = "create", obj.id
                self.claimed_items.add(obj.id)
                self._link_item_images(obj, it)
                return
            self.claimed_items.add(obj.id)
            row.target_id = obj.id
            self._basis(row, obj)
            if product_id is not None and product_id != obj.product_id:
                fields["product_id"] = product_id
            if {"purchase_line_id", "purchase_line_ref"} & it.model_fields_set:
                # 显式给出（含 null 解除关联）才修改；走 PATCH 的统一关联校验与核实保护（BUG-014）
                fields["purchase_line_id"] = line_id
            if self.options.on_existing == "skip":
                row.action = "skip"
                return
            version_before, start = obj.version, len(s.info.get("proposals_created", []))
            picked = self._pick(obj, fields)
            if "favorite" in picked:
                picked["favorite"] = bool(picked["favorite"])
            if picked:
                row.diff["fields"] = {k: [getattr(obj, k), v] for k, v in picked.items()}
                items_api.patch_item(obj.id, ItemPatch(version=obj.version, **picked), s, self.actor)
                s.refresh(obj)
            current_tags = [t.name for t in obj.tags]
            new_tags = [t for t in it.tags if normalize_text(t) not in {normalize_text(x) for x in current_tags}]
            if new_tags:
                items_api.put_tags(obj.id, TagsPut(version=obj.version, tags=current_tags + new_tags), s, self.actor)
                row.diff["tags_added"] = new_tags
            self._link_item_images(obj, it)
            self._settle(row, obj, version_before, start)

        self._run(row, run)
        if it.ref:
            if row.action == "error":
                self.failed["item"].add(it.ref)
            else:
                self.refs["item"][it.ref] = row.target_id

    def _link_item_images(self, obj: WardrobeItem, it: ImportItem) -> None:
        for img in it.images:
            self.session.refresh(obj)
            if any(x.image_id == img.image_id for x in obj.images):
                continue
            body = ItemImageLink(version=obj.version, **img.model_dump())
            items_api.add_item_image(obj.id, body, self.session, self.actor)

    # ───────────── 穿搭 ─────────────

    def import_outfit(self, o: ImportOutfit) -> None:
        row = self._row("outfit", o.ref, o.model_dump(mode="json", exclude_unset=True))

        def run(row: Row) -> None:
            s = self.session
            items = None
            if o.items is not None:
                items = [
                    OutfitItemIn(item_id=self._ref("item", oi.item_ref, oi.item_id), slot=oi.slot,
                                 sort_order=oi.sort_order)
                    for oi in o.items
                ]  # fmt: skip
            obj = None
            if o.id is not None:
                obj = s.get(Outfit, o.id)
                if obj is None or obj.deleted_at is not None:
                    raise ApiError(404, "NOT_FOUND", f"穿搭 {o.id} 不存在")
                row.match_reason = "id"
            else:
                hits = [
                    x for x in s.scalars(select(Outfit).where(Outfit.deleted_at.is_(None)))
                    if normalize_text(x.name) == normalize_text(o.name)
                ]  # fmt: skip
                if len(hits) == 1:
                    obj = hits[0]
                    row.match_reason = "name"
            if obj is None:
                body = OutfitCreate(
                    **o.model_dump(include=set(OUTFIT_FIELDS), exclude_unset=True), items=items or [], tags=o.tags
                )
                row.action, row.target_id = "create", outfits_api.create_outfit(body, s, self.actor)["id"]
                return
            row.target_id = obj.id
            self._basis(row, obj)
            if self.options.on_existing == "skip":
                row.action = "skip"
                return
            version_before = obj.version
            fields = self._pick(obj, o.model_dump(include=set(OUTFIT_FIELDS), exclude_unset=True))
            if fields:
                row.diff["fields"] = {k: [getattr(obj, k), v] for k, v in fields.items()}
                outfits_api.patch_outfit(obj.id, OutfitPatch(version=obj.version, **fields), s, self.actor)
                s.refresh(obj)
            if items is not None and [(x.item_id, x.slot) for x in obj.items] != [(x.item_id, x.slot) for x in items]:
                outfits_api.put_outfit_items(obj.id, OutfitItemsPut(version=obj.version, items=items), s, self.actor)
                s.refresh(obj)
                row.diff["items_replaced"] = True
            current_tags = [t.name for t in obj.tags]
            new_tags = [t for t in o.tags if normalize_text(t) not in {normalize_text(x) for x in current_tags}]
            if new_tags:
                outfits_api.put_outfit_tags(obj.id, TagsPut(version=obj.version, tags=current_tags + new_tags), s,
                                            self.actor)  # fmt: skip
                row.diff["tags_added"] = new_tags
            s.refresh(obj)
            row.action = "update" if obj.version != version_before else "skip"

        self._run(row, run)
        if o.ref and row.action != "error":
            self.refs["outfit"][o.ref] = row.target_id

    # ───────────── 入口 ─────────────

    def run(self) -> list[Row]:
        for p in self.payload.products:
            self.import_product(p)
        for pur in self.payload.purchases:
            self.import_purchase(pur)
        for it in self.payload.items:
            self.import_item(it)
        for o in self.payload.outfits:
            self.import_outfit(o)
        # 不变量（BUG-011 复查）：会修改已有记录的行都必须带匹配时的版本，否则提交时无法发现预览后的修改。
        # 新增实体类型时若漏记，这里直接让整个请求失败（不写入任何数据），而不是静默放过。
        missing = [r.index for r in self.rows if r.action in ("update", "propose") and "basis_version" not in r.diff]
        if missing:
            raise ApiError(500, "INTERNAL_INVARIANT", f"导入行 {missing} 缺少预览版本依据（程序缺陷），未做任何修改")
        return self.rows


def summarize(rows: list[Row]) -> dict:
    counts = {a: 0 for a in ("create", "update", "propose", "link", "skip", "error")}
    for r in rows:
        counts[r.action] = counts.get(r.action, 0) + 1
    counts["proposals"] = sum(len(r.diff.get("proposals", [])) for r in rows)
    counts["warnings"] = sum(len(r.warnings) for r in rows)
    return counts


def pending_proposals_of(session: Session, job_id: int) -> list[ChangeProposal]:
    return list(session.scalars(select(ChangeProposal).where(ChangeProposal.import_job_id == job_id)))
