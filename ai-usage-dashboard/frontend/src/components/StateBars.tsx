import { t as translate, useLanguage } from "../i18n";
import { useState } from 'react';
import type { QuotaWindow, Source } from '../api/types';
import { cardWindows } from '../domain/quota';
import { errorText, sourceName } from '../domain/sources';
import { fmtAgo, fmtDateTimeRel } from '../time/tz';
import type { Clock } from './common';

function ClockIcon() {
  useLanguage();
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="var(--warn-icon)" strokeWidth="2" strokeLinecap="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  );
}

function AlertIcon() {
  useLanguage();
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="var(--danger-icon)" strokeWidth="2" strokeLinecap="round">
      <path d="M12 3l9 16H3z" />
      <path d="M12 10v4M12 17v.5" />
    </svg>
  );
}

/**
 * 额度观测过时：当前窗口的最近记录超过 stale_after_seconds。
 * 只改变显示，不改数据；不据此断言本地服务停止（source-errors.md）。
 */
export function StaleBar({
  windows,
  staleAfterSeconds,
  clock,
  sources = [],
}: {
  windows: QuotaWindow[];
  staleAfterSeconds: number;
  clock: Clock;
  /** 用来判断快照来源之后是否检查成功过 */
  sources?: Source[];
}) {
  useLanguage();
  const stale = cardWindows(windows).filter((w) => w.status === 'current' && w.freshness === 'stale' && w.latest_snapshot);
  if (stale.length === 0) return null;
  const latest = stale
    .map((w) => w.latest_snapshot!.effective_at)
    .sort()
    .at(-1)!;
  // 快照来源在最近一次额度记录之后仍检查成功：说明采集在运行，只是没有新的额度记录
  const ids = new Set(stale.map((w) => w.latest_snapshot!.source_id));
  const checkedAfter = sources
    .filter((x) => ids.has(x.id) && x.last_success_at && x.last_success_at > latest)
    .map((x) => x.last_success_at!)
    .sort()
    .at(-1);
  return (
    <div className="state-bar warn" role="status">
      <div className="state-bar-main">
        <ClockIcon />
        <div>
          <div className="title">{translate("额度观测可能已过时")}</div>
          <div className="body">
            {translate("最近一次额度记录在")} <span className="num">{fmtDateTimeRel(latest, clock.asOfMs, clock.tz)}</span>（{fmtAgo(latest, clock.asOfMs)}
            {translate("），超过")} {Math.round(staleAfterSeconds / 60)} {translate("分钟的过时阈值。卡片上的数字是那时的记录，不是现在的额度。")}
            <br />
            {checkedAfter ? (
              <>
                {translate("来源在")} <span className="num">{fmtDateTimeRel(checkedAfter, clock.asOfMs, clock.tz)}</span>{' '}
                {translate("检查成功，但之后没有新的额度记录；检查成功不代表额度被重新观测。")}
              </>
            ) : (
              translate("可能是这段时间没有新的使用记录或没有同步；仅凭这一点不能判断本地服务是否在运行。")
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** 同步失败：尝试过但失败。保留最后一次成功的数据，不清空。 */
/** compact：首页只显示一行，详情默认收起 */
export function FailureBars({ sources, providerLabel, clock, compact = false }: { sources: Source[]; providerLabel: string; clock: Clock; compact?: boolean }) {
  useLanguage();
  const failed = sources.filter((s) => s.connection_status === 'error');
  return (
    <>
      {failed.map((s) => (
        <FailureBar key={s.id} s={s} providerLabel={providerLabel} clock={clock} defaultOpen={!compact} />
      ))}
    </>
  );
}

function FailureBar({ s, providerLabel, clock, defaultOpen }: { s: Source; providerLabel: string; clock: Clock; defaultOpen: boolean }) {
  useLanguage();
  const [open, setOpen] = useState(defaultOpen);
  const err = errorText(s.error_code) ?? errorText('unknown_error')!;
  const t = (iso: string) => fmtDateTimeRel(iso, clock.asOfMs, clock.tz);
  const detailsId = `fail-${s.id}`;

  let retry: string;
  if (s.retry_mode === 'automatic') {
    retry = s.next_attempt_at ? translate("下次自动重试 {0}（计划时间，休眠或关机时不保证执行）", t(s.next_attempt_at)) : translate("自动重试：尚无下一次计划");
  } else if (s.retry_mode === 'manual') {
    retry = translate("没有自动重试，需要手动恢复");
  } else {
    retry = translate("自动采集已停止（不会自动重试）；按“建议”修正来源或命名空间后重启服务");
  }

  return (
    <div className="state-bar danger" role="alert">
      <div className="state-bar-row">
        <div className="state-bar-main">
          <AlertIcon />
          <div>
            <div className="title">{sourceName(s, providerLabel)}{translate("同步失败")}</div>
            <div className="body">
              {err.title}。
              {s.last_success_at ? (
                <>
                  {translate("下面显示的是")} <span className="num">{t(s.last_success_at)}</span> {translate("最后一次成功检查时已有的数据，之后的时段按“覆盖未知”处理。")}
                </>
              ) : (
                translate("还没有成功同步过，这个来源暂无可显示的数据。")
              )}
            </div>
          </div>
        </div>
        <button type="button" className="btn-ghost" aria-expanded={open} aria-controls={detailsId} onClick={() => setOpen(!open)}>
          {open ? translate("收起详情") : translate("展开详情")}
        </button>
      </div>
      {open && (
        <dl className="state-details" id={detailsId}>
          <div>
            <dt>{translate("错误代码")}</dt>
            <dd className="num">{s.error_code ?? 'unknown_error'}</dd>
          </div>
          <div>
            <dt>{translate("最近尝试")}</dt>
            <dd className="num">
              {s.last_attempt_at ? t(s.last_attempt_at) : '—'}
              {s.consecutive_failure_count ? translate("（连续 {0} 次）", s.consecutive_failure_count) : ''}
            </dd>
          </div>
          <div>
            <dt>{translate("重试")}</dt>
            <dd>{retry}</dd>
          </div>
          <div>
            <dt>{translate("建议")}</dt>
            <dd>{err.action}</dd>
          </div>
        </dl>
      )}
    </div>
  );
}
