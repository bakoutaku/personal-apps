<script setup lang="ts">
import { computed, ref, useId } from "vue";
import { dict } from "../lib/dictionaries";

const props = defineProps<{ modelValue: string[]; label?: string }>();
const emit = defineEmits<{ "update:modelValue": [tags: string[]] }>();
const draft = ref("");
const listId = useId();

const suggestions = computed(() => dict.tags.map((t) => t.name).filter((n) => !props.modelValue.includes(n)));

function add() {
  // 标签允许包含逗号（后端按完整名称保存），因此只用回车/按钮确认，不按逗号拆分
  const name = draft.value.trim();
  if (name && !props.modelValue.includes(name)) emit("update:modelValue", [...props.modelValue, name]);
  draft.value = "";
}

function remove(name: string) {
  emit("update:modelValue", props.modelValue.filter((t) => t !== name));
}
</script>

<template>
  <div class="tag-input">
    <ul v-if="modelValue.length" class="current">
      <li v-for="t in modelValue" :key="t" class="chip">
        #{{ t }}
        <button type="button" class="x" :aria-label="`移除标签 ${t}`" @click="remove(t)">×</button>
      </li>
    </ul>
    <div class="row">
      <input
        v-model="draft"
        class="input"
        :list="listId"
        :aria-label="label ?? '添加标签'"
        placeholder="输入标签后按回车"
        @keydown.enter.prevent="add"
      />
      <button type="button" class="btn ghost small" :disabled="!draft.trim()" @click="add">添加</button>
    </div>
    <datalist :id="listId">
      <option v-for="s in suggestions" :key="s" :value="s" />
    </datalist>
  </div>
</template>

<style scoped>
.tag-input {
  display: grid;
  gap: 8px;
}
.current {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.x {
  border: 0;
  background: none;
  cursor: pointer;
  padding: 0 0 0 2px;
  font-size: 14px;
  line-height: 1;
  color: var(--ink-2);
}
.row {
  display: flex;
  gap: 8px;
}
</style>
