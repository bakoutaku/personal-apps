<script setup lang="ts">
// 新建 / 编辑衣物。只提交真正改动的字段；标签、图片是单独的接口，按返回的最新 version 依次调用。
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { onBeforeRouteLeave, useRouter } from "vue-router";
import { api } from "../api/client";
import type { ImageInfo, ItemDetail, Product } from "../api/types";
import ImageUploader from "../components/ImageUploader.vue";
import ProductPicker from "../components/ProductPicker.vue";
import TagInput from "../components/TagInput.vue";
import { categoryOptions, dict, loadDictionaries, refreshDictionaries } from "../lib/dictionaries";
import { errorMessage, fieldErrors, isConflict } from "../lib/errors";
import { CONDITION_LABELS, SIZE_SYSTEM_LABELS, STATUS_LABELS, label } from "../lib/labels";
import { notify } from "../lib/toast";

const props = defineProps<{ id?: number }>();
const router = useRouter();
const isNew = computed(() => props.id === undefined);

const FIELDS = [
  "category_id", "color_code", "color_name", "color_hex", "size_label", "size_system", "condition",
  "acquired_on", "location", "alterations", "favorite", "notes", "status", "retired_on", "wear_count", "last_worn_on",
] as const;
type Field = (typeof FIELDS)[number];
type Form = Record<Exclude<Field, "category_id" | "favorite" | "wear_count">, string> & {
  category_id: number | null;
  favorite: boolean;
  // type=number 的输入框：有值时是数字，清空时是空字符串
  wear_count: number | "";
};

function emptyForm(): Form {
  return {
    category_id: null, color_code: "", color_name: "", color_hex: "", size_label: "", size_system: "",
    condition: "", acquired_on: "", location: "", alterations: "", favorite: false, notes: "",
    status: "owned", retired_on: "", wear_count: 0, last_worn_on: "",
  };
}

const item = ref<ItemDetail | null>(null);
const form = reactive<Form>(emptyForm());
const original = ref<Form>(emptyForm());
const tags = ref<string[]>([]);
const originalTags = ref<string[]>([]);
const product = ref<Product | null>(null);
const pickingProduct = ref(false);
// 新建时可以不选已有商品，而是内联新建一个「自建商品」
const productMode = ref<"existing" | "new">("existing");
const newProduct = reactive({ brand: "", category: "", name_ja: "", name_zh: "", name_en: "" });
const stagedImages = ref<ImageInfo[]>([]);
// 编辑已有衣物时，已上传但关联失败的图片保留在这里，可直接重试
const pendingImages = ref<ImageInfo[]>([]);
// 新建时衣物与照片关联是多个独立提交的请求。衣物一旦创建就记住它，失败后重试只继续未完成的照片，
// 不会再新建一件衣物（也不会再新建自建商品）。
const created = ref<ItemDetail | null>(null);
// 衣物已创建、照片尚未全部关联时：商品、衣物信息和标签都已保存，界面锁定为只读，
// 避免用户以为之后在这里做的修改也会被保存（重试只处理照片）。
const locked = computed(() => isNew.value && created.value !== null);

const loading = ref(false);
const saving = ref(false);
const error = ref<string | null>(null);
const errors = ref<Record<string, string>>({});
const conflict = ref(false);

const statusOptions = computed(() =>
  (dict.enums.item_status ?? Object.keys(STATUS_LABELS)).filter((s) => s !== "returned" || original.value.status === "returned"),
);

function toForm(it: ItemDetail): Form {
  const f = emptyForm();
  for (const k of FIELDS) {
    const v = (it as unknown as Record<string, unknown>)[k];
    (f as Record<Field, unknown>)[k] = v ?? (k === "favorite" ? false : k === "category_id" ? null : "");
  }
  return f;
}

function adopt(it: ItemDetail) {
  item.value = it;
  product.value = it.product;
  original.value = toForm(it);
  Object.assign(form, toForm(it));
  tags.value = [...it.tags];
  originalTags.value = [...it.tags];
}

let requestId = 0;
onBeforeUnmount(() => { requestId++; });

async function load() {
  const id = ++requestId;
  void loadDictionaries();
  if (isNew.value) return;
  loading.value = true;
  error.value = null;
  conflict.value = false;
  pendingImages.value = [];
  try {
    const it = await api.item(props.id!);
    if (id !== requestId) return; // 已切换到其他衣物或离开页面
    adopt(it);
    document.title = `编辑 ${it.name} · Wardrobe`;
  } catch (e) {
    if (id === requestId) error.value = errorMessage(e);
  } finally {
    if (id === requestId) loading.value = false;
  }
}
watch(
  () => props.id,
  () => {
    // 新建与编辑路由复用同一组件实例时，不能沿用上一次新建的进度
    created.value = null;
    stagedImages.value = [];
    void load();
  },
  { immediate: true },
);

