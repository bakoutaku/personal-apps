<script setup lang="ts">
import { t as translate } from "../i18n";
// 购买记录：新建（含多条明细，可同时生成衣物）与查看/编辑。退货在衣物上记录，购买记录本身保持原样。
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { onBeforeRouteLeave, useRouter } from "vue-router";
import { api } from "../api/client";
import type { MatchCandidate, Product, Purchase, PurchaseLine } from "../api/types";
import ProductPicker from "../components/ProductPicker.vue";
import PurchaseLineForm from "../components/PurchaseLineForm.vue";
import { errorMessage, fieldErrors, isConflict } from "../lib/errors";
import { CHANNEL_LABELS, SIZE_SYSTEM_LABELS, label, yen } from "../lib/labels";
import { type LineDraft, emptyLine, lineDraft, lineErrors, linePayload } from "../lib/purchaseLine";
import { notify } from "../lib/toast";

const props = defineProps<{ id?: number }>();
const router = useRouter();
const isNew = computed(() => props.id === undefined);

const purchase = ref<Purchase | null>(null);
const head = reactive({ purchased_on: today(), channel: "store", store_name: "", order_no: "", total_amount: "" as string | number, currency: "JPY", notes: "" });
const newLines = ref<LineDraft[]>([emptyLine()]);
const createItems = ref(true);
const editingHead = ref(false);
const editingLine = ref<number | null>(null);
const lineEdit = ref<LineDraft>(emptyLine());
const addingLine = ref(false);
const addLine = ref<LineDraft>(emptyLine());
const addCreateItems = ref(true);
const matching = ref<number | null>(null);
const candidates = ref<MatchCandidate[]>([]);

const loading = ref(false);
const busy = ref(false);
const error = ref<string | null>(null);
const errors = ref<Record<string, string>>({});
const conflict = ref(false);
let saved = false;

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function resetHead(p: Purchase) {
  Object.assign(head, {
    purchased_on: p.purchased_on, channel: p.channel, store_name: p.store_name ?? "", order_no: p.order_no ?? "",
    total_amount: p.total_amount ?? "", currency: p.currency, notes: p.notes ?? "",
  });
}

let requestId = 0;
onBeforeUnmount(() => { requestId++; });

/**
 * keepDrafts：明细操作后的后台刷新，保留购买头里尚未保存的编辑（明细草稿本来就存在独立的 ref 中）。
 * 只有打开页面或用户明确选择「重新载入」时才放弃草稿。
 */
async function load(keepDrafts = false) {
  const id = ++requestId;
  if (!keepDrafts) {
    error.value = null;
    conflict.value = false;
  }
  // 新建后路由复用同一个组件实例
  saved = false;
  if (isNew.value) return;
  loading.value = !purchase.value || purchase.value.id !== props.id;
  try {
    const p = await api.purchase(props.id!);
    if (id !== requestId) return; // 已切换到其他购买记录或离开页面
    const keepHead = keepDrafts && editingHead.value && Object.keys(headChanges.value).length > 0;
    purchase.value = p;
    if (!keepHead) resetHead(p);
    document.title = translate("购买 {0} · Wardrobe", p.purchased_on);
  } catch (e) {
    if (id === requestId) error.value = errorMessage(e);
  } finally {
    if (id === requestId) loading.value = false;
  }
}
watch(() => props.id, () => load(), { immediate: true });

function headPayload(): Record<string, unknown> {
  const t = (v: string) => (v.trim() === "" ? null : v.trim());
  return {
    purchased_on: head.purchased_on,
    channel: head.channel,
    store_name: t(head.store_name),
    order_no: t(head.order_no),
    total_amount: head.total_amount === "" ? null : Number(head.total_amount),
    currency: head.currency.trim().toUpperCase() || "JPY",
    notes: t(head.notes),
  };
}

const headChanges = computed(() => {
  const p = purchase.value;
  if (!p) return {};
  const next = headPayload();
  const prev: Record<string, unknown> = { purchased_on: p.purchased_on, channel: p.channel, store_name: p.store_name, order_no: p.order_no, total_amount: p.total_amount, currency: p.currency, notes: p.notes };
  return Object.fromEntries(Object.entries(next).filter(([k, v]) => v !== prev[k]));
});

const dirty = computed(() => {
  if (isNew.value) return Boolean(head.store_name || head.order_no || newLines.value.some((l) => l.product_id || l.name_raw || l.item_code_raw));
  return (editingHead.value && Object.keys(headChanges.value).length > 0) || editingLine.value !== null || addingLine.value;
});
onBeforeRouteLeave(() => {
  if (dirty.value && !saved && !window.confirm(translate("有尚未保存的修改，确定离开吗？"))) return false;
});

