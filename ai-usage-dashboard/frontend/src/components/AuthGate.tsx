import { LanguagePicker } from "./LanguagePicker";
import { t as translate, useLanguage } from "../i18n";
// HTTP 模式的入口：先恢复本应用会话，401 时显示本机配对；成功后才读取数据。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AuthClient, type PairResult } from '../api/auth';
import { CollectorClient } from '../api/collectorSettings';
import type { LaunchConnector, LaunchOutcome } from '../api/launchPairing';
import { HttpAdapter } from '../api/httpAdapter';
import { LabelWriter } from '../api/labelWriter';
import { App } from '../App';

type GateState =
  | { s: 'checking' }
  | { s: 'unpaired'; expired: boolean; launchFailed?: LaunchFailure }
  | { s: 'unreachable' }
  | { s: 'error'; detail: string }
  | { s: 'ready' };

type LaunchFailure = (LaunchOutcome & { kind: 'launch_failed' })['reason'];

export function AuthGate({ launch }: { launch?: LaunchConnector }) {
  useLanguage();
  const auth = useMemo(() => new AuthClient(), []);
  const [state, setState] = useState<GateState>({ s: 'checking' });
  const stateRef = useRef(state);
  stateRef.current = state;

  const adapter = useMemo(() => new HttpAdapter(), []);
  // 写入器跨重新配对保留（未确认的创建请求、草稿只在内存里）
  const writer = useMemo(() => new LabelWriter(auth), [auth]);
  // 采集设置的表单草稿同样跨重新配对保留（仅内存，不自动重发）
  const collector = useMemo(() => new CollectorClient(auth), [auth]);
  // 数据请求 401：会话在别处失效或过期 → 回到配对界面，清掉内存里的 CSRF。
  adapter.onUnauthorized = () => {
    auth.forget();
    if (stateRef.current.s === 'ready') setState({ s: 'unpaired', expired: true });
  };

  const check = useCallback(async () => {
    setState({ s: 'checking' });
    // 一键启动：先 restore，已有会话就不配对；401 才用启动码（只消费一次，双挂载共享同一 promise）
    const outcome: LaunchOutcome = launch ? await launch.connect(auth) : { kind: 'session', state: await auth.restore() };
    if (outcome.kind === 'launch_failed') {
      setState({ s: 'unpaired', expired: false, launchFailed: outcome.reason });
      return;
    }
    const r = outcome.state;
    if (r.status === 'authenticated') setState({ s: 'ready' });
    else if (r.status === 'unpaired') setState({ s: 'unpaired', expired: false });
    else if (r.status === 'unreachable') setState({ s: 'unreachable' });
    else setState({ s: 'error', detail: `HTTP ${r.httpStatus} · ${r.code}` });
  }, [auth, launch]);

  useEffect(() => {
    void check();
  }, [check]);

  // 页面打开期间又收到启动 fragment：已连上就丢弃；还没连上就用它重新连接
  useEffect(
    () =>
      launch?.onOffer(() => {
        if (stateRef.current.s === 'ready') launch.discard();
        else void check();
      }),
    [launch, check],
  );

  const logout = useCallback(async () => {
    await auth.logout();
    setState({ s: 'unpaired', expired: false });
  }, [auth]);

  const toPairing = useCallback(() => {
    auth.forget();
    setState({ s: 'unpaired', expired: true });
  }, [auth]);

  if (state.s === 'ready') return <App adapter={adapter} session={{ onLogout: logout, onUnauthorized: toPairing, writer, collector }} />;

  return (
    <div data-provider="gpt">
      <div className="page" style={{ maxWidth: 720 }}>
        <header className="brand">
          <span className="brand-name">
            Usage<span>.</span>
          </span>
          <LanguagePicker />
          <span className="eyebrow">{translate("AI 使用记录 · 本机优先")}</span>
        </header>
        {state.s === 'checking' && (
          <div className="placeholder" aria-busy="true">
            {launch?.pending ? translate("正在自动连接本机服务…") : translate("正在连接本机服务…")}
          </div>
        )}
        {state.s === 'unreachable' && (
          <div className="gate-card" role="alert">
            <h1>{translate("本地服务不可达")}</h1>
            <p>{translate("页面连不上本机的数据服务。请重新点击启动图标，或确认服务仍在运行后重试。这不代表进程一定已经停止。")}</p>
            <p className="small muted">
              {translate("开发时：在 backend/ 目录用")} <code>python3 -m usage_dashboard serve --dev-origin http://127.0.0.1:5174</code> {translate("启动。")}
            </p>
            <button type="button" className="btn-primary" onClick={() => void check()}>
              {translate("重试")}
            </button>
          </div>
        )}
        {state.s === 'error' && (
          <div className="gate-card" role="alert">
            <h1>{translate("无法确认本机会话")}</h1>
            <p>
              {translate("服务返回了意外的结果：")}<code>{state.detail}</code>
            </p>
            <button type="button" className="btn-primary" onClick={() => void check()}>
              {translate("重试")}
            </button>
          </div>
        )}
        {state.s === 'unpaired' && state.launchFailed && <LaunchFailedNote reason={state.launchFailed} />}
        {state.s === 'unpaired' && <PairingPanel auth={auth} expired={state.expired} manualOnly={!!state.launchFailed} onPaired={() => setState({ s: 'ready' })} />}
      </div>
    </div>
  );
}

