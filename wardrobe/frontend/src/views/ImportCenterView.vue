<script setup lang="ts">
import { t as translate } from "../i18n";
// 导入中心：粘贴/选择 JSON → 预览（数据不变）→ 在批次页提交或丢弃；另有导入记录、待确认提议、变更记录。
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "../api/client";
import type { ChangeEntry, ImportJob, Proposal } from "../api/types";
import BatchSuggestions from "../components/BatchSuggestions.vue";
import ProposalList from "../components/ProposalList.vue";
import { errorMessage, fieldDetails } from "../lib/errors";
import { formatTime, formatValue } from "../lib/format";
import { ENTITY_LABELS, IMPORT_STATUS_LABELS, OP_LABELS, PROPOSAL_STATUS_LABELS, label } from "../lib/labels";

const TABS = [
  { key: "new", label: translate("新导入") },
  { key: "jobs", label: translate("导入记录") },
  { key: "suggest", label: translate("整理建议") },
  { key: "proposals", label: translate("待确认提议") },
  { key: "changes", label: translate("变更记录") },
] as const;
type TabKey = (typeof TABS)[number]["key"];

const route = useRoute();
const router = useRouter();
const tab = computed<TabKey>(() => (TABS.some((t) => t.key === route.query.tab) ? (route.query.tab as TabKey) : "new"));
const setTab = (key: TabKey) => router.replace({ query: key === "new" ? {} : { tab: key } });

// ── 新导入 ──
const EXAMPLE = {
  format: "wardrobe.import/v1",
  source_label: translate("示例：手动整理的小票"),
  products: [{ ref: "p-1", brand: "uniqlo", name_ja: "サンプルT", colors: [{ color_code: "09", name_ja: "BLACK", hex: "#1A1A1A", is_default: true }] }],
  purchases: [
    {
      ref: "o-1", purchased_on: "2025-11-03", store_name: translate("示例店"), create_items: true,
      lines: [{ ref: "l-1", product_ref: "p-1", color_code: "09", size_label: "M", quantity: 1, unit_price: 1990 }],
    },
  ],
};
const text = ref("");
const parseError = ref<string | null>(null);
const previewError = ref<(() => string) | null>(null);
const previewDetails = ref<{ loc: string; message: string }[]>([]);
const previewing = ref(false);

async function readFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (file) text.value = await file.text();
}

async function preview() {
  parseError.value = null;
  previewError.value = null;
  previewDetails.value = [];
  let payload: unknown;
  try {
    payload = JSON.parse(text.value);
  } catch (e) {
    parseError.value = translate("不是有效的 JSON：{0}", e instanceof Error ? e.message : String(e));
    return;
  }
  previewing.value = true;
  try {
    const job = await api.previewImport(payload);
    await router.push({ name: "import", params: { id: job.job_id } });
  } catch (e) {
    previewError.value = () => errorMessage(e);
    previewDetails.value = fieldDetails(e).map((d) => ({ loc: d.loc.join(" › "), message: d.message }));
  } finally {
    previewing.value = false;
  }
}

// ── 导入记录 ──
const jobs = ref<ImportJob[]>([]);
const jobsTotal = ref(0);
// ── 提议 ──
const proposals = ref<Proposal[]>([]);
const proposalsTotal = ref(0);
const proposalStatus = ref("pending");
// ── 变更记录 ──
const changes = ref<ChangeEntry[]>([]);
const changesTotal = ref(0);
const changeFilter = ref({ entity: "", actor: "", op: "" });

const loading = ref(false);
const error = ref<(() => string) | null>(null);
let requestId = 0;

async function load(append = false) {
  const id = ++requestId;
  const which = tab.value;
  if (which === "new" || which === "suggest") return; // 「整理建议」由 BatchSuggestions 自己读取
  loading.value = true;
  error.value = null;
  try {
    if (which === "jobs") {
      const page = await api.imports({ limit: 50, offset: append ? jobs.value.length : 0 });
      if (id !== requestId) return;
      jobs.value = append ? [...jobs.value, ...page.items] : page.items;
      jobsTotal.value = page.total;
    } else if (which === "proposals") {
      const page = await api.proposals({ status: proposalStatus.value, limit: 100, offset: append ? proposals.value.length : 0 });
      if (id !== requestId) return;
      proposals.value = append ? [...proposals.value, ...page.items] : page.items;
      proposalsTotal.value = page.total;
    } else {
      const f = changeFilter.value;
      const page = await api.changes({ entity: f.entity || undefined, actor: f.actor.trim() || undefined, op: f.op || undefined, limit: 50, offset: append ? changes.value.length : 0 });
      if (id !== requestId) return;
      changes.value = append ? [...changes.value, ...page.items] : page.items;
      changesTotal.value = page.total;
    }
  } catch (e) {
    if (id === requestId) error.value = () => errorMessage(e);
  } finally {
    if (id === requestId) loading.value = false;
  }
}
watch(tab, () => load(), { immediate: true });
watch(proposalStatus, () => load());

