<script setup lang="ts">
import { t as translate } from "../i18n";
// 穿搭：查看与编辑同一页。保存时依次提交字段、条目、标签，每一步使用上一步返回的 version。
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { onBeforeRouteLeave, useRouter } from "vue-router";
import { api } from "../api/client";
import type { ImageInfo, ItemSummary, Outfit } from "../api/types";
import ImageUploader from "../components/ImageUploader.vue";
import ItemCard from "../components/ItemCard.vue";
import ItemPicker from "../components/ItemPicker.vue";
import TagInput from "../components/TagInput.vue";
import { loadDictionaries, refreshDictionaries } from "../lib/dictionaries";
import { errorMessage, fieldErrors, isConflict } from "../lib/errors";
import { SEASON_LABELS, SLOT_LABELS, label } from "../lib/labels";
import { notify } from "../lib/toast";

const props = defineProps<{ id?: number }>();
const router = useRouter();
const isNew = computed(() => props.id === undefined);

interface Entry { item: ItemSummary; slot: string }
const outfit = ref<Outfit | null>(null);
const editing = ref(false);
const form = reactive({ name: "", description: "", season: "", occasion: "", rating: "" as string | number });
const entries = ref<Entry[]>([]);
const tags = ref<string[]>([]);
const cover = ref<ImageInfo | null>(null);
const picking = ref(false);
const loading = ref(false);
const saving = ref(false);
const error = ref<(() => string) | null>(null);
const errors = ref<Record<string, string>>({});
const conflict = ref(false);
let saved = false;

// 根据分类路径猜一个默认位置，用户可以再改
function guessSlot(it: ItemSummary): string {
  const path = it.category?.path_slugs.join(" ") ?? "";
  for (const [needle, slot] of [["outer", "outer"], ["bottom", "bottom"], ["pants", "bottom"], ["skirt", "bottom"], ["dress", "dress"], ["shoe", "shoes"], ["bag", "bag"], ["inner", "inner"], ["accessor", "accessory"], ["tops", "top"]] as const) {
    if (path.includes(needle)) return slot;
  }
  return "other";
}

function reset(o: Outfit | null) {
  form.name = o?.name ?? "";
  form.description = o?.description ?? "";
  form.season = o?.season ?? "";
  form.occasion = o?.occasion ?? "";
  form.rating = o?.rating ?? "";
  entries.value = o ? o.items.map((e) => ({ item: e.item, slot: e.slot })) : [];
  tags.value = o ? [...o.tags] : [];
  cover.value = o?.cover_image ?? null;
}

let requestId = 0;
onBeforeUnmount(() => { requestId++; });

async function load() {
  const id = ++requestId;
  void loadDictionaries();
  conflict.value = false;
  error.value = null;
  if (isNew.value) {
    outfit.value = null;
    reset(null);
    editing.value = true;
    return;
  }
  // 新建后路由复用同一个组件实例，需要回到查看模式
  editing.value = false;
  saved = false;
  loading.value = true;
  try {
    const o = await api.outfit(props.id!);
    if (id !== requestId) return; // 已切换到其他穿搭或离开页面
    outfit.value = o;
    reset(o);
    document.title = `${o.name} · Wardrobe`;
  } catch (e) {
    if (id === requestId) error.value = () => errorMessage(e);
  } finally {
    if (id === requestId) loading.value = false;
  }
}
watch(() => props.id, load, { immediate: true });

