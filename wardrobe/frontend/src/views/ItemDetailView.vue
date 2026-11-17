<script setup lang="ts">
import { t as translate } from "../i18n";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ApiError, api } from "../api/client";
import type { ImageInfo, ItemDetail, Proposal } from "../api/types";
import ColorDot from "../components/ColorDot.vue";
import ColorSuggestPanel from "../components/ColorSuggestPanel.vue";
import ImageGallery from "../components/ImageGallery.vue";
import ProposalList from "../components/ProposalList.vue";
import SimilarItems from "../components/SimilarItems.vue";
import TagSuggestPanel from "../components/TagSuggestPanel.vue";
import { errorMessage, isConflict } from "../lib/errors";
import { notify, type Toast } from "../lib/toast";
import { useDelayedLoading } from "../lib/useDelayedLoading";
import {
  COLOR_FAMILIES,
  FIBER_LABELS,
  GENDER_LABELS,
  PART_LABELS,
  SCHEME_LABELS,
  SOURCE_LABELS,
  STATUS_LABELS,
  label,
  yen,
} from "../lib/labels";

const props = defineProps<{ id: number }>();
const router = useRouter();
const item = ref<ItemDetail | null>(null);
const error = ref<{ status: number; message: () => string } | null>(null);
const loading = ref(true);
const showLoading = useDelayedLoading(loading);
const proposals = ref<Proposal[]>([]);
const busy = ref(false);
const actionError = ref<(() => string) | null>(null);
const returning = ref(false);
const analyzingColor = ref(false);
const suggestingTags = ref(false);
const returnForm = ref<{ returned_on: string; refund_amount: string | number }>({ returned_on: today(), refund_amount: "" });

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// 页面代次：切换到另一件衣物（同一组件实例被复用）或离开页面时加 1。
// 所有异步操作开始时记下代次，结果（成功、失败、finally）只在代次未变时作用于页面。
let pageGen = 0;
let proposalReq = 0;

async function loadProposals(id: number) {
  const req = ++proposalReq;
  const gen = pageGen;
  try {
    const page = await api.proposals({ entity: "wardrobe_item", entity_id: id });
    if (req === proposalReq && gen === pageGen) proposals.value = page.items;
  } catch {
    // 提议只是附加信息，读取失败不影响详情显示；旧请求的失败直接忽略
    if (req === proposalReq && gen === pageGen) proposals.value = [];
  }
}

let requestId = 0;
onBeforeUnmount(() => {
  requestId++;
  pageGen++;
  proposalReq++;
});
watch(
  () => props.id,
  () => {
    pageGen++;
    proposalReq++;
    item.value = null;
    busy.value = false;
    actionError.value = null;
    returning.value = false;
    returnForm.value = { returned_on: today(), refund_amount: "" };
    proposals.value = [];
  },
);

async function load() {
  const id = ++requestId;
  loading.value = true;
  error.value = null;
  if (!item.value) document.title = translate("衣物详情 · Wardrobe");
  try {
    const result = await api.item(props.id);
    if (id !== requestId) return;
    item.value = result;
    document.title = `${item.value.name} · Wardrobe`;
    void loadProposals(result.id);
  } catch (e) {
    if (id !== requestId) return;
    if (e instanceof ApiError && e.status === 404) item.value = null;
    error.value = e instanceof ApiError ? { status: e.status, message: () => errorMessage(e) } : { status: 0, message: () => errorMessage(e) };
  } finally {
    if (id === requestId) loading.value = false;
  }
}
watch(() => props.id, load, { immediate: true });
// 换到另一件衣物时收起颜色分析（面板也按衣物 id 重建，旧请求不会写到新衣物上）
watch(() => props.id, () => {
  analyzingColor.value = false;
  suggestingTags.value = false;
});

const product = computed(() => item.value?.product ?? null);
// 相似推荐的依据快照：任一项变化（含同一件衣物在页面内刷新）都会重新读取推荐
const similarBasis = computed(() => {
  const it = item.value;
  if (!it) return "";
  const c = it.resolved.color;
  return JSON.stringify([it.version, it.category?.id ?? null, c.family, c.hex, [...it.tags].sort()]);
});
// 衣物自己的照片在前，商品图在后；同一张图只出现一次
const images = computed<ImageInfo[]>(() => {
  if (!item.value) return [];
  const seen = new Set<number>();
  return [...item.value.images, ...(product.value?.images ?? [])].filter((img) => !seen.has(img.id) && seen.add(img.id));
});
const color = computed(() => item.value?.resolved.color ?? null);
// HEX-only 是照片建议的默认接受路径；有颜色事实时必须提供可读文字。
const colorText = computed(() => {
  const c = color.value;
  return c?.name || c?.hex || c?.code || COLOR_FAMILIES.find((f) => f.key === c?.family)?.label || c?.family || translate("未记录");
});
const size = computed(() => item.value?.resolved.size ?? null);
const line = computed(() => item.value?.purchase?.line ?? null);
const categoryLinks = computed(() => {
  const c = item.value?.category;
  return c ? c.path.map((name, i) => ({ name, slug: c.path_slugs[i] })) : [];
});

