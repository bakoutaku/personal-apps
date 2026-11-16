<script setup lang="ts">
// 商品资料：基本字段、编号、颜色、尺码、材质、图片分区保存。每次保存都用上一次响应里的最新 version。
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRouter } from "vue-router";
import { api } from "../api/client";
import type { ImageInfo, Product, Proposal } from "../api/types";
import ColorDot from "../components/ColorDot.vue";
import ImageUploader from "../components/ImageUploader.vue";
import ProposalList from "../components/ProposalList.vue";
import { categoryOptions, dict, loadDictionaries } from "../lib/dictionaries";
import { errorMessage, fieldErrors, isConflict } from "../lib/errors";
import { FIBER_LABELS, GENDER_LABELS, IMAGE_ROLE_LABELS, PART_LABELS, SCHEME_LABELS, SIZE_SYSTEM_LABELS, label } from "../lib/labels";
import { notify } from "../lib/toast";

const props = defineProps<{ id: number }>();
const router = useRouter();
const product = ref<Product | null>(null);
const proposals = ref<Proposal[]>([]);
const loading = ref(true);
const loadError = ref<string | null>(null);
// 每个分区单独显示自己的错误
const sectionError = reactive<Record<string, string | null>>({});
const fieldErrs = ref<Record<string, string>>({});
const conflict = ref(false);
const busy = ref<string | null>(null);
// 已上传但尚未关联的图片：关联失败时保留，可直接重试，不需要重新选择文件
const pendingImages = ref<ImageInfo[]>([]);

// 页面代次：切换到另一个商品（同一组件实例）或离开页面时加一。写请求（保存、关联图片、删除…）的响应
// 只有在发起时的代次仍是当前代次时才更新表单、标题、错误、busy 和提议。
// 注意：本地不再等待并不等于撤销写入，后端事务照常完成。
const pageGen = ref(0);
const isCurrent = (g: number) => g === pageGen.value;

const BASIC = [
  "name_ja", "name_zh", "name_en", "gender", "detail_url", "season_label", "list_price", "currency",
  "material_text", "care_text", "description", "notes",
] as const;
type BasicForm = Record<(typeof BASIC)[number] | "brand_id" | "category_id", string | number | null>;
const basic = reactive<BasicForm>({} as BasicForm);
const basicOriginal = ref<BasicForm>({} as BasicForm);

interface ColorRow { color_code: string; name_ja: string; name_zh: string; hex: string; is_default: boolean }
// size_detail 目前没有编辑控件，但整体替换（PUT）时必须原样带回，否则会被清空
interface SizeRow { size_label: string; size_system: string; size_detail: Record<string, unknown> | null }
interface MaterialRow { part: string; part_raw: string; fiber: string; fiber_raw: string; percent: string | number }
const colors = ref<ColorRow[]>([]);
const sizes = ref<SizeRow[]>([]);
const materials = ref<MaterialRow[]>([]);
const newIdent = reactive({ scheme: "item_no", value: "" });

function toBasic(p: Product): BasicForm {
  const f = { brand_id: p.brand?.id ?? null, category_id: p.category?.id ?? null } as BasicForm;
  for (const k of BASIC) f[k] = ((p as unknown as Record<string, unknown>)[k] ?? "") as string | number;
  return f;
}

const s = (v: string | null | undefined) => v ?? "";

function adopt(p: Product) {
  product.value = p;
  basicOriginal.value = toBasic(p);
  Object.assign(basic, toBasic(p));
  colors.value = p.colors.map((c) => ({ color_code: s(c.color_code), name_ja: s(c.name_ja), name_zh: s(c.name_zh), hex: s(c.hex), is_default: c.is_default }));
  sizes.value = p.sizes.map((x) => ({ size_label: x.size_label, size_system: x.size_system, size_detail: x.size_detail ?? null }));
  materials.value = p.materials.map((m) => ({ part: m.part, part_raw: s(m.part_raw), fiber: m.fiber, fiber_raw: s(m.fiber_raw), percent: m.percent === null ? "" : String(m.percent) }));
  document.title = `${p.name_ja || p.name_zh || p.name_en || "商品"} · Wardrobe`;
}

