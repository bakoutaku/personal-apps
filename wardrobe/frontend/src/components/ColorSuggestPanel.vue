<script setup lang="ts">
import { t as translate } from "../i18n";
// Phase 5A-2：从这件衣物自己的一张照片得到颜色候选 → 预览颜色整组的改动 → 生成待确认提议。
// 只生成提议，不修改衣物；接受/拒绝仍在提议列表中进行。接口见 docs/PHASE5A_BACKEND_CONTRACT.md。
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { api } from "../api/client";
import type { ColorAnalysis, ColorRegion, ImageInfo, ItemDetail, Proposal } from "../api/types";
import { errorMessage } from "../lib/errors";
import { COLOR_FAMILIES, SOURCE_LABELS, label } from "../lib/labels";
import ColorDot from "./ColorDot.vue";

const props = defineProps<{ item: ItemDetail }>();
const emit = defineEmits<{ created: [proposal: Proposal]; close: [] }>();

const ownImages = computed<ImageInfo[]>(() => props.item.images);
const imageId = ref<number | null>(ownImages.value.find((i) => i.role === "main")?.id ?? ownImages.value[0]?.id ?? null);
const image = computed(() => ownImages.value.find((i) => i.id === imageId.value) ?? null);
const region = ref<ColorRegion | null>(null);
const analysis = ref<ColorAnalysis | null>(null);
const analyzing = ref(false);
const generating = ref(false);
const error = ref<(() => string) | null>(null);
const chosen = ref<string | null>(null);
const colorName = ref("");
const colorCode = ref("");
const created = ref<Proposal | null>(null);

// 请求代次：换图片、改区域、重新分析、离开页面后，旧请求的结果（成功或失败）都不再生效。
// 生成提议另有自己的代次：生成后（或生成进行中）改了候选、名称、编号，旧的「已生成」不再代表当前预览。
let generation = 0;
let submission = 0;
let alive = true;
onBeforeUnmount(() => {
  alive = false;
  generation++;
  submission++;
});

function invalidate() {
  generation++;
  submission++;
  generating.value = false;
  analysis.value = null;
  chosen.value = null;
  error.value = null;
  analyzing.value = false;
}
watch(imageId, () => {
  region.value = null;
  created.value = null;
  // 名称和编号通常只适用于上一张照片里的衣物，换照片时一并清空
  colorName.value = "";
  colorCode.value = "";
  invalidate();
});
watch([chosen, colorName, colorCode], () => {
  if (!created.value && !generating.value) return;
  submission++;
  generating.value = false;
  created.value = null;
});
// 当前图片被移除时，回到仍存在的图片
watch(ownImages, (list) => {
  if (!list.some((i) => i.id === imageId.value)) imageId.value = list[0]?.id ?? null;
});

async function analyze() {
  if (imageId.value === null) return;
  const gen = ++generation;
  analyzing.value = true;
  error.value = null;
  analysis.value = null;
  chosen.value = null;
  created.value = null;
  try {
    const result = await api.colorAnalysis(props.item.id, imageId.value, region.value);
    if (gen !== generation) return;
    analysis.value = result;
    chosen.value = result.candidates[0]?.hex ?? null;
  } catch (e) {
    if (gen === generation) error.value = () => errorMessage(e);
  } finally {
    if (gen === generation) analyzing.value = false;
  }
}

// 分析之后衣物有任何修改（例如记一次穿着），服务端会拒绝用旧版本生成建议，界面提前提示
const outdated = computed(() => analysis.value !== null && analysis.value.item_version !== props.item.version);

const proposed = computed(() => ({
  color_code: colorCode.value.trim() || null,
  color_name: colorName.value.trim() || null,
  color_hex: chosen.value,
}));
const current = computed(() => analysis.value?.current_color ?? { color_code: props.item.color_code, color_name: props.item.color_name, color_hex: props.item.color_hex });
const unchanged = computed(
  () => current.value.color_code === proposed.value.color_code && current.value.color_name === proposed.value.color_name && current.value.color_hex === proposed.value.color_hex,
);

