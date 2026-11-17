<script setup lang="ts">
import { t as translate } from "../i18n";
// 颜色圆点：优先用实际 HEX；没有时用按颜色名称 / 色号推算的示意色（后端 swatch），再没有用颜色族的代表色
import { computed } from "vue";
import { colorSwatch } from "../lib/labels";

const props = withDefaults(
  defineProps<{ hex?: string | null; swatch?: string | null; family?: string | null; size?: number }>(),
  { hex: null, swatch: null, family: null, size: 12 },
);
const background = computed(() => props.hex ?? props.swatch ?? colorSwatch(props.family) ?? "transparent");
const empty = computed(() => !props.hex && !props.swatch && !colorSwatch(props.family));
const title = computed(() => (!props.hex && (props.swatch || colorSwatch(props.family)) ? translate("示意色（按颜色名称推算，不是实测颜色）") : undefined));
</script>

<template>
  <span
    class="dot"
    :class="{ empty }"
    :style="{ background, width: `${size}px`, height: `${size}px` }"
    :title="title"
    aria-hidden="true"
  />
</template>

<style scoped>
.dot {
  display: inline-block;
  flex: none;
  border-radius: 50%;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.14);
}
.dot.empty {
  box-shadow: inset 0 0 0 1px var(--line-strong);
  background: repeating-linear-gradient(45deg, transparent 0 3px, var(--line) 3px 4px) !important;
}
</style>