const norm = (v: unknown) => (v === "" || v === undefined ? null : v);

const changes = computed(() => {
  const out: Record<string, unknown> = {};
  for (const k of FIELDS) if (norm(form[k]) !== norm(original.value[k])) out[k] = norm(form[k]);
  if (product.value && item.value && product.value.id !== item.value.product.id) out.product_id = product.value.id;
  // 状态离开「已退货」时退款金额必须清空（后端规则）
  if ("status" in out && original.value.status === "returned") out.refund_amount = null;
  return out;
});
const tagsChanged = computed(() => JSON.stringify(tags.value) !== JSON.stringify(originalTags.value));
const dirty = computed(() =>
  isNew.value
    ? Boolean(
        product.value ||
          Object.values(newProduct).some((v) => v.trim()) ||
          Object.keys(changes.value).length ||
          tags.value.length ||
          stagedImages.value.length,
      )
    : Boolean(Object.keys(changes.value).length || tagsChanged.value || pendingImages.value.length),
);

let saved = false;
onBeforeRouteLeave(() => {
  if (dirty.value && !saved && !window.confirm("有尚未保存的修改，确定离开吗？")) return false;
});

function selectProduct(p: Product) {
  product.value = p;
  pickingProduct.value = false;
}

function fieldPayload(): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const k of FIELDS) {
    if (k === "status" && form.status === "owned") continue;
    if (k === "wear_count" && form.wear_count === 0) continue;
    const v = norm(form[k]);
    if (v !== null && v !== false) out[k] = v;
  }
  return out;
}

async function linkStaged(current: ItemDetail): Promise<ItemDetail> {
  for (const img of [...stagedImages.value]) {
    if (!current.images.some((x) => x.id === img.id)) {
      current = await api.addItemImage(current.id, { version: current.version, image_id: img.id, role: current.images.length ? "gallery" : "main" });
    }
    created.value = current;
    stagedImages.value = stagedImages.value.filter((x) => x.id !== img.id);
  }
  return current;
}

async function save() {
  error.value = null;
  errors.value = {};
  conflict.value = false;
  const n = form.wear_count;
  if (n === "" || !Number.isInteger(n) || n < 0) {
    errors.value = { wear_count: "请填写 0 或以上的整数" };
    return;
  }
  saving.value = true;
  try {
    let current: ItemDetail;
    if (isNew.value) {
      if (created.value) {
        // 重试：表单已锁定，只继续关联照片。先读最新状态（上次的关联可能已成功但响应丢失）
        current = await api.item(created.value.id);
        created.value = current;
      } else {
        const body: Record<string, unknown> = { ...fieldPayload(), tags: tags.value };
        if (productMode.value === "existing") {
          if (!product.value) throw new Error("请选择商品，或改为新建商品");
          body.product_id = product.value.id;
        } else {
          const p: Record<string, unknown> = {};
          for (const [k, v] of Object.entries(newProduct)) if (v.trim()) p[k] = v.trim();
          if (!p.name_ja && !p.name_zh && !p.name_en) throw new Error("新建商品至少需要一个名称");
          body.product = p;
        }
        current = await api.createItem(body);
        created.value = current;
        if (productMode.value === "new") void refreshDictionaries();
      }
      current = await linkStaged(current);
    } else {
      current = item.value!;
      // 每一步成功后立即作为新的基准：后面的步骤失败时，重试只提交尚未完成的部分，并使用最新 version
      const sent = changes.value;
      if (Object.keys(sent).length) {
        current = await api.updateItem(current.id, { version: current.version, ...sent });
        item.value = current;
        const fresh = toForm(current);
        original.value = fresh;
        for (const k of FIELDS) if (k in sent) (form as Record<Field, unknown>)[k] = fresh[k];
        product.value = current.product;
      }
      if (tagsChanged.value) {
        current = await api.setItemTags(current.id, current.version, tags.value);
        item.value = current;
        originalTags.value = [...current.tags];
        void refreshDictionaries();
      }
    }
    adopt(current);
    saved = true;
    notify(isNew.value ? "已添加衣物" : "已保存");
    await router.push({ name: "item", params: { id: current.id } });
  } catch (e) {
    error.value = created.value
      ? `衣物已创建（#${created.value.id}），但还有 ${stagedImages.value.length} 张照片未关联：${errorMessage(e)}。再次保存只会继续关联剩余照片，不会重复创建。`
      : errorMessage(e);
    errors.value = fieldErrors(e);
    conflict.value = isConflict(e) && !created.value;
  } finally {
    saving.value = false;
  }
}

