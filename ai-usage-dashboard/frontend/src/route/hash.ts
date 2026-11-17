import { t as translate } from "../i18n";
// hash 路由：#/gpt[/页面]?products=codex&view=window&pool=<id>&window=<window_id>
// 首页（用量图）没有页面段；二级页面：quota 额度、details 明细、sources 数据来源、about 关于。
// 只放筛选和视图；令牌、数据都不进 URL。
import { PRODUCTS_BY_PROVIDER, type Product, type Provider } from '../api/types';
import { isDateKey } from '../time/tz';

export const VIEWS = ['window', 'recent5h', 'day', 'week', 'month'] as const;
export type View = (typeof VIEWS)[number];

export const PAGES = ['home', 'quota', 'details', 'sources', 'about'] as const;
export type Page = (typeof PAGES)[number];

export interface Route {
  provider: Provider;
  /** 首页 = 用量图；其余是二级页面。换页面不改变数据范围。 */
  page: Page;
  /** null = 全部产品 */
  products: Product[] | null;
  view: View;
  pool: string | null;
  window: string | null;
  /** 日 / 周 / 月视图的锚定日期（当地 YYYY-MM-DD）；null = 以 as_of 所在日期为准 */
  date: string | null;
  /** 在图上选中的时间段 [from, to)（UTC ISO），只过滤明细 */
  range: { from: string; to: string } | null;
}

export interface ParsedRoute {
  route: Route;
  /** 被忽略的非法参数，用于提示；不白屏。 */
  dropped: string[];
}

const KNOWN_KEYS = new Set(['products', 'view', 'pool', 'window', 'date', 'range']);

export function parseHash(hash: string, defaults: { provider: Provider; view: View }): ParsedRoute {
  const dropped: string[] = [];
  const raw = hash.replace(/^#/, '');
  const [pathPart = '', queryPart = ''] = raw.split('?', 2);
  const segs = pathPart.replace(/^\/+/, '').split('/');
  const seg = segs[0] ?? '';
  const pageSeg = segs[1] ?? '';
  let page: Page = 'home';
  if (pageSeg !== '' && pageSeg !== 'home') {
    if ((PAGES as readonly string[]).includes(pageSeg)) page = pageSeg as Page;
    else dropped.push('page');
  }

  let provider: Provider = defaults.provider;
  if (seg === 'gpt' || seg === 'claude') provider = seg;
  // 只提示参数名，不回显原值（hash 里可能夹带不该显示的内容）
  else if (seg !== '') dropped.push('provider');

  const params = new URLSearchParams(queryPart);
  const seen = new Set<string>();
  for (const k of params.keys()) {
    if (!KNOWN_KEYS.has(k)) dropped.push(k);
    if (seen.has(k)) dropped.push(translate("{0}（重复）", k));
    seen.add(k);
  }

  let products: Product[] | null = null;
  const productsRaw = params.getAll('products');
  if (productsRaw.length === 1 && productsRaw[0] !== '') {
    const allowed = PRODUCTS_BY_PROVIDER[provider];
    const list = productsRaw[0]!.split(',').filter(Boolean);
    const valid = list.filter((p): p is Product => (allowed as readonly string[]).includes(p));
    if (valid.length !== list.length) dropped.push('products');
    products = valid.length > 0 ? [...new Set(valid)] : null;
  } else if (productsRaw.length > 1) {
    dropped.push('products');
  }

  // 没有额度池的供应商（Claude）默认看最近五小时活动
  let view: View = provider === 'claude' && defaults.view === 'window' ? 'recent5h' : defaults.view;
  const viewRaw = params.getAll('view');
  if (viewRaw.length === 1) {
    if ((VIEWS as readonly string[]).includes(viewRaw[0]!)) view = viewRaw[0] as View;
    else dropped.push('view');
  }

  const single = (k: string) => {
    const v = params.getAll(k);
    return v.length === 1 && v[0] ? v[0] : null;
  };

  let date = single('date');
  if (date && !isDateKey(date)) {
    dropped.push('date');
    date = null;
  }

  let range: Route['range'] = null;
  const rangeRaw = single('range');
  if (rangeRaw) {
    const [a, b] = rangeRaw.split(',');
    const fa = Date.parse(a ?? '');
    const fb = Date.parse(b ?? '');
    if (Number.isFinite(fa) && Number.isFinite(fb) && fa < fb) range = { from: new Date(fa).toISOString(), to: new Date(fb).toISOString() };
    else dropped.push('range');
  }

  return {
    route: { provider, page, products, view, pool: single('pool'), window: single('window'), date, range },
    dropped: [...new Set(dropped)],
  };
}

export function formatHash(r: Route): string {
  const params = new URLSearchParams();
  if (r.products && r.products.length > 0) params.set('products', r.products.join(','));
  params.set('view', r.view);
  if (r.pool) params.set('pool', r.pool);
  if (r.window) params.set('window', r.window);
  if (r.date) params.set('date', r.date);
  if (r.range) params.set('range', `${r.range.from},${r.range.to}`);
  // URLSearchParams 会把逗号编码成 %2C；为了可读性还原。
  return `#/${r.provider}${r.page === 'home' ? '' : `/${r.page}`}?${params.toString().replace(/%2C/g, ',').replace(/%3A/g, ':')}`;
}