async function act(
  run: (it: ItemDetail) => Promise<ItemDetail>,
  done: string,
  undo?: (result: ItemDetail) => Toast["action"],
): Promise<boolean> {
  const target = item.value;
  if (!target || loading.value || error.value) return false;
  const gen = pageGen;
  busy.value = true;
  actionError.value = null;
  try {
    const result = await run(target);
    // 必须与当前页面比较：只比较 result.id 与开始时的 id 无法发现已切换到另一件衣物
    if (gen !== pageGen) return false;
    item.value = result;
    notify(done, { action: undo?.(result) });
    void loadProposals(result.id);
    return true;
  } catch (e) {
    if (gen !== pageGen) return false;
    actionError.value = () => errorMessage(e);
    if (isConflict(e)) await load();
    return false;
  } finally {
    if (gen === pageGen) busy.value = false;
  }
}

function wear() {
  const it = item.value;
  if (!it) return;
  const before = { wear_count: it.wear_count, last_worn_on: it.last_worn_on };
  return act((x) => api.wearItem(x.id, { version: x.version, worn_on: today() }), translate("已记录穿着一次"), (after) => ({
    label: translate("撤销"),
    run: () => undoWear(after, before),
  }));
}

// 用记录后的 version 改回原值：之后这件衣物又被修改过（包括再记一次穿着）时返回冲突，不会覆盖新的修改。
// 撤销总是针对原衣物；结果只影响点击撤销时的同一个页面（离开再回到同一件衣物是新的页面代次，只比较衣物 id 不够），
// 且不能用较旧的 version 覆盖页面上更新的状态。按路由判断目标，因为详情可能还在读取、item 为空。
async function undoWear(after: ItemDetail, before: Pick<ItemDetail, "wear_count" | "last_worn_on">) {
  const gen = pageGen;
  const onTarget = () => gen === pageGen && props.id === after.id;
  try {
    const restored = await api.updateItem(after.id, { version: after.version, ...before });
    if (onTarget()) {
      // 详情读取还在进行时，它可能是撤销之前的快照：重新读取，让旧响应作废
      if (loading.value || !item.value) void load();
      else if (item.value.version < restored.version) item.value = restored;
    }
    notify(translate("已撤销这次穿着记录"));
  } catch (e) {
    notify(isConflict(e) ? translate("这件衣物之后又被修改过，无法撤销；可在编辑页修改穿着次数") : errorMessage(e), { kind: "error" });
    if (isConflict(e) && onTarget()) await load();
  }
}
const toggleVerify = () =>
  act((it) => api.verifyItem(it.id, it.version, it.verification !== "verified"), item.value?.verification === "verified" ? translate("已取消核实") : translate("已标记为核实"));

async function submitReturn() {
  const gen = pageGen;
  // type=number 的 v-model 得到数字，空输入时是空字符串
  const refund = String(returnForm.value.refund_amount ?? "").trim();
  const ok = await act(
    (it) => api.returnItem(it.id, { version: it.version, returned_on: returnForm.value.returned_on, refund_amount: refund === "" ? null : Number(refund) }),
    translate("已记录退货"),
  );
  if (ok && gen === pageGen) returning.value = false;
}

async function remove() {
  const it = item.value;
  if (!it || loading.value || error.value || !window.confirm(translate("删除「{0}」？删除后可以立即撤销。", it.name))) return;
  const gen = pageGen;
  busy.value = true;
  actionError.value = null;
  try {
    await api.deleteItem(it.id, it.version);
    // 删除只把 version 加 1，撤销时用它恢复
    const deletedVersion = it.version + 1;
    notify(translate("已删除「{0}」", it.name), {
      action: {
        label: translate("撤销"),
        run: async () => {
          try {
            await api.restoreItem(it.id, deletedVersion);
            notify(translate("已恢复"));
            await router.push({ name: "item", params: { id: it.id } });
          } catch (e) {
            notify(errorMessage(e), { kind: "error" });
          }
        },
      },
    });
    // 删除完成时已经切到另一件衣物：保留可撤销的提示，但不把用户从当前页面带走
    if (gen === pageGen) await router.push("/");
  } catch (e) {
    if (gen === pageGen) actionError.value = () => errorMessage(e);
  } finally {
    if (gen === pageGen) busy.value = false;
  }
}

