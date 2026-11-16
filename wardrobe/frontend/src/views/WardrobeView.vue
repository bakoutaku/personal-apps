<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, api } from "../api/client";
import { useDelayedLoading } from "../lib/useDelayedLoading";
import type { Brand, CategoryNode, Facets, ItemSummary } from "../api/types";
import FilterPanel from "../components/FilterPanel.vue";
import ItemCard from "../components/ItemCard.vue";
import QuickGroups from "../components/QuickGroups.vue";
import { type Filters, LIST_KEYS, activeCount, fromQuery, toApiQuery, toQuery } from "../lib/filters";
import { COLOR_FAMILIES, FIBER_LABELS, SORT_OPTIONS, STATUS_LABELS, label } from "../lib/labels";
import { inertOutside, tabbable } from "../lib/modal";

const PAGE_SIZE = 48;
const route = useRoute();
const router = useRouter();

// 保留衣橱自己的查询条件，详情路由的 query 不得重置缓存或触发搜索。
const listQuery = ref(route.query);
const filters = computed<Filters>(() => fromQuery(listQuery.value));
const items = ref<ItemSummary[]>([]);
const total = ref(0);
const facets = ref<Facets | null>(null);
const categories = ref<CategoryNode[]>([]);
const brands = ref<Brand[]>([]);
const loading = ref(true);
const showLoading = useDelayedLoading(loading);
const loadingMore = ref(false);
const error = ref<string | null>(null);
const paginationError = ref<string | null>(null);
const dictionaryError = ref<string | null>(null);
const drawerOpen = ref(false);
const search = ref(filters.value.q);
const sidebar = ref<HTMLElement | null>(null);
const filterToggle = ref<HTMLButtonElement | null>(null);
let previousOverflow: string | null = null;
let alive = true;
let releaseInert: (() => void) | undefined;
// 与样式中的抽屉断点一致；变宽后抽屉变回侧栏，必须解除模态状态。
let drawerMedia: MediaQueryList | undefined;

function closeOnWide(event: MediaQueryListEvent) {
  if (!event.matches) drawerOpen.value = false;
}

function releaseModal() {
  releaseInert?.();
  releaseInert = undefined;
  drawerMedia?.removeEventListener("change", closeOnWide);
  drawerMedia = undefined;
  document.removeEventListener("keydown", drawerKeydown, true);
  document.removeEventListener("focusin", guardFocus, true);
  restoreScroll();
}

function guardFocus(event: FocusEvent) {
  if (drawerOpen.value && sidebar.value && !sidebar.value.contains(event.target as Node)) {
    tabbable(sidebar.value)[0]?.focus();
  }
}

function restoreScroll() {
  if (previousOverflow !== null) document.body.style.overflow = previousOverflow;
  previousOverflow = null;
}

watch(drawerOpen, async (open) => {
  if (open) {
    previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    await nextTick();
    if (alive && drawerOpen.value && sidebar.value) {
      releaseInert?.();
      releaseInert = inertOutside(sidebar.value);
      drawerMedia = window.matchMedia?.("(max-width: 900px)");
      drawerMedia?.addEventListener("change", closeOnWide);
      document.addEventListener("keydown", drawerKeydown, true);
      document.addEventListener("focusin", guardFocus, true);
      tabbable(sidebar.value)[0]?.focus();
    }
  } else {
    releaseModal();
    await nextTick();
    if (alive) filterToggle.value?.focus();
  }
});

