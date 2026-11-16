<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "../api/client";
import { useDelayedLoading } from "../lib/useDelayedLoading";
import type { Purchase } from "../api/types";
import { errorMessage } from "../lib/errors";
import { CHANNEL_LABELS, label, yen } from "../lib/labels";

const PAGE = 50;
const route = useRoute();
const router = useRouter();
const purchases = ref<Purchase[]>([]);
const total = ref(0);
const loading = ref(true);
const showLoading = useDelayedLoading(loading);
const error = ref<string | null>(null);
const q = ref("");
let requestId = 0;

const str = (v: unknown) => (typeof v === "string" ? v : "");

async function load(append = false) {
  const id = ++requestId;
  loading.value = true;
  error.value = null;
  try {
    const page = await api.purchases({
      q: str(route.query.q) || undefined,
      channel: str(route.query.channel) || undefined,
      date_from: str(route.query.date_from) || undefined,
      date_to: str(route.query.date_to) || undefined,
      limit: PAGE,
      offset: append ? purchases.value.length : 0,
    });
    if (id !== requestId) return;
    purchases.value = append ? [...purchases.value, ...page.items] : page.items;
    total.value = page.total;
  } catch (e) {
    if (id === requestId) error.value = errorMessage(e);
  } finally {
    if (id === requestId) loading.value = false;
  }
}

watch(() => route.fullPath, () => {
  if (route.name !== "purchases") return;
  if (q.value.trim() !== str(route.query.q)) q.value = str(route.query.q);
  void load();
}, { immediate: true });

let timer: ReturnType<typeof setTimeout> | undefined;
watch(q, (v) => {
  clearTimeout(timer);
  if (v.trim() === str(route.query.q)) return;
  timer = setTimeout(() => setQuery({ q: v.trim() }), 300);
});
onBeforeUnmount(() => clearTimeout(timer));

function setQuery(patch: Record<string, string>) {
  const next: Record<string, string> = {};
  for (const [k, v] of Object.entries({ ...route.query, ...patch })) if (typeof v === "string" && v) next[k] = v;
  void router.replace({ query: next });
}

function lineTotal(p: Purchase): number | null {
  if (p.total_amount !== null) return p.total_amount;
  if (!p.lines.some((l) => l.unit_price !== null)) return null;
  return p.lines.reduce((sum, l) => sum + (l.unit_price ?? 0) * l.quantity - (l.discount_amount ?? 0), 0);
}
const itemCount = (p: Purchase) => p.lines.reduce((n, l) => n + l.quantity, 0);
const unmatched = (p: Purchase) => p.lines.filter((l) => l.product_match !== "confirmed").length;
</script>

<template>
  <div class="page" :aria-busy="loading">
    <div class="page-head">
      <h1>购买记录 <span class="muted count">{{ loading && !purchases.length ? "" : `${total} 笔` }}</span></h1>
      <RouterLink :to="{ name: 'purchase-new' }" class="btn">记录一笔购买</RouterLink>
    </div>
    <div class="filters">
      <input v-model="q" class="input" type="search" placeholder="订单号、小票名称或编号、备注" aria-label="搜索购买记录" />
      <select class="input" :value="str(route.query.channel)" aria-label="渠道" @change="setQuery({ channel: ($event.target as HTMLSelectElement).value })">
        <option value="">全部渠道</option>
        <option v-for="(t, k) in CHANNEL_LABELS" :key="k" :value="k">{{ t }}</option>
      </select>
      <label class="date">从 <input type="date" class="input" :value="str(route.query.date_from)" @change="setQuery({ date_from: ($event.target as HTMLInputElement).value })" /></label>
      <label class="date">到 <input type="date" class="input" :value="str(route.query.date_to)" @change="setQuery({ date_to: ($event.target as HTMLInputElement).value })" /></label>
    </div>
    <p class="load-feedback" role="status">{{ showLoading ? "正在加载…" : "" }}</p>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <div v-if="purchases.length" class="table-wrap">
      <table class="data">
        <thead>
          <tr><th>日期</th><th>店铺 / 订单</th><th>渠道</th><th>内容</th><th class="num">金额</th></tr>
        </thead>
        <tbody>
          <tr v-for="p in purchases" :key="p.id" :data-testid="`purchase-row-${p.id}`">
            <td class="nowrap"><RouterLink :to="{ name: 'purchase', params: { id: p.id } }">{{ p.purchased_on }}</RouterLink></td>
            <td>
              <RouterLink :to="{ name: 'purchase', params: { id: p.id } }">{{ p.store_name ?? "未记录店铺" }}</RouterLink>
              <div v-if="p.order_no" class="muted mono">{{ p.order_no }}</div>
            </td>
            <td>{{ label(CHANNEL_LABELS, p.channel) }}</td>
            <td>
              {{ p.lines.length }} 条明细 · {{ itemCount(p) }} 件
              <span v-if="unmatched(p)" class="badge warn">{{ unmatched(p) }} 条未确认商品</span>
              <div class="muted names">{{ p.lines.map((l) => l.product?.name_ja ?? l.name_raw ?? "（未命名）").join("、") }}</div>
            </td>
            <td class="num">{{ yen(lineTotal(p), p.currency) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else-if="!loading && !error" class="empty-note">
      <p>没有购买记录。</p>
      <RouterLink :to="{ name: 'purchase-new' }" class="btn ghost">记录一笔购买</RouterLink>
    </div>
    <div v-if="purchases.length < total && !loading" class="more">
      <button type="button" class="btn ghost" @click="load(true)">加载更多（还有 {{ total - purchases.length }} 笔）</button>
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
  flex: 0 1 220px;
}
.date {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--ink-2);
}
.num {
  text-align: right !important;
  white-space: nowrap;
}
.nowrap {
  white-space: nowrap;
}
.mono {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
}
.names {
  font-size: 12px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.more {
  display: flex;
  justify-content: center;
  margin-top: 24px;
}
</style>