/** 切换到另一个商品时清空本页的操作状态，旧请求的结果不会再写进来。 */
function resetPage() {
  product.value = null;
  proposals.value = [];
  busy.value = null;
  for (const k of Object.keys(sectionError)) sectionError[k] = null;
  fieldErrs.value = {};
  conflict.value = false;
  pendingImages.value = [];
  newIdent.value = "";
}

async function loadProposals() {
  const g = pageGen.value;
  const id = props.id;
  try {
    const items = (await api.proposals({ entity: "product", entity_id: id })).items;
    if (isCurrent(g)) proposals.value = items;
  } catch {
    if (isCurrent(g)) proposals.value = [];
  }
}

let requestId = 0;
onBeforeUnmount(() => {
  requestId++;
  pageGen.value++;
});

async function load() {
  const id = ++requestId;
  void loadDictionaries();
  loading.value = true;
  loadError.value = null;
  conflict.value = false;
  try {
    const p = await api.product(props.id);
    if (id !== requestId) return; // 只采用最新一次请求（切换到其他商品或已离开）
    adopt(p);
    void loadProposals();
  } catch (e) {
    if (id === requestId) loadError.value = errorMessage(e);
  } finally {
    if (id === requestId) loading.value = false;
  }
}
watch(
  () => props.id,
  () => {
    pageGen.value++;
    resetPage();
    void load();
  },
  { immediate: true },
);

const norm = (v: unknown) => (v === "" || v === undefined ? null : v);
const basicChanges = computed(() => {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(basic)) {
    let value = norm(v);
    if (k === "list_price" && value !== null) value = Number(value);
    if (value !== norm(basicOriginal.value[k as keyof BasicForm])) out[k] = value;
  }
  return out;
});

const snapshot = computed(() => (product.value ? JSON.stringify([
  product.value.colors.map((c) => [s(c.color_code), s(c.name_ja), s(c.name_zh), s(c.hex), c.is_default]),
  product.value.sizes.map((x) => [x.size_label, x.size_system]),
  product.value.materials.map((m) => [m.part, s(m.part_raw), m.fiber, s(m.fiber_raw), m.percent === null ? "" : String(m.percent)]),
]) : ""));
const editsSnapshot = computed(() => JSON.stringify([
  colors.value.map((c) => [c.color_code, c.name_ja, c.name_zh, c.hex, c.is_default]),
  sizes.value.map((x) => [x.size_label, x.size_system]),
  materials.value.map((m) => [m.part, m.part_raw, m.fiber, m.fiber_raw, m.percent]),
]));
const dirty = computed(() => Boolean(product.value) && (Object.keys(basicChanges.value).length > 0 || snapshot.value !== editsSnapshot.value));
onBeforeRouteLeave(() => {
  if (dirty.value && !window.confirm("有尚未保存的修改，确定离开吗？")) return false;
});
// 在商品页之间切换会复用同一组件实例，同样提醒未保存的修改
onBeforeRouteUpdate((to, from) => {
  if (to.params.id !== from.params.id && dirty.value && !window.confirm("有尚未保存的修改，确定离开吗？")) return false;
});

async function run(section: string, call: (p: Product) => Promise<Product | null>, done: string): Promise<boolean> {
  const current = product.value;
  if (!current) return false;
  const g = pageGen.value;
  busy.value = section;
  sectionError[section] = null;
  fieldErrs.value = {};
  conflict.value = false;
  try {
    const updated = await call(current);
    // 已切换到其他商品或离开页面：不改动当前页面（包括标题、提示和提议）
    if (!isCurrent(g)) return false;
    if (updated) {
      // 只采用服务器结果中本分区以外未改动的部分：其他分区里尚未保存的编辑保留
      const keep = { basic: { ...basic }, colors: colors.value, sizes: sizes.value, materials: materials.value };
      const keepDirtyBasic = section !== "basic" ? basicChanges.value : {};
      adopt(updated);
      if (section !== "basic") Object.assign(basic, Object.fromEntries(Object.keys(keepDirtyBasic).map((k) => [k, keep.basic[k as keyof BasicForm]])));
      if (section !== "colors") colors.value = keep.colors;
      if (section !== "sizes") sizes.value = keep.sizes;
      if (section !== "materials") materials.value = keep.materials;
    }
    notify(done);
    void loadProposals();
    return true;
  } catch (e) {
    if (!isCurrent(g)) return false;
    sectionError[section] = errorMessage(e);
    fieldErrs.value = fieldErrors(e);
    conflict.value = isConflict(e);
    return false;
  } finally {
    // 旧操作结束时不能清除新页面上正在进行的操作状态
    if (isCurrent(g)) busy.value = null;
  }
}

