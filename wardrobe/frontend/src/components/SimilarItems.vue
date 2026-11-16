<script setup lang="ts">
// Phase 5B：按分类、有效颜色族、共有标签的固定规则推荐相似的持有中衣物（只读，规则见 docs/PHASE5B_SIMILAR_ITEMS.md）。
import { onBeforeUnmount, ref, watch } from "vue";
import { api } from "../api/client";
import type { SimilarItems } from "../api/types";
import { errorMessage } from "../lib/errors";
import { useDelayedLoading } from "../lib/useDelayedLoading";
import ItemCard from "./ItemCard.vue";

// basis：推荐依据的快照（version、有效分类、有效颜色、标签）。同一件衣物的资料在页面内刷新后（例如接受颜色提议）
// item.id 不变、组件不会重建，靠它触发重新读取；只用 version 不够，因为上游商品/购买变化会重算有效颜色而不提升衣物 version。
const props = defineProps<{ itemId: number; basis: string }>();
const result = ref<SimilarItems | null>(null);
const loading = ref(false);
// 同一件衣物重新读取期间保留上一份结果，但明确标示「正在更新」，不把旧理由当成新资料的结果
const updating = ref(false);
const showLoading = useDelayedLoading(loading);
const error = ref<string | null>(null);

// 只采用最新一次请求；换衣物或离开页面后，旧请求的成功或失败都不再生效
let req = 0;
onBeforeUnmount(() => { req++; });

async function load(id: number, refresh = false) {
  const mine = ++req;
  loading.value = true;
  updating.value = refresh && result.value !== null;
  error.value = null;
  if (!updating.value) result.value = null;
  try {
    const out = await api.similarItems(id);
    if (mine === req) result.value = out;
  } catch (e) {
    if (mine !== req) return;
    // 更新失败时不继续显示基于旧资料的推荐
    result.value = null;
    error.value = errorMessage(e);
  } finally {
    if (mine === req) {
      loading.value = false;
      updating.value = false;
    }
  }
}
watch(
  () => [props.itemId, props.basis] as const,
  ([id], old) => load(id, old !== undefined && old[0] === id),
  { immediate: true },
);
</script>

<template>
  <section class="similar" aria-labelledby="similar-title" :aria-busy="loading">
    <div class="head">
      <h2 id="similar-title">相似衣物</h2>
      <span class="muted small">按同类、颜色和共有标签匹配持有中的衣物，不使用图像识别</span>
    </div>
    <p v-if="updating" class="muted small" role="status" data-testid="similar-updating">衣物资料已变化，正在更新推荐…</p>
    <p v-else-if="showLoading" class="muted small">正在查找…</p>
    <p v-else-if="error" class="muted small failed" role="status">
      暂时无法读取相似衣物：{{ error }}
      <button type="button" class="btn ghost small" data-testid="similar-retry" @click="load(itemId)">重试</button>
    </p>
    <p v-if="result && !result.items.length && !updating && !showLoading" class="empty muted" data-testid="similar-empty">
      没有足够相似的持有中衣物（需要同类、同色或共有标签）。
    </p>
    <ul v-if="result && result.items.length && (updating || !showLoading)" class="grid" :class="{ stale: updating }">
      <li v-for="s in result.items" :key="s.item.id" :data-testid="`similar-${s.item.id}`">
        <ItemCard :item="s.item" />
        <ul class="reasons" :aria-label="`相似理由（${s.score} 分）`">
          <li v-for="r in s.reasons" :key="r.kind" class="chip">{{ r.label }}</li>
        </ul>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.similar {
  margin-top: 48px;
  border-top: 1px solid var(--line);
  padding-top: 24px;
}
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 14px;
  margin-bottom: 16px;
}
.head h2 {
  font-size: 18px;
}
.small {
  font-size: 12px;
}
.failed {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.empty {
  margin: 0;
  font-size: 14px;
}
.grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 24px 16px;
}
.grid > li {
  display: grid;
  gap: 8px;
  align-content: start;
  min-width: 0;
}
.grid.stale {
  opacity: 0.5;
}
.reasons {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
</style>