function drawerKeydown(event: KeyboardEvent) {
  if (!drawerOpen.value) return;
  if (event.key === "Escape") {
    event.preventDefault();
    drawerOpen.value = false;
  } else if (event.key === "Tab") {
    const controls = sidebar.value ? tabbable(sidebar.value) : [];
    if (!controls.length) return;
    event.preventDefault();
    const index = controls.indexOf(document.activeElement as HTMLElement);
    const next = index < 0 ? 0 : (index + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
    controls[next]?.focus();
  }
}
let requestId = 0;
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let queryKey = "";
const listCache = new Map<string, { items: ItemSummary[]; total: number; facets: Facets | null }>();

function rememberList() {
  listCache.delete(queryKey);
  listCache.set(queryKey, { items: items.value, total: total.value, facets: facets.value });
  // 缓存只服务当前会话的浏览恢复，避免筛选组合无限占用内存。
  if (listCache.size > 10) listCache.delete(listCache.keys().next().value!);
}

function cancelSearch() {
  clearTimeout(searchTimer);
  searchTimer = undefined;
}

function update(patch: Partial<Filters>, replace = false) {
  // 尚未生效的搜索词并入本次筛选导航，之后不会再用 replace 改写这条历史。
  if (searchTimer !== undefined) {
    cancelSearch();
    if (!("q" in patch)) patch = { ...patch, q: search.value.trim() };
  }
  const next = toQuery({ ...filters.value, ...patch });
  return replace ? router.replace({ query: next }) : router.push({ query: next });
}

async function load(restoreCount = 0) {
  const id = ++requestId;
  loadingMore.value = false;
  const query = toApiQuery(filters.value);
  loading.value = true;
  error.value = null;
  paginationError.value = null;
  try {
    const target = Math.max(PAGE_SIZE, restoreCount);
    const firstLimit = Math.min(200, target);
    const [page, f] = await Promise.all([
      api.items({ ...query, sort: filters.value.sort, limit: firstLimit, offset: 0 }),
      api.facets(query),
    ]);
    if (id !== requestId) return; // 只采用最新一次请求的结果
    let refreshed = page.items;
    let refreshedTotal = page.total;
    // 后端单次上限 200；恢复更多已加载项时分段重取，完成前保留缓存 DOM 和滚动位置。
    if (firstLimit < target && page.items.length === firstLimit) {
      while (refreshed.length < Math.min(target, refreshedTotal)) {
        const limit = Math.min(200, target - refreshed.length);
        const next = await api.items({ ...query, sort: filters.value.sort, limit, offset: refreshed.length });
        if (id !== requestId) return;
        refreshed = [...refreshed, ...next.items];
        refreshedTotal = next.total;
        if (next.items.length < limit) break;
      }
    }
    items.value = refreshed;
    total.value = refreshedTotal;
    facets.value = f;
    rememberList();
  } catch (e) {
    if (id !== requestId) return;
    error.value = e instanceof ApiError ? e.message : String(e);
    if (!restoreCount) {
      items.value = [];
      total.value = 0;
    }
  } finally {
    if (id === requestId) loading.value = false;
  }
}

async function loadMore() {
  if (loading.value || loadingMore.value || !hasMore.value) return;
  const id = requestId;
  loadingMore.value = true;
  paginationError.value = null;
  try {
    const page = await api.items({
      ...toApiQuery(filters.value),
      sort: filters.value.sort,
      limit: PAGE_SIZE,
      offset: items.value.length,
    });
    if (id === requestId) {
      items.value = [...items.value, ...page.items];
      total.value = page.total;
      rememberList();
    }
  } catch (e) {
    if (id === requestId) paginationError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    if (id === requestId) loadingMore.value = false;
  }
}

watch(() => route.fullPath, () => {
  if (route.name !== "wardrobe") return;
  listQuery.value = route.query;
  // 待执行的搜索属于导航前的页面；Back/Forward 等外部导航取消它，输入框跟随新 URL。
  if (searchTimer !== undefined) {
    cancelSearch();
    search.value = filters.value.q;
  }
  const key = JSON.stringify(toQuery(filters.value));
  if (key !== queryKey) {
    queryKey = key;
    const cached = listCache.get(key);
    items.value = cached?.items ?? [];
    total.value = cached?.total ?? 0;
    facets.value = cached?.facets ?? null;
    void load(cached?.items.length ?? 0);
  }
}, { immediate: true });

let deactivatedOnce = false;
onActivated(() => {
  // 在其他页面可能新增或修改了品牌、分类（Phase 4 编辑页、设置页）；初次挂载已由 onMounted 读取
  if (deactivatedOnce) void loadDictionaries();
  // 离开时已取消搜索防抖；输入框回到与 URL 一致的搜索词，不显示未生效的文字。
  if (search.value.trim() !== filters.value.q) search.value = filters.value.q;
  // 初次挂载/筛选改变已由 watch 加载；从详情返回则刷新完整的已加载范围。
  if (!loading.value) void load(items.value.length);
});
onDeactivated(() => {
  deactivatedOnce = true;
  requestId++;
  loading.value = false;
  loadingMore.value = false;
  cancelSearch();
  drawerOpen.value = false;
  releaseModal();
});
watch(
  () => filters.value.q,
  (q) => {
    if (q !== search.value.trim()) search.value = q;
  },
);
watch(search, (q) => {
  // 与 URL 一致（包括由 URL 回填）时不需要导航。
  cancelSearch();
  if (q.trim() === filters.value.q) return;
  searchTimer = setTimeout(() => {
    searchTimer = undefined;
    if (route.name === "wardrobe" && q.trim() !== filters.value.q) update({ q: q.trim() }, true);
  }, 300);
});

async function loadDictionaries() {
  try {
    const [c, b] = await Promise.all([api.categories(), api.brands()]);
    categories.value = c.items;
    brands.value = b.items;
    dictionaryError.value = null;
  } catch (e) {
    dictionaryError.value = e instanceof ApiError ? e.message : String(e);
  }
}
onMounted(loadDictionaries);
onBeforeUnmount(() => {
  alive = false;
  releaseModal();
  requestId++;
  cancelSearch();
});

function findCategory(slug: string, nodes: CategoryNode[]): CategoryNode | null {
  for (const n of nodes) {
    if (n.slug === slug) return n;
    const found = findCategory(slug, n.children);
    if (found) return found;
  }
  return null;
}

const chips = computed(() => {
  const f = filters.value;
  const out: { key: string; text: string; patch: Partial<Filters> }[] = [];
  if (f.q) out.push({ key: "q", text: `“${f.q}”`, patch: { q: "" } });
  if (f.category)
    out.push({ key: "cat", text: findCategory(f.category, categories.value)?.name_zh ?? f.category, patch: { category: null } });
  const names: Record<(typeof LIST_KEYS)[number], (v: string) => string> = {
    brand: (v) => brands.value.find((b) => b.slug === v)?.name ?? v,
    color: (v) => COLOR_FAMILIES.find((c) => c.key === v)?.label ?? v,
    size: (v) => `尺码 ${v}`,
    tag: (v) => `#${v}`,
    material: (v) => label(FIBER_LABELS, v),
  };
  for (const k of LIST_KEYS)
    for (const v of f[k]) out.push({ key: `${k}:${v}`, text: names[k](v), patch: { [k]: f[k].filter((x) => x !== v) } });
  if (f.status !== "owned")
    out.push({ key: "status", text: f.status === "all" ? "全部状态" : label(STATUS_LABELS, f.status), patch: { status: "owned" } });
  return out;
});

const nActive = computed(() => activeCount(filters.value));
const hasMore = computed(() => items.value.length < total.value);

function clearAll() {
  search.value = "";
  router.push({ query: filters.value.sort === "-created_at" ? {} : { sort: filters.value.sort } });
}
</script>

<template>
  <div class="layout">
    <aside id="wardrobe-filters" ref="sidebar" class="sidebar" :class="{ open: drawerOpen }" :role="drawerOpen ? 'dialog' : undefined" :aria-modal="drawerOpen || undefined" aria-label="筛选">
      <div class="drawer-head">
        <h2>筛选</h2>
        <button type="button" class="link-btn" @click="drawerOpen = false">完成</button>
      </div>
      <FilterPanel :filters="filters" :facets="facets" :categories="categories" :brands="brands" @change="update" />
    </aside>
    <div v-if="drawerOpen" class="scrim" @click="drawerOpen = false" />

    <section class="content" :aria-busy="loading">
      <div class="toolbar">
        <div class="title-row">
          <h1>我的衣橱</h1>
          <span class="count" aria-live="polite">{{ showLoading ? "加载中…" : loading && !items.length ? "" : `${total} 件` }}</span>
          <RouterLink :to="{ name: 'item-new' }" class="btn small add">添加衣物</RouterLink>
        </div>
        <div class="controls">
          <label class="search">
            <span class="visually-hidden">搜索</span>
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>
            <input v-model="search" type="search" placeholder="搜索名称、编号、颜色、材质、标签…" autocomplete="off" />
          </label>
          <button ref="filterToggle" type="button" class="btn ghost filter-toggle" aria-controls="wardrobe-filters" :aria-expanded="drawerOpen" @click="drawerOpen = true">
            筛选<span v-if="nActive" class="badge">{{ nActive }}</span>
          </button>
          <label class="sort">
            <span class="visually-hidden">排序</span>
            <select :value="filters.sort" @change="update({ sort: ($event.target as HTMLSelectElement).value })">
              <option v-for="o in SORT_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </label>
        </div>
        <QuickGroups :groups="facets?.groups" :selected="filters.group" @select="(key) => update({ group: key })" />
        <div v-if="chips.length" class="chips">
          <button v-for="c in chips" :key="c.key" type="button" class="chip removable" @click="update(c.patch)">
            {{ c.text }} <span aria-hidden="true">×</span><span class="visually-hidden">移除</span>
          </button>
          <button type="button" class="link-btn" @click="clearAll">清除全部</button>
        </div>
      </div>

      <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
      <p v-if="dictionaryError" class="error-banner" role="alert">{{ dictionaryError }}</p>
      <p v-if="paginationError" class="error-banner" role="alert">{{ paginationError }}</p>

      <ul v-if="showLoading && !items.length" class="grid" aria-hidden="true">
        <li v-for="n in 10" :key="n"><div class="skeleton frame-skel" /></li>
      </ul>
      <ul v-else-if="items.length" class="grid" :class="{ dim: showLoading }">
        <li v-for="item in items" :key="item.id"><ItemCard :item="item" /></li>
      </ul>
      <div v-else-if="!loading && !error" class="empty">
        <template v-if="nActive">
          <p>没有符合条件的衣物。</p>
          <button type="button" class="btn ghost" @click="clearAll">清除筛选条件</button>
        </template>
        <template v-else>
          <p>衣橱里还没有衣物。</p>
          <p class="muted">
            可以<RouterLink :to="{ name: 'item-new' }">添加衣物</RouterLink>，或在<RouterLink :to="{ name: 'imports' }">导入中心</RouterLink>批量导入 JSON。
          </p>
        </template>
      </div>

      <div v-if="hasMore && !loading" class="more">
        <button type="button" class="btn ghost" :disabled="loadingMore" @click="loadMore">
          {{ loadingMore ? "加载中…" : `加载更多（还有 ${total - items.length} 件）` }}
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.layout {
  max-width: 1600px;
  margin: 0 auto;
  padding: 0 24px 64px;
  display: grid;
  grid-template-columns: var(--sidebar-w) minmax(0, 1fr);
  gap: 40px;
}
.sidebar {
  position: sticky;
  top: var(--header-h);
  align-self: start;
  max-height: calc(100vh - var(--header-h));
  overflow-y: auto;
  padding: 20px 4px 24px 0;
  scrollbar-width: thin;
}
.drawer-head {
  display: none;
}
.content {
  min-width: 0;
  padding-top: 24px;
}
.toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 14px;
  margin-bottom: 24px;
}
.title-row {
  display: flex;
  align-items: baseline;
  gap: 14px;
}
h1 {
  font-size: 26px;
}
.add {
  margin-left: auto;
  align-self: center;
}
.count {
  color: var(--ink-3);
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}
.controls {
  display: flex;
  gap: 10px;
  align-items: center;
}
.search {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  height: 44px;
  padding: 0 14px;
  border: 1px solid var(--line-strong);
  background: var(--surface);
  border-radius: var(--radius);
}
.search:focus-within {
  border-color: var(--ink);
}
.search svg {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: var(--ink-3);
  stroke-width: 2;
  flex: none;
}
.search input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  font-size: 15px;
}
.sort select {
  height: 44px;
  padding: 0 34px 0 12px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  background: var(--surface)
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' fill='none' stroke='%231a1a1a' stroke-width='1.5'/%3E%3C/svg%3E")
    no-repeat right 12px center / 10px;
  appearance: none;
  cursor: pointer;
  font-size: 14px;
}
.filter-toggle {
  display: none;
  height: 44px;
}
.badge {
  display: inline-grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  border-radius: 9px;
  background: var(--ink);
  color: #fff;
  font-size: 11px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.chip.removable {
  border: 0;
  cursor: pointer;
  font-size: 13px;
  padding: 4px 12px;
  color: var(--ink);
}
.chip.removable:hover {
  background: #e6e5e0;
}
.grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 36px 20px;
  transition: opacity 0.15s;
}
.grid.dim {
  opacity: 0.55;
}
.frame-skel {
  aspect-ratio: 3 / 4;
}
.empty {
  padding: 72px 0;
  display: grid;
  gap: 12px;
  justify-items: start;
}
.empty p {
  margin: 0;
}
code {
  background: var(--chip);
  padding: 1px 6px;
  font-size: 13px;
}
.more {
  display: flex;
  justify-content: center;
  margin-top: 40px;
}
.scrim {
  display: none;
}

