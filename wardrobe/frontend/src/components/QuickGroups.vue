<script setup lang="ts">
import { t as translate } from "../i18n";
// 快捷分组按钮（「T恤」「衬衫」「半袖」…）：衣橱列表与挑选衣物共用。
// 分组定义与件数来自后端 /items/facets 的 groups；没有衣物的分组不显示（当前选中的除外）。
import { computed, ref, watch } from "vue";
import type { QuickGroup } from "../api/types";

const props = defineProps<{ groups: QuickGroup[] | undefined; selected: string | null }>();
const emit = defineEmits<{ select: [key: string | null] }>();

const visible = (g: QuickGroup) => g.count > 0 || g.key === props.selected;
const main = computed(() => (props.groups ?? []).filter((g) => !g.more && visible(g)));
const more = computed(() => (props.groups ?? []).filter((g) => g.more && visible(g)));
const showMore = ref(false);
// 选中的是「更多」里的分组时自动展开，避免选中项被藏起来（分组数据可能晚于选中状态到达）
watch(
  [() => props.selected, more],
  ([key]) => {
    if (key && more.value.some((g) => g.key === key)) showMore.value = true;
  },
  { immediate: true },
);

function pick(key: string) {
  emit("select", key === props.selected ? null : key);
}
</script>

<template>
  <div v-if="groups?.length" class="quick" role="group" :aria-label='translate("按种类筛选")' data-testid="quick-groups">
    <button type="button" class="q" :aria-pressed="selected === null" @click="emit('select', null)">{{ translate("全部") }}</button>
    <button
      v-for="g in main"
      :key="g.key"
      type="button"
      class="q"
      :aria-pressed="selected === g.key"
      :data-testid="`group-${g.key}`"
      @click="pick(g.key)"
    >
      {{ translate(g.label) }}<span class="n">{{ g.count }}</span>
    </button>
    <template v-if="more.length">
      <button type="button" class="q toggle" :aria-expanded="showMore" data-testid="group-more" @click="showMore = !showMore">
        {{ translate("更多") }}{{ showMore ? "▴" : "▾" }}
      </button>
      <template v-if="showMore">
        <button
          v-for="g in more"
          :key="g.key"
          type="button"
          class="q"
          :aria-pressed="selected === g.key"
          :data-testid="`group-${g.key}`"
          @click="pick(g.key)"
        >
          {{ translate(g.label) }}<span class="n">{{ g.count }}</span>
        </button>
      </template>
    </template>
  </div>
</template>

<style scoped>
.quick {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 2px;
  scrollbar-width: thin;
}
.q {
  flex: none;
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  padding: 5px 12px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface);
  color: var(--ink);
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
}
.q[aria-pressed="true"] {
  background: var(--ink);
  border-color: var(--ink);
  color: var(--surface);
}
.q .n {
  font-size: 11px;
  color: var(--ink-3);
}
.q[aria-pressed="true"] .n {
  color: inherit;
  opacity: 0.75;
}
.q.toggle {
  color: var(--ink-2);
}
</style>