function changeLink(c: ChangeEntry) {
  if (c.op === "delete") return null;
  const names: Record<string, string> = { wardrobe_item: "item", product: "product", purchase: "purchase", outfit: "outfit" };
  return names[c.entity] ? { name: names[c.entity]!, params: { id: c.entity_id } } : null;
}

function summarize(v: unknown): string {
  const s = formatValue(v);
  return s.length > 160 ? `${s.slice(0, 160)}…` : s;
}

function counts(job: ImportJob): string {
  const s = job.summary as Record<string, number>;
  const parts = (["create", "update", "propose", "skip", "error"] as const)
    .filter((k) => s[k])
    .map((k) => `${{ create: translate("新建"), update: translate("更新"), propose: translate("提议"), skip: translate("跳过"), error: translate("错误") }[k]} ${s[k]}`);
  return parts.join(" · ") || translate("无内容");
}
</script>

<template>
  <div class="page">
    <div class="page-head"><h1>{{ translate("导入中心") }}</h1></div>
    <div class="tabs" role="tablist">
      <button v-for="t in TABS" :key="t.key" type="button" role="tab" :aria-selected="tab === t.key" @click="setTab(t.key)">{{ t.label }}</button>
    </div>

    <section v-if="tab === 'new'" class="panel">
      <h2>{{ translate("粘贴或选择导入文件（wardrobe.import/v1）") }}</h2>
      <p class="muted small">
        {{ translate("预览会完整执行一遍再回滚，") }}<strong>{{ translate("不会改变任何数据") }}</strong>{{ translate("；确认无误后在下一页提交。提交前会自动备份，提交后整批可撤销。 已核实的记录不会被直接修改，而是生成待确认提议。格式说明见") }}
        <a href="/api/v1/imports/schema" target="_blank" rel="noopener">JSON Schema</a> {{ translate("与 docs/API.md §10。") }}
      </p>
      <div class="actions">
        <label class="btn ghost small">{{ translate("选择 .json 文件") }}<input type="file" accept="application/json,.json" class="visually-hidden" @change="readFile" /></label>
        <button type="button" class="btn ghost small" @click="text = JSON.stringify(EXAMPLE, null, 2)">{{ translate("填入示例") }}</button>
      </div>
      <label class="field wide json">
        <span class="visually-hidden">{{ translate("导入 JSON") }}</span>
        <textarea v-model="text" spellcheck="false" placeholder='{"format": "wardrobe.import/v1", ...}' :aria-invalid="!!parseError || !!previewError" />
      </label>
      <p v-if="parseError" class="error-banner" role="alert">{{ parseError }}</p>
      <div v-if="previewError" class="error-banner" role="alert">
        <p class="m0">{{ previewError?.() }}</p>
        <ul v-if="previewDetails.length" class="details">
          <li v-for="(d, i) in previewDetails" :key="i"><code>{{ d.loc }}</code>：{{ d.message }}</li>
        </ul>
      </div>
      <div class="form-actions">
        <button type="button" class="btn" :disabled="previewing || !text.trim()" @click="preview">{{ previewing ? translate("预览中…") : translate("预览导入") }}</button>
      </div>
    </section>

    <p v-if="error" class="error-banner" role="alert">{{ error?.() }}</p>

    <section v-if="tab === 'jobs'">
      <div v-if="jobs.length" class="table-wrap">
        <table class="data">
          <thead><tr><th>{{ translate("批次") }}</th><th>{{ translate("来源") }}</th><th>{{ translate("状态") }}</th><th>{{ translate("结果") }}</th><th>{{ translate("时间") }}</th></tr></thead>
          <tbody>
            <tr v-for="j in jobs" :key="j.job_id">
              <td><RouterLink :to="{ name: 'import', params: { id: j.job_id } }">#{{ j.job_id }}</RouterLink></td>
              <td>{{ j.source_label ?? translate("（未命名）") }}<div class="muted small">{{ j.actor }}</div></td>
              <td><span class="badge" :class="{ dark: j.status === 'committed' }">{{ label(IMPORT_STATUS_LABELS, j.status) }}</span></td>
              <td class="small">{{ counts(j) }}</td>
              <td class="small nowrap">{{ formatTime(j.committed_at ?? j.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else-if="!loading" class="empty-note">{{ translate("还没有导入记录。") }}</p>
      <div v-if="jobs.length < jobsTotal && !loading" class="more"><button type="button" class="btn ghost" @click="load(true)">{{ translate("加载更多") }}</button></div>
    </section>

    <BatchSuggestions v-if="tab === 'suggest'" />

    <section v-if="tab === 'proposals'">
      <div class="filters">
        <label class="field">
          <span>{{ translate("状态") }}</span>
          <select v-model="proposalStatus">
            <option v-for="(t, k) in PROPOSAL_STATUS_LABELS" :key="k" :value="k">{{ t }}</option>
            <option value="all">{{ translate("全部") }}</option>
          </select>
        </label>
        <span class="muted small">{{ proposalsTotal }} {{ translate("条") }}</span>
      </div>
      <ProposalList v-if="proposals.length" :proposals="proposals" show-target @changed="load()" />
      <p v-else-if="!loading" class="empty-note">{{ proposalStatus === "pending" ? translate("没有待确认的提议。") : translate("没有记录。") }}</p>
      <div v-if="proposals.length < proposalsTotal && !loading" class="more"><button type="button" class="btn ghost" @click="load(true)">{{ translate("加载更多") }}</button></div>
    </section>

    <section v-if="tab === 'changes'">
      <form class="filters" @submit.prevent="load()">
        <label class="field">
          <span>{{ translate("对象") }}</span>
          <select v-model="changeFilter.entity" @change="load()">
            <option value="">{{ translate("全部") }}</option>
            <option v-for="k in ['wardrobe_item', 'product', 'purchase', 'purchase_line', 'outfit', 'brand', 'category', 'tag', 'image']" :key="k" :value="k">{{ label(ENTITY_LABELS, k) }}</option>
          </select>
        </label>
        <label class="field">
          <span>{{ translate("操作") }}</span>
          <select v-model="changeFilter.op" @change="load()">
            <option value="">{{ translate("全部") }}</option>
            <option v-for="(t, k) in OP_LABELS" :key="k" :value="k">{{ t }}</option>
          </select>
        </label>
        <label class="field"><span>{{ translate("请求方") }}</span><input v-model="changeFilter.actor" :placeholder='translate("例如 web-ui、ai:codex")' @change="load()" /></label>
      </form>
      <div v-if="changes.length" class="table-wrap">
        <table class="data">
          <thead><tr><th>{{ translate("时间") }}</th><th>{{ translate("请求方") }}</th><th>{{ translate("对象") }}</th><th>{{ translate("操作") }}</th><th>{{ translate("内容") }}</th></tr></thead>
          <tbody>
            <tr v-for="c in changes" :key="c.id">
              <td class="small nowrap">{{ formatTime(c.occurred_at) }}</td>
              <td class="small">{{ c.actor }}</td>
              <td class="small nowrap">
                {{ label(ENTITY_LABELS, c.entity) }}
                <RouterLink v-if="changeLink(c)" :to="changeLink(c)!">#{{ c.entity_id }}</RouterLink>
                <template v-else>#{{ c.entity_id }}</template>
              </td>
              <td class="small nowrap">
                {{ label(OP_LABELS, c.op) }}
                <div v-if="c.import_job_id" class="muted"><RouterLink :to="{ name: 'import', params: { id: c.import_job_id } }">{{ translate("导入") }} {{ c.import_job_id }}</RouterLink></div>
                <div v-if="c.proposal_id" class="muted">{{ translate("提议") }} {{ c.proposal_id }}</div>
              </td>
              <td class="small">
                <div v-if="c.before !== null && c.before !== undefined" class="muted">{{ translate("之前：") }}{{ summarize(c.before) }}</div>
                <div v-if="c.after !== null && c.after !== undefined">{{ translate("之后：") }}{{ summarize(c.after) }}</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else-if="!loading" class="empty-note">{{ translate("没有变更记录。") }}</p>
      <div v-if="changes.length < changesTotal && !loading" class="more"><button type="button" class="btn ghost" @click="load(true)">{{ translate("加载更多") }}</button></div>
    </section>
  </div>
</template>

<style scoped>
.small {
  font-size: 13px;
}
.nowrap {
  white-space: nowrap;
}
.m0 {
  margin: 0;
}
.json {
  margin-top: 12px;
}
.json textarea {
  min-height: 320px;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 13px;
  line-height: 1.5;
}
.details {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 13px;
}
label.btn:focus-within {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: end;
  margin-bottom: 16px;
}
.filters .field {
  min-width: 160px;
}
.more {
  display: flex;
  justify-content: center;
  margin-top: 20px;
}
</style>
