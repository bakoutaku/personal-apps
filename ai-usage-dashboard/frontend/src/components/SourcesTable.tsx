import type { Fetched } from '../api/adapter';
import type { Source } from '../api/types';
import { CONNECTION_TEXT, COVERAGE_TEXT, coverageSummary, errorText, sourceName } from '../domain/sources';
import { fmtDateTimeRel } from '../time/tz';
import { FetchProblem, ReasonList, StatusDot, type Clock } from './common';

interface Props {
  sources: Fetched<Source[]>;
  providerLabel: string;
  clock: Clock;
}

export function SourcesTable({ sources, providerLabel, clock }: Props) {
  return (
    <section id="sources" className="sources-panel" aria-labelledby="sources-h">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div className="eyebrow">数据来源</div>
          <h2 id="sources-h">接入状态与覆盖范围分开看</h2>
        </div>
        <span className="small muted">“可用”不代表历史完整；本机数据不能代表其他设备</span>
      </div>
      {!sources.ok ? (
        <FetchProblem result={sources} what="数据来源" />
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>来源</th>
                <th>接入状态</th>
                <th>覆盖状态</th>
                <th title="最近一次检查成功的时间；检查成功不代表有新记录或新的额度观测">最近检查成功</th>
                <th>限制 / 依据</th>
              </tr>
            </thead>
            <tbody>
              {sources.data.map((s) => (
                <SourceRow key={s.id} s={s} providerLabel={providerLabel} clock={clock} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function SourceRow({ s, providerLabel, clock }: { s: Source; providerLabel: string; clock: Clock }) {
  const cov = coverageSummary(s);
  const err = errorText(s.error_code);
  const connDot = s.connection_status === 'available' ? 'ok' : s.connection_status === 'error' ? 'err' : 'off';
  const covDot = cov === 'complete' ? 'ok' : cov === 'partial' ? 'part' : cov === 'gap' ? 'err' : null;
  const covRange = s.coverage
    .map((c) => `${fmtDateTimeRel(c.from, clock.asOfMs, clock.tz)}–${fmtDateTimeRel(c.to, clock.asOfMs, clock.tz)}${c.scope === 'local_device' ? ' 本机' : ''}`)
    .join('；');
  const notes = [
    ...s.limitations,
    s.history_status === 'empty' ? '已完整扫描，暂无有效记录' : null,
  ].filter((x): x is string => !!x);

  return (
    <tr className={s.connection_status === 'error' ? 'row-danger' : undefined}>
      <td>
        {sourceName(s, providerLabel)}
        {s.device_label && <div className="small muted">{s.device_label}</div>}
      </td>
      <td>
        <span className="nowrap">
          <StatusDot kind={connDot} /> {CONNECTION_TEXT[s.connection_status]}
        </span>
        {err && (
          <div className="small" style={{ color: 'var(--danger)', marginTop: 4 }}>
            {err.title}
            {s.consecutive_failure_count ? ` · 连续失败 ${s.consecutive_failure_count} 次` : ''}
          </div>
        )}
      </td>
      <td>
        {covDot && <StatusDot kind={covDot} />} <span className={cov === 'unknown' ? 'muted' : undefined}>{COVERAGE_TEXT[cov]}</span>
        {covRange && <div className="small muted num">{covRange}</div>}
      </td>
      <td className="num">
        {s.last_success_at ? fmtDateTimeRel(s.last_success_at, clock.asOfMs, clock.tz) : <span className="subtle">—</span>}
        {s.last_record_at && <div className="small muted">最近记录 {fmtDateTimeRel(s.last_record_at, clock.asOfMs, clock.tz)}</div>}
        {s.connection_status !== 'not_configured' && (
          <div className="small muted" title="下次计划只是计划时间，休眠、关机或服务停止时不会执行">
            {s.retry_mode === 'automatic'
              ? s.next_attempt_at
                ? `自动采集 · 下次 ${fmtDateTimeRel(s.next_attempt_at, clock.asOfMs, clock.tz)}`
                : '自动采集 · 尚无下次计划'
              : s.retry_mode === 'manual'
                ? s.connection_status === 'error'
                  ? '手动导入 · 需手动恢复'
                  : '手动导入'
                : '自动采集已停止'}
          </div>
        )}
      </td>
      <td className="small muted" style={{ fontSize: 13 }}>
        {s.coverage.length > 0 && (
          <>
            <ReasonList codes={s.coverage.map((c) => c.reason)} sep="；" />
            {notes.length > 0 && '；'}
          </>
        )}
        {notes.join('；') || (s.coverage.length === 0 ? '—' : null)}
        {err && <div style={{ marginTop: 4 }}>建议：{err.action}</div>}
      </td>
    </tr>
  );
}