@media (min-width: 1500px) {
  .grid {
    grid-template-columns: repeat(5, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .layout {
    grid-template-columns: minmax(0, 1fr);
    padding: 0 16px 48px;
    gap: 0;
  }
  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 40;
    width: min(86vw, 340px);
    max-height: none;
    padding: 16px 20px 32px;
    background: var(--surface);
    transform: translateX(-102%);
    /* 关闭时 visibility:hidden，抽屉里的控件不会被 Tab 键选中（等滑出动画结束后再隐藏） */
    visibility: hidden;
    transition:
      transform 0.22s ease,
      visibility 0s linear 0.22s;
    box-shadow: 0 0 40px rgba(0, 0, 0, 0.18);
  }
  .sidebar.open {
    transform: none;
    visibility: visible;
    transition: transform 0.22s ease;
  }
  .drawer-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--line);
  }
  .drawer-head h2 {
    font-size: 18px;
  }
  .scrim {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 30;
    background: rgba(0, 0, 0, 0.32);
  }
  .filter-toggle {
    display: inline-flex;
  }
  .controls {
    flex-wrap: wrap;
  }
  .search {
    flex-basis: 100%;
  }
  .sort {
    flex: 1;
  }
  .sort select {
    width: 100%;
  }
  .grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 28px 12px;
  }
  h1 {
    font-size: 22px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .sidebar {
    transition: none;
  }
}
</style>
