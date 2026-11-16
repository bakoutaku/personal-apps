<script setup lang="ts">
// 修改提议列表：逐条或勾选后批量接受 / 拒绝。接受时后端会按记录当前状态重新校验。
import { computed, ref, watch } from "vue";
import { api } from "../api/client";
import type { Proposal } from "../api/types";
import { dict, loadDictionaries } from "../lib/dictionaries";
import { errorMessage } from "../lib/errors";
import { formatTime, formatValue } from "../lib/format";
import { ENTITY_LABELS, FIELD_LABELS, PROPOSAL_STATUS_LABELS, label } from "../lib/labels";
import { notify } from "../lib/toast";

const props = withDefaults(defineProps<{ proposals: Proposal[]; title?: string; showTarget?: boolean }>(), {
  title: "",
  showTarget: false,
});
const emit = defineEmits<{ changed: [] }>();
void loadDictionaries();
const selected = ref<number[]>([]);
const busy = ref(false);
const errors = ref<Record<number, string>>({});

const pending = computed(() => props.proposals.filter((p) => p.status === "pending"));
watch(
  () => props.proposals,
  () => {
    selected.value = selected.value.filter((id) => pending.value.some((p) => p.proposal_id === id));
  },
);
const allSelected = computed(() => pending.value.length > 0 && selected.value.length === pending.value.length);

function toggleAll() {
  selected.value = allSelected.value ? [] : pending.value.map((p) => p.proposal_id);
}

const isGroup = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

// 整组提议（颜色、尺码、状态、匹配）接受时整组写入，值为空的字段会被清空，因此逐个字段列出，不能省略空值
function groupRows(p: Proposal) {
  const before = p.current_value;
  const after = p.proposed_value;
  if (!isGroup(before) || !isGroup(after)) return null;
  const keys = [...new Set([...Object.keys(after), ...Object.keys(before)])];
  const empty = (v: unknown) => v === null || v === undefined || v === "";
  return keys.map((key) => ({
    key,
    label: label(FIELD_LABELS, key),
    before: formatValue(before[key]),
    after: formatValue(after[key]),
    clears: !empty(before[key]) && empty(after[key]),
  }));
}

// 分类提议的值是分类 id；显示为分类名称（字典尚未读到时退回显示 id）
function shown(p: Proposal, v: unknown): string {
  if (p.field === "category_id" && typeof v === "number") {
    const c = dict.flatCategories.find((x) => x.id === v);
    return c ? `${c.name_zh}（#${v}）` : `分类 #${v}`;
  }
  return formatValue(v);
}

function ruleReasons(p: Proposal): string[] {
  const ev = p.rule_context?.evidence as { tags?: { name: string; reasons: { label: string }[] }[]; reasons?: { label: string }[] } | undefined;
  if (!ev) return [];
  if (ev.tags) return ev.tags.map((t) => `#${t.name}：${t.reasons.map((r) => r.label).join("；")}`);
  return (ev.reasons ?? []).map((r) => r.label);
}

// 来源说明按提议生成时的规则版本：tagcat/3 起标签也来自商品名称中的常用叫法，旧提议保持原说法
function ruleSource(ctx: NonNullable<Proposal["rule_context"]>): string {
  if (ctx.kind === "category") return "根据商品名称中的分类名称";
  const version = Number(/^wardrobe-tagcat\/(\d+)$/.exec(ctx.algorithm)?.[1] ?? 0);
  return version >= 3 ? "根据同一商品的其他衣物、同类相似衣物的标签和商品名称中的常用叫法" : "根据同一商品的其他衣物和同类相似衣物的标签";
}

function targetLink(p: Proposal) {
  if (p.entity === "wardrobe_item") return { name: "item", params: { id: p.entity_id } };
  if (p.entity === "product") return { name: "product", params: { id: p.entity_id } };
  return null;
}

async function decide(p: Proposal, decision: "accept" | "reject") {
  busy.value = true;
  delete errors.value[p.proposal_id];
  try {
    await (decision === "accept" ? api.acceptProposal(p.proposal_id) : api.rejectProposal(p.proposal_id));
    notify(decision === "accept" ? "已接受提议" : "已拒绝提议");
    emit("changed");
  } catch (e) {
    errors.value = { ...errors.value, [p.proposal_id]: errorMessage(e) };
  } finally {
    busy.value = false;
  }
}

