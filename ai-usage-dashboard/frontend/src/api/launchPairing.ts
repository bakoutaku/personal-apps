// 一键启动的免手输配对（launch pairing fragment-v1，见 docs/overview-redesign-and-launch-handoff.md）。
// 后端用 --open-browser 打开 http://127.0.0.1:<port>/#launch_pairing=<一次性配对码>。fragment 不会发给服务器；
// 前端在挂载、路由解析和任何请求之前同步取出并用 history.replaceState 清掉，码只留在本模块的内存里。
// 不写浏览器存储、路由、日志或错误正文；无效 / 重复参数也先清掉，不回显原值。
import { AuthClient, isPairingCode, type PairResult, type SessionState } from './auth';

const KEY = 'launch_pairing';

export interface LaunchFragment {
  /** hash 里出现过 launch_pairing（无论是否有效），已经清除 */
  present: boolean;
  /** 只有“整个 fragment 恰好是一个 launch_pairing 参数且格式有效”时才有值 */
  code: string | null;
}

/** 纯函数：判断 hash 是否带启动码。不修改任何东西。 */
export function parseLaunchFragment(hash: string): LaunchFragment {
  const raw = hash.replace(/^#/, '');
  if (!raw.includes(KEY)) return { present: false, code: null };
  // 入口只允许 `#launch_pairing=<code>` 这一种形状；路由形状（#/gpt?...）里夹带的也视为无效并清除
  if (raw.startsWith('/')) return { present: true, code: null };
  const params = new URLSearchParams(raw);
  const keys = [...params.keys()];
  const values = params.getAll(KEY);
  if (keys.length !== 1 || values.length !== 1) return { present: true, code: null };
  const code = values[0]!;
  return { present: true, code: isPairingCode(code) ? code : null };
}

/** 入口调用：取出启动码并把地址换成不带 fragment 的首页。同一文档里 hash 变化时也要调用（见 main.tsx）。 */
export function consumeLaunchFragment(
  loc: Pick<Location, 'hash' | 'pathname' | 'search'> = window.location,
  hist: Pick<History, 'replaceState'> = window.history,
): LaunchFragment {
  const f = parseLaunchFragment(loc.hash);
  if (f.present) hist.replaceState(null, '', `${loc.pathname}${loc.search}`);
  return f;
}

export type LaunchOutcome =
  | { kind: 'session'; state: SessionState }
  /** 有启动码但自动配对没有成功（码已用 / 过期 / 被拒 / 限流 / 无效链接）；码已丢弃 */
  | { kind: 'launch_failed'; reason: Exclude<PairResult, { ok: true }>['reason'] };

/**
 * 把一次性启动码交给 AuthClient：先 restore()，已有 Cookie 会话就丢弃启动码不再配对；401 才 pair(code)。
 * 只消费一次：StrictMode 双挂载 / 重复检查共享同一个进行中的 promise，避免第一次 201、第二次 401。
 * 结束后（成功或失败）码都从内存清掉，之后的检查退回普通 restore()。
 */
export class LaunchConnector {
  private code: string | null;
  private invalid: boolean;
  private inflight: Promise<LaunchOutcome> | null = null;
  private used = false;
  private listener: (() => void) | null = null;

  constructor(fragment: LaunchFragment) {
    this.code = fragment.code;
    this.invalid = fragment.present && fragment.code === null;
  }

  /** 还有没用掉的启动信息（有效码或需要提示的无效链接） */
  get pending(): boolean {
    return this.code !== null || this.invalid;
  }

  /**
   * 已打开的页面又收到启动 fragment（同一文档里 hash 变化，不会重新执行入口）：换成新的启动信息并通知。
   * 正在连接时忽略，避免同一轮里换码。
   */
  offer(fragment: LaunchFragment): void {
    if (!fragment.present || this.inflight) return;
    this.code = fragment.code;
    this.invalid = fragment.code === null;
    this.used = false;
    this.listener?.();
  }

  /** 页面已经连上：丢弃尚未使用的启动信息 */
  discard(): void {
    if (this.inflight) return;
    this.code = null;
    this.invalid = false;
    this.used = true;
  }

  onOffer(fn: () => void): () => void {
    this.listener = fn;
    return () => {
      if (this.listener === fn) this.listener = null;
    };
  }

  connect(auth: AuthClient): Promise<LaunchOutcome> {
    if (this.inflight) return this.inflight;
    if (this.used) return auth.restore().then((state) => ({ kind: 'session', state }));
    this.inflight = this.run(auth).finally(() => {
      this.code = null;
      this.invalid = false;
      this.used = true;
      this.inflight = null;
    });
    return this.inflight;
  }

  private async run(auth: AuthClient): Promise<LaunchOutcome> {
    const state = await auth.restore();
    const code = this.code;
    this.code = null;
    if (state.status !== 'unpaired') return { kind: 'session', state };
    if (code === null) return this.invalid ? { kind: 'launch_failed', reason: 'malformed' } : { kind: 'session', state };
    const r = await auth.pair(code);
    if (r.ok) return { kind: 'session', state: { status: 'authenticated', expiresAt: r.expiresAt } };
    if (r.reason === 'unreachable') return { kind: 'session', state: { status: 'unreachable' } };
    return { kind: 'launch_failed', reason: r.reason };
  }
}
