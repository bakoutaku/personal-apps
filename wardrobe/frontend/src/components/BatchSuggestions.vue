<script setup lang="ts">
import { t as translate } from "../i18n";
// Phase 5C 批量：列出持有中、有标签 / 分类建议的衣物，勾选后一次生成待确认提议；
// 接受 / 拒绝在「待确认提议」中逐条或批量进行。只读预览，生成前不修改任何衣物。
import { computed, onBeforeUnmount, ref } from "vue";
import { api } from "../api/client";
import type { ItemSuggestions, ItemSummary } from "../api/types";
import { apiErrorText, errorMessage } from "../lib/errors";
import { notify } from "../lib/toast";

type Row = ItemSuggestions & { item: ItemSummary };
const PAGE = 50;
const MAX_BATCH = 100; // 与后端 POST /tag-suggestions/batch 的上限一致
const rows = ref<Row[]>([]);
const total = ref(0);
const loading = ref(false);
const error = ref<(() => string) | null>(null);
const busy = ref(false);
// 每件衣物的勾选：标签名列表与是否采用分类建议
const picks = ref<Record<number, { tags: string[]; category: boolean }>>({});
const results = ref<Record<number, { ok: boolean; error?: { code: string; message: string }; count?: number }>>({});

// 读取与生成各有自己的请求代次，互不使对方失效；两者在界面与函数中互斥（生成中不读取，读取中不生成）
let loadReq = 0;
let submitReq = 0;
onBeforeUnmount(() => {
  loadReq++;
  submitReq++;
});

async function load(append = false) {
  if (busy.value) return;
  const mine = ++loadReq;
  loading.value = true;
  error.value = null;
  try {
    const page = await api.batchTagSuggestions({ limit: PAGE, offset: append ? rows.value.length : 0 });
    if (mine !== loadReq) return;
    rows.value = append ? [...rows.value, ...page.items] : page.items;
    total.value = page.total;
    if (!append) {
      picks.value = {};
      results.value = {};
    }
    for (const r of page.items) picks.value[r.item_id] = { tags: r.tags.map((t) => t.name), category: r.category !== null };
  } catch (e) {
    if (mine === loadReq) error.value = () => errorMessage(e);
  } finally {
    if (mine === loadReq) loading.value = false;
  }
}
void load();

const selected = computed(() =>
  rows.value.filter((r) => {
    const p = picks.value[r.item_id];
    return p && !results.value[r.item_id] && (p.tags.length || (p.category && r.category));
  }),
);

const overLimit = computed(() => selected.value.length > MAX_BATCH);

// 超过上限时只保留前 MAX_BATCH 件的勾选，其余取消
function keepFirst() {
  for (const r of selected.value.slice(MAX_BATCH)) picks.value[r.item_id] = { tags: [], category: false };
}

function setAll(on: boolean) {
  for (const r of rows.value) {
    if (results.value[r.item_id]) continue;
    picks.value[r.item_id] = { tags: on ? r.tags.map((t) => t.name) : [], category: on && r.category !== null };
  }
}

async function submit() {
  if (!selected.value.length || overLimit.value || loading.value || busy.value) return;
  const mine = ++submitReq;
  busy.value = true;
  error.value = null;
  try {
    const body = selected.value.map((r) => ({
      item_id: r.item_id,
      version: r.item_version,
      tags: picks.value[r.item_id]!.tags,
      category_id: picks.value[r.item_id]!.category && r.category ? r.category.category_id : null,
    }));
    const out = await api.createBatchTagSuggestions(body);
    if (mine !== submitReq) return;
    for (const r of out.results) results.value[r.item_id] = { ok: r.ok, count: r.proposals?.length, error: r.error ?? undefined };
    notify(translate("已为 {0} 件衣物生成待确认提议{1}", out.succeeded, out.failed ? translate("，{0} 件失败（原因见列表）", out.failed) : ""), { kind: out.failed ? "error" : "info" });
  } catch (e) {
    if (mine === submitReq) error.value = () => errorMessage(e);
  } finally {
    if (mine === submitReq) busy.value = false;
  }
}
</script>

