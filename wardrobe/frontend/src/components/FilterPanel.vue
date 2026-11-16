<script setup lang="ts">
import { computed } from "vue";
import type { Brand, CategoryNode, Facets } from "../api/types";
import { type Filters, type ListKey, toggle } from "../lib/filters";
import { COLOR_FAMILIES, FIBER_LABELS, STATUS_LABELS, label } from "../lib/labels";
import CategoryTree from "./CategoryTree.vue";

const props = defineProps<{
  filters: Filters;
  facets: Facets | null;
  categories: CategoryNode[];
  brands: Brand[];
}>();
const emit = defineEmits<{ change: [patch: Partial<Filters>] }>();

const counts = computed(() => props.facets ?? null);

function pathTo(slug: string | null, nodes: CategoryNode[], trail: string[] = []): string[] {
  if (!slug) return [];
  for (const n of nodes) {
    const here = [...trail, n.slug];
    if (n.slug === slug) return here;
    const found = pathTo(slug, n.children, here);
    if (found.length) return found;
  }
  return [];
}
const selectedPath = computed(() => pathTo(props.filters.category, props.categories));

/** 某个维度的可选值：有计数的值 + 已选中的值（即使计数为 0 也保留，方便取消）。 */
function options(key: Exclude<keyof Facets, "total" | "category" | "groups">, selected: string[]): [string, number][] {
  const c = counts.value?.[key] ?? {};
  const keys = new Set([...Object.keys(c), ...selected]);
  return [...keys].map((k) => [k, c[k] ?? 0] as [string, number]);
}

const brandOptions = computed(() =>
  options("brand", props.filters.brand)
    .map(([slug, n]) => ({ slug, n, name: props.brands.find((b) => b.slug === slug)?.name ?? slug }))
    .sort((a, b) => b.n - a.n || a.name.localeCompare(b.name)),
);
const sizeOrder = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL", "4XL"];
const sizeOptions = computed(() =>
  options("size", props.filters.size).sort(([a], [b]) => {
    const ia = sizeOrder.indexOf(a);
    const ib = sizeOrder.indexOf(b);
    if (ia >= 0 && ib >= 0) return ia - ib;
    if (ia >= 0 || ib >= 0) return ia >= 0 ? -1 : 1;
    return a.localeCompare(b, "ja", { numeric: true });
  }),
);
const tagOptions = computed(() => options("tag", props.filters.tag).sort((a, b) => b[1] - a[1]));
const materialOptions = computed(() => options("material", props.filters.material).sort((a, b) => b[1] - a[1]));
const colorOptions = computed(() =>
  COLOR_FAMILIES.map((c) => ({ ...c, n: counts.value?.color[c.key] ?? 0 })).filter(
    (c) => c.n > 0 || props.filters.color.includes(c.key),
  ),
);
const statusOptions = computed(() => {
  const c = counts.value?.status ?? {};
  const all = Object.values(c).reduce((a, b) => a + b, 0);
  const rest = Object.keys(c)
    .filter((k) => k !== "owned")
    .map((k) => ({ value: k, label: label(STATUS_LABELS, k), n: c[k] }));
  return [{ value: "owned", label: "持有中", n: c.owned ?? 0 }, ...rest, { value: "all", label: "全部", n: all }];
});

function flip(key: ListKey, value: string) {
  emit("change", { [key]: toggle(props.filters[key], value) });
}
</script>