async function run(fn: () => Promise<unknown>, done: string, after?: () => void) {
  busy.value = true;
  error.value = null;
  errors.value = {};
  conflict.value = false;
  try {
    await fn();
    notify(done);
    after?.();
    await load(true);
  } catch (e) {
    error.value = errorMessage(e);
    errors.value = fieldErrors(e);
    conflict.value = isConflict(e);
  } finally {
    busy.value = false;
  }
}

async function createPurchase() {
  error.value = null;
  errors.value = Object.assign({}, ...newLines.value.map((l, i) => lineErrors(l, `lines.${i}.`)));
  if (Object.keys(errors.value).length) {
    error.value = translate("请修正标出的字段");
    return;
  }
  busy.value = true;
  try {
    const lines = newLines.value.map(linePayload);
    const created = await api.createPurchase({ ...headPayload(), lines, create_items: createItems.value && lines.length > 0 });
    saved = true;
    notify(createItems.value ? translate("已记录购买，并生成了对应的衣物") : translate("已记录购买"));
    await router.push({ name: "purchase", params: { id: created.id } });
  } catch (e) {
    error.value = errorMessage(e);
    errors.value = fieldErrors(e);
  } finally {
    busy.value = false;
  }
}

const saveHead = () =>
  run(() => api.updatePurchase(purchase.value!.id, { version: purchase.value!.version, ...headChanges.value }), translate("已保存"), () => (editingHead.value = false));

function startEditLine(l: PurchaseLine) {
  editingLine.value = l.id;
  lineEdit.value = lineDraft(l);
}

function lineChanges(l: PurchaseLine): Record<string, unknown> {
  const before = linePayload(lineDraft(l));
  const after = linePayload(lineEdit.value);
  const out = Object.fromEntries(Object.entries(after).filter(([k, v]) => v !== before[k]));
  // 更换商品走「匹配」接口，这里只在用户明确改了商品时提交
  return out;
}

function invalid(d: LineDraft): boolean {
  errors.value = lineErrors(d);
  if (Object.keys(errors.value).length) error.value = translate("请修正标出的字段");
  return Object.keys(errors.value).length > 0;
}

const saveLine = (l: PurchaseLine) =>
  invalid(lineEdit.value) ||
  run(() => api.updateLine(l.id, { version: l.version, ...lineChanges(l) }), translate("已保存明细"), () => (editingLine.value = null));
const toggleLineVerify = (l: PurchaseLine) =>
  run(() => api.verifyLine(l.id, l.version!, l.verification !== "verified"), l.verification === "verified" ? translate("已取消核实") : translate("已核实明细"));
const deleteLine = (l: PurchaseLine) => {
  if (!window.confirm(translate("删除这条明细？仍有衣物关联时不能删除。"))) return;
  return run(() => api.deleteLine(l.id, purchase.value!.version), translate("已删除明细"));
};
const createLineItem = (l: PurchaseLine) => run(() => api.createItem({ purchase_line_id: l.id }), translate("已为这条明细添加一件衣物"));
const submitAddLine = () =>
  invalid(addLine.value) ||
  run(
    () => api.addLine(purchase.value!.id, { version: purchase.value!.version, ...linePayload(addLine.value), create_items: addCreateItems.value && !!addLine.value.product_id }),
    translate("已追加明细"),
    () => {
      addingLine.value = false;
      addLine.value = emptyLine();
    },
  );

async function openMatch(l: PurchaseLine) {
  matching.value = matching.value === l.id ? null : l.id;
  candidates.value = [];
  if (matching.value === null) return;
  try {
    candidates.value = (await api.matchCandidates(l.id)).candidates;
  } catch {
    candidates.value = [];
  }
}
const confirmMatch = (l: PurchaseLine, product: { id: number }) =>
  run(() => api.matchLine(l.id, { version: l.version, product_id: product.id, product_match: "confirmed" }), translate("已确认商品"), () => (matching.value = null));