async function bulk(decision: "accept" | "reject") {
  if (!selected.value.length) return;
  busy.value = true;
  try {
    const res = await api.bulkProposals(selected.value, decision);
    const next: Record<number, string> = {};
    for (const r of res.results) if (!r.ok && r.error) next[r.proposal_id] = r.error.message;
    errors.value = next;
    notify(`${decision === "accept" ? "接受" : "拒绝"}：成功 ${res.succeeded} 条${res.failed ? `，失败 ${res.failed} 条（原因见列表）` : ""}`, {
      kind: res.failed ? "error" : "info",
    });
    selected.value = selected.value.filter((id) => next[id]);
    emit("changed");
  } catch (e) {
    notify(errorMessage(e), { kind: "error" });
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="proposals" :aria-label="title || '修改提议'">
    <div class="head">
      <h2 v-if="title">{{ title }}</h2>
      <div v-if="pending.length > 1" class="actions">
        <label class="field check"><input type="checkbox" :checked="allSelected" @change="toggleAll" /><span>全选</span></label>
        <button type="button" class="btn small" :disabled="busy || !selected.length" @click="bulk('accept')">接受所选（{{ selected.length }}）</button>
        <button type="button" class="btn ghost small" :disabled="busy || !selected.length" @click="bulk('reject')">拒绝所选</button>
      </div>
    </div>
    <ul>
      <li v-for="p in proposals" :key="p.proposal_id" class="proposal" :data-testid="`proposal-${p.proposal_id}`">
        <div class="line1">
          <label v-if="p.status === 'pending' && pending.length > 1" class="pick">
            <input v-model="selected" type="checkbox" :value="p.proposal_id" :aria-label="`选择提议 ${p.proposal_id}`" />
          </label>
          <strong>{{ label(FIELD_LABELS, p.field) }}</strong>
          <span v-if="showTarget" class="muted">
            {{ label(ENTITY_LABELS, p.entity) }}
            <RouterLink v-if="targetLink(p)" :to="targetLink(p)!">#{{ p.entity_id }}</RouterLink>
            <template v-else>#{{ p.entity_id }}</template>
          </span>
          <span class="badge" :class="{ warn: p.status === 'pending' }">{{ label(PROPOSAL_STATUS_LABELS, p.status) }}</span>
        </div>
        <table v-if="groupRows(p)" class="group" :aria-label="`${label(FIELD_LABELS, p.field)}的整组前后对比`">
          <thead><tr><th></th><th>当前</th><th>接受后</th></tr></thead>
          <tbody>
            <tr v-for="r in groupRows(p)!" :key="r.key">
              <th>{{ r.label }}</th>
              <td>{{ r.before }}</td>
              <td class="new" :class="{ clears: r.clears }">{{ r.after }}<span v-if="r.clears" class="clear-tag">将清空</span></td>
            </tr>
          </tbody>
        </table>
        <dl v-else class="diff">
          <div><dt>当前</dt><dd>{{ shown(p, p.current_value) }}</dd></div>
          <div><dt>{{ p.field === "tags_add" ? "追加" : "建议" }}</dt><dd class="new">{{ shown(p, p.proposed_value) }}</dd></div>
        </dl>
        <div v-if="p.rule_context" class="rule-source" data-testid="rule-source">
          来源：规则建议（{{ p.rule_context.algorithm }}，{{ ruleSource(p.rule_context) }}，不是图像识别）<template v-if="p.field === 'tags_add'">；接受时只追加，不删除已有标签</template>
          <ul><li v-for="(r, i) in ruleReasons(p)" :key="i">{{ r }}</li></ul>
        </div>
        <p v-if="p.ai_context" class="ai-source" data-testid="ai-source">
          <span class="swatch" :style="{ background: p.ai_context.candidate.hex }" aria-hidden="true" />
          <span>
            来源：本地照片颜色分析（{{ p.ai_context.algorithm }}，像素统计，不是语义识别）· 照片
            {{ p.ai_context.image_id === null ? "（已删除）" : `#${p.ai_context.image_id}` }}
            {{ p.ai_context.region ? "的选定区域" : "整图" }} · 候选 {{ p.ai_context.candidate.hex }}，像素占比 {{ Math.round(p.ai_context.candidate.pixel_share * 100) }}%
            · 生成时衣物版本 {{ p.ai_context.target_version }}（衣物之后有任何修改，接受时会提示已过期）
          </span>
        </p>
        <p class="meta muted">
          来自 {{ p.actor }}<template v-if="p.import_job_id">（<RouterLink :to="{ name: 'import', params: { id: p.import_job_id } }">导入批次 {{ p.import_job_id }}</RouterLink>）</template>
          · {{ formatTime(p.created_at) }}<template v-if="p.reason"> · {{ p.reason }}</template>
        </p>
        <p v-if="errors[p.proposal_id]" class="field-error" role="alert">{{ errors[p.proposal_id] }}</p>
        <div v-if="p.status === 'pending'" class="actions">
          <button type="button" class="btn small" :disabled="busy" @click="decide(p, 'accept')">接受</button>
          <button type="button" class="btn ghost small" :disabled="busy" @click="decide(p, 'reject')">拒绝</button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.proposals {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 8px 16px;
}
.head h2 {
  font-size: 16px;
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
}
.proposal {
  border: 1px solid var(--line);
  border-left: 3px solid #e0c27a;
  background: var(--surface);
  padding: 12px 14px;
  display: grid;
  gap: 8px;
  min-width: 0;
}
.line1 {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  align-items: center;
}
.group {
  border-collapse: collapse;
  font-size: 13px;
  width: 100%;
}
.group th,
.group td {
  text-align: left;
  padding: 2px 8px 2px 0;
  overflow-wrap: anywhere;
  vertical-align: top;
}
.group thead th {
  color: var(--ink-3);
  font-weight: 400;
  font-size: 12px;
}
.group tbody th {
  color: var(--ink-3);
  font-weight: 400;
  white-space: nowrap;
}
.group .new {
  font-weight: 600;
}
.group .clears {
  color: var(--danger);
}
.clear-tag {
  margin-left: 6px;
  font-size: 11px;
  border: 1px solid currentColor;
  padding: 0 4px;
  font-weight: 400;
}
.diff {
  display: grid;
  gap: 4px;
  margin: 0;
  font-size: 13px;
}
.diff div {
  display: grid;
  grid-template-columns: 3em minmax(0, 1fr);
  gap: 8px;
}
.diff dt {
  color: var(--ink-3);
}
.diff dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.diff .new {
  font-weight: 600;
}
.rule-source {
  font-size: 12px;
  color: var(--ink-2);
}
.rule-source ul {
  margin: 2px 0 0;
  padding-left: 18px;
}
.ai-source {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  margin: 0;
  font-size: 12px;
  color: var(--ink-2);
}
.ai-source .swatch {
  width: 14px;
  height: 14px;
  border: 1px solid var(--line-strong);
  flex-shrink: 0;
  margin-top: 2px;
}
.meta {
  margin: 0;
  font-size: 12px;
}
</style>