<template>
  <div class="panel">
    <section>
      <h3>分类</h3>
      <CategoryTree
        :nodes="categories"
        :counts="counts?.category ?? {}"
        :selected="filters.category"
        :selected-path="selectedPath"
        @select="emit('change', { category: $event })"
      />
    </section>

    <section v-if="colorOptions.length">
      <h3>颜色</h3>
      <div class="swatches">
        <button
          v-for="c in colorOptions"
          :key="c.key"
          type="button"
          class="swatch"
          :class="{ active: filters.color.includes(c.key) }"
          :aria-pressed="filters.color.includes(c.key)"
          :title="`${c.label}（${c.n}）`"
          @click="flip('color', c.key)"
        >
          <span class="chip-color" :style="{ background: c.swatch }" />
          <span class="swatch-label">{{ c.label }}</span>
        </button>
      </div>
    </section>

    <section v-if="brandOptions.length">
      <h3>品牌</h3>
      <label v-for="b in brandOptions" :key="b.slug" class="check">
        <input type="checkbox" :checked="filters.brand.includes(b.slug)" @change="flip('brand', b.slug)" />
        <span>{{ b.name }}</span>
        <span class="count">{{ b.n }}</span>
      </label>
    </section>

    <section v-if="sizeOptions.length">
      <h3>尺码</h3>
      <div class="pills">
        <button
          v-for="[s, n] in sizeOptions"
          :key="s"
          type="button"
          class="pill"
          :class="{ active: filters.size.includes(s) }"
          :aria-pressed="filters.size.includes(s)"
          :title="`${n} 件`"
          @click="flip('size', s)"
        >
          {{ s }}
        </button>
      </div>
    </section>

    <section v-if="tagOptions.length">
      <h3>标签</h3>
      <div class="pills">
        <button
          v-for="[t, n] in tagOptions"
          :key="t"
          type="button"
          class="pill"
          :class="{ active: filters.tag.includes(t) }"
          :aria-pressed="filters.tag.includes(t)"
          @click="flip('tag', t)"
        >
          {{ t }} <span class="count">{{ n }}</span>
        </button>
      </div>
    </section>

    <section v-if="materialOptions.length">
      <h3>材质</h3>
      <label v-for="[m, n] in materialOptions" :key="m" class="check">
        <input type="checkbox" :checked="filters.material.includes(m)" @change="flip('material', m)" />
        <span>{{ label(FIBER_LABELS, m) }}</span>
        <span class="count">{{ n }}</span>
      </label>
    </section>

    <section>
      <h3>状态</h3>
      <label v-for="s in statusOptions" :key="s.value" class="check">
        <input type="radio" name="status" :checked="filters.status === s.value" @change="emit('change', { status: s.value })" />
        <span>{{ s.label }}</span>
        <span class="count">{{ s.n }}</span>
      </label>
    </section>
  </div>
</template>

<style scoped>
.panel {
  display: grid;
  gap: 4px;
}
section {
  padding: 14px 0;
  border-bottom: 1px solid var(--line);
}
section:last-child {
  border-bottom: 0;
}
h3 {
  font-size: 12px;
  letter-spacing: 0.14em;
  color: var(--ink-3);
  margin-bottom: 8px;
}
.count {
  margin-left: auto;
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.check {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 14px;
  cursor: pointer;
}
.check span {
  min-width: 0;
  overflow-wrap: anywhere;
}
.check input {
  accent-color: var(--ink);
  margin: 0;
}
.swatches {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px 4px;
}
.swatch {
  display: grid;
  justify-items: center;
  gap: 4px;
  border: 0;
  background: none;
  padding: 2px 0;
  cursor: pointer;
}
.chip-color {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.15);
}
.swatch.active .chip-color {
  outline: 2px solid var(--ink);
  outline-offset: 2px;
}
.swatch-label {
  font-size: 11px;
  color: var(--ink-2);
}
.swatch.active .swatch-label {
  color: var(--ink);
  font-weight: 700;
}
.pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  background: var(--surface);
  font-size: 13px;
  cursor: pointer;
  max-width: 100%;
  min-width: 0;
  overflow-wrap: anywhere;
}
.pill .count {
  margin-left: 0;
  flex-shrink: 0;
}
.pill.active {
  border-color: var(--ink);
  background: var(--ink);
  color: #fff;
}
.pill.active .count {
  color: #d6d6d6;
}
</style>