async function removePurchase() {
  const p = purchase.value;
  if (!p || !window.confirm(translate("删除这笔购买记录？仍有衣物关联时不能删除。"))) return;
  busy.value = true;
  try {
    await api.deletePurchase(p.id, p.version);
    const deletedVersion = p.version + 1;
    notify(translate("已删除购买记录"), {
      action: {
        label: translate("撤销"),
        run: async () => {
          try {
            await api.restorePurchase(p.id, deletedVersion);
            notify(translate("已恢复购买记录"));
            await router.push({ name: "purchase", params: { id: p.id } });
          } catch (e) {
            notify(errorMessage(e), { kind: "error" });
          }
        },
      },
    });
    saved = true;
    await router.push({ name: "purchases" });
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}

function reasonText(r: string): string {
  const [kind, value] = r.split(":");
  if (kind === "name_similarity") return translate("名称相似 {0}%", Math.round(Number(value) * 100));
  if (kind === "identifier") return translate("小票编号与商品番号相同");
  return r;
}
const productName = (l: PurchaseLine) => l.product?.name_ja || l.product?.name_zh || l.product?.name_en || null;
const MATCH_LABELS: Record<string, string> = { confirmed: translate("已确认"), suggested: translate("待确认"), unmatched: translate("未匹配") };
const total = computed(() => {
  const p = purchase.value;
  if (!p) return null;
  return p.total_amount ?? (p.lines.some((l) => l.unit_price !== null) ? p.lines.reduce((s, l) => s + (l.unit_price ?? 0) * l.quantity - (l.discount_amount ?? 0), 0) : null);
});
</script>

<template>
  <div class="page">
    <RouterLink :to="{ name: 'purchases' }" class="link-btn">{{ translate("← 全部购买记录") }}</RouterLink>
    <p v-if="loading" class="muted">{{ translate("加载中…") }}</p>

    <!-- 新建 -->
    <form v-else-if="isNew" novalidate @submit.prevent="createPurchase">
      <div class="page-head"><h1>{{ translate("记录一笔购买") }}</h1></div>
      <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
      <section class="panel">
        <h2>{{ translate("购买信息") }}</h2>
        <div class="form-grid">
          <label class="field"><span>{{ translate("日期（必填）") }}</span><input v-model="head.purchased_on" type="date" required :aria-invalid="!!errors.purchased_on" /></label>
          <label class="field">
            <span>{{ translate("渠道") }}</span>
            <select v-model="head.channel"><option v-for="(t, k) in CHANNEL_LABELS" :key="k" :value="k">{{ t }}</option></select>
          </label>
          <label class="field"><span>{{ translate("店铺") }}</span><input v-model="head.store_name" :placeholder='translate("例如 UNIQLO 银座店")' /></label>
          <label class="field"><span>{{ translate("订单号 / 小票号") }}</span><input v-model="head.order_no" /></label>
          <label class="field"><span>{{ translate("实付总额") }}</span><input v-model="head.total_amount" type="number" min="0" inputmode="numeric" /></label>
          <label class="field"><span>{{ translate("币种") }}</span><input v-model="head.currency" maxlength="3" :aria-invalid="!!errors.currency" /></label>
          <label class="field wide"><span>{{ translate("备注") }}</span><input v-model="head.notes" /></label>
        </div>
      </section>
      <section v-for="(_line, i) in newLines" :key="i" class="panel">
        <div class="panel-head">
          <h2>{{ translate("明细") }} {{ i + 1 }}</h2>
          <button v-if="newLines.length > 1" type="button" class="link-btn" @click="newLines.splice(i, 1)">{{ translate("删除这条") }}</button>
        </div>
        <PurchaseLineForm v-model="newLines[i]!" :errors="errors" :prefix="`lines.${i}.`" />
      </section>
      <div class="actions add-row">
        <button type="button" class="btn ghost small" @click="newLines.push(emptyLine())">{{ translate("再加一条明细") }}</button>
        <label class="field check"><input v-model="createItems" type="checkbox" /><span>{{ translate("按数量自动生成衣物（需要每条明细都选择了商品）") }}</span></label>
      </div>
      <div class="form-actions">
        <button type="submit" class="btn" :disabled="busy || !head.purchased_on">{{ busy ? translate("保存中…") : translate("保存购买记录") }}</button>
        <RouterLink :to="{ name: 'purchases' }" class="btn ghost">{{ translate("取消") }}</RouterLink>
      </div>
    </form>

    <p v-else-if="error && !purchase" class="error-banner" role="alert">{{ error }}</p>

    <!-- 查看 / 编辑 -->
    <template v-else-if="purchase">
      <div class="page-head">
        <div>
          <div class="muted">{{ translate("购买 #") }}{{ purchase.id }} · {{ label(CHANNEL_LABELS, purchase.channel) }}</div>
          <h1>{{ purchase.purchased_on }} {{ purchase.store_name ?? "" }}</h1>
        </div>
        <div class="actions">
          <button type="button" class="btn ghost small" :disabled="busy" @click="editingHead = !editingHead">{{ editingHead ? translate("取消编辑") : translate("编辑购买信息") }}</button>
          <button type="button" class="btn danger small" :disabled="busy" @click="removePurchase">{{ translate("删除") }}</button>
        </div>
      </div>
      <p v-if="error" class="error-banner" role="alert">
        {{ error }}
        <button v-if="conflict" type="button" class="link-btn" @click="load()">{{ translate("重新载入（放弃未保存修改）") }}</button>
      </p>

      <form v-if="editingHead" class="panel" novalidate @submit.prevent="saveHead">
        <div class="form-grid">
          <label class="field"><span>{{ translate("日期") }}</span><input v-model="head.purchased_on" type="date" required /></label>
          <label class="field">
            <span>{{ translate("渠道") }}</span>
            <select v-model="head.channel"><option v-for="(t, k) in CHANNEL_LABELS" :key="k" :value="k">{{ t }}</option></select>
          </label>
          <label class="field"><span>{{ translate("店铺") }}</span><input v-model="head.store_name" /></label>
          <label class="field"><span>{{ translate("订单号 / 小票号") }}</span><input v-model="head.order_no" /></label>
          <label class="field"><span>{{ translate("实付总额") }}</span><input v-model="head.total_amount" type="number" min="0" /></label>
          <label class="field"><span>{{ translate("币种") }}</span><input v-model="head.currency" maxlength="3" /></label>
          <label class="field wide"><span>{{ translate("备注") }}</span><input v-model="head.notes" /></label>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn" :disabled="busy || !Object.keys(headChanges).length">{{ translate("保存") }}</button>
          <button type="button" class="btn ghost" @click="resetHead(purchase); editingHead = false">{{ translate("取消") }}</button>
        </div>
      </form>
      <dl v-else class="facts panel">
        <div v-if="purchase.order_no"><dt>{{ translate("订单号") }}</dt><dd class="mono">{{ purchase.order_no }}</dd></div>
        <div><dt>{{ translate("金额") }}</dt><dd>{{ total === null ? translate("未记录") : yen(total, purchase.currency) }}<span v-if="purchase.total_amount === null && total !== null" class="muted">{{ translate("（按明细计算）") }}</span></dd></div>
        <div v-if="purchase.notes"><dt>{{ translate("备注") }}</dt><dd>{{ purchase.notes }}</dd></div>
      </dl>

      <section class="panel">
        <div class="panel-head">
          <h2>{{ translate("明细（") }}{{ purchase.lines.length }}）</h2>
          <button type="button" class="btn ghost small" :aria-expanded="addingLine" @click="addingLine = !addingLine">{{ addingLine ? translate("取消追加") : translate("追加明细") }}</button>
        </div>
        <form v-if="addingLine" class="sub-form" novalidate @submit.prevent="submitAddLine">
          <PurchaseLineForm v-model="addLine" :errors="errors" />
          <label class="field check"><input v-model="addCreateItems" type="checkbox" :disabled="!addLine.product_id" /><span>{{ translate("按数量生成衣物") }}</span></label>
          <div class="form-actions"><button type="submit" class="btn small" :disabled="busy">{{ translate("追加") }}</button></div>
        </form>

        <ul class="lines">
          <li v-for="l in purchase.lines" :key="l.id" class="line" :data-testid="`line-${l.id}`">
            <div class="line-head">
              <div class="title">
                <RouterLink v-if="l.product_id" :to="{ name: 'product', params: { id: l.product_id } }"><strong>{{ productName(l) }}</strong></RouterLink>
                <strong v-else>{{ l.name_raw ?? translate("（未命名明细）") }}</strong>
                <span class="badge" :class="{ warn: l.product_match !== 'confirmed' }">{{ translate("商品") }}{{ MATCH_LABELS[l.product_match] ?? l.product_match }}</span>
                <span v-if="l.verification === 'verified'" class="badge dark">{{ translate("已核实") }}</span>
              </div>
              <div class="price">
                {{ l.unit_price !== null ? yen(l.unit_price, purchase.currency) : "" }} × {{ l.quantity }}
                <span v-if="l.discount_amount" class="muted">{{ translate("（折扣") }} {{ yen(l.discount_amount, purchase.currency) }}）</span>
              </div>
            </div>
            <p class="muted detail">
              <template v-if="l.item_code_raw">{{ translate("编号") }} <span class="mono">{{ l.item_code_raw }}</span> · </template>
              <template v-if="l.name_raw && l.product_id">{{ translate("小票名") }} {{ l.name_raw }} · </template>
              {{ translate("颜色") }} {{ l.color_name ?? l.color_code ?? "—" }} {{ translate("· 尺码") }} {{ l.size_label ?? "—" }}<template v-if="l.size_system">（{{ label(SIZE_SYSTEM_LABELS, l.size_system) }}）</template>
              <template v-if="l.returned_quantity"> {{ translate("· 已退") }} {{ l.returned_quantity }} {{ translate("件") }}</template>
            </p>
            <p class="items">
              {{ translate("衣物：") }}
              <template v-if="l.item_ids?.length">
                <RouterLink v-for="(iid, n) in l.item_ids" :key="iid" :to="{ name: 'item', params: { id: iid } }">{{ n ? "、" : "" }}#{{ iid }}</RouterLink>
              </template>
              <span v-else class="muted">{{ translate("尚无") }}</span>
              <span v-if="(l.item_ids?.length ?? 0) < l.quantity" class="muted">（{{ l.quantity - (l.item_ids?.length ?? 0) }} {{ translate("件未建衣物）") }}</span>
            </p>
            <div class="actions">
              <button type="button" class="btn ghost small" :disabled="busy" @click="editingLine === l.id ? (editingLine = null) : startEditLine(l)">{{ editingLine === l.id ? translate("取消编辑") : translate("编辑") }}</button>
              <button type="button" class="btn ghost small" :disabled="busy" :aria-expanded="matching === l.id" @click="openMatch(l)">{{ l.product_match === "confirmed" ? translate("更换商品") : translate("匹配商品") }}</button>
              <button v-if="l.product_id && (l.item_ids?.length ?? 0) < l.quantity" type="button" class="btn ghost small" :disabled="busy" @click="createLineItem(l)">{{ translate("添加一件衣物") }}</button>
              <button type="button" class="btn ghost small" :disabled="busy" @click="toggleLineVerify(l)">{{ l.verification === "verified" ? translate("取消核实") : translate("核实") }}</button>
              <button type="button" class="btn danger small" :disabled="busy" @click="deleteLine(l)">{{ translate("删除") }}</button>
            </div>
            <form v-if="editingLine === l.id" class="sub-form" novalidate @submit.prevent="saveLine(l)">
              <PurchaseLineForm v-model="lineEdit" :errors="errors" :allow-product="false" />
              <div class="form-actions"><button type="submit" class="btn small" :disabled="busy">{{ translate("保存明细") }}</button></div>
            </form>
            <div v-if="matching === l.id" class="sub-form">
              <p v-if="candidates.length" class="muted">{{ translate("推荐（按编号与名称相似度）：") }}</p>
              <ul v-if="candidates.length" class="candidates">
                <li v-for="c in candidates" :key="c.product.id">
                  <span>{{ c.product.name_ja || c.product.name_zh || c.product.name_en }} <span class="muted">· {{ c.product.brand ?? translate("无品牌") }} · {{ (c.reasons ?? []).map(reasonText).join("、") }}</span></span>
                  <button type="button" class="btn small" :disabled="busy" @click="confirmMatch(l, c.product)">{{ translate("选这个") }}</button>
                </li>
              </ul>
              <p class="muted">{{ translate("或搜索其他商品：") }}</p>
              <ProductPicker :selected-id="l.product_id" @select="(p: Product) => confirmMatch(l, p)" />
            </div>
          </li>
        </ul>
        <p v-if="!purchase.lines.length" class="muted">{{ translate("没有明细。") }}</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.add-row {
  justify-content: space-between;
  margin-bottom: 8px;
}
.facts {
  display: grid;
  gap: 6px;
  margin-top: 0;
}
.facts div {
  display: grid;
  grid-template-columns: 6em minmax(0, 1fr);
  gap: 12px;
}
.facts dt {
  color: var(--ink-3);
  font-size: 13px;
}
.facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.mono {
  font-family: ui-monospace, Menlo, monospace;
}
.lines {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 14px;
}
.line {
  border-top: 1px solid var(--line);
  padding-top: 14px;
  display: grid;
  gap: 8px;
  min-width: 0;
}
.line-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 6px 16px;
}
.title {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  align-items: center;
  overflow-wrap: anywhere;
  min-width: 0;
}
.price {
  white-space: nowrap;
}
.detail,
.items {
  margin: 0;
  font-size: 13px;
  overflow-wrap: anywhere;
}
.sub-form {
  border: 1px dashed var(--line-strong);
  padding: 14px;
  display: grid;
  gap: 10px;
}
.candidates {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.candidates li {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  font-size: 14px;
  overflow-wrap: anywhere;
}
</style>
