<script setup lang="ts">
import { t as translate } from "../i18n";
// 导入批次：预览结果（逐行动作与差异）→ 提交 / 丢弃；已提交的批次可整批撤销。
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { api } from "../api/client";
import type { ImportJob, ImportRow, Proposal } from "../api/types";
import ProposalList from "../components/ProposalList.vue";
import { apiErrorText, errorMessage, fieldDetails } from "../lib/errors";
import { formatTime, formatValue } from "../lib/format";
import { ACTION_LABELS, ENTITY_LABELS, FIELD_LABELS, IMPORT_STATUS_LABELS, label } from "../lib/labels";
import { notify } from "../lib/toast";

const props = defineProps<{ id: number }>();
const job = ref<ImportJob | null>(null);
const rows = ref<ImportRow[]>([]);
const proposals = ref<Proposal[]>([]);
const loading = ref(true);
const busy = ref(false);
const error = ref<(() => string) | null>(null);
const errorDetails = ref<string[]>([]);
const allowPartial = ref(false);
const actionFilter = ref("");
const entityFilter = ref("");

let requestId = 0;
onBeforeUnmount(() => { requestId++; });

async function load() {
  const id = ++requestId;
  const jobId = props.id;
  loading.value = true;
  error.value = null;
  // 切换到另一个批次时不显示上一个批次的内容
  if (job.value && job.value.job_id !== jobId) {
    job.value = null;
    rows.value = [];
    proposals.value = [];
  }
  try {
    const [j, r] = await Promise.all([api.importJob(jobId), api.importRows(jobId)]);
    if (id !== requestId) return;
    job.value = j;
    rows.value = r.items;
    document.title = translate("导入批次 {0} · Wardrobe", j.job_id);
    const p = await api.proposals({ import_job_id: jobId, status: "all", limit: 200 }).catch(() => ({ items: [] as Proposal[] }));
    if (id === requestId) proposals.value = p.items;
  } catch (e) {
    if (id === requestId) error.value = () => errorMessage(e);
  } finally {
    if (id === requestId) loading.value = false;
  }
}
watch(() => props.id, load, { immediate: true });

function describeDetails(e: unknown): string[] {
  return fieldDetails(e).map((d) => `${d.loc.join(" › ")}：${d.message}`).concat(
    // 撤销冲突、预览过期等错误的 details 不是字段错误，原样列出
    ((e as { details?: unknown[] }).details ?? [])
      .filter((d) => !(d && typeof d === "object" && "loc" in (d as object)))
      .map((d) => formatValue(d)),
  );
}

async function act(fn: () => Promise<unknown>, done: string) {
  busy.value = true;
  error.value = null;
  errorDetails.value = [];
  try {
    await fn();
    notify(done);
    await load();
  } catch (e) {
    error.value = () => errorMessage(e);
    errorDetails.value = describeDetails(e);
  } finally {
    busy.value = false;
  }
}

const commit = () => act(() => api.commitImport(props.id, allowPartial.value), translate("已提交导入（提交前已自动备份）"));
const discard = () => {
  if (window.confirm(translate("丢弃这个预览？不会改变任何数据。"))) void act(() => api.discardImport(props.id), translate("已丢弃预览"));
};
const revert = () => {
  if (window.confirm(translate("撤销整批导入？新建的记录会被删除，更新会恢复原值；如有后续修改冲突，将不做任何改动并列出冲突。")))
    void act(() => api.revertImport(props.id), translate("已撤销这批导入（撤销前已自动备份）"));
};

const summary = computed(() => (job.value?.summary ?? {}) as Record<string, number>);
const errorCount = computed(() => summary.value.error ?? 0);
const entities = computed(() => [...new Set(rows.value.map((r) => r.entity))]);
const visibleRows = computed(() =>
  rows.value.filter((r) => (!actionFilter.value || r.action === actionFilter.value) && (!entityFilter.value || r.entity === entityFilter.value)),
);