const saveBasic = () => run("basic", (p) => api.updateProduct(p.id, { version: p.version, ...basicChanges.value }), "已保存基本资料");

function colorPayload() {
  return colors.value.map((c, i) => {
    const out: Record<string, unknown> = { is_default: c.is_default, sort_order: i };
    for (const k of ["color_code", "name_ja", "name_zh", "hex"] as const) if (c[k].trim()) out[k] = c[k].trim();
    return out;
  });
}
const saveColors = () => run("colors", (p) => api.putProductColors(p.id, p.version, colorPayload()), "已保存颜色");
const saveSizes = () =>
  run(
    "sizes",
    (p) =>
      api.putProductSizes(p.id, p.version, sizes.value.map((x, i) => ({
        size_label: x.size_label.trim(),
        size_system: x.size_system,
        ...(x.size_detail ? { size_detail: x.size_detail } : {}),
        sort_order: i,
      }))),
    "已保存尺码",
  );
const saveMaterials = () =>
  run(
    "materials",
    (p) =>
      api.putProductMaterials(p.id, p.version, materials.value.map((m) => {
        const out: Record<string, unknown> = { part: m.part.trim() || "body", fiber: m.fiber.trim() };
        if (m.part_raw.trim()) out.part_raw = m.part_raw.trim();
        if (m.fiber_raw.trim()) out.fiber_raw = m.fiber_raw.trim();
        if (String(m.percent ?? "").trim()) out.percent = Number(m.percent);
        return out;
      })),
    "已保存材质",
  );
const reparseMaterials = () => run("materials", (p) => api.putProductMaterials(p.id, p.version, null), "已按材质原文重新解析");

function setDefault(i: number) {
  colors.value.forEach((c, j) => (c.is_default = i === j));
}

async function addIdentifier() {
  const value = newIdent.value.trim();
  const ok = await run("identifiers", (p) => api.addIdentifier(p.id, { version: p.version, scheme: newIdent.scheme, value }), "已添加编号");
  // 只有仍在本页且成功时才清空输入，不影响切换后另一个商品的输入
  if (ok) newIdent.value = "";
}
const removeIdentifier = (iid: number) => run("identifiers", (p) => api.removeIdentifier(p.id, iid, p.version), "已删除编号");

async function addImage(img: ImageInfo, g = pageGen.value): Promise<boolean> {
  // 上传开始后切换了商品：图片不能关联到新显示的商品上
  if (!isCurrent(g)) return false;
  if (!pendingImages.value.some((x) => x.id === img.id)) pendingImages.value.push(img);
  // ImageUploader 会等待本函数完成再关联下一张，因此每次都使用上一次返回的 version
  const ok = await run(
    "images",
    (p) => (p.images.some((x) => x.id === img.id) ? Promise.resolve(p) : api.addProductImage(p.id, { version: p.version, image_id: img.id, role: p.images.length ? "gallery" : "main" })),
    "已添加图片",
  );
  if (ok) pendingImages.value = pendingImages.value.filter((x) => x.id !== img.id);
  return ok;
}
// 回调在渲染时绑定当时的代次；上传组件被卸载后仍会调用它最后收到的回调，因此不能在调用时才读取代次
const uploadHandler = computed(() => {
  const g = pageGen.value;
  return (img: ImageInfo) => addImage(img, g);
});

async function retryImages() {
  for (const img of [...pendingImages.value]) if (!(await addImage(img))) break;
}
const removeImage = (img: ImageInfo) => run("images", (p) => api.removeProductImage(p.id, img.id, p.version), "已移除图片");
const toggleVerify = () =>
  run("verify", (p) => api.verifyProduct(p.id, p.version, p.verification !== "verified"), product.value?.verification === "verified" ? "已取消核实" : "已标记为核实");

