<script setup lang="ts">
// 多图展示：主图（原图，完整显示）+ 缩略图条。左右方向键切换。
import { computed, ref, watch } from "vue";
import type { ImageInfo } from "../api/types";

const props = defineProps<{ images: ImageInfo[]; alt: string; fallbackColor?: string | null }>();
const index = ref(0);
const failedUrls = ref(new Set<string>());
const current = computed(() => props.images[index.value] ?? null);

watch(
  () => props.images,
  () => { index.value = 0; failedUrls.value = new Set(); },
);

function move(delta: number) {
  if (!props.images.length) return;
  index.value = (index.value + delta + props.images.length) % props.images.length;
}
</script>

<template>
  <div class="gallery" @keydown.left.prevent="move(-1)" @keydown.right.prevent="move(1)">
    <div class="main" :style="!current && fallbackColor ? { background: fallbackColor } : undefined">
      <img v-if="current && !failedUrls.has(current.url)" :key="current.url" :src="current.url" :alt="alt" @error="failedUrls.add(current.url)" />
      <span v-else class="no-image">{{ current ? "图片加载失败" : "暂无图片" }}</span>
      <template v-if="images.length > 1">
        <button type="button" class="nav prev" aria-label="上一张" @click="move(-1)">‹</button>
        <button type="button" class="nav next" aria-label="下一张" @click="move(1)">›</button>
        <span class="position">{{ index + 1 }} / {{ images.length }}</span>
      </template>
    </div>
    <ul v-if="images.length > 1" class="thumbs" role="listbox" aria-label="图片">
      <li v-for="(img, i) in images" :key="img.id">
        <button
          type="button"
          class="thumb"
          role="option"
          :aria-selected="i === index"
          :class="{ active: i === index }"
          @click="index = i"
        >
          <img :src="img.thumb_url" :alt="`${alt}（第 ${i + 1} 张）`" loading="lazy" />
        </button>
      </li>
    </ul>
    <p v-if="current?.source_note || current?.source_url" class="source muted">
      图片来源：{{ current.source_note ?? "" }}
      <a v-if="current.source_url" :href="current.source_url" target="_blank" rel="noopener noreferrer">链接</a>
    </p>
  </div>
</template>

<style scoped>
.gallery {
  display: grid;
  gap: 12px;
}
.main {
  position: relative;
  aspect-ratio: 3 / 4;
  background: var(--image-bg);
  display: grid;
  place-items: center;
  overflow: hidden;
}
.main img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.no-image {
  font-size: 13px;
  color: var(--ink-2);
  background: rgba(255, 255, 255, 0.85);
  padding: 2px 10px;
}
.nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 40px;
  height: 40px;
  border: 0;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.85);
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
}
.prev {
  left: 12px;
}
.next {
  right: 12px;
}
.position {
  position: absolute;
  bottom: 12px;
  right: 12px;
  background: rgba(255, 255, 255, 0.85);
  padding: 0 8px;
  font-size: 12px;
}
.thumbs {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(64px, 1fr));
  gap: 8px;
}
.thumb {
  display: block;
  width: 100%;
  padding: 0;
  border: 1px solid transparent;
  background: var(--image-bg);
  cursor: pointer;
}
.thumb.active {
  border-color: var(--ink);
}
.thumb img {
  display: block;
  width: 100%;
  aspect-ratio: 3 / 4;
  object-fit: cover;
}
.source {
  margin: 0;
  font-size: 12px;
}
</style>
