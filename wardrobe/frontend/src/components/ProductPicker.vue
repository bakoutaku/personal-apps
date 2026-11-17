<script setup lang="ts">
import { t as translate } from "../i18n";
import { onBeforeUnmount, ref, watch } from "vue";
import { api } from "../api/client";
import type { Product } from "../api/types";
import { errorMessage } from "../lib/errors";

const props = defineProps<{ selectedId?: number | null }>();
const emit = defineEmits<{ select: [product: Product] }>();
const q = ref("");
const results = ref<Product[]>([]);
const loading = ref(false);
const error = ref<(() => string) | null>(null);
let timer: ReturnType<typeof setTimeout> | undefined;
let requestId = 0;

async function search() {
  const id = ++requestId;
  loading.value = true;
  error.value = null;
  try {
    const page = await api.products({ q: q.value.trim() || undefined, limit: 20 });
    if (id === requestId) results.value = page.items;
  } catch (e) {
    if (id === requestId) error.value = () => errorMessage(e);
  } finally {
    if (id === requestId) loading.value = false;
  }
}

watch(q, () => {
  clearTimeout(timer);
  timer = setTimeout(search, 250);
});
void search();
onBeforeUnmount(() => {
  clearTimeout(timer);
  requestId++;
});

function name(p: Product) {
  return p.name_ja || p.name_zh || p.name_en || translate("商品 {0}", p.id);
}
</script>

<template>
  <div class="picker">
    <input v-model="q" class="input" type="search" :placeholder='translate("按商品名称搜索…")' :aria-label='translate("搜索商品")' />
    <p v-if="error" class="field-error" role="alert">{{ error?.() }}</p>
    <ul class="results" :aria-busy="loading">
      <li v-for="p in results" :key="p.id">
        <button type="button" class="result" :aria-pressed="p.id === props.selectedId" @click="emit('select', p)">
          <img v-if="p.images[0]" :src="p.images[0].thumb_url" alt="" />
          <span v-else class="ph" />
          <span class="text">
            <strong>{{ name(p) }}</strong>
            <span class="muted">{{ p.brand?.name ?? translate("无品牌") }} · {{ p.category?.path.join(" / ") ?? translate("未分类") }}</span>
          </span>
        </button>
      </li>
      <li v-if="!loading && !results.length" class="muted none">{{ translate("没有找到商品") }}</li>
    </ul>
  </div>
</template>

<style scoped>
.picker {
  display: grid;
  gap: 8px;
}
.results {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.result {
  display: flex;
  gap: 10px;
  align-items: center;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
  text-align: left;
  cursor: pointer;
}
.result[aria-pressed="true"] {
  background: var(--chip);
  box-shadow: inset 3px 0 0 var(--ink);
}
img,
.ph {
  width: 36px;
  height: 48px;
  object-fit: cover;
  background: var(--image-bg);
  flex-shrink: 0;
}
.text {
  display: grid;
  min-width: 0;
  font-size: 13px;
  overflow-wrap: anywhere;
}
.none {
  padding: 12px;
  font-size: 13px;
}
</style>
