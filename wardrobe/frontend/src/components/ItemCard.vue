<script setup lang="ts">
import { t as translate } from "../i18n";
import { computed, ref, watch } from "vue";
import type { ItemSummary } from "../api/types";
import { STATUS_LABELS, label } from "../lib/labels";
import ColorDot from "./ColorDot.vue";

const props = defineProps<{ item: ItemSummary }>();

const imageFailed = ref(false);
watch(() => props.item.thumb_url, () => { imageFailed.value = false; });

const color = computed(() => props.item.resolved.color);
const size = computed(() => props.item.resolved.size.label);
const secondary = computed(() =>
  props.item.name_zh && props.item.name_zh !== props.item.name ? props.item.name_zh : null,
);
const statusLabel = computed(() => (props.item.status === "owned" ? null : label(STATUS_LABELS, props.item.status)));
</script>

<template>
  <RouterLink :to="{ name: 'item', params: { id: item.id } }" class="card" :data-testid="`item-card-${item.id}`">
    <div class="frame">
      <img v-if="item.thumb_url && !imageFailed" :src="item.thumb_url" :alt="item.name" loading="lazy" decoding="async" @error="imageFailed = true" />
      <div v-else class="placeholder" :style="{ background: color.hex ?? item.color_swatch?.hex ?? undefined }">
        <span>{{ item.name }}</span>
      </div>
      <span v-if="statusLabel" class="status">{{ statusLabel }}</span>
    </div>
    <div class="meta">
      <div class="brand">{{ item.brand ?? translate("无品牌") }}</div>
      <div class="name">{{ item.name }}</div>
      <div v-if="secondary" class="name-zh">{{ secondary }}</div>
      <div class="facts">
        <span v-if="color.name || color.hex" class="color">
          <ColorDot :hex="color.hex" :swatch="item.color_swatch?.hex" :family="color.family" />
          {{ color.name ?? "" }}
        </span>
        <span v-if="size" class="size">{{ size }}</span>
      </div>
    </div>
  </RouterLink>
</template>

<style scoped>
.card {
  display: block;
  min-width: 0;
  overflow-wrap: anywhere;
  text-decoration: none;
  color: inherit;
}
.frame {
  position: relative;
  aspect-ratio: 3 / 4;
  overflow: hidden;
  background: var(--image-bg);
}
.frame img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.35s ease;
}
.card:hover .frame img {
  transform: scale(1.025);
}
.placeholder {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: end start;
  padding: 14px;
  background: var(--image-bg);
}
.placeholder span {
  min-width: 0;
  max-width: 100%;
  background: rgba(255, 255, 255, 0.9);
  padding: 2px 8px;
  font-size: 12px;
  color: var(--ink-2);
}
.status {
  position: absolute;
  top: 10px;
  left: 10px;
  background: var(--ink);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 2px 8px;
}
.meta {
  padding: 10px 2px 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 2px;
}
.brand {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--ink-3);
  text-transform: uppercase;
}
.name {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.name-zh {
  font-size: 12px;
  color: var(--ink-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.facts {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--ink-2);
}
.color {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.size {
  padding-left: 12px;
  border-left: 1px solid var(--line);
}
@media (prefers-reduced-motion: reduce) {
  .frame img {
    transition: none;
  }
}
</style>