const norm = (v: unknown) => (v === "" || v === undefined ? null : v);
const fieldChanges = computed(() => {
  const o = outfit.value;
  const out: Record<string, unknown> = {};
  const next = { name: form.name.trim(), description: norm(form.description), season: norm(form.season), occasion: norm(form.occasion), rating: norm(form.rating) === null ? null : Number(form.rating), cover_image_id: cover.value?.id ?? null };
  const prev = { name: o?.name ?? "", description: o?.description ?? null, season: o?.season ?? null, occasion: o?.occasion ?? null, rating: o?.rating ?? null, cover_image_id: o?.cover_image?.id ?? null };
  for (const k of Object.keys(next) as (keyof typeof next)[]) if (next[k] !== prev[k]) out[k] = next[k];
  return out;
});
const itemsPayload = computed(() => entries.value.map((e, i) => ({ item_id: e.item.id, slot: e.slot, sort_order: i })));
const itemsChanged = computed(() =>
  JSON.stringify(itemsPayload.value) !== JSON.stringify((outfit.value?.items ?? []).map((e, i) => ({ item_id: e.item.id, slot: e.slot, sort_order: i }))),
);
const tagsChanged = computed(() => JSON.stringify(tags.value) !== JSON.stringify(outfit.value?.tags ?? []));
const dirty = computed(() => editing.value && (Object.keys(fieldChanges.value).length > 0 || itemsChanged.value || tagsChanged.value));

onBeforeRouteLeave(() => {
  if (dirty.value && !saved && !window.confirm(translate("有尚未保存的修改，确定离开吗？"))) return false;
});

function add(it: ItemSummary) {
  if (!entries.value.some((e) => e.item.id === it.id)) entries.value.push({ item: it, slot: guessSlot(it) });
}
function move(i: number, d: -1 | 1) {
  const j = i + d;
  if (j < 0 || j >= entries.value.length) return;
  const list = [...entries.value];
  [list[i], list[j]] = [list[j]!, list[i]!];
  entries.value = list;
}

async function save() {
  saving.value = true;
  error.value = null;
  errors.value = {};
  conflict.value = false;
  try {
    let current: Outfit;
    if (isNew.value) {
      const body: Record<string, unknown> = { name: form.name.trim(), items: itemsPayload.value, tags: tags.value };
      for (const [k, v] of Object.entries(fieldChanges.value)) if (k !== "name" && v !== null) body[k] = v;
      current = await api.createOutfit(body);
    } else {
      // 每一步成功后立即作为新的基准（差异按 outfit 计算）：后面的步骤失败时，重试只提交剩余部分并使用最新 version
      current = outfit.value!;
      if (Object.keys(fieldChanges.value).length) outfit.value = current = await api.updateOutfit(current.id, { version: current.version, ...fieldChanges.value });
      if (itemsChanged.value) outfit.value = current = await api.setOutfitItems(current.id, current.version, itemsPayload.value);
      if (tagsChanged.value) outfit.value = current = await api.setOutfitTags(current.id, current.version, tags.value);
    }
    if (tagsChanged.value || (isNew.value && tags.value.length)) void refreshDictionaries();
    saved = true;
    notify(isNew.value ? translate("已创建穿搭") : translate("已保存穿搭"));
    if (isNew.value) {
      await router.push({ name: "outfit", params: { id: current.id } });
    } else {
      outfit.value = current;
      reset(current);
      editing.value = false;
      saved = false;
    }
  } catch (e) {
    error.value = () => errorMessage(e);
    errors.value = fieldErrors(e);
    conflict.value = isConflict(e);
  } finally {
    saving.value = false;
  }
}

function cancel() {
  if (isNew.value) {
    router.push({ name: "outfits" });
    return;
  }
  reset(outfit.value);
  editing.value = false;
}

async function remove() {
  const o = outfit.value;
  if (!o || !window.confirm(translate("删除穿搭「{0}」？其中的衣物不会被删除。", o.name))) return;
  try {
    await api.deleteOutfit(o.id, o.version);
    notify(translate("已删除穿搭「{0}」", o.name));
    await router.push({ name: "outfits" });
  } catch (e) {
    error.value = () => errorMessage(e);
  }
}

const viewEntries = computed(() => outfit.value?.items ?? []);
</script>