async function generate() {
  const a = analysis.value;
  if (!a || !chosen.value || outdated.value) return;
  const sub = ++submission;
  generating.value = true;
  error.value = null;
  try {
    const out = await api.colorSuggestion(props.item.id, {
      version: a.item_version,
      image_id: a.image_id,
      region: a.region,
      candidate_hex: chosen.value,
      color_code: proposed.value.color_code,
      color_name: proposed.value.color_name,
    });
    if (sub !== submission) {
      // 输入已改变：不再显示「已生成」，但服务器上确实新建了提议，仍刷新列表让它可见
      if (alive) emit("created", out.proposal);
      return;
    }
    created.value = out.proposal;
    emit("created", out.proposal);
  } catch (e) {
    if (sub === submission) error.value = () => errorMessage(e);
  } finally {
    if (sub === submission) generating.value = false;
  }
}

// ── 区域选择：在图片上拖出矩形；坐标为方向修正后整图的 0～1 比例（与后端一致）──
const frame = ref<HTMLElement | null>(null);
let start: { x: number; y: number } | null = null;
const draft = ref<ColorRegion | null>(null);

function point(e: PointerEvent) {
  const r = frame.value!.getBoundingClientRect();
  return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
}
function down(e: PointerEvent) {
  if (!frame.value) return;
  start = point(e);
  draft.value = null;
  frame.value.setPointerCapture?.(e.pointerId);
}
function move(e: PointerEvent) {
  if (!start) return;
  const p = point(e);
  draft.value = { x: Math.min(start.x, p.x), y: Math.min(start.y, p.y), w: Math.abs(p.x - start.x), h: Math.abs(p.y - start.y) };
}
function up() {
  // 太小的拖动视为点击，不改变区域
  if (draft.value && draft.value.w >= 0.02 && draft.value.h >= 0.02) setRegion(draft.value);
  start = null;
  draft.value = null;
}
const round4 = (v: number) => Math.round(v * 10000) / 10000;
function setRegion(r: ColorRegion | null) {
  region.value = r && { x: round4(r.x), y: round4(r.y), w: round4(Math.min(r.w, 1 - r.x)), h: round4(Math.min(r.h, 1 - r.y)) };
  created.value = null;
  invalidate();
}
// 键盘/精确输入：以百分比编辑区域
const pct = computed(() => region.value ?? { x: 0, y: 0, w: 1, h: 1 });
function setPct(key: keyof ColorRegion, value: string) {
  const n = Number(value) / 100;
  if (!Number.isFinite(n)) return;
  const next = { ...pct.value, [key]: Math.min(1, Math.max(key === "w" || key === "h" ? 0.01 : 0, n)) };
  next.w = Math.min(next.w, 1 - next.x);
  next.h = Math.min(next.h, 1 - next.y);
  setRegion(next.w > 0 && next.h > 0 ? next : null);
}
const shown = computed(() => draft.value ?? region.value);
const box = (r: ColorRegion) => ({ left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%` });

const familyLabel = (f: string | null) => COLOR_FAMILIES.find((c) => c.key === f)?.label ?? f ?? "";
const reasonText = (r: string | null) =>
  r === "no_opaque_pixels" ? translate("所选区域全部是透明像素。") : r === "no_dominant_color" ? translate("没有占比达到 3% 的颜色（例如细碎花纹），无法给出候选。") : "";
const show = (v: string | null) => v ?? translate("（空）");
</script>

<template>
  <section class="panel color-panel" :aria-label='translate("分析照片颜色")'>
    <div class="panel-head">
      <h2>{{ translate("分析照片颜色") }}</h2>
      <button type="button" class="link-btn" @click="emit('close')">{{ translate("收起") }}</button>
    </div>
    <p class="note">
      {{ translate("根据照片像素统计颜色候选（本地计算，不上传图片），") }}<strong>{{ translate("可能受背景和光线影响") }}</strong>{{ translate("。占比只是该颜色在所选区域中的像素比例，不代表准确率。 生成的是待确认提议，接受之前不会修改这件衣物。") }}
    </p>

    <p v-if="!ownImages.length" class="muted">
      {{ translate("这件衣物还没有自己的照片。请先在") }}
      <RouterLink :to="{ name: 'item-edit', params: { id: item.id } }">{{ translate("编辑页") }}</RouterLink>
      {{ translate("上传照片（商品图可能是其他色款，因此不用于分析）。") }}
    </p>

    <template v-else>
      <div class="pick-image" role="radiogroup" :aria-label='translate("选择照片")'>
        <label v-for="img in ownImages" :key="img.id" class="thumb" :class="{ on: img.id === imageId }">
          <input v-model="imageId" type="radio" name="color-image" :value="img.id" class="visually-hidden" />
          <img :src="img.thumb_url" :alt="translate('照片 {0}', img.id)" />
        </label>
      </div>

      <div v-if="image" class="workspace">
        <div>
          <div
            ref="frame"
            class="frame"
            data-testid="region-frame"
            @pointerdown.prevent="down"
            @pointermove="move"
            @pointerup="up"
            @pointercancel="up"
          >
            <img :src="image.url" :alt='translate("用于分析的原图")' draggable="false" />
            <div v-if="shown" class="region" :style="box(shown)" />
          </div>
          <p class="muted small">{{ translate("在图片上拖动可只分析衣物所在的区域。") }}</p>
          <details class="exact">
            <summary>{{ translate("精确输入区域（%）") }}</summary>
            <div class="exact-grid">
              <label v-for="k in ['x', 'y', 'w', 'h'] as const" :key="k" class="field">
                <span>{{ { x: translate("左"), y: translate("上"), w: translate("宽"), h: translate("高") }[k] }}</span>
                <input type="number" min="0" max="100" step="1" :value="Math.round(pct[k] * 100)" @change="setPct(k, ($event.target as HTMLInputElement).value)" />
              </label>
            </div>
          </details>
          <div class="actions">
            <span class="small">{{ region ? translate("区域：左 {0}% 上 {1}% 宽 {2}% 高 {3}%", Math.round(region.x * 100), Math.round(region.y * 100), Math.round(region.w * 100), Math.round(region.h * 100)) : translate("整张图片") }}</span>
            <button v-if="region" type="button" class="link-btn" @click="setRegion(null)">{{ translate("使用整张图片") }}</button>
          </div>
        </div>

        <div class="results">
          <button type="button" class="btn small" :disabled="analyzing" @click="analyze">{{ analyzing ? translate("分析中…") : analysis ? translate("重新分析") : translate("分析颜色") }}</button>
          <p v-if="error" class="error-banner" role="alert">{{ error?.() }}</p>

          <template v-if="analysis">
            <p v-if="analysis.status === 'no_suggestion'" class="muted" data-testid="no-suggestion">{{ translate("没有颜色候选：") }}{{ reasonText(analysis.reason) }}</p>
            <template v-else>
              <p class="muted small">{{ translate("算法") }} {{ analysis.algorithm }}{{ translate("；选择一个候选：") }}</p>
              <p v-if="!analysis.region" class="muted small hint-bg">{{ translate("分析的是整张照片，排第一的颜色可能是背景；可以先在图片上框选衣物再分析。") }}</p>
              <div class="candidates" role="radiogroup" :aria-label='translate("颜色候选")'>
                <label v-for="c in analysis.candidates" :key="c.hex" class="cand" :class="{ on: chosen === c.hex }" :data-testid="`cand-${c.hex}`">
                  <input v-model="chosen" type="radio" name="color-cand" :value="c.hex" class="visually-hidden" />
                  <span class="swatch" :style="{ background: c.hex }" />
                  <span class="cand-text">
                    <strong>{{ c.hex }}</strong>
                    <span class="muted">{{ familyLabel(c.color_family) }} {{ translate("· 像素占比") }} {{ Math.round(c.pixel_share * 100) }}%</span>
                  </span>
                </label>
              </div>

              <div class="names">
                <label class="field"><span>{{ translate("颜色名称（可选）") }}</span><input v-model="colorName" :placeholder='translate("例如 NAVY")' /></label>
                <label class="field"><span>{{ translate("颜色编号（可选）") }}</span><input v-model="colorCode" :placeholder='translate("例如 69")' /></label>
              </div>
              <p class="muted small">{{ translate("编号和名称不会根据颜色自动推测；留空时，接受后会清空衣物原来的对应值。") }}</p>

              <table class="data preview" :aria-label='translate("颜色整组的前后对比")'>
                <thead><tr><th></th><th>{{ translate("衣物颜色覆盖（当前）") }}</th><th>{{ translate("接受后写入") }}</th></tr></thead>
                <tbody>
                  <tr><th>{{ translate("颜色值") }}</th><td><ColorDot :hex="current.color_hex" :size="12" /> {{ show(current.color_hex) }}</td><td><ColorDot :hex="proposed.color_hex" :size="12" /> {{ show(proposed.color_hex) }}</td></tr>
                  <tr><th>{{ translate("名称") }}</th><td>{{ show(current.color_name) }}</td><td :class="{ clears: current.color_name && !proposed.color_name }">{{ show(proposed.color_name) }}</td></tr>
                  <tr><th>{{ translate("编号") }}</th><td>{{ show(current.color_code) }}</td><td :class="{ clears: current.color_code && !proposed.color_code }">{{ show(proposed.color_code) }}</td></tr>
                </tbody>
              </table>
              <p class="muted small">
                {{ translate("当前有效颜色：") }}<ColorDot :hex="analysis.resolved_color.hex" :family="analysis.resolved_color.family" :size="12" />
                {{ analysis.resolved_color.name ?? analysis.resolved_color.hex ?? translate("未记录") }}{{ translate("（来源：") }}{{ label(SOURCE_LABELS, analysis.resolved_color.source) || translate("无") }}{{ translate("）。 衣物自己的颜色优先于购买记录和商品默认值，接受后有效颜色将来自「手动指定」。购买记录和商品资料不会改变。") }}
              </p>

              <p v-if="outdated" class="error-banner" role="alert">{{ translate("分析之后这件衣物已被修改，请重新分析后再生成提议。") }}</p>
              <p v-if="created" class="done" role="status">{{ translate("已生成待确认提议 #") }}{{ created.proposal_id }}{{ translate("（尚未应用），可在下方提议列表中接受或拒绝。") }}</p>
              <button
                v-else
                type="button"
                class="btn"
                :disabled="generating || !chosen || outdated || unchanged"
                @click="generate"
              >
                {{ generating ? translate("生成中…") : unchanged ? translate("与当前颜色相同") : translate("生成待确认提议") }}
              </button>
            </template>
          </template>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.color-panel {
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
.pick-image {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.thumb {
  width: 56px;
  aspect-ratio: 3 / 4;
  border: 2px solid transparent;
  cursor: pointer;
}
.thumb.on {
  border-color: var(--ink);
}
.thumb:focus-within {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}
.frame {
  position: relative;
  max-width: 320px;
  touch-action: none;
  user-select: none;
  cursor: crosshair;
  background: var(--image-bg);
  /* 区域外的暗色遮罩只覆盖图片本身 */
  overflow: hidden;
}
.frame img {
  display: block;
  width: 100%;
  height: auto;
  pointer-events: none;
}
.region {
  position: absolute;
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px var(--ink), 0 0 0 9999px rgba(0, 0, 0, 0.35);
  pointer-events: none;
}
.exact summary {
  cursor: pointer;
  font-size: 13px;
}
.exact-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 6px;
}
.results {
  display: grid;
  gap: 10px;
  align-content: start;
  justify-items: start;
  min-width: 0;
}
.candidates {
  display: grid;
  gap: 6px;
  width: 100%;
}
.cand {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 6px 8px;
  border: 1px solid var(--line);
  cursor: pointer;
}
.cand.on {
  border-color: var(--ink);
  box-shadow: inset 3px 0 0 var(--ink);
}
.cand:focus-within {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
.swatch {
  width: 28px;
  height: 28px;
  border: 1px solid var(--line-strong);
  flex-shrink: 0;
}
.cand-text {
  display: grid;
  font-size: 13px;
}
.names {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
}
.preview {
  font-size: 13px;
}
.preview th:first-child {
  white-space: nowrap;
}
.clears {
  color: var(--danger);
}
.done {
  border: 1px solid #b9d7b9;
  background: #eef7ee;
  padding: 8px 12px;
  font-size: 13px;
  margin: 0;
}
@media (min-width: 1100px) {
  .workspace {
    grid-template-columns: minmax(0, 320px) minmax(0, 1fr);
  }
}
</style>