function targetLink(r: ImportRow) {
  // 预览中的记录尚未存在，撤销后新建的记录已删除，都不提供链接
  if (!r.target_id || job.value?.status !== "committed") return null;
  const names: Record<string, string> = { product: "product", purchase: "purchase", item: "item", wardrobe_item: "item", outfit: "outfit" };
  return names[r.entity] ? { name: names[r.entity]!, params: { id: r.target_id } } : null;
}

function diffFields(r: ImportRow): [string, unknown, unknown][] {
  return Object.entries(r.diff?.fields ?? {}).map(([k, v]) => [k, (v as unknown[])[0], (v as unknown[])[1]]);
}
</script>

<template>
  <div class="page">
    <RouterLink :to="{ name: 'imports', query: { tab: 'jobs' } }" class="link-btn">{{ translate("← 导入记录") }}</RouterLink>
    <p v-if="loading && !job" class="muted">{{ translate("加载中…") }}</p>
    <p v-else-if="error && !job" class="error-banner" role="alert">{{ error?.() }}</p>
    <template v-else-if="job">
      <div class="page-head">
        <div>
          <div class="muted">{{ translate("导入批次 #") }}{{ job.job_id }} · {{ job.actor }} · {{ formatTime(job.created_at) }}</div>
          <h1>{{ job.source_label ?? translate("（未命名导入）") }}</h1>
        </div>
        <span class="badge" :class="{ dark: job.status === 'committed' }">{{ label(IMPORT_STATUS_LABELS, job.status) }}</span>
      </div>

      <section class="panel">
        <ul class="summary">
          <li v-for="k in ['create', 'update', 'propose', 'skip', 'error']" :key="k" :class="{ bad: k === 'error' && summary[k] }">
            <strong>{{ summary[k] ?? 0 }}</strong><span>{{ label(ACTION_LABELS, k) }}</span>
          </li>
        </ul>
        <ul v-if="job.summary.job_warnings?.length" class="warnings">
          <li v-for="w in job.summary.job_warnings" :key="w.code" class="badge warn">{{ translate(w.message) }}</li>
        </ul>
        <p v-if="job.status === 'previewed'" class="muted small">{{ translate("这是预览结果，数据库尚未改变。提交时会重新执行并与预览逐行比对；预览之后若相关记录被改过，会要求重新预览。") }}</p>
        <p v-if="job.backup_file" class="muted small">{{ translate("提交前备份：") }}<code>{{ job.backup_file }}</code></p>
        <p v-if="job.committed_at" class="muted small">{{ translate("提交于") }} {{ formatTime(job.committed_at) }}<template v-if="job.reverted_at">{{ translate("，撤销于") }} {{ formatTime(job.reverted_at) }}</template></p>

        <div v-if="error" class="error-banner" role="alert">
          <p class="m0">{{ error?.() }}</p>
          <ul v-if="errorDetails.length" class="details"><li v-for="(d, i) in errorDetails" :key="i">{{ d }}</li></ul>
        </div>

        <div class="actions">
          <template v-if="job.status === 'previewed'">
            <label v-if="errorCount" class="field check"><input v-model="allowPartial" type="checkbox" /><span>{{ translate("跳过") }} {{ errorCount }} {{ translate("行错误，只提交其余行") }}</span></label>
            <button type="button" class="btn" :disabled="busy || (errorCount > 0 && !allowPartial)" @click="commit">{{ busy ? translate("处理中…") : translate("提交导入") }}</button>
            <button type="button" class="btn ghost" :disabled="busy" @click="discard">{{ translate("丢弃预览") }}</button>
          </template>
          <button v-else-if="job.status === 'committed'" type="button" class="btn danger" :disabled="busy" @click="revert">{{ translate("撤销整批导入") }}</button>
        </div>
      </section>

      <ProposalList v-if="proposals.length" class="panel" :proposals="proposals" :title='translate("本批次生成的修改提议")' show-target @changed="load" />

      <section class="panel">
        <div class="panel-head">
          <h2>{{ translate("逐行结果（") }}{{ rows.length }}）</h2>
          <div class="actions">
            <select v-model="actionFilter" class="input" :aria-label='translate("按动作筛选")'>
              <option value="">{{ translate("全部动作") }}</option>
              <option v-for="(t, k) in ACTION_LABELS" :key="k" :value="k">{{ t }}</option>
            </select>
            <select v-model="entityFilter" class="input" :aria-label='translate("按对象筛选")'>
              <option value="">{{ translate("全部对象") }}</option>
              <option v-for="e in entities" :key="e" :value="e">{{ label(ENTITY_LABELS, e) }}</option>
            </select>
          </div>
        </div>
        <ol class="rows">
          <li v-for="r in visibleRows" :key="r.row_index" :class="`act-${r.action}`" :data-testid="`row-${r.row_index}`">
            <div class="row-head">
              <span class="badge" :class="{ dark: r.action === 'create', warn: r.action === 'propose' || r.action === 'error' || r.action === 'dependency_failed' }">{{ label(ACTION_LABELS, r.action) }}</span>
              <strong>{{ label(ENTITY_LABELS, r.entity) }}</strong>
              <code v-if="r.ref">{{ r.ref }}</code>
              <RouterLink v-if="targetLink(r)" :to="targetLink(r)!">#{{ r.target_id }}</RouterLink>
              <span v-else-if="r.target_id" class="muted">#{{ r.target_id }}</span>
              <span v-if="r.match_reason" class="muted small">{{ translate("匹配：") }}{{ r.match_reason }}</span>
            </div>
            <table v-if="diffFields(r).length" class="data diff">
              <thead><tr><th>{{ translate("字段") }}</th><th>{{ translate("原值") }}</th><th>{{ translate("新值") }}</th></tr></thead>
              <tbody>
                <tr v-for="[k, a, b] in diffFields(r)" :key="k">
                  <td>{{ label(FIELD_LABELS, k) }}</td>
                  <td class="muted">{{ formatValue(a) }}</td>
                  <td>{{ formatValue(b) }}</td>
                </tr>
              </tbody>
            </table>
            <ul v-if="r.errors.length" class="msgs bad">
              <li v-for="(e, i) in r.errors" :key="i">{{ e.code }}：{{ apiErrorText(e.code, e.message) }}</li>
            </ul>
            <ul v-if="r.warnings.length" class="msgs">
              <li v-for="(w, i) in r.warnings" :key="i">{{ w.code }}：{{ translate(w.message) }}</li>
            </ul>
          </li>
        </ol>
        <p v-if="!visibleRows.length" class="muted">{{ translate("没有符合条件的行。") }}</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.small {
  font-size: 13px;
}
.m0 {
  margin: 0;
}
.summary {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
}
.summary li {
  display: grid;
  font-size: 13px;
  color: var(--ink-2);
}
.summary strong {
  font-size: 24px;
  color: var(--ink);
}
.summary .bad strong {
  color: var(--danger);
}
.warnings {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.details {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 13px;
}
.actions .input {
  width: auto;
}
.rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
}
.rows li {
  border-left: 3px solid var(--line-strong);
  padding: 6px 0 6px 12px;
  display: grid;
  gap: 6px;
  min-width: 0;
}
.rows .act-create {
  border-left-color: var(--ink);
}
.rows .act-propose {
  border-left-color: #e0c27a;
}
.rows .act-error,
.rows .act-dependency_failed {
  border-left-color: var(--danger);
}
.row-head {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  align-items: center;
  overflow-wrap: anywhere;
}
.diff {
  font-size: 13px;
}
.msgs {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: #7a5a10;
}
.msgs.bad {
  color: var(--danger);
}
</style>