<template>
  <div class="page">
    <RouterLink :to="{ name: 'outfits' }" class="link-btn">{{ translate("← 全部穿搭") }}</RouterLink>
    <p v-if="loading" class="muted">{{ translate("加载中…") }}</p>
    <p v-else-if="error && !outfit && !isNew" class="error-banner" role="alert">{{ error?.() }}</p>

    <template v-else-if="!editing && outfit">
      <div class="page-head">
        <div>
          <h1>{{ outfit.name }}</h1>
          <p class="muted sub">
            {{ outfit.items.length }} {{ translate("件") }}<template v-if="outfit.season"> · {{ label(SEASON_LABELS, outfit.season) }}</template><template v-if="outfit.occasion"> · {{ outfit.occasion }}</template>
            <template v-if="outfit.rating"> · <span class="stars">{{ "★".repeat(outfit.rating) }}</span></template>
          </p>
        </div>
        <div class="actions">
          <button type="button" class="btn small" @click="editing = true">{{ translate("编辑") }}</button>
          <button type="button" class="btn danger small" @click="remove">{{ translate("删除") }}</button>
        </div>
      </div>
      <p v-if="error" class="error-banner" role="alert">{{ error?.() }}</p>
      <div v-if="outfit.tags.length" class="tags">
        <RouterLink v-for="t in outfit.tags" :key="t" class="chip" :to="{ name: 'outfits', query: { tag: t } }">#{{ t }}</RouterLink>
      </div>
      <p v-if="outfit.description" class="desc">{{ outfit.description }}</p>
      <div class="view-layout">
        <img v-if="outfit.cover_image" :src="outfit.cover_image.url" :alt="translate('{0} 封面', outfit.name)" class="cover" />
        <ul class="grid">
          <li v-for="e in viewEntries" :key="e.item.id">
            <span class="slot">{{ label(SLOT_LABELS, e.slot) }}</span>
            <ItemCard :item="e.item" />
          </li>
        </ul>
      </div>
      <p v-if="!viewEntries.length" class="muted">{{ translate("这套穿搭还没有衣物。") }}</p>
    </template>

    <form v-else-if="editing" novalidate @submit.prevent="save">
      <div class="page-head"><h1>{{ isNew ? translate("新建穿搭") : translate("编辑：{0}", outfit?.name) }}</h1></div>
      <p v-if="error" class="error-banner" role="alert">
        {{ error?.() }}
        <button v-if="conflict" type="button" class="link-btn" @click="load">{{ translate("载入最新版本（放弃未保存修改）") }}</button>
      </p>
      <section class="panel">
        <div class="form-grid">
          <label class="field wide">
            <span>{{ translate("名称（必填）") }}</span>
            <input v-model="form.name" required :aria-invalid="!!errors.name" />
            <span v-if="errors.name" class="field-error">{{ errors.name }}</span>
          </label>
          <label class="field">
            <span>{{ translate("季节") }}</span>
            <select v-model="form.season">
              <option value="">{{ translate("未指定") }}</option>
              <option v-for="(t, k) in SEASON_LABELS" :key="k" :value="k">{{ t }}</option>
            </select>
          </label>
          <label class="field"><span>{{ translate("场合") }}</span><input v-model="form.occasion" :placeholder='translate("例如 通勤")' /></label>
          <label class="field">
            <span>{{ translate("评分") }}</span>
            <select v-model="form.rating">
              <option value="">{{ translate("未评分") }}</option>
              <option v-for="n in 5" :key="n" :value="n">{{ "★".repeat(n) }}</option>
            </select>
          </label>
          <label class="field wide"><span>{{ translate("说明") }}</span><textarea v-model="form.description" /></label>
          <div class="field wide">
            <span>{{ translate("标签") }}</span>
            <TagInput v-model="tags" :label='translate("添加穿搭标签")' />
          </div>
          <div class="field wide">
            <span>{{ translate("封面照片") }}</span>
            <div class="cover-edit">
              <img v-if="cover" :src="cover.thumb_url" :alt='translate("当前封面")' />
              <ImageUploader :label="cover ? translate('更换封面') : translate('上传封面')" @uploaded="(img: ImageInfo) => { cover = img; }" />
              <button v-if="cover" type="button" class="link-btn" @click="cover = null">{{ translate("移除封面") }}</button>
            </div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>{{ translate("衣物（") }}{{ entries.length }}）</h2>
          <button type="button" class="btn ghost small" :aria-expanded="picking" @click="picking = !picking">{{ picking ? translate("收起") : translate("添加衣物") }}</button>
        </div>
        <ItemPicker v-if="picking" class="picker" :excluded="entries.map((e) => e.item.id)" @pick="add" />
        <ol v-if="entries.length" class="entries">
          <li v-for="(e, i) in entries" :key="e.item.id" :data-testid="`entry-${e.item.id}`">
            <img v-if="e.item.thumb_url" :src="e.item.thumb_url" alt="" />
            <span v-else class="ph" />
            <span class="name">{{ e.item.name }}<span class="muted"> · {{ e.item.brand ?? translate("无品牌") }}</span></span>
            <select v-model="e.slot" class="input slot-select" :aria-label="translate('{0} 的位置', e.item.name)">
              <option v-for="(t, k) in SLOT_LABELS" :key="k" :value="k">{{ t }}</option>
            </select>
            <span class="row-actions">
              <button type="button" class="link-btn" :disabled="i === 0" :aria-label='translate("上移")' @click="move(i, -1)">↑</button>
              <button type="button" class="link-btn" :disabled="i === entries.length - 1" :aria-label='translate("下移")' @click="move(i, 1)">↓</button>
              <button type="button" class="link-btn" @click="entries.splice(i, 1)">{{ translate("移除") }}</button>
            </span>
          </li>
        </ol>
        <p v-else class="muted">{{ translate("还没有加入衣物。") }}</p>
        <p v-if="errors['items.0.item_id'] || errors.items" class="field-error">{{ errors["items.0.item_id"] || errors.items }}</p>
      </section>

      <div class="form-actions">
        <button type="submit" class="btn" :disabled="saving || !form.name.trim() || (!isNew && !dirty)">{{ saving ? translate("保存中…") : isNew ? translate("创建穿搭") : translate("保存") }}</button>
        <button type="button" class="btn ghost" @click="cancel">{{ translate("取消") }}</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.sub {
  margin: 4px 0 0;
  font-size: 14px;
}
.stars {
  color: #b58a12;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}
.desc {
  white-space: pre-wrap;
  max-width: 70ch;
}
.view-layout {
  display: grid;
  gap: 24px;
}
.cover {
  max-width: min(420px, 100%);
  aspect-ratio: 3 / 4;
  object-fit: cover;
  background: var(--image-bg);
}
.grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 24px 16px;
}
.grid li {
  display: grid;
  gap: 6px;
  min-width: 0;
}
.slot {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-2);
}
.cover-edit {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}
.cover-edit img {
  width: 72px;
  aspect-ratio: 3 / 4;
  object-fit: cover;
}
.picker {
  margin-bottom: 16px;
}
.entries {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.entries li {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) 130px auto;
  gap: 10px;
  align-items: center;
  border-bottom: 1px solid var(--line);
  padding-bottom: 8px;
}
.entries img,
.ph {
  width: 40px;
  aspect-ratio: 3 / 4;
  object-fit: cover;
  background: var(--image-bg);
  display: block;
}
.name {
  font-size: 14px;
  overflow-wrap: anywhere;
}
.row-actions {
  display: flex;
  gap: 10px;
}
@media (max-width: 600px) {
  .entries li {
    grid-template-columns: 40px minmax(0, 1fr);
  }
  .slot-select,
  .row-actions {
    grid-column: 2;
  }
}
</style>
