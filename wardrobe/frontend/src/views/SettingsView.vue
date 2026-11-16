<script setup lang="ts">
// 设置：品牌、分类、标签字典与数据（备份、导出、系统信息）。字典没有 version，采用「后写生效」。
import { computed, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "../api/client";
import type { Backup, Brand, CategoryNode, Meta, Tag } from "../api/types";
import { dict, refreshDictionaries } from "../lib/dictionaries";
import { errorMessage } from "../lib/errors";
import { formatBytes } from "../lib/format";
import { ENTITY_LABELS, TAG_KIND_LABELS, label } from "../lib/labels";
import { notify } from "../lib/toast";

const TABS = [
  { key: "brands", label: "品牌" },
  { key: "categories", label: "分类" },
  { key: "tags", label: "标签" },
  { key: "data", label: "数据与备份" },
] as const;
type TabKey = (typeof TABS)[number]["key"];
const route = useRoute();
const router = useRouter();
const tab = computed<TabKey>(() => (TABS.some((t) => t.key === route.query.tab) ? (route.query.tab as TabKey) : "brands"));
const setTab = (key: TabKey) => router.replace({ query: key === "brands" ? {} : { tab: key } });

const error = ref<string | null>(null);
const busy = ref(false);

async function act(fn: () => Promise<unknown>, done: string, after?: () => void) {
  busy.value = true;
  error.value = null;
  try {
    await fn();
    notify(done);
    after?.();
    await refreshDictionaries();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}

void refreshDictionaries();

// ── 品牌 ──
const newBrand = reactive({ slug: "", name: "", name_ja: "", name_zh: "", website: "" });
const editingBrand = ref<number | null>(null);
const brandEdit = reactive({ name: "", name_ja: "", name_zh: "", website: "" });
const opt = (v: string) => (v.trim() ? v.trim() : null);

function startBrand(b: Brand) {
  editingBrand.value = b.id;
  Object.assign(brandEdit, { name: b.name, name_ja: b.name_ja ?? "", name_zh: b.name_zh ?? "", website: b.website ?? "" });
}
const saveBrand = (b: Brand) =>
  act(() => api.updateBrand(b.id, { name: brandEdit.name.trim(), name_ja: opt(brandEdit.name_ja), name_zh: opt(brandEdit.name_zh), website: opt(brandEdit.website) }), "已保存品牌", () => (editingBrand.value = null));
const addBrand = () =>
  act(
    () => api.createBrand({ slug: newBrand.slug.trim(), name: newBrand.name.trim(), name_ja: opt(newBrand.name_ja), name_zh: opt(newBrand.name_zh), website: opt(newBrand.website) }),
    "已添加品牌",
    () => Object.assign(newBrand, { slug: "", name: "", name_ja: "", name_zh: "", website: "" }),
  );

// ── 分类 ──
interface Row { node: CategoryNode; depth: number }
const rows = computed<Row[]>(() => {
  const out: Row[] = [];
  const walk = (nodes: CategoryNode[], depth: number) => nodes.forEach((n) => { out.push({ node: n, depth }); walk(n.children, depth + 1); });
  walk(dict.categories, 0);
  return out;
});
const editingCat = ref<number | null>(null);
const catEdit = reactive({ name_zh: "", name_ja: "", parent: "" as string | number, sort_order: 0 });
const addingUnder = ref<number | "root" | null>(null);
const newCat = reactive({ slug: "", name_zh: "", name_ja: "" });

function descendants(n: CategoryNode): number[] {
  return [n.id, ...n.children.flatMap(descendants)];
}
// 移动目标不能是自己或子孙；深度上限 3 由后端校验
const parentChoices = (n: CategoryNode) => rows.value.filter((r) => !descendants(n).includes(r.node.id) && r.depth < 2);

function startCat(n: CategoryNode) {
  editingCat.value = n.id;
  const flat = dict.flatCategories.find((c) => c.id === n.id);
  Object.assign(catEdit, { name_zh: n.name_zh, name_ja: n.name_ja ?? "", parent: n.parent_id ?? "", sort_order: flat?.sort_order ?? 0 });
}
function saveCat(n: CategoryNode) {
  const body: Record<string, unknown> = { name_zh: catEdit.name_zh.trim(), name_ja: opt(catEdit.name_ja), sort_order: Number(catEdit.sort_order) || 0 };
  const parent = catEdit.parent === "" ? null : Number(catEdit.parent);
  if (parent !== n.parent_id) body.parent = parent;
  return act(() => api.updateCategory(n.id, body), "已保存分类", () => (editingCat.value = null));
}
const deleteCat = (n: CategoryNode) => {
  if (window.confirm(`删除分类「${n.name_zh}」？有子分类或仍被使用时不能删除。`)) void act(() => api.deleteCategory(n.id), "已删除分类");
};
const addCat = () =>
  act(
    () => api.createCategory({ slug: newCat.slug.trim(), name_zh: newCat.name_zh.trim(), name_ja: opt(newCat.name_ja), ...(addingUnder.value !== "root" ? { parent: addingUnder.value } : {}) }),
    "已添加分类",
    () => {
      addingUnder.value = null;
      Object.assign(newCat, { slug: "", name_zh: "", name_ja: "" });
    },
  );

// ── 标签 ──
const editingTag = ref<number | null>(null);
const tagEdit = reactive({ name: "", kind: "free", color_hex: "" });
function startTag(t: Tag) {
  editingTag.value = t.id;
  Object.assign(tagEdit, { name: t.name, kind: t.kind, color_hex: t.color_hex ?? "" });
}
const saveTag = (t: Tag) =>
  act(() => api.updateTag(t.id, { name: tagEdit.name.trim(), kind: tagEdit.kind, color_hex: opt(tagEdit.color_hex) }), "已保存标签", () => (editingTag.value = null));
const deleteTag = (t: Tag) => {
  if (window.confirm(`删除标签「${t.name}」？`)) void act(() => api.deleteTag(t.id), "已删除标签");
};

// ── 数据 ──
const backups = ref<Backup[]>([]);
const meta = ref<Meta | null>(null);
async function loadData() {
  try {
    const [b, m] = await Promise.all([api.backups(), api.meta()]);
    backups.value = b.items;
    meta.value = m;
  } catch (e) {
    error.value = errorMessage(e);
  }
}
watch(tab, (t) => { if (t === "data") void loadData(); }, { immediate: true });

const backupNow = () => act(() => api.createBackup(), "已创建备份", () => void loadData());

async function exportJson() {
  busy.value = true;
  error.value = null;
  try {
    const data = await api.exportAll();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const d = new Date();
    a.href = url;
    a.download = `wardrobe-export-${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="page">
    <div class="page-head"><h1>设置</h1></div>
    <div class="tabs" role="tablist">
      <button v-for="t in TABS" :key="t.key" type="button" role="tab" :aria-selected="tab === t.key" @click="setTab(t.key)">{{ t.label }}</button>
    </div>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <p v-if="dict.error" class="error-banner" role="alert">{{ dict.error }}</p>

    <!-- 品牌 -->
    <template v-if="tab === 'brands'">
      <section class="panel">
        <div class="table-wrap">
          <table class="data">
            <thead><tr><th>标识</th><th>名称</th><th>日文名</th><th>中文名</th><th>网站</th><th></th></tr></thead>
            <tbody>
              <tr v-for="b in dict.brands" :key="b.id">
                <td><code>{{ b.slug }}</code></td>
                <template v-if="editingBrand === b.id">
                  <td><input v-model="brandEdit.name" class="input" aria-label="名称" /></td>
                  <td><input v-model="brandEdit.name_ja" class="input" aria-label="日文名" /></td>
                  <td><input v-model="brandEdit.name_zh" class="input" aria-label="中文名" /></td>
                  <td><input v-model="brandEdit.website" class="input" aria-label="网站" /></td>
                  <td class="nowrap">
                    <button type="button" class="btn small" :disabled="busy || !brandEdit.name.trim()" @click="saveBrand(b)">保存</button>
                    <button type="button" class="link-btn" @click="editingBrand = null">取消</button>
                  </td>
                </template>
                <template v-else>
                  <td>{{ b.name }}</td>
                  <td>{{ b.name_ja }}</td>
                  <td>{{ b.name_zh }}</td>
                  <td class="url">{{ b.website }}</td>
                  <td><button type="button" class="link-btn" @click="startBrand(b)">编辑</button></td>
                </template>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <form class="panel" @submit.prevent="addBrand">
        <h2>添加品牌</h2>
        <div class="form-grid">
          <label class="field"><span>标识（小写字母、数字、-）</span><input v-model="newBrand.slug" pattern="[a-z0-9][a-z0-9\-]*" placeholder="例如 muji" /></label>
          <label class="field"><span>名称</span><input v-model="newBrand.name" /></label>
          <label class="field"><span>日文名</span><input v-model="newBrand.name_ja" /></label>
          <label class="field"><span>中文名</span><input v-model="newBrand.name_zh" /></label>
          <label class="field"><span>网站</span><input v-model="newBrand.website" type="url" /></label>
        </div>
        <div class="form-actions"><button type="submit" class="btn" :disabled="busy || !newBrand.slug.trim() || !newBrand.name.trim()">添加</button></div>
      </form>
    </template>

    <!-- 分类 -->
    <section v-if="tab === 'categories'" class="panel">
      <div class="panel-head">
        <h2>分类（最多三级）</h2>
        <button type="button" class="btn ghost small" @click="addingUnder = 'root'">添加一级分类</button>
      </div>
      <form v-if="addingUnder === 'root'" class="sub-form" @submit.prevent="addCat">
        <input v-model="newCat.name_zh" class="input" placeholder="中文名" aria-label="中文名" />
        <input v-model="newCat.name_ja" class="input" placeholder="日文名（可选）" aria-label="日文名" />
        <input v-model="newCat.slug" class="input" placeholder="标识，例如 tops-polo" aria-label="标识" />
        <button type="submit" class="btn small" :disabled="busy || !newCat.slug.trim() || !newCat.name_zh.trim()">添加</button>
        <button type="button" class="link-btn" @click="addingUnder = null">取消</button>
      </form>
      <ul class="tree">
        <li v-for="r in rows" :key="r.node.id" :style="{ paddingLeft: `${r.depth * 24}px` }">
          <template v-if="editingCat === r.node.id">
            <form class="sub-form" @submit.prevent="saveCat(r.node)">
              <input v-model="catEdit.name_zh" class="input" aria-label="中文名" />
              <input v-model="catEdit.name_ja" class="input" placeholder="日文名" aria-label="日文名" />
              <select v-model="catEdit.parent" class="input" aria-label="上级分类">
                <option value="">（一级分类）</option>
                <option v-for="p in parentChoices(r.node)" :key="p.node.id" :value="p.node.id">{{ "　".repeat(p.depth) }}{{ p.node.name_zh }}</option>
              </select>
              <input v-model="catEdit.sort_order" class="input narrow" type="number" aria-label="排序" title="排序" />
              <button type="submit" class="btn small" :disabled="busy || !catEdit.name_zh.trim()">保存</button>
              <button type="button" class="link-btn" @click="editingCat = null">取消</button>
            </form>
          </template>
          <div v-else class="cat-row">
            <span><strong>{{ r.node.name_zh }}</strong> <span class="muted">{{ r.node.name_ja ?? "" }} · <code>{{ r.node.slug }}</code></span></span>
            <span class="row-actions">
              <button type="button" class="link-btn" @click="startCat(r.node)">编辑/移动</button>
              <button v-if="r.depth < 2" type="button" class="link-btn" @click="addingUnder = r.node.id">添加子分类</button>
              <button type="button" class="link-btn" @click="deleteCat(r.node)">删除</button>
            </span>
          </div>
          <form v-if="addingUnder === r.node.id" class="sub-form" @submit.prevent="addCat">
            <input v-model="newCat.name_zh" class="input" placeholder="中文名" aria-label="子分类中文名" />
            <input v-model="newCat.name_ja" class="input" placeholder="日文名（可选）" aria-label="子分类日文名" />
            <input v-model="newCat.slug" class="input" placeholder="标识" aria-label="子分类标识" />
            <button type="submit" class="btn small" :disabled="busy || !newCat.slug.trim() || !newCat.name_zh.trim()">添加</button>
            <button type="button" class="link-btn" @click="addingUnder = null">取消</button>
          </form>
        </li>
      </ul>
    </section>

    <!-- 标签 -->
    <section v-if="tab === 'tags'" class="panel">
      <p class="muted small">新标签在衣物或穿搭编辑时直接输入即可创建。全角/半角、片假名/平假名视为同一个标签。</p>
      <div class="table-wrap">
        <table class="data">
          <thead><tr><th>标签</th><th>类型</th><th>使用次数</th><th></th></tr></thead>
          <tbody>
            <tr v-for="t in dict.tags" :key="t.id">
              <template v-if="editingTag === t.id">
                <td><input v-model="tagEdit.name" class="input" aria-label="标签名" /></td>
                <td>
                  <select v-model="tagEdit.kind" class="input" aria-label="类型">
                    <option v-for="(l, k) in TAG_KIND_LABELS" :key="k" :value="k">{{ l }}</option>
                  </select>
                </td>
                <td>{{ t.usage ?? 0 }}</td>
                <td class="nowrap">
                  <button type="button" class="btn small" :disabled="busy || !tagEdit.name.trim()" @click="saveTag(t)">保存</button>
                  <button type="button" class="link-btn" @click="editingTag = null">取消</button>
                </td>
              </template>
              <template v-else>
                <td><RouterLink :to="{ name: 'wardrobe', query: { tag_exact: t.name } }">#{{ t.name }}</RouterLink></td>
                <td>{{ label(TAG_KIND_LABELS, t.kind) }}</td>
                <td>{{ t.usage ?? 0 }}</td>
                <td class="nowrap">
                  <button type="button" class="link-btn" @click="startTag(t)">编辑</button>
                  <button type="button" class="link-btn" :disabled="!!t.usage" :title="t.usage ? '仍在使用，不能删除' : ''" @click="deleteTag(t)">删除</button>
                </td>
              </template>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!dict.tags.length" class="muted">还没有标签。</p>
    </section>

    <!-- 数据 -->
    <template v-if="tab === 'data'">
      <section class="panel">
        <div class="panel-head">
          <h2>备份</h2>
          <button type="button" class="btn small" :disabled="busy" @click="backupNow">立即备份</button>
        </div>
        <p class="muted small">备份包含数据库与全部图片，保存在数据目录的 backups/ 中。提交导入、撤销导入和数据库迁移前会自动备份。恢复备份只能在终端执行 <code>./wardrobe restore &lt;文件&gt;</code>（需先停止服务），网页不提供恢复以免误操作。</p>
        <ul v-if="backups.length" class="backups">
          <li v-for="b in backups" :key="b.name"><code>{{ b.name }}</code> <span class="muted">{{ formatBytes(b.bytes) }}</span></li>
        </ul>
        <p v-else class="muted">还没有备份。</p>
      </section>
      <section class="panel">
        <h2>导出</h2>
        <p class="muted small">导出全部未删除数据为 JSON，格式与导入相同，可在导入中心重新导入。</p>
        <button type="button" class="btn ghost" :disabled="busy" @click="exportJson">下载导出文件</button>
      </section>
      <section v-if="meta" class="panel">
        <h2>系统信息</h2>
        <dl class="facts">
          <div><dt>版本</dt><dd>{{ meta.app_version }}</dd></div>
          <div><dt>数据库结构</dt><dd>{{ meta.schema_revision }}<span v-if="meta.schema_head && meta.schema_head !== meta.schema_revision" class="badge warn">需要迁移到 {{ meta.schema_head }}</span></dd></div>
          <div><dt>数据目录</dt><dd><code>{{ meta.data_dir }}</code></dd></div>
          <div v-for="(n, k) in meta.counts" :key="k"><dt>{{ label(ENTITY_LABELS, k) }}</dt><dd>{{ n }}</dd></div>
        </dl>
      </section>
    </template>
  </div>
</template>

<style scoped>
.small {
  font-size: 13px;
}
.nowrap {
  white-space: nowrap;
}
.url {
  font-size: 12px;
}
table.data .input {
  min-width: 100px;
}
.tree {
  list-style: none;
  margin: 0;
  padding: 0;
}
.tree li {
  border-bottom: 1px solid var(--line);
  padding-top: 8px;
  padding-bottom: 8px;
}
.cat-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 4px 16px;
  overflow-wrap: anywhere;
}
.row-actions {
  display: flex;
  gap: 12px;
}
.sub-form {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 8px 0;
}
.sub-form .input {
  width: auto;
  flex: 1 1 140px;
}
.sub-form .narrow {
  flex: 0 0 80px;
}
.backups {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
  font-size: 13px;
}
.facts {
  display: grid;
  gap: 4px;
  margin: 0;
  font-size: 14px;
}
.facts div {
  display: grid;
  grid-template-columns: 8em minmax(0, 1fr);
  gap: 12px;
}
.facts dt {
  color: var(--ink-3);
}
.facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}
</style>