async function addImage(img: ImageInfo): Promise<boolean> {
  if (isNew.value || !item.value) {
    if (!stagedImages.value.some((x) => x.id === img.id)) stagedImages.value.push(img);
    return true;
  }
  if (!pendingImages.value.some((x) => x.id === img.id)) pendingImages.value.push(img);
  error.value = null;
  try {
    // ImageUploader 等待本函数完成后才处理下一张，所以总是使用上一次关联返回的 version
    if (!item.value.images.some((x) => x.id === img.id)) {
      const role = item.value.images.length ? "gallery" : "main";
      // 图片操作只更新图片与 version，保留表单里尚未保存的字段
      item.value = await api.addItemImage(item.value.id, { version: item.value.version, image_id: img.id, role });
    }
    pendingImages.value = pendingImages.value.filter((x) => x.id !== img.id);
    return true;
  } catch (e) {
    error.value = `${pendingImages.value.length} 张照片尚未关联：${errorMessage(e)}`;
    conflict.value = isConflict(e);
    return false;
  }
}

async function retryImages() {
  for (const img of [...pendingImages.value]) if (!(await addImage(img))) break;
}

async function removeImage(img: ImageInfo) {
  if (isNew.value || !item.value) {
    stagedImages.value = stagedImages.value.filter((x) => x.id !== img.id);
    return;
  }
  try {
    item.value = await api.removeItemImage(item.value.id, img.id, item.value.version);
  } catch (e) {
    error.value = errorMessage(e);
    conflict.value = isConflict(e);
  }
}

const images = computed(() => {
  if (!isNew.value) return item.value?.images ?? [];
  // 部分成功后：已关联到新衣物的照片在前，仍待关联的在后
  const linked = created.value?.images ?? [];
  return [...linked, ...stagedImages.value.filter((x) => !linked.some((l) => l.id === x.id))];
});
// 新建时只能移除尚未关联的照片；已关联的请在衣物编辑页处理
const removable = (img: ImageInfo) => !isNew.value || stagedImages.value.some((x) => x.id === img.id);
const createdProductName = computed(() => {
  const p = created.value?.product;
  return p ? p.name_ja || p.name_zh || p.name_en || `商品 ${p.id}` : "";
});
const err = (k: string) => errors.value[k];

function cancel() {
  if (created.value) router.push({ name: "item", params: { id: created.value.id } });
  else if (isNew.value) router.push("/");
  else router.push({ name: "item", params: { id: props.id } });
}
</script>

