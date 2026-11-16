<script setup lang="ts">
// Phase 5C：这件衣物的标签 / 分类规则建议 → 勾选 → 生成待确认提议（不直接修改衣物）。
// 规则见 docs/PHASE5C_TAG_CATEGORY_SUGGESTIONS.md。
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { api } from "../api/client";
import type { ItemDetail, ItemSuggestions, Proposal } from "../api/types";
import { errorMessage } from "../lib/errors";

const props = defineProps<{ item: ItemDetail }>();
const emit = defineEmits<{ created: [proposals: Proposal[]]; close: [] }>();

const data = ref<ItemSuggestions | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);
const pickedTags = ref<string[]>([]);
const pickCategory = ref(false);
const creating = ref(false);
const created = ref<Proposal[] | null>(null);

// 读取与生成各有自己的请求代次，互不使对方失效；生成中不能重新读取（按钮禁用、函数也拒绝）。
// 离开或换衣物（面板按衣物 id 重建）后旧结果不生效
let loadReq = 0;
let submitReq = 0;
let alive = true;
onBeforeUnmount(() => {
  alive = false;
  loadReq++;
  submitReq++;
});

async function load() {
  if (creating.value) return;
  const mine = ++loadReq;
  loading.value = true;
  error.value = null;
  created.value = null;
  try {
    const out = await api.tagSuggestions(props.item.id);
    if (mine !== loadReq) return;
    data.value = out;
    pickedTags.value = out.tags.map((t) => t.name);
    pickCategory.value = out.category !== null;
  } catch (e) {
    if (mine === loadReq) error.value = errorMessage(e);
  } finally {
    if (mine === loadReq) loading.value = false;
  }
}
void load();

// 建议读取之后衣物有修改：服务端会拒绝旧 version，界面提前提示
const outdated = computed(() => data.value !== null && data.value.item_version !== props.item.version);
// 生成期间改动勾选：结果仍如实显示，但不再算作「当前勾选已生成」
let picksChanged = false;
watch([pickedTags, pickCategory], () => {
  created.value = null;
  picksChanged = true;
}, { deep: true });

const NOTES: Record<string, string> = {
  already_categorized: "这件衣物已经有分类。",
  no_keyword_match: "商品名称中没有找到已有分类的名称。",
  ambiguous: "商品名称同时含有不同大类、或同一层级难分长短的多个分类名称，无法判断。",
};

async function submit() {
  const d = data.value;
  if (!d || outdated.value || loading.value || creating.value) return;
  const mine = ++submitReq;
  picksChanged = false;
  creating.value = true;
  error.value = null;
  try {
    const out = await api.createTagSuggestions(props.item.id, {
      version: d.item_version,
      tags: pickedTags.value,
      category_id: pickCategory.value && d.category ? d.category.category_id : null,
    });
    if (!alive) return;
    // 即使期间改了勾选，服务器上的提议确实已建立：仍通知列表刷新，但只在未改动时显示「已生成」
    emit("created", out.proposals);
    if (mine === submitReq && !picksChanged) created.value = out.proposals;
  } catch (e) {
    if (mine === submitReq) error.value = errorMessage(e);
  } finally {
    if (mine === submitReq) creating.value = false;
  }
}

const nothing = computed(() => !!data.value && !data.value.tags.length && !data.value.category);
const nonePicked = computed(() => !pickedTags.value.length && !(pickCategory.value && data.value?.category));
</script>

<template>
  <section class="panel tag-panel" aria-label="标签与分类建议">
    <div class="panel-head">
      <h2>标签与分类建议</h2>
      <button type="button" class="link-btn" @click="emit('close')">收起</button>
    </div>
    <p class="note">根据同一商品的其他衣物、同类的相似衣物和商品名称按固定规则给出，不是图像识别。生成的是待确认提议：标签只追加、不删除已有标签；接受之前不会修改这件衣物。</p>

    <p v-if="loading" class="muted small">正在计算建议…</p>
    <p v-if="error" class="error-banner" role="alert">{{ error }} <button type="button" class="link-btn" :disabled="creating" @click="load">重试</button></p>

    <template v-if="data && !loading">
      <p v-if="nothing" class="muted" data-testid="tag-nothing">暂时没有可建议的标签或分类。<template v-if="data.category_note">{{ NOTES[data.category_note] }}</template></p>
      <fieldset v-if="data.tags.length" class="group">
        <legend>追加标签</legend>
        <label v-for="t in data.tags" :key="t.name" class="opt" :data-testid="`tag-opt-${t.name}`">
          <input v-model="pickedTags" type="checkbox" :value="t.name" />
          <span><strong>#{{ t.name }}</strong><span class="muted small">{{ t.reasons.map((r) => r.label).join("；") }}</span></span>
        </label>
      </fieldset>
      <fieldset v-if="data.category" class="group">
        <legend>分类</legend>
        <label class="opt" data-testid="cat-opt">
          <input v-model="pickCategory" type="checkbox" />
          <span><strong>{{ data.category.path.join(" / ") }}</strong><span class="muted small">{{ data.category.reasons.map((r) => r.label).join("；") }}</span></span>
        </label>
      </fieldset>
      <p v-else-if="!nothing && data.category_note" class="muted small">分类：{{ NOTES[data.category_note] }}</p>

      <template v-if="!nothing">
        <p v-if="outdated" class="error-banner" role="alert">读取建议之后这件衣物已被修改，请重新读取。<button type="button" class="link-btn" :disabled="creating" @click="load">重新读取</button></p>
        <p v-if="created" class="done" role="status">已生成 {{ created.length }} 条待确认提议（尚未应用），可在下方提议列表中接受或拒绝。</p>
        <button v-else type="button" class="btn" :disabled="creating || outdated || nonePicked" @click="submit">{{ creating ? "生成中…" : "生成待确认提议" }}</button>
      </template>
    </template>
  </section>
</template>

<style scoped>
.tag-panel {
  margin: 0;
}
.note {
  font-size: 13px;
  color: var(--ink-2);
  margin: 0 0 12px;
}
.small {
  font-size: 12px;
}
.group {
  border: 0;
  margin: 0 0 12px;
  padding: 0;
  display: grid;
  gap: 6px;
}
.group legend {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 4px;
}
.opt {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font-size: 14px;
  cursor: pointer;
}
.opt > span {
  display: grid;
  min-width: 0;
  overflow-wrap: anywhere;
}
.done {
  border: 1px solid #b9d7b9;
  background: #eef7ee;
  padding: 8px 12px;
  font-size: 13px;
  margin: 0;
}
</style>
