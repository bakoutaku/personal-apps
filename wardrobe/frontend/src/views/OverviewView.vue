<script setup lang="ts">
// 衣橱总览：持有中的全部衣物一张表列完（不分页），名称、颜色、尺码、材质、分类、适穿季节都写成纯文本，
// 方便浏览，也方便浏览器里的 AI 插件直接读取。缺失的信息写「未记录」，不留空白。
import { computed, onMounted, ref } from "vue";
import { api } from "../api/client";
import type { OverviewRow } from "../api/types";
import ColorDot from "../components/ColorDot.vue";
import { errorMessage } from "../lib/errors";
import { FIBER_LABELS, PART_LABELS, label } from "../lib/labels";
import { useDelayedLoading } from "../lib/useDelayedLoading";

const MISSING = "未记录";
const rows = ref<OverviewRow[]>([]);
const loading = ref(true);
const showLoading = useDelayedLoading(loading);
const error = ref<string | null>(null);

onMounted(async () => {
  try {
    rows.value = (await api.overview()).items;
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    loading.value = false;
  }
});

function materialText(r: OverviewRow): string {
  if (!r.materials.length) return r.material_text ?? MISSING;
  const parts = new Map<string, string[]>();
  for (const m of r.materials) {
    const fiber = m.fiber === "other" && m.fiber_raw ? m.fiber_raw : label(FIBER_LABELS, m.fiber);
    parts.set(m.part, [...(parts.get(m.part) ?? []), m.percent === null ? fiber : `${fiber} ${m.percent}%`]);
  }
  if (parts.size === 1 && parts.has("body")) return parts.get("body")!.join("、");
  return [...parts].map(([part, fibers]) => `${label(PART_LABELS, part)}：${fibers.join("、")}`).join("；");
}

function colorText(r: OverviewRow): string {
  const { name, code } = r.color;
  if (!name && !code) return MISSING;
  return name && code && name !== code ? `${name}（${code}）` : (name ?? code)!;
}

const withMaterial = computed(() => rows.value.filter((r) => r.materials.length || r.material_text).length);
const withSeason = computed(() => rows.value.filter((r) => r.seasons.length).length);
</script>

<template>
  <div class="page" :aria-busy="loading">
    <div class="page-head">
      <h1>衣橱总览 <span class="muted count">{{ loading ? "" : `${rows.length} 件` }}</span></h1>
    </div>
    <p class="load-feedback" role="status">{{ showLoading ? "正在加载…" : "" }}</p>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <template v-if="rows.length">
      <p class="muted note" data-testid="overview-coverage">
        持有中的全部衣物，按分类排列。材质已记录 {{ withMaterial }} / {{ rows.length }} 件，适穿季节已记录
        {{ withSeason }} / {{ rows.length }} 件；没有的信息显示为「{{ MISSING }}」。
      </p>
      <div class="table-wrap">
        <table class="data overview">
          <caption class="sr-only">衣橱总览：持有中的全部衣物，共 {{ rows.length }} 件</caption>
          <thead>
            <tr>
              <th scope="col">编号</th>
              <th scope="col">名称</th>
              <th scope="col">品牌</th>
              <th scope="col">商品编号</th>
              <th scope="col">颜色</th>
              <th scope="col">尺码</th>
              <th scope="col">材质</th>
              <th scope="col">分类</th>
              <th scope="col">适穿季节</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.id" :data-testid="`overview-row-${r.id}`">
              <td class="mono">{{ r.id }}</td>
              <td class="name">
                <RouterLink :to="{ name: 'item', params: { id: r.id } }">{{ r.name_ja ?? r.name_zh ?? r.name_en ?? "（未命名）" }}</RouterLink>
                <div v-if="r.name_zh && r.name_ja" class="muted">{{ r.name_zh }}</div>
              </td>
              <td class="nowrap">{{ r.brand ?? MISSING }}</td>
              <td class="mono">{{ r.item_no ?? MISSING }}</td>
              <td class="nowrap">
                <span class="inline">
                  <ColorDot :hex="r.color.hex" :swatch="r.color.swatch" :family="r.color.family" />
                  {{ colorText(r) }}
                </span>
              </td>
              <td class="nowrap">{{ r.size.label ?? MISSING }}</td>
              <td class="material">{{ materialText(r) }}</td>
              <td class="category">{{ r.category ? r.category.path.join(" › ") : MISSING }}</td>
              <td class="nowrap">{{ r.seasons.length ? r.seasons.join("、") : MISSING }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
    <div v-else-if="!loading && !error" class="empty-note">
      <p>衣橱里还没有持有中的衣物。</p>
      <RouterLink :to="{ name: 'item-new' }" class="btn ghost">添加衣物</RouterLink>
    </div>
  </div>
</template>

<style scoped>
.count {
  font-size: 14px;
  font-weight: 400;
}
.note {
  margin: 0 0 14px;
  font-size: 13px;
}
.inline {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.nowrap {
  white-space: nowrap;
}
.overview td {
  vertical-align: top;
}
.name {
  min-width: 12em;
}
.category {
  min-width: 9em;
}
.material {
  white-space: pre-line; /* 官网原文有多行（多种可能组成、按颜色分列）时保留换行 */
  min-width: 14em;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
