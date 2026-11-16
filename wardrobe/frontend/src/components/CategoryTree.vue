<script setup lang="ts">
// 三级分类树。只显示有衣物的分类（以及当前选中的路径），计数已包含子分类。
import { computed } from "vue";
import type { CategoryNode } from "../api/types";

const props = defineProps<{
  nodes: CategoryNode[];
  counts: Record<string, number>;
  selected: string | null;
  selectedPath: string[];
  depth?: number;
}>();
const emit = defineEmits<{ select: [slug: string | null] }>();

const visible = computed(() =>
  props.nodes.filter((n) => (props.counts[String(n.id)] ?? 0) > 0 || props.selectedPath.includes(n.slug)),
);
const isOpen = (n: CategoryNode) => props.selectedPath.includes(n.slug);
</script>

<template>
  <ul class="tree" :class="`depth-${depth ?? 0}`">
    <li v-for="n in visible" :key="n.id">
      <button
        type="button"
        class="node"
        :class="{ active: selected === n.slug, open: isOpen(n) }"
        :aria-pressed="selected === n.slug"
        @click="emit('select', selected === n.slug ? null : n.slug)"
      >
        <span class="name">{{ n.name_zh }}</span>
        <span class="count">{{ counts[String(n.id)] ?? 0 }}</span>
      </button>
      <CategoryTree
        v-if="n.children.length && isOpen(n)"
        :nodes="n.children"
        :counts="counts"
        :selected="selected"
        :selected-path="selectedPath"
        :depth="(depth ?? 0) + 1"
        @select="emit('select', $event)"
      />
    </li>
  </ul>
</template>

<style scoped>
.tree {
  list-style: none;
  margin: 0;
  padding: 0;
}
.tree.depth-1,
.tree.depth-2 {
  padding-left: 12px;
  border-left: 1px solid var(--line);
  margin-left: 4px;
}
.node {
  width: 100%;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 5px 4px;
  border: 0;
  background: none;
  text-align: left;
  cursor: pointer;
  font-size: 14px;
  color: var(--ink-2);
}
.node:hover {
  color: var(--ink);
}
.node.open {
  color: var(--ink);
}
.node.active {
  color: var(--ink);
  font-weight: 700;
}
.count {
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
</style>
