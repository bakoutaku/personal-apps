import { t as translate, useLanguage } from "../i18n";
import type { Source } from '../api/types';
import { sourceName } from '../domain/sources';
import { fmtAgo, fmtDateTimeRel } from '../time/tz';
import type { Clock } from './common';

/**
 * 没有当前额度窗口时，说明已导入的历史是什么状态。只用来源自身的字段
 * （history_status / last_record_at / last_success_at），不推断“没有使用”。
 */
export function HistoryExplainer({ sources, providerLabel, clock }: { sources: Source[]; providerLabel: string; clock: Clock }) {
  useLanguage();
  const relevant = sources.filter((s) => s.connection_status !== 'not_configured' || s.history_status !== 'unknown');
  if (relevant.length === 0) return <p className="small muted" style={{ margin: '8px 0 0' }}>{translate("还没有已接入的来源。")}</p>;
  const t = (iso: string) => `${fmtDateTimeRel(iso, clock.asOfMs, clock.tz)}（${fmtAgo(iso, clock.asOfMs)}）`;
  return (
    <ul className="explain-list">
      {relevant.map((s) => {
        let text: string;
        if (s.history_status === 'has_records' && s.last_record_at) {
          text = translate("已有记录，最近一条在 {0}。最近五小时内没有落在当前额度窗口里的数据，不代表这段时间没有使用。", t(s.last_record_at));
        } else if (s.history_status === 'empty') {
          text = translate("已完整扫描所选来源，没有有效记录。");
        } else {
          text = translate("历史状态未知（尚未完整扫描或格式未确认），不能判断有没有记录。");
        }
        return (
          <li key={s.id}>
            <strong>{sourceName(s, providerLabel)}</strong>：{text}
            {s.last_success_at && <span className="subtle"> {translate("最近成功同步")} {t(s.last_success_at)}。</span>}
          </li>
        );
      })}
    </ul>
  );
}
