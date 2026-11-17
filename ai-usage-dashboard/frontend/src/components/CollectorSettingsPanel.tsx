import { t as translate, useLanguage } from "../i18n";
// 数据来源页的“自动采集”设置：启用 / 停用本机 Codex、Claude Code 日志目录。
// - 未启用的来源不读取任何日志；启用前必须勾选确认页面上显示的读取范围。
// - 已有历史二选一，默认“仅从启用后开始”。
// - 检查成功 ≠ 有新记录；这里分别显示最近检查成功、最近记录与下次计划。
// - 保存只在点击时发送一次；401 时草稿留在内存，重新配对后恢复，不自动重发。
import { useCallback, useEffect, useState } from 'react';
import {
  reasonText,
  type CollectorClient,
  type CollectorSettings,
  type CollectorSource,
  type HistoryChoice,
  type SettingsDraft,
  type SettingsRequest,
} from '../api/collectorSettings';
import { errorText } from '../domain/sources';
import { fmtDateTimeRel } from '../time/tz';
import { StatusDot, type Clock } from './common';

interface Props {
  client: CollectorClient;
  /** 有数据时沿用页面时钟；空库时为 null，用本机时间显示 */
  clock: Clock | null;
  /** 页面每次整屏读取后变化，设置状态随之重读 */
  refreshToken: unknown;
  onUnauthorized: () => void;
  /** 保存成功后让页面重读数据 */
  onChanged: () => void;
}

const NAME: Record<CollectorSource['provider'], string> = { gpt: 'GPT · Codex', claude: 'Claude · Code' };

function when(iso: string | null, clock: Clock | null): string | null {
  if (!iso) return null;
  const tz = clock?.tz ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
  return fmtDateTimeRel(iso, clock?.asOfMs ?? Date.now(), tz);
}

export function CollectorSettingsPanel({ client, clock, refreshToken, onUnauthorized, onChanged }: Props) {
  useLanguage();
  const [settings, setSettings] = useState<CollectorSettings | null>(null);
  const [loadProblem, setLoadProblem] = useState<(() => string) | null>(null);
  const [form, setForm] = useState<SettingsDraft | null>(() => client.draft);
  const [restored, setRestored] = useState(() => client.draft !== null);

  const load = useCallback(async () => {
    const r = await client.load();
    if (r.ok) {
      setSettings(r.settings);
      setLoadProblem(null);
    } else if (r.kind === 'unauthorized') {
      onUnauthorized();
    } else {
      setLoadProblem(() => () => r.kind === 'unconfirmed' ? translate("本地服务不可达，暂时无法读取采集设置。") : translate("暂时无法读取采集设置。"));
    }
  }, [client, onUnauthorized]);

  useEffect(() => {
    void load();
  }, [load, refreshToken]);

  const applied = (next: CollectorSettings) => {
    setSettings(next);
    onChanged();
  };

  const readOnly = settings !== null && settings.mode !== 'settings';

  return (
    <section className="sources-panel" aria-labelledby="collector-h">
      <div>
        <div className="eyebrow">{translate("自动采集")}</div>
        <h2 id="collector-h">{translate("本机日志目录")}</h2>
        <p className="small muted" style={{ margin: '6px 0 0' }}>
          {translate("只读取本机 Codex 与 Claude Code 的日志，服务运行时每")} {settings?.interval_seconds ?? 60} {translate("秒检查一次；关闭启动窗口即停止，已有数据保留。 不包括 ChatGPT / Claude 网页或桌面聊天、Work、Cowork，也不读取订阅额度。")}
        </p>
      </div>
      {loadProblem && <div className="notice error">{loadProblem()}</div>}
      {settings?.settings_error && (
        <div className="notice error" role="alert">
          {translate("采集设置文件无效，本次没有读取任何日志。重新启用来源会写入新的设置，原文件改名保留。")}
        </div>
      )}
      {settings?.mode === 'startup_config' && <div className="notice warn-notice">{translate("本次由启动参数指定采集配置，下面只显示状态，页面设置暂不可改。")}</div>}
      {settings?.mode === 'disabled' && <div className="notice warn-notice">{translate("本次启动没有开启采集，下面只显示状态。")}</div>}
      {!settings && !loadProblem && <div className="small muted">{translate("正在读取采集设置…")}</div>}
      {settings?.sources.map((s) => (
        <SourceCard
          key={s.provider}
          s={s}
          clock={clock}
          readOnly={readOnly}
          client={client}
          form={form?.provider === s.provider ? form : null}
          restored={restored && form?.provider === s.provider}
          onForm={(f) => {
            setForm(f);
            setRestored(false);
            if (!f) client.draft = null;
          }}
          onApplied={applied}
          onUnauthorized={onUnauthorized}
        />
      ))}
      <p className="small muted" style={{ margin: 0 }}>
        {translate("“最近检查成功”只表示那次检查读到了目录，不代表有新记录；额度百分比以额度页的记录时间为准。")}
      </p>
    </section>
  );
}