<template>
  <div class="page narrow">
    <div class="page-head">
      <h1>{{ isNew ? "添加衣物" : `编辑：${item?.name ?? ""}` }}</h1>
      <RouterLink v-if="!isNew && item" :to="{ name: 'product', params: { id: item.product.id } }" class="link-btn">
        编辑商品资料（名称、颜色、尺码、材质）→
      </RouterLink>
    </div>

    <p v-if="loading" class="muted">加载中…</p>
    <template v-else-if="isNew || item">
      <p v-if="error" class="error-banner" role="alert">
        {{ error }}
        <button v-if="conflict" type="button" class="link-btn" @click="load">载入最新版本（放弃未保存修改）</button>
      </p>
      <p v-if="locked && created" class="locked-note" role="status" data-testid="partial-created">
        衣物 #{{ created.id }} 已创建：商品、衣物信息和标签都已保存，这里不能再修改。现在只需完成剩余照片的关联；
        其他修改请在完成后到衣物编辑页进行。
      </p>

      <form novalidate @submit.prevent="save">
        <section class="panel">
          <h2>商品</h2>
          <template v-if="isNew && locked && created">
            <p class="chosen">
              已保存：<strong>{{ createdProductName }}</strong>
              <span class="muted"> · {{ created.product.brand?.name ?? "无品牌" }}</span>
            </p>
          </template>
          <template v-else-if="isNew">
            <div class="tabs" role="tablist" aria-label="商品来源">
              <button type="button" role="tab" :aria-selected="productMode === 'existing'" @click="productMode = 'existing'">选择已有商品</button>
              <button type="button" role="tab" :aria-selected="productMode === 'new'" @click="productMode = 'new'">新建商品</button>
            </div>
            <template v-if="productMode === 'existing'">
              <p v-if="product" class="chosen">已选择：<strong>{{ product.name_ja || product.name_zh || product.name_en }}</strong></p>
              <ProductPicker :selected-id="product?.id" @select="selectProduct" />
            </template>
            <div v-else class="form-grid">
              <label class="field">
                <span>品牌</span>
                <select v-model="newProduct.brand">
                  <option value="">无品牌</option>
                  <option v-for="b in dict.brands" :key="b.id" :value="b.slug">{{ b.name }}</option>
                </select>
              </label>
              <label class="field">
                <span>分类</span>
                <select v-model="newProduct.category">
                  <option value="">未分类</option>
                  <option v-for="c in categoryOptions()" :key="c.id" :value="c.slug">{{ c.label }}</option>
                </select>
              </label>
              <label class="field"><span>日文名</span><input v-model="newProduct.name_ja" /></label>
              <label class="field"><span>中文名</span><input v-model="newProduct.name_zh" /></label>
              <label class="field"><span>英文名</span><input v-model="newProduct.name_en" /></label>
              <p class="hint field wide">只填写名称即可；颜色、尺码、编号、材质可在保存后到「商品资料」页补充。</p>
            </div>
          </template>
          <template v-else-if="product">
            <p class="chosen">
              <strong>{{ product.name_ja || product.name_zh || product.name_en }}</strong>
              <span class="muted"> · {{ product.brand?.name ?? "无品牌" }}</span>
              <button type="button" class="link-btn" @click="pickingProduct = !pickingProduct">{{ pickingProduct ? "取消更换" : "更换商品" }}</button>
            </p>
            <p v-if="err('product_id')" class="field-error">{{ err("product_id") }}</p>
            <ProductPicker v-if="pickingProduct" :selected-id="product.id" @select="selectProduct" />
          </template>
        </section>

        <section class="panel">
          <h2>这件衣物</h2>
          <p class="hint muted">颜色和尺码留空时，按「购买明细 → 商品默认」自动取值；只有与购买记录不同时才需要填写。</p>
          <div class="form-grid">
            <label class="field">
              <span>分类</span>
              <select v-model="form.category_id" :disabled="locked" :aria-invalid="!!err('category_id')">
                <option :value="null">跟随商品分类</option>
                <option v-for="c in categoryOptions()" :key="c.id" :value="c.id">{{ c.label }}</option>
              </select>
            </label>
            <label class="field">
              <span>颜色名称</span>
              <input v-model="form.color_name" :disabled="locked" placeholder="例如 NAVY" />
            </label>
            <label class="field">
              <span>颜色编号</span>
              <input v-model="form.color_code" :disabled="locked" placeholder="例如 69" />
            </label>
            <label class="field">
              <span>颜色值</span>
              <span class="color-row">
                <input v-model="form.color_hex" :disabled="locked" placeholder="#1F2A44" :aria-invalid="!!err('color_hex')" />
                <input type="color" :disabled="locked" :value="(form.color_hex as string) || '#ffffff'" aria-label="选择颜色" @input="form.color_hex = ($event.target as HTMLInputElement).value.toUpperCase()" />
              </span>
              <span v-if="err('color_hex')" class="field-error">{{ err("color_hex") }}</span>
            </label>
            <label class="field">
              <span>尺码</span>
              <input v-model="form.size_label" :disabled="locked" placeholder="例如 L" />
            </label>
            <label class="field">
              <span>尺码体系</span>
              <select v-model="form.size_system" :disabled="locked">
                <option value="">—</option>
                <option v-for="(t, k) in SIZE_SYSTEM_LABELS" :key="k" :value="k">{{ t }}</option>
              </select>
            </label>
            <label class="field">
              <span>状况</span>
              <select v-model="form.condition" :disabled="locked">
                <option value="">未记录</option>
                <option v-for="(t, k) in CONDITION_LABELS" :key="k" :value="k">{{ t }}</option>
              </select>
            </label>
            <label class="field">
              <span>取得日期</span>
              <input v-model="form.acquired_on" type="date" :disabled="locked" :aria-invalid="!!err('acquired_on')" />
            </label>
            <label class="field">
              <span>收纳位置</span>
              <input v-model="form.location" :disabled="locked" placeholder="例如 卧室衣柜" />
            </label>
            <label class="field">
              <span>状态</span>
              <select v-model="form.status" :disabled="locked || (original.status === 'returned' && !isNew)" :aria-invalid="!!err('status')">
                <option v-for="s in statusOptions" :key="s" :value="s">{{ label(STATUS_LABELS, s) }}</option>
              </select>
              <span v-if="original.status === 'returned' && !isNew" class="hint">已退货；如需改回，请在详情页操作</span>
            </label>
            <label v-if="form.status !== 'owned' && form.status !== 'wishlist'" class="field">
              <span>离开日期</span>
              <input v-model="form.retired_on" type="date" :disabled="locked" :aria-invalid="!!err('retired_on')" />
              <span v-if="err('retired_on')" class="field-error">{{ err("retired_on") }}</span>
            </label>
            <template v-if="!isNew">
              <label class="field">
                <span>穿着次数</span>
                <input v-model="form.wear_count" type="number" min="0" step="1" :aria-invalid="!!err('wear_count')" />
                <span v-if="err('wear_count')" class="field-error">{{ err("wear_count") }}</span>
              </label>
              <label class="field">
                <span>最近穿着</span>
                <input v-model="form.last_worn_on" type="date" :aria-invalid="!!err('last_worn_on')" />
                <span v-if="err('last_worn_on')" class="field-error">{{ err("last_worn_on") }}</span>
              </label>
            </template>
            <label class="field check">
              <input v-model="form.favorite" type="checkbox" :disabled="locked" />
              <span>收藏</span>
            </label>
            <label class="field wide">
              <span>修改记录</span>
              <input v-model="form.alterations" :disabled="locked" placeholder="例如 裤长改短 3cm" />
            </label>
            <label class="field wide">
              <span>备注</span>
              <textarea v-model="form.notes" :disabled="locked" />
            </label>
          </div>
        </section>

        <section class="panel">
          <h2>标签</h2>
          <template v-if="locked">
            <ul v-if="tags.length" class="locked-tags" data-testid="locked-tags">
              <li v-for="t in tags" :key="t" class="chip">#{{ t }}</li>
            </ul>
            <p v-else class="muted">没有标签</p>
          </template>
          <TagInput v-else v-model="tags" />
        </section>

        <section class="panel">
          <div class="panel-head">
            <h2>衣物照片</h2>
            <ImageUploader label="上传照片" @uploaded="addImage" />
          </div>
          <p v-if="pendingImages.length" class="pending">
            {{ pendingImages.length }} 张照片已上传但尚未关联。
            <button type="button" class="btn ghost small" @click="retryImages">重试关联</button>
          </p>
          <p v-if="!images.length" class="muted">还没有这件衣物自己的照片；列表会使用商品图。</p>
          <ul v-else class="thumbs">
            <li v-for="(img, i) in images" :key="img.id">
              <img :src="img.thumb_url" :alt="`照片 ${i + 1}`" />
              <span v-if="img.role === 'main' || (isNew && i === 0 && !created?.images.length)" class="badge dark">主图</span>
              <button v-if="removable(img)" type="button" class="btn danger small" @click="removeImage(img)">移除</button>
            </li>
          </ul>
        </section>

        <div class="form-actions">
          <button type="submit" class="btn" :disabled="saving || (!isNew && !dirty)">
            {{ saving ? "保存中…" : created ? "继续关联照片" : isNew ? "添加衣物" : "保存修改" }}
          </button>
          <RouterLink v-if="created" :to="{ name: 'item', params: { id: created.id } }" class="btn ghost">查看已创建的衣物</RouterLink>
          <button type="button" class="btn ghost" @click="cancel">取消</button>
        </div>
      </form>
    </template>
    <p v-else-if="error" class="error-banner" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.chosen {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  align-items: baseline;
  margin: 0 0 10px;
  overflow-wrap: anywhere;
}
.hint {
  margin: 0 0 12px;
  font-size: 13px;
}
.locked-note {
  border: 1px solid #e0c27a;
  background: #fbf5e6;
  color: #7a5a10;
  padding: 12px 16px;
  border-radius: var(--radius);
  font-size: 14px;
}
.locked-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.color-row {
  display: flex;
  gap: 6px;
}
.color-row input[type="color"] {
  width: 42px;
  min-height: 38px;
  padding: 2px;
  border: 1px solid var(--line-strong);
  background: var(--surface);
  flex-shrink: 0;
}
.pending {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 0 0 12px;
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
  position: relative;
  display: grid;
  gap: 6px;
}
.thumbs img {
  width: 100%;
  aspect-ratio: 3 / 4;
  object-fit: cover;
  background: var(--image-bg);
}
.thumbs .badge {
  position: absolute;
  top: 6px;
  left: 6px;
}
</style>
