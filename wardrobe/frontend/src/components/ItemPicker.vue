<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { api } from "../api/client";
import type { ItemSummary, QuickGroup } from "../api/types";
import { errorMessage } from "../lib/errors";
import ColorDot from "./ColorDot.vue";
import QuickGroups from "./QuickGroups.vue";

const props = defineProps<{ excluded: number[] }>();
const emit = defineEmits<{ pick: [item: ItemSummary] }>();
const q = ref("");
const group = ref<string | null>(null);
const groups = ref<QuickGroup[]>();
const results = ref<ItemSummary[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);
let timer: ReturnType<typeof setTimeout> | undefined;
let requestId = 0;

async function search() {
  const id = ++requestId;
  loading.value = true;
  error.value = null;
  try {
    const query = { q: q.value.trim() || undefined, status: "owned" };
    const [page, facets] = await Promise.all([
      api.items({ ...query, group: group.value ?? undefined, limit: 40 }),
      api.facets(query),
    ]);
    if (id === requestId) {
      results.value = page.items;
      groups.value = facets.groups;
    }
  } catch (e) {
    if (id === requestId) error.value = errorMessage(e);
  } finally {
    if (id === requestId) loading.value = false;
  }
}

watch(q, () => {
  clearTimeout(timer);
  timer = setTimeout(search, 250);
});
watch(group, () => {
  clearTimeout(timer);
  void search();
});
void search();
onBeforeUnmount(() => {
  clearTimeout(timer);
  requestId++;
});
</script>

<template>
  <div class="picker">
    <input v-model="q" class="input" type="search" placeholder="搜索要加入的衣物…" aria-label="搜索衣物" />
    <QuickGroups :groups="groups" :selected="group" @select="(key) => (group = key)" />
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
    <ul class="grid" :aria-busy="loading">
      <li v-for="it in results" :key="it.id">
        <button type="button" class="pick" :disabled="props.excluded.includes(it.id)" @click="emit('pick', it)">
          <img v-if="it.thumb_url" :src="it.thumb_url" alt="" loading="lazy" />
          <span v-else class="ph" :style="{ background: it.resolved.color.hex ?? it.color_swatch?.hex ?? undefined }" />
          <span class="name">{{ it.name }}</span>
          <span class="meta">
            <ColorDot :hex="it.resolved.color.hex" :swatch="it.color_swatch?.hex" :family="it.resolved.color.family" :size="10" />
            {{ it.resolved.size.label ?? "" }}
          </span>
          <span v-if="props.excluded.includes(it.id)" class="added">已加入</span>
        </button>
      </li>
    </ul>
    <p v-if="!loading && !results.length" class="muted">没有找到衣物</p>
  </div>
</template>

<style scoped>
.picker {
  display: grid;
  gap: 10px;
}
.grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 10px;
  max-height: 420px;
  overflow-y: auto;
}
.pick {
  position: relative;
  display: grid;
  gap: 4px;
  width: 100%;
  padding: 0 0 6px;
  border: 1px solid var(--line);
  background: var(--surface);
  text-align: left;
  cursor: pointer;
  font-size: 12px;
  min-width: 0;
}
.pick:disabled {
  cursor: default;
  opacity: 0.5;
}
img,
.ph {
  display: block;
  width: 100%;
  aspect-ratio: 3 / 4;
  object-fit: cover;
  background: var(--image-bg);
}
.name {
  padding: 0 6px;
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.meta {
  padding: 0 6px;
  color: var(--ink-3);
  display: flex;
  gap: 4px;
  align-items: center;
}
.added {
  position: absolute;
  top: 6px;
  left: 6px;
  background: var(--ink);
  color: #fff;
  font-size: 11px;
  padding: 1px 6px;
}
</style>