function back() {
  // 从衣橱列表进入时返回原来的筛选与滚动位置；直接打开详情页时回到衣橱首页
  if (window.history.state?.back) router.back();
  else router.push("/");
}
</script>

<template>
  <div class="detail" :aria-busy="loading">
    <button type="button" class="link-btn back" @click="back">{{ translate("← 返回") }}</button>

    <p class="load-feedback" role="status">{{ showLoading ? (item ? translate("正在刷新衣物…") : translate("正在加载衣物…")) : "" }}</p>
    <p v-if="error && item" class="error-banner" role="alert">{{ translate("刷新失败，仍显示上次读取的只读内容：") }}{{ error.message() }} <button type="button" class="link-btn" @click="load">{{ translate("重试刷新") }}</button></p>
    <div v-if="loading && !item" class="layout loading-shell" aria-hidden="true">
      <template v-if="showLoading">
        <div class="skeleton" style="aspect-ratio: 3 / 4" />
        <div class="info"><div class="skeleton" style="height: 160px" /></div>
      </template>
    </div>

    <div v-else-if="error && !item" class="state">
      <h1>{{ error.status === 404 ? translate("找不到这件衣物") : translate("加载失败") }}</h1>
      <p class="error-banner" role="alert">{{ error.message() }}</p>
      <RouterLink to="/" class="btn ghost">{{ translate("返回我的衣橱") }}</RouterLink>
    </div>

    <article v-else-if="item && product" class="layout" :inert="loading || !!error || undefined">
      <ImageGallery :images="images" :alt="item.name" :fallback-color="color?.hex" />

      <div class="info">
        <nav v-if="categoryLinks.length" class="crumbs" :aria-label='translate("分类")'>
          <template v-for="(c, i) in categoryLinks" :key="c.slug">
            <span v-if="i" aria-hidden="true">/</span>
            <RouterLink :to="{ name: 'wardrobe', query: { category: c.slug } }">{{ c.name }}</RouterLink>
          </template>
        </nav>
        <div class="brand">{{ product.brand?.name ?? translate("无品牌") }}</div>
        <h1>{{ item.name }}</h1>
        <p v-if="product.name_zh && product.name_zh !== item.name" class="name-zh">{{ product.name_zh }}</p>
        <div class="badges">
          <span v-if="item.status !== 'owned'" class="badge dark">{{ label(STATUS_LABELS, item.status) }}</span>
          <span v-if="item.verification === 'verified'" class="badge" :title='translate("关键资料已由本人核实")'>{{ translate("已核实") }}</span>
          <span v-if="product.origin === 'manual'" class="badge" :title='translate("没有官方资料，由用户自建")'>{{ translate("自建商品") }}</span>
          <span v-if="item.favorite" class="badge">{{ translate("收藏") }}</span>
        </div>

        <div class="item-actions actions">
          <RouterLink :to="{ name: 'item-edit', params: { id: item.id } }" class="btn small">{{ translate("编辑") }}</RouterLink>
          <button type="button" class="btn ghost small" :disabled="busy || loading || !!error" @click="wear">{{ translate("记一次穿着") }}</button>
          <button v-if="item.status === 'owned'" type="button" class="btn ghost small" :disabled="busy || loading || !!error" :aria-expanded="returning" @click="returning = !returning">{{ translate("退货…") }}</button>
          <button type="button" class="btn ghost small" :aria-expanded="analyzingColor" @click="analyzingColor = !analyzingColor">{{ translate("分析照片颜色") }}</button>
          <button type="button" class="btn ghost small" :aria-expanded="suggestingTags" @click="suggestingTags = !suggestingTags">{{ translate("建议标签/分类") }}</button>
          <button type="button" class="btn ghost small" :disabled="busy || loading || !!error" @click="toggleVerify">{{ item.verification === "verified" ? translate("取消核实") : translate("标记为已核实") }}</button>
          <button type="button" class="btn danger small" :disabled="busy || loading || !!error" @click="remove">{{ translate("删除") }}</button>
        </div>
        <form v-if="returning" class="return-form panel" @submit.prevent="submitReturn">
          <label class="field"><span>{{ translate("退货日期") }}</span><input v-model="returnForm.returned_on" type="date" required /></label>
          <label class="field"><span>{{ translate("退款金额（") }}{{ item.purchase?.currency ?? product.currency }}）</span><input v-model="returnForm.refund_amount" type="number" min="0" inputmode="numeric" /></label>
          <div class="actions">
            <button type="submit" class="btn small" :disabled="busy || loading || !!error">{{ translate("确认退货") }}</button>
            <button type="button" class="btn ghost small" @click="returning = false">{{ translate("取消") }}</button>
          </div>
          <p class="muted hint-small">{{ translate("只改这件衣物，购买记录保持原样。") }}</p>
        </form>
        <p v-if="actionError" class="error-banner" role="alert">{{ actionError?.() }}</p>
        <ColorSuggestPanel
          v-if="analyzingColor"
          :key="item.id"
          :item="item"
          @created="loadProposals(item.id)"
          @close="analyzingColor = false"
        />
        <TagSuggestPanel
          v-if="suggestingTags"
          :key="`tags-${item.id}`"
          :item="item"
          @created="loadProposals(item.id)"
          @close="suggestingTags = false"
        />
        <ProposalList v-if="proposals.length" :proposals="proposals" :title='translate("待确认的修改提议")' @changed="load" />

        <dl class="key-facts">
          <div>
            <dt>{{ translate("颜色") }}</dt>
            <dd>
              <span class="inline">
                <ColorDot :hex="color?.hex" :swatch="item?.color_swatch?.hex" :family="color?.family" :size="16" />
                {{ colorText }}<span v-if="color?.code && color.code !== colorText" class="muted">（{{ color.code }}）</span>
              </span>
              <span v-if="color?.source" class="source">{{ translate("来源：") }}{{ label(SOURCE_LABELS, color.source) }}</span>
            </dd>
          </div>
          <div>
            <dt>{{ translate("尺码") }}</dt>
            <dd>
              {{ size?.label ?? translate("未记录") }}
              <span v-if="size?.source" class="source">{{ translate("来源：") }}{{ label(SOURCE_LABELS, size.source) }}</span>
            </dd>
          </div>
          <div v-if="item.acquired_on">
            <dt>{{ translate("取得日期") }}</dt>
            <dd>{{ item.acquired_on }}</dd>
          </div>
          <div v-if="item.location">
            <dt>{{ translate("收纳位置") }}</dt>
            <dd>{{ item.location }}</dd>
          </div>
          <div>
            <dt>{{ translate("穿着") }}</dt>
            <dd>{{ item.wear_count }} {{ translate("次") }}<span v-if="item.last_worn_on" class="muted">{{ translate("（最近") }} {{ item.last_worn_on }}）</span></dd>
          </div>
          <div v-if="item.alterations">
            <dt>{{ translate("修改") }}</dt>
            <dd>{{ item.alterations }}</dd>
          </div>
          <div v-if="item.status === 'returned'">
            <dt>{{ translate("退货") }}</dt>
            <dd>
              {{ item.retired_on ?? "" }}<span v-if="item.refund_amount !== null">{{ translate("，退款") }} {{ yen(item.refund_amount, item.purchase?.currency ?? product.currency) }}</span>
            </dd>
          </div>
          <div v-else-if="item.retired_on">
            <dt>{{ translate("离开衣橱") }}</dt>
            <dd>{{ item.retired_on }}</dd>
          </div>
        </dl>

        <div v-if="item.tags.length" class="tags">
          <RouterLink
            v-for="t in item.tags"
            :key="t"
            class="chip"
            :to="{ name: 'wardrobe', query: { tag_exact: t } }"
          >
            #{{ t }}
          </RouterLink>
        </div>
        <p v-if="item.notes" class="notes">{{ item.notes }}</p>

        <section>
          <h2 class="with-link">{{ translate("商品信息") }} <RouterLink :to="{ name: 'product', params: { id: product.id } }" class="link-btn">{{ translate("查看 / 编辑商品资料") }}</RouterLink></h2>
          <dl class="table">
            <div v-for="ident in product.identifiers" :key="ident.id">
              <dt>{{ label(SCHEME_LABELS, ident.scheme) }}</dt>
              <dd class="mono">{{ ident.value }}</dd>
            </div>
            <div v-if="product.name_en">
              <dt>{{ translate("英文名") }}</dt>
              <dd>{{ product.name_en }}</dd>
            </div>
            <div v-if="product.gender">
              <dt>{{ translate("类别") }}</dt>
              <dd>{{ label(GENDER_LABELS, product.gender) }}</dd>
            </div>
            <div v-if="product.season_label">
              <dt>{{ translate("季节") }}</dt>
              <dd>{{ product.season_label }}</dd>
            </div>
            <div v-if="product.list_price !== null">
              <dt>{{ translate("标价") }}</dt>
              <dd>{{ yen(product.list_price, product.currency) }}</dd>
            </div>
            <div v-if="product.colors.length">
              <dt>{{ translate("商品颜色") }}</dt>
              <dd class="color-list">
                <span v-for="c in product.colors" :key="c.id" class="inline">
                  <ColorDot :hex="c.hex" :family="c.color_family" />
                  {{ c.name_ja ?? c.name_zh ?? c.color_code }}<span v-if="c.is_default" class="muted">{{ translate("（默认）") }}</span>
                </span>
              </dd>
            </div>
            <div v-if="product.sizes.length">
              <dt>{{ translate("商品尺码") }}</dt>
              <dd>{{ product.sizes.map((s) => s.size_label).join(" / ") }}</dd>
            </div>
            <div v-if="product.detail_url">
              <dt>{{ translate("详情页") }}</dt>
              <dd>
                <a :href="product.detail_url" target="_blank" rel="noopener noreferrer">{{ translate("在新窗口打开") }}</a>
              </dd>
            </div>
          </dl>
          <p v-if="product.description" class="desc">{{ product.description }}</p>
        </section>

        <section v-if="product.material_text || product.materials.length">
          <h2>{{ translate("材质") }}</h2>
          <p v-if="product.material_text" class="raw">{{ product.material_text }}</p>
          <table v-if="product.materials.length" class="materials">
            <thead>
              <tr><th>{{ translate("部位") }}</th><th>{{ translate("纤维") }}</th><th>{{ translate("比例") }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="(m, i) in product.materials" :key="i">
                <td>{{ m.part_raw ?? label(PART_LABELS, m.part) }}</td>
                <td>{{ label(FIBER_LABELS, m.fiber) }}<span v-if="m.fiber_raw" class="muted">（{{ m.fiber_raw }}）</span></td>
                <td class="num">{{ m.percent !== null ? `${m.percent}%` : "" }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section v-if="product.care_text || product.care_symbols.length">
          <h2>{{ translate("保养") }}</h2>
          <p v-if="product.care_text">{{ product.care_text }}</p>
          <p v-if="product.care_symbols.length" class="muted">{{ product.care_symbols.join("、") }}</p>
        </section>

        <section v-if="item.purchase && line">
          <h2 class="with-link">{{ translate("购买记录") }} <RouterLink :to="{ name: 'purchase', params: { id: item.purchase.purchase_id } }" class="link-btn">{{ translate("打开购买记录") }}</RouterLink></h2>
          <dl class="table">
            <div>
              <dt>{{ translate("日期") }}</dt>
              <dd>{{ item.purchase.purchased_on }}</dd>
            </div>
            <div v-if="item.purchase.store_name">
              <dt>{{ translate("店铺") }}</dt>
              <dd>{{ item.purchase.store_name }}</dd>
            </div>
            <div v-if="line.item_code_raw">
              <dt>{{ translate("小票编号") }}</dt>
              <dd class="mono">{{ line.item_code_raw }}</dd>
            </div>
            <div v-if="line.name_raw">
              <dt>{{ translate("小票名称") }}</dt>
              <dd>{{ line.name_raw }}</dd>
            </div>
            <div v-if="line.color_name || line.color_code">
              <dt>{{ translate("购买颜色") }}</dt>
              <dd>{{ line.color_name ?? "" }}<span v-if="line.color_code" class="muted">（{{ line.color_code }}）</span></dd>
            </div>
            <div v-if="line.size_label">
              <dt>{{ translate("购买尺码") }}</dt>
              <dd>{{ line.size_label }}</dd>
            </div>
            <div v-if="line.unit_price !== null">
              <dt>{{ translate("单价") }}</dt>
              <dd>
                {{ yen(line.unit_price, item.purchase.currency) }}
                <span v-if="line.discount_amount" class="muted">{{ translate("（折扣") }} {{ yen(line.discount_amount, item.purchase.currency) }}）</span>
              </dd>
            </div>
            <div>
              <dt>{{ translate("数量") }}</dt>
              <dd>{{ line.quantity }} {{ translate("件") }}<span v-if="line.returned_quantity" class="muted">{{ translate("（已退") }} {{ line.returned_quantity }}）</span></dd>
            </div>
          </dl>
        </section>

        <section v-if="item.outfits.length">
          <h2>{{ translate("所在穿搭") }}</h2>
          <ul class="outfits">
            <li v-for="o in item.outfits" :key="o.id"><RouterLink :to="{ name: 'outfit', params: { id: o.id } }">{{ o.name }}</RouterLink></li>
          </ul>
        </section>

        <p class="updated muted">{{ translate("衣物编号") }} {{ item.id }} {{ translate("· 版本") }} {{ item.version }} {{ translate("· 最近更新") }} {{ item.updated_at.replace("T", " ").replace("Z", " UTC") }}</p>
      </div>
    </article>
    <SimilarItems v-if="item && product" :key="item.id" :item-id="item.id" :basis="similarBasis" />
  </div>
</template>

<style scoped>
.detail {
  overflow-wrap: anywhere;
}
.info > *, section > *, dd, .inline {
  min-width: 0;
}
.tags .chip {
  max-width: 100%;
}
.materials {
  table-layout: fixed;
}
.detail {
  max-width: 1280px;
  margin: 0 auto;
  padding: 20px 24px 72px;
}
.back {
  margin-bottom: 16px;
}
.return-form {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
  align-items: end;
  margin: 0;
}
.return-form .actions,
.return-form .hint-small {
  grid-column: 1 / -1;
  margin: 0;
  font-size: 12px;
}
.with-link {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 12px;
}
.with-link .link-btn {
  font-weight: 400;
}
.layout {
  display: grid;
  grid-template-columns: minmax(0, 11fr) minmax(0, 9fr);
  gap: 56px;
  align-items: start;
}
.layout > :first-child {
  position: sticky;
  top: calc(var(--header-h) + 20px);
}
.state {
  display: grid;
  gap: 16px;
  justify-items: start;
  padding: 48px 0;
}
.info {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 18px;
  min-width: 0;
}
.crumbs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 13px;
  color: var(--ink-3);
}
.crumbs a {
  color: var(--ink-2);
}
.brand {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  color: var(--ink-3);
  text-transform: uppercase;
}
h1 {
  font-size: 28px;
  line-height: 1.35;
  margin-top: -10px;
}
.name-zh {
  margin: -12px 0 0;
  color: var(--ink-2);
}
.badges {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.badges:empty {
  display: none;
}
.badge {
  border: 1px solid var(--line-strong);
  padding: 1px 8px;
  font-size: 12px;
  color: var(--ink-2);
}
.badge.dark {
  background: var(--ink);
  border-color: var(--ink);
  color: #fff;
}
.key-facts,
.table {
  margin: 0;
  display: grid;
  border-top: 1px solid var(--line);
}
.key-facts > div,
.table > div {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
dt {
  color: var(--ink-3);
  font-size: 13px;
}
dd {
  margin: 0;
  font-size: 14px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 10px;
}
.inline {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.source {
  font-size: 12px;
  color: var(--ink-3);
}
.tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.tags .chip {
  text-decoration: none;
  font-size: 13px;
}
.notes,
.desc {
  margin: 0;
  white-space: pre-wrap;
  color: var(--ink-2);
}
section {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
  padding-top: 10px;
}
h2 {
  font-size: 16px;
}
.raw {
  margin: 0;
  font-size: 14px;
  color: var(--ink-2);
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
}
.color-list {
  gap: 4px 16px;
}
.materials {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}
.materials th,
.materials td {
  text-align: left;
  padding: 8px 0;
  border-bottom: 1px solid var(--line);
}
.materials th {
  font-weight: 400;
  color: var(--ink-3);
  font-size: 13px;
}
.num {
  text-align: right !important;
  font-variant-numeric: tabular-nums;
}
.outfits {
  margin: 0;
  padding-left: 18px;
}
.updated {
  font-size: 12px;
  margin: 8px 0 0;
}
@media (max-width: 900px) {
  .detail {
    padding: 16px 16px 48px;
  }
  .layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 24px;
  }
  .layout > :first-child {
    position: static;
  }
  h1 {
    font-size: 22px;
  }
}
</style>