async function remove() {
  const p = product.value;
  if (!p || !window.confirm("删除这个商品？只有没有衣物引用时才能删除。")) return;
  const g = pageGen.value;
  busy.value = "delete";
  sectionError.delete = null;
  try {
    await api.deleteProduct(p.id, p.version);
    const deletedVersion = p.version + 1;
    // 删除已经发生：即使已离开本页也要告诉用户，并保留撤销入口
    notify("已删除商品", {
      action: {
        label: "撤销",
        run: async () => {
          try {
            await api.restoreProduct(p.id, deletedVersion);
            notify("已恢复商品");
            await router.push({ name: "product", params: { id: p.id } });
          } catch (e) {
            notify(errorMessage(e), { kind: "error" });
          }
        },
      },
    });
    if (isCurrent(g)) await router.push("/");
  } catch (e) {
    if (isCurrent(g)) sectionError.delete = errorMessage(e);
  } finally {
    if (isCurrent(g)) busy.value = null;
  }
}

const title = computed(() => (product.value ? product.value.name_ja || product.value.name_zh || product.value.name_en : ""));
const fe = (k: string) => fieldErrs.value[k];
</script>

<template>
  <div class="page">
    <button type="button" class="link-btn" @click="router.back()">← 返回</button>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="loadError" class="error-banner" role="alert">{{ loadError }}</p>
    <template v-else-if="product">
      <div class="page-head">
        <div>
          <div class="muted">{{ product.brand?.name ?? "无品牌" }} · 商品 #{{ product.id }} · 版本 {{ product.version }}</div>
          <h1>{{ title }}</h1>
        </div>
        <div class="actions">
          <span v-if="product.verification === 'verified'" class="badge dark">已核实</span>
          <span v-if="product.origin === 'manual'" class="badge">自建商品</span>
          <button type="button" class="btn ghost small" :disabled="!!busy" @click="toggleVerify">{{ product.verification === "verified" ? "取消核实" : "标记为已核实" }}</button>
          <button type="button" class="btn danger small" :disabled="!!busy" @click="remove">删除商品</button>
        </div>
      </div>
      <p v-if="sectionError.verify || sectionError.delete" class="error-banner" role="alert">{{ sectionError.verify || sectionError.delete }}</p>
      <p v-if="conflict" class="error-banner" role="alert">
        商品已在别处被修改。
        <button type="button" class="link-btn" @click="load">载入最新版本（放弃未保存修改）</button>
      </p>
      <p class="muted">有 {{ product.item_count ?? 0 }} 件衣物使用这个商品。已核实的商品只能由你在这里修改；AI 和导入的改动会成为下方的待确认提议。</p>

      <ProposalList v-if="proposals.length" class="panel" :proposals="proposals" title="待确认的修改提议" @changed="load" />

      <form class="panel" novalidate @submit.prevent="saveBasic">
        <h2>基本资料</h2>
        <div class="form-grid">
          <label class="field">
            <span>品牌</span>
            <select v-model="basic.brand_id">
              <option :value="null">无品牌</option>
              <option v-for="b in dict.brands" :key="b.id" :value="b.id">{{ b.name }}</option>
            </select>
          </label>
          <label class="field">
            <span>分类</span>
            <select v-model="basic.category_id">
              <option :value="null">未分类</option>
              <option v-for="c in categoryOptions()" :key="c.id" :value="c.id">{{ c.label }}</option>
            </select>
          </label>
          <label class="field"><span>日文名</span><input v-model="basic.name_ja" :aria-invalid="!!fe('name_ja')" /></label>
          <label class="field"><span>中文名</span><input v-model="basic.name_zh" /></label>
          <label class="field"><span>英文名</span><input v-model="basic.name_en" /></label>
          <label class="field">
            <span>男女款</span>
            <select v-model="basic.gender">
              <option value="">未记录</option>
              <option v-for="(t, k) in GENDER_LABELS" :key="k" :value="k">{{ t }}</option>
            </select>
          </label>
          <label class="field"><span>季节标注</span><input v-model="basic.season_label" placeholder="例如 2025FW" /></label>
          <label class="field"><span>标价</span><input v-model="basic.list_price" type="number" min="0" inputmode="numeric" :aria-invalid="!!fe('list_price')" /></label>
          <label class="field"><span>币种</span><input v-model="basic.currency" maxlength="3" placeholder="JPY" :aria-invalid="!!fe('currency')" /><span v-if="fe('currency')" class="field-error">{{ fe("currency") }}</span></label>
          <label class="field wide"><span>详情页链接</span><input v-model="basic.detail_url" type="url" /></label>
          <label class="field wide"><span>材质原文</span><textarea v-model="basic.material_text" placeholder="表地:ナイロン100%／裏地:…" /></label>
          <label class="field wide"><span>保养说明</span><textarea v-model="basic.care_text" /></label>
          <label class="field wide"><span>商品说明</span><textarea v-model="basic.description" /></label>
          <label class="field wide"><span>备注</span><textarea v-model="basic.notes" /></label>
        </div>
        <p v-if="sectionError.basic" class="error-banner" role="alert">{{ sectionError.basic }}</p>
        <div class="form-actions">
          <button type="submit" class="btn" :disabled="!!busy || !Object.keys(basicChanges).length">保存基本资料</button>
        </div>
      </form>

      <section class="panel">
        <h2>编号</h2>
        <p class="muted small">不同体系的编号（详情页编号、商品番号、JAN…）分开保存，不会自动视为同一个。</p>
        <ul v-if="product.identifiers.length" class="idents">
          <li v-for="i in product.identifiers" :key="i.id">
            <span class="muted">{{ label(SCHEME_LABELS, i.scheme) }}</span>
            <code>{{ i.value }}</code>
            <button type="button" class="link-btn" :disabled="!!busy" @click="removeIdentifier(i.id)">删除</button>
          </li>
        </ul>
        <form class="inline-form" @submit.prevent="addIdentifier">
          <select v-model="newIdent.scheme" class="input" aria-label="编号体系">
            <option v-for="(t, k) in SCHEME_LABELS" :key="k" :value="k">{{ t }}</option>
          </select>
          <input v-model="newIdent.value" class="input" placeholder="编号" aria-label="编号" />
          <button type="submit" class="btn ghost small" :disabled="!!busy || !newIdent.value.trim()">添加编号</button>
        </form>
        <p v-if="sectionError.identifiers" class="error-banner" role="alert">{{ sectionError.identifiers }}</p>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>颜色</h2>
          <button type="button" class="btn ghost small" @click="colors.push({ color_code: '', name_ja: '', name_zh: '', hex: '', is_default: !colors.length })">添加颜色</button>
        </div>
        <div class="table-wrap">
          <table class="data">
            <thead><tr><th></th><th>编号</th><th>日文名</th><th>中文名</th><th>颜色值</th><th>默认</th><th></th></tr></thead>
            <tbody>
              <tr v-for="(c, i) in colors" :key="i">
                <td><ColorDot :hex="/^#[0-9a-fA-F]{6}$/.test(c.hex) ? c.hex : null" :size="16" /></td>
                <td><input v-model="c.color_code" class="input" aria-label="颜色编号" /></td>
                <td><input v-model="c.name_ja" class="input" aria-label="日文颜色名" /></td>
                <td><input v-model="c.name_zh" class="input" aria-label="中文颜色名" /></td>
                <td><input v-model="c.hex" class="input" placeholder="#1F2A44" aria-label="颜色值" /></td>
                <td><input type="radio" name="default-color" :checked="c.is_default" aria-label="设为默认颜色" @change="setDefault(i)" /></td>
                <td><button type="button" class="link-btn" @click="colors.splice(i, 1)">删除</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!colors.length" class="muted small">没有颜色</p>
        <p v-if="sectionError.colors" class="error-banner" role="alert">{{ sectionError.colors }}</p>
        <div class="form-actions"><button type="button" class="btn" :disabled="!!busy" @click="saveColors">保存颜色</button></div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>尺码</h2>
          <button type="button" class="btn ghost small" @click="sizes.push({ size_label: '', size_system: 'alpha', size_detail: null })">添加尺码</button>
        </div>
        <ul class="rows">
          <li v-for="(x, i) in sizes" :key="i">
            <input v-model="x.size_label" class="input" placeholder="尺码" aria-label="尺码" />
            <select v-model="x.size_system" class="input" aria-label="尺码体系">
              <option v-for="(t, k) in SIZE_SYSTEM_LABELS" :key="k" :value="k">{{ t }}</option>
            </select>
            <button type="button" class="link-btn" @click="sizes.splice(i, 1)">删除</button>
          </li>
        </ul>
        <p v-if="!sizes.length" class="muted small">没有尺码</p>
        <p v-if="sectionError.sizes" class="error-banner" role="alert">{{ sectionError.sizes }}</p>
        <div class="form-actions"><button type="button" class="btn" :disabled="!!busy" @click="saveSizes">保存尺码</button></div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>材质结构</h2>
          <div class="actions">
            <button type="button" class="btn ghost small" :disabled="!!busy || !product.material_text" @click="reparseMaterials">按材质原文重新解析</button>
            <button type="button" class="btn ghost small" @click="materials.push({ part: 'body', part_raw: '', fiber: 'cotton', fiber_raw: '', percent: '' })">添加一行</button>
          </div>
        </div>
        <div class="table-wrap">
          <table class="data">
            <thead><tr><th>部位</th><th>部位原文</th><th>纤维</th><th>纤维原文</th><th>%</th><th></th></tr></thead>
            <tbody>
              <tr v-for="(m, i) in materials" :key="i">
                <td>
                  <select v-model="m.part" class="input" aria-label="部位">
                    <option v-for="(t, k) in PART_LABELS" :key="k" :value="k">{{ t }}</option>
                    <option v-if="!(m.part in PART_LABELS)" :value="m.part">{{ m.part }}</option>
                  </select>
                </td>
                <td><input v-model="m.part_raw" class="input" aria-label="部位原文" /></td>
                <td>
                  <select v-model="m.fiber" class="input" aria-label="纤维">
                    <option v-for="(t, k) in FIBER_LABELS" :key="k" :value="k">{{ t }}</option>
                    <option v-if="!(m.fiber in FIBER_LABELS)" :value="m.fiber">{{ m.fiber }}</option>
                  </select>
                </td>
                <td><input v-model="m.fiber_raw" class="input" aria-label="纤维原文" /></td>
                <td><input v-model="m.percent" class="input pct" type="number" min="0" max="100" step="0.1" aria-label="比例" /></td>
                <td><button type="button" class="link-btn" @click="materials.splice(i, 1)">删除</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!materials.length" class="muted small">没有材质结构</p>
        <p v-if="sectionError.materials" class="error-banner" role="alert">{{ sectionError.materials }}</p>
        <div class="form-actions"><button type="button" class="btn" :disabled="!!busy" @click="saveMaterials">保存材质</button></div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>商品图片</h2>
          <ImageUploader label="上传商品图" source-type="user_upload" :disabled="!!busy" :on-uploaded="uploadHandler" />
        </div>
        <ul v-if="product.images.length" class="thumbs">
          <li v-for="img in product.images" :key="img.id">
            <img :src="img.thumb_url" :alt="label(IMAGE_ROLE_LABELS, img.role)" />
            <span class="badge">{{ label(IMAGE_ROLE_LABELS, img.role) }}</span>
            <button type="button" class="btn danger small" :disabled="!!busy" @click="removeImage(img)">移除</button>
          </li>
        </ul>
        <p v-else class="muted small">没有商品图片</p>
        <p v-if="sectionError.images" class="error-banner" role="alert">{{ sectionError.images }}</p>
        <p v-if="pendingImages.length && busy !== 'images'" class="pending">
          {{ pendingImages.length }} 张图片已上传但尚未关联。
          <button type="button" class="btn ghost small" :disabled="!!busy" @click="retryImages">重试关联</button>
        </p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.small {
  font-size: 13px;
}
.idents,
.rows {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  display: grid;
  gap: 8px;
}
.idents li {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  align-items: baseline;
  overflow-wrap: anywhere;
}
.rows li,
.inline-form {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.rows .input,
.inline-form .input {
  width: auto;
  flex: 1 1 140px;
}
table.data td {
  padding: 4px 6px;
  vertical-align: middle;
}
table.data .input {
  min-width: 90px;
}
.pct {
  min-width: 70px !important;
}
.pending {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 12px 0 0;
  font-size: 13px;
}
.thumbs {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 12px;
}
.thumbs li {
  display: grid;
  gap: 6px;
  justify-items: start;
}
.thumbs img {
  width: 100%;
  aspect-ratio: 3 / 4;
  object-fit: cover;
  background: var(--image-bg);
}
</style>
