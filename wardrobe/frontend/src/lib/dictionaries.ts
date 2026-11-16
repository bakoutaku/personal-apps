// 品牌、分类、标签、枚举的共享缓存。编辑页和设置页修改后调用 refresh() 让其他页面看到最新值。
import { reactive } from "vue";
import { api } from "../api/client";
import type { Brand, CategoryNode, FlatCategory, Meta, Tag } from "../api/types";

export const dict = reactive({
  brands: [] as Brand[],
  categories: [] as CategoryNode[],
  flatCategories: [] as FlatCategory[],
  tags: [] as Tag[],
  enums: {} as Meta["enums"],
  loaded: false,
  error: null as string | null,
});

let pending: Promise<void> | null = null;

export function loadDictionaries(force = false): Promise<void> {
  if (dict.loaded && !force) return Promise.resolve();
  if (pending && !force) return pending;
  pending = (async () => {
    try {
      const [b, c, f, t, m] = await Promise.all([api.brands(), api.categories(), api.flatCategories(), api.tags(), api.meta()]);
      dict.brands = b.items;
      dict.categories = c.items;
      dict.flatCategories = f.items;
      dict.tags = t.items;
      dict.enums = m.enums;
      dict.loaded = true;
      dict.error = null;
    } catch (e) {
      dict.error = e instanceof Error ? e.message : String(e);
    } finally {
      pending = null;
    }
  })();
  return pending;
}

export const refreshDictionaries = () => loadDictionaries(true);

/** 分类树按层级缩进展开，供 <select> 使用。 */
export function categoryOptions(nodes: CategoryNode[] = dict.categories, depth = 0): { id: number; slug: string; label: string }[] {
  return nodes.flatMap((n) => [
    { id: n.id, slug: n.slug, label: `${"　".repeat(depth)}${n.name_zh}` },
    ...categoryOptions(n.children, depth + 1),
  ]);
}
