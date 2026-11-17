<script setup lang="ts">
import { t as translate } from "../i18n";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "../api/client";
import { useDelayedLoading } from "../lib/useDelayedLoading";
import type { Outfit } from "../api/types";
import { errorMessage } from "../lib/errors";
import { SEASON_LABELS, label } from "../lib/labels";

const PAGE = 48;
const route = useRoute();
const router = useRouter();
const outfits = ref<Outfit[]>([]);
const total = ref(0);
const loading = ref(true);
const showLoading = useDelayedLoading(loading);
const error = ref<(() => string) | null>(null);
const q = ref(typeof route.query.q === "string" ? route.query.q : "");
let requestId = 0;

const season = computed(() => (typeof route.query.season === "string" ? route.query.season : ""));
const tag = computed(() => (typeof route.query.tag === "string" ? route.query.tag : ""));

async function load(append = false) {
  const id = ++requestId;
  loading.value = true;
  error.value = null;
  try {
    const page = await api.outfits({
      q: (route.query.q as string) || undefined,
      season: season.value || undefined,
      tag: tag.value || undefined,
      limit: PAGE,
      offset: append ? outfits.value.length : 0,
    });
    if (id !== requestId) return;
    outfits.value = append ? [...outfits.value, ...page.items] : page.items;
    total.value = page.total;
  } catch (e) {
    if (id === requestId) error.value = () => errorMessage(e);
  } finally {
    if (id === requestId) loading.value = false;
  }
}

watch(() => route.fullPath, () => {
  if (route.name !== "outfits") return;
  const urlQ = typeof route.query.q === "string" ? route.query.q : "";
  if (q.value.trim() !== urlQ) q.value = urlQ;
  void load();
}, { immediate: true });

let timer: ReturnType<typeof setTimeout> | undefined;
watch(q, (v) => {
  clearTimeout(timer);
  if (v.trim() === (route.query.q ?? "")) return;
  timer = setTimeout(() => setQuery({ q: v.trim() || undefined }), 300);
});
onBeforeUnmount(() => clearTimeout(timer));

function setQuery(patch: Record<string, string | undefined>) {
  const next = { ...route.query, ...patch };
  for (const k of Object.keys(next)) if (!next[k]) delete next[k];
  void router.replace({ query: next });
}

function thumbs(o: Outfit): string[] {
  if (o.cover_image) return [o.cover_image.thumb_url];
  return o.items.map((e) => e.item.thumb_url).filter((u): u is string => !!u).slice(0, 4);
}
</script>

<template>
  <div class="page" :aria-busy="loading">
    <div class="page-head">
      <h1>{{ translate("穿搭组合") }} <span class="muted count">{{ loading && !outfits.length ? "" : translate("{0} 套", total) }}</span></h1>
      <RouterLink :to="{ name: 'outfit-new' }" class="btn">{{ translate("新建穿搭") }}</RouterLink>
    </div>
    <div class="filters">
      <input v-model="q" class="input" type="search" :placeholder='translate("按名称搜索")' :aria-label='translate("按名称搜索穿搭")' />
      <select class="input" :value="season" :aria-label='translate("季节")' @change="setQuery({ season: ($event.target as HTMLSelectElement).value || undefined })">
        <option value="">{{ translate("全部季节") }}</option>
        <option v-for="(t, k) in SEASON_LABELS" :key="k" :value="k">{{ t }}</option>
      </select>
      <span v-if="tag" class="chip">#{{ tag }} <button type="button" class="link-btn" :aria-label='translate("移除标签筛选")' @click="setQuery({ tag: undefined })">×</button></span>
    </div>
    <p class="load-feedback" role="status">{{ showLoading ? translate("正在加载…") : "" }}</p>
    <p v-if="error" class="error-banner" role="alert">{{ error?.() }}</p>
    <ul v-if="outfits.length" class="grid">
      <li v-for="o in outfits" :key="o.id">
        <RouterLink :to="{ name: 'outfit', params: { id: o.id } }" class="card" :data-testid="`outfit-card-${o.id}`">
          <div class="cover" :class="`n${thumbs(o).length}`">
            <img v-for="(u, i) in thumbs(o)" :key="i" :src="u" alt="" loading="lazy" />
            <span v-if="!thumbs(o).length" class="empty-cover">{{ o.items.length }} {{ translate("件") }}</span>
          </div>
          <div class="meta">
            <strong>{{ o.name }}</strong>
            <span class="muted">
              {{ o.items.length }} {{ translate("件") }}<template v-if="o.season"> · {{ label(SEASON_LABELS, o.season) }}</template><template v-if="o.occasion"> · {{ o.occasion }}</template>
            </span>
            <span v-if="o.rating" class="stars" :aria-label="translate('评分 {0}', o.rating)">{{ "★".repeat(o.rating) }}</span>
          </div>
        </RouterLink>
      </li>
    </ul>
    <div v-else-if="!loading && !error" class="empty-note">
      <p>{{ route.query.q || season || tag ? translate("没有符合条件的穿搭。") : translate("还没有穿搭组合。") }}</p>
      <RouterLink :to="{ name: 'outfit-new' }" class="btn ghost">{{ translate("新建第一套穿搭") }}</RouterLink>
    </div>
    <div v-if="outfits.length < total && !loading" class="more">
      <button type="button" class="btn ghost" @click="load(true)">{{ translate("加载更多（还有") }} {{ total - outfits.length }} {{ translate("套）") }}</button>
    </div>
  </div>
</template>

<style scoped>
.count {
  font-size: 14px;
  font-weight: 400;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 20px;
  align-items: center;
}
.filters .input {
  width: auto;
  flex: 0 1 240px;
}
.grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 28px 20px;
}
.card {
  display: grid;
  gap: 10px;
  text-decoration: none;
  min-width: 0;
}
.cover {
  aspect-ratio: 3 / 4;
  background: var(--image-bg);
  display: grid;
  gap: 2px;
  overflow: hidden;
}
.cover.n2,
.cover.n3,
.cover.n4 {
  grid-template-columns: 1fr 1fr;
}
.cover.n3 img:first-child {
  grid-row: span 2;
}
.cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  min-height: 0;
}
.empty-cover {
  display: grid;
  place-items: center;
  color: var(--ink-3);
}
.meta {
  display: grid;
  gap: 2px;
  font-size: 14px;
  overflow-wrap: anywhere;
}
.meta .muted {
  font-size: 12px;
}
.stars {
  color: #b58a12;
  font-size: 12px;
}
.more {
  display: flex;
  justify-content: center;
  margin-top: 32px;
}
@media (max-width: 720px) {
  .grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 20px 12px;
  }
}
</style>