<template>
  <section class="batch" :aria-label='translate("批量标签与分类建议")'>
    <p class="muted small">
      {{ translate("根据同一商品的其他衣物、同类的相似衣物和商品名称按固定规则给出（不是图像识别）。勾选后生成的是待确认提议，标签只追加、不删除已有标签； 请到「待确认提议」中逐条或批量接受 / 拒绝。") }}
    </p>
    <div class="actions bar">
      <span class="muted small">{{ loading ? translate("正在计算…") : translate("{0} 件衣物有建议", total) }}</span>
      <button type="button" class="link-btn" :disabled="busy" @click="setAll(true)">{{ translate("全选") }}</button>
      <button type="button" class="link-btn" :disabled="busy" @click="setAll(false)">{{ translate("全不选") }}</button>
      <button type="button" class="btn small" :disabled="busy || loading || overLimit || !selected.length" @click="submit">
        {{ busy ? translate("生成中…") : translate("为选中的 {0} 件生成提议", selected.length) }}
      </button>
    </div>
    <p v-if="overLimit" class="error-banner" role="alert" data-testid="batch-limit">
      {{ translate("一次最多为") }} {{ MAX_BATCH }} {{ translate("件衣物生成提议，当前选中") }} {{ selected.length }} {{ translate("件。") }}
      <button type="button" class="link-btn" :disabled="busy" @click="keepFirst">{{ translate("只保留前") }} {{ MAX_BATCH }} {{ translate("件") }}</button>
    </p>
    <p v-if="error" class="error-banner" role="alert">{{ error?.() }} <button type="button" class="link-btn" :disabled="busy || loading" @click="load()">{{ translate("重试") }}</button></p>
    <p v-if="!loading && !error && !rows.length" class="empty-note" data-testid="batch-empty">{{ translate("没有可建议的衣物。") }}</p>
    <ul class="rows">
      <li v-for="r in rows" :key="r.item_id" :data-testid="`batch-${r.item_id}`">
        <div class="who">
          <img v-if="r.item.thumb_url" :src="r.item.thumb_url" alt="" />
          <span v-else class="ph" />
          <RouterLink :to="{ name: 'item', params: { id: r.item_id } }">{{ r.item.name }}</RouterLink>
          <span v-if="results[r.item_id]" class="badge" :class="{ warn: !results[r.item_id]!.ok }" role="status">{{ results[r.item_id]!.ok ? translate("已生成 {0} 条提议", results[r.item_id]!.count ?? 0) : translate("失败：{0}", results[r.item_id]!.error ? apiErrorText(results[r.item_id]!.error!.code, results[r.item_id]!.error!.message) : "") }}</span>
        </div>
        <div class="opts">
          <label v-for="t in r.tags" :key="t.name" class="opt" :title="t.reasons.map((x) => x.label).join('；')">
            <input v-model="picks[r.item_id]!.tags" type="checkbox" :value="t.name" :disabled="busy || !!results[r.item_id]" />
            #{{ t.name }}
          </label>
          <label v-if="r.category" class="opt" :title="r.category.reasons.map((x) => x.label).join('；')">
            <input v-model="picks[r.item_id]!.category" type="checkbox" :disabled="busy || !!results[r.item_id]" />
            {{ translate("分类：") }}{{ r.category.path.join(" / ") }}
          </label>
        </div>
      </li>
    </ul>
    <div v-if="rows.length < total && !loading" class="more">
      <button type="button" class="btn ghost" :disabled="busy" @click="load(true)">{{ translate("加载更多（还有") }} {{ total - rows.length }} {{ translate("件）") }}</button>
    </div>
  </section>
</template>

<style scoped>
.small {
  font-size: 13px;
}
.bar {
  margin: 12px 0;
}
.rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
}
.rows > li {
  border-bottom: 1px solid var(--line);
  padding-bottom: 10px;
  display: grid;
  gap: 6px;
}
.who {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  overflow-wrap: anywhere;
}
.who img,
.ph {
  width: 30px;
  aspect-ratio: 3 / 4;
  object-fit: cover;
  background: var(--image-bg);
}
.opts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  padding-left: 40px;
}
.opt {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 14px;
}
.more {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}
</style>