const LAUNCH_FAILED: Record<LaunchFailure, string> = {
  get invalid_code() { return translate("启动时带来的一次性连接码已经用过或已过期（5 分钟有效）。"); },
  get malformed() { return translate("启动链接不完整或无效。"); },
  get forbidden() { return translate("服务拒绝了这个页面的来源。"); },
  get rate_limited() { return translate("连接尝试次数过多，请稍后再试。"); },
  get unreachable() { return translate("本地服务不可达。"); },
  get error() { return translate("自动连接没有成功。"); },
};

/** 一键启动的自动连接失败：简短说明，不显示码或原始链接。 */
function LaunchFailedNote({ reason }: { reason: LaunchFailure }) {
  useLanguage();
  return (
    <div className="gate-card" role="alert">
      <h1>{translate("自动连接没有成功")}</h1>
      <p>{LAUNCH_FAILED[reason]}{translate("请关闭这个页面，重新点击启动图标；仍不行时退出服务后再启动。")}</p>
    </div>
  );
}

const PAIR_ERROR: Record<string, string> = {
  get invalid_code() { return translate("配对码不正确、已经用过或已过期（5 分钟有效）。过期时请重启后端取得新码。"); },
  get malformed() { return translate("配对码格式不对。请完整复制终端里显示的那一串字符。"); },
  get forbidden() { return translate("服务拒绝了这个页面的来源。开发时请确认后端用 --dev-origin http://127.0.0.1:5174 启动。"); },
  get unreachable() { return translate("本地服务不可达，请确认后端仍在运行。"); },
  get error() { return translate("配对没有成功，请重试。"); },
};

function PairingPanel({ auth, expired, manualOnly, onPaired }: { auth: AuthClient; expired: boolean; manualOnly: boolean; onPaired: () => void }) {
  useLanguage();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Extract<PairResult, { ok: false }> | null>(null);
  const error = failure?.reason === 'rate_limited'
    ? failure.retryAfterSeconds
      ? translate("尝试次数过多，请约 {0} 分钟后再试。", Math.ceil(failure.retryAfterSeconds / 60))
      : translate("尝试次数过多，请稍后再试。")
    : failure ? PAIR_ERROR[failure.reason] ?? PAIR_ERROR.error! : null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setFailure(null);
    let r: PairResult;
    try {
      r = await auth.pair(code);
    } finally {
      // 无论成功与否都立即清空输入里的码
      setCode('');
      setBusy(false);
    }
    if (r.ok) {
      onPaired();
      return;
    }
    setFailure(r);
  };

  const form = (
    <form className="gate-card" onSubmit={submit} autoComplete="off">
      {manualOnly ? (
        <h2 className="gate-sub">{translate("手动输入配对码")}</h2>
      ) : (
        <h1>{expired ? translate("本机会话已失效，请重新连接") : translate("连接本机服务")}</h1>
      )}
      <p>
        {manualOnly ? '' : translate("点击启动图标会自动打开并连接，不需要输入。")}
        {translate("手动启动服务时，终端里会显示一次性配对码（5 分钟有效，只能用一次），粘贴到下面即可；这台浏览器会记住本应用的会话，刷新页面不需要重新配对。")}
      </p>
      <p className="small muted">{translate("这是本应用的配对码，不是 OpenAI / Claude 的账号密码；页面不会要求供应商凭据。")}</p>
      <label htmlFor="pairing-code" className="eyebrow">
        {translate("配对码")}
      </label>
      <input
        id="pairing-code"
        className="code-input num"
        type="text"
        inputMode="text"
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        spellCheck={false}
        value={code}
        onChange={(e) => setCode(e.target.value)}
        aria-describedby={error ? 'pairing-error' : undefined}
        aria-invalid={error ? true : undefined}
      />
      {error && (
        <p id="pairing-error" className="notice error" role="alert" style={{ margin: 0 }}>
          {error}
        </p>
      )}
      <div>
        <button type="submit" className="btn-primary" disabled={busy || code.trim() === ''}>
          {busy ? translate("正在配对…") : translate("配对")}
        </button>
      </div>
    </form>
  );
  // 自动连接失败时，手动面板只作故障备用，默认收起
  return manualOnly ? (
    <details className="gate-fallback">
      <summary>{translate("备用：手动输入配对码")}</summary>
      {form}
    </details>
  ) : (
    form
  );
}