function SourceCard({
  s,
  clock,
  readOnly,
  client,
  form,
  restored,
  onForm,
  onApplied,
  onUnauthorized,
}: {
  s: CollectorSource;
  clock: Clock | null;
  readOnly: boolean;
  client: CollectorClient;
  form: SettingsDraft | null;
  restored: boolean;
  onForm: (f: SettingsDraft | null) => void;
  onApplied: (next: CollectorSettings) => void;
  onUnauthorized: () => void;
}) {
  useLanguage();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<(() => string) | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [confirmAction, setConfirmAction] = useState<'disable' | 'import' | null>(null);

  const submit = async (request: SettingsRequest, draft: SettingsDraft | null) => {
    setBusy(true);
    setProblem(null);
    const r = await client.save(request);
    setBusy(false);
    if (r.ok) {
      setConfirmed(false);
      setConfirmAction(null);
      onForm(null);
      onApplied(r.settings);
      return;
    }
    if (r.kind === 'unauthorized') {
      client.draft = draft; // 只保存在内存；重新配对后恢复表单，不自动提交
      onUnauthorized();
      return;
    }
    setProblem(() => () =>
      r.kind === 'invalid'
        ? reasonText(r.reason)
        : r.kind === 'unconfirmed'
          ? translate("没有收到本地服务的回应，设置可能没有保存。刷新后查看状态再决定是否重试。")
          : r.kind === 'csrf_invalid'
            ? translate("页面会话校验失败，请刷新页面后重试。")
            : translate("设置未保存（HTTP {0}）。", r.status),
    );
  };

  const scope = form ? (form.location === 'standard' ? s.standard_display_path : form.customPath.trim()) : '';
  const err = errorText(s.error_code);
  const paused = s.enabled && s.retry_mode === 'disabled';
  const waiting = s.enabled && s.retry_mode === 'automatic' && (s.error_code === 'source_missing' || s.error_code === 'unsupported_format') && s.last_record_at === null;
  const dot = !s.enabled ? 'off' : s.connection_status === 'error' ? (waiting ? 'part' : 'err') : s.connection_status === 'available' ? 'ok' : 'part';

  return (
    <div className="section" style={{ gap: 10, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <strong>
          <StatusDot kind={dot} /> {NAME[s.provider]}
        </strong>
        <span className="small muted">
          {s.enabled ? (paused ? translate("已启用 · 已暂停") : s.boundary_status === 'pending' ? translate("已启用 · 准备中") : translate("已启用 · 自动采集")) : translate("未启用 · 不读取日志")}
        </span>
      </div>

      {s.enabled && (
        <dl className="small" style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '4px 14px', margin: 0 }}>
          <dt className="muted">{translate("读取范围")}</dt>
          <dd style={{ margin: 0 }}>
            <code>{s.display_path}</code> {translate("下的 .jsonl 日志")}
          </dd>
          <dt className="muted">{translate("已有历史")}</dt>
          <dd style={{ margin: 0 }}>
            {s.history === 'from_enable'
              ? translate("仅从启用后开始{0}，启用前的历史未导入", s.enabled_at ? translate("（{0} 起）", when(s.enabled_at, clock)) : '')
              : translate("已导入已有历史并继续采集")}
          </dd>
          <dt className="muted" title={translate("检查成功只表示读到了目录，不代表有新记录")}>{translate("最近检查成功")}</dt>
          <dd style={{ margin: 0 }} className="num">{when(s.last_success_at, clock) ?? '—'}</dd>
          <dt className="muted" title={translate("已入库记录中最新的来源时间")}>{translate("最近记录")}</dt>
          <dd style={{ margin: 0 }} className="num">{when(s.last_record_at, clock) ?? translate("尚无记录")}</dd>
          <dt className="muted" title={translate("计划时间；休眠或服务停止时不会执行")}>{translate("下次检查")}</dt>
          <dd style={{ margin: 0 }} className="num">
            {s.retry_mode === 'automatic' && s.next_attempt_at ? when(s.next_attempt_at, clock) : s.retry_mode === 'automatic' ? translate("即将检查") : '—'}
          </dd>
        </dl>
      )}

      {s.enabled && s.boundary_status === 'pending' && (
        <div className="small muted">{translate("正在建立历史边界：读取启用时已有的内容，只用于排除旧记录，不会把它们计入用量。")}</div>
      )}
      {s.enabled && s.boundary_status === 'missing' && (
        <div className="notice error">{translate("“仅从启用后开始”的边界记录缺失，已暂停以免补入旧历史。请停用后重新启用。")}</div>
      )}
      {s.enabled && waiting && <div className="small muted">{translate("目录里还没有日志（或目录尚不存在），会继续每分钟检查。")}</div>}
      {s.enabled && err && !waiting && s.boundary_status !== 'missing' && (
        <div className="small" style={{ color: 'var(--danger)' }}>
          {paused && s.error_code === 'unknown_error'
            ? translate("已暂停：检测到来源账户归属变化，没有混入其他账户的数据。已有记录保留；请检查日志来源后停用此来源。")
            : `${err.title}${s.consecutive_failure_count ? translate(" · 连续失败 {0} 次", s.consecutive_failure_count) : ''}${paused ? translate(" · 已暂停") : translate(" · 将按计划重试，已有记录保留")}`}
        </div>
      )}
      {!s.enabled && s.last_record_at && (
        <div className="small muted">{translate("已停用；之前采集的记录保留（最近记录")} {when(s.last_record_at, clock)}）。</div>
      )}

      {problem && <div className="small field-error" role="alert">{problem()}</div>}

      {!readOnly && !form && (
        <div className="confirm-row">
          {!s.enabled && (
            <button
              type="button"
              className="btn-primary"
              onClick={() => onForm({ provider: s.provider, location: s.location === 'custom' ? 'custom' : 'standard', customPath: '', history: 'from_enable' })}
            >
              {translate("设置并启用…")}
            </button>
          )}
          {s.enabled && confirmAction === null && (
            <>
              {s.history === 'from_enable' && (
                <button type="button" className="text-btn" onClick={() => setConfirmAction('import')} disabled={busy}>
                  {translate("补入已有历史…")}
                </button>
              )}
              <button type="button" className="text-btn danger-btn" onClick={() => setConfirmAction('disable')} disabled={busy}>
                {translate("停用…")}
              </button>
            </>
          )}
          {confirmAction === 'disable' && (
            <>
              <span className="small">{translate("停用后不再读取这个目录，已有记录保留。")}</span>
              <button type="button" className="text-btn danger-btn" disabled={busy} onClick={() => void submit({ provider: s.provider, enabled: false }, null)}>
                {translate("确认停用")}
              </button>
              <button type="button" className="text-btn" disabled={busy} onClick={() => setConfirmAction(null)}>
                {translate("取消")}
              </button>
            </>
          )}
          {confirmAction === 'import' && s.display_path && (
            <>
              <span className="small">
                {translate("将读取")} <code>{s.display_path}</code> {translate("中全部已有日志并导入历史用量（已导入的不会重复）。")}
              </span>
              <button
                type="button"
                className="text-btn"
                disabled={busy}
                onClick={() =>
                  void submit(
                    {
                      provider: s.provider,
                      enabled: true,
                      location: s.location === 'custom' ? 'custom' : 'standard',
                      ...(s.location === 'custom' ? { custom_path: s.display_path ?? '' } : {}),
                      history: 'import_history',
                      confirm_scope: s.display_path ?? '',
                    },
                    null,
                  )
                }
              >
                {translate("确认导入")}
              </button>
              <button type="button" className="text-btn" disabled={busy} onClick={() => setConfirmAction(null)}>
                {translate("取消")}
              </button>
            </>
          )}
        </div>
      )}

      {!readOnly && form && (
        <form
          className="section"
          style={{ gap: 12 }}
          onSubmit={(e) => {
            e.preventDefault();
            if (!confirmed || !scope) return;
            void submit(
              {
                provider: s.provider,
                enabled: true,
                location: form.location,
                ...(form.location === 'custom' ? { custom_path: form.customPath.trim() } : {}),
                history: form.history,
                confirm_scope: scope,
              },
              form,
            );
          }}
        >
          {restored && <div className="notice warn-notice small">{translate("已恢复会话失效前填写的内容，尚未保存。确认后再点“启用”。")}</div>}
          <fieldset className="field" disabled={busy}>
            <legend className="eyebrow">{translate("读取位置")}</legend>
            <div className="check-row">
              <label className="check">
                <input
                  type="radio"
                  name={`loc-${s.provider}`}
                  checked={form.location === 'standard'}
                  onChange={() => {
                    setConfirmed(false);
                    onForm({ ...form, location: 'standard' });
                  }}
                />
                {translate("标准目录")} <code>{s.standard_display_path}</code>
              </label>
              <label className="check">
                <input
                  type="radio"
                  name={`loc-${s.provider}`}
                  checked={form.location === 'custom'}
                  onChange={() => {
                    setConfirmed(false);
                    onForm({ ...form, location: 'custom' });
                  }}
                />
                {translate("自定义目录")}
              </label>
              {form.location === 'custom' && (
                <input
                  className="code-input"
                  value={form.customPath}
                  placeholder={translate("例如 ~/Logs/codex-sessions")}
                  aria-label={translate("自定义日志目录")}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(e) => {
                    setConfirmed(false);
                    onForm({ ...form, customPath: e.target.value });
                  }}
                />
              )}
              {form.location === 'custom' && <span className="small muted">{translate("请选择具体的日志目录；不能是主目录、磁盘根目录或本应用的数据目录。")}</span>}
            </div>
          </fieldset>
          <fieldset className="field" disabled={busy}>
            <legend className="eyebrow">{translate("已有历史")}</legend>
            <div className="check-row">
              {(
                [
                  ['from_enable', translate("仅从启用后开始（推荐）"), translate("启用时已有的记录不计入，之后新增的记录和新聊天都会采集。重启后边界不变。")],
                  ['import_history', translate("导入已有历史并继续采集"), translate("首次会读取目录里全部已有日志，目录大时需要一些时间。")],
                ] as [HistoryChoice, string, string][]
              ).map(([value, label, note]) => (
                <label key={value} className="check" style={{ alignItems: 'flex-start' }}>
                  <input type="radio" name={`hist-${s.provider}`} checked={form.history === value} onChange={() => onForm({ ...form, history: value })} />
                  <span>
                    {label}
                    <br />
                    <span className="small muted">{note}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <label className="check" style={{ alignItems: 'flex-start' }}>
            <input type="checkbox" checked={confirmed} disabled={busy || !scope} onChange={(e) => setConfirmed(e.target.checked)} />
            <span className="small">
              {translate("我确认读取")} <code>{scope || translate("（请填写目录）")}</code> {translate("及其子目录中的 .jsonl 日志。只保存用量、时间与会话标识等字段，不保存对话内容，不修改日志。")}
            </span>
          </label>
          <div className="drawer-actions">
            <button type="submit" className="btn-primary" disabled={busy || !confirmed || !scope}>
              {busy ? translate("正在保存…") : translate("启用")}
            </button>
            <button type="button" className="text-btn" disabled={busy} onClick={() => onForm(null)}>
              {translate("取消")}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
