import { t as translate, useLanguage } from "../i18n";
import { PRODUCTS_BY_PROVIDER, type Label, type Product, type Provider, type Source, type UsageBucket, type UsageEvent } from '../api/types';
import { productName } from '../domain/quota';
import { selectionConnection, sourceName } from '../domain/sources';
import { canStack, classifyBucket, describeComponents, fmtTokens } from '../domain/usage';
import type { HistoryData } from '../state/loadDashboard';
import { fmtDateTimeRel, fmtRangeLabel, fmtTime } from '../time/tz';
import { FetchProblem, ReasonList, StatusDot, type Clock } from './common';
import { AddLabelButton } from './LabelButtons';
import { useLabelEditing, type EditorRequest } from './labelEditing';

interface Props {
  history: HistoryData | null;
  sources: Source[];
  clock: Clock;
  provider: Provider;
  products: Product[] | null;
  onClearSelection: () => void;
}

interface Row {
  from: string;
  to: string;
  buckets: UsageBucket[];
}

/** 过去的桶倒序列出；连续的“无记录·覆盖未知”合并为一行。 */
function rowsFrom(buckets: UsageBucket[]): Row[] {
  const rows: Row[] = [];
  for (const b of buckets) {
    if (b.record_state === 'future') continue;
    const prev = rows.at(-1);
    if (prev && classifyBucket(b) === 'no_records_unknown' && prev.buckets.every((x) => classifyBucket(x) === 'no_records_unknown')) {
      prev.to = b.to;
      prev.buckets.push(b);
    } else {
      rows.push({ from: b.from, to: b.to, buckets: [b] });
    }
  }
  return rows.reverse();
}

function eventsIn(events: UsageEvent[], from: string, to: string): UsageEvent[] {
  const f = Date.parse(from);
  const t = Date.parse(to);
  return events.filter((e) => {
    const x = Date.parse(e.occurred_at);
    return x >= f && x < t;
  });
}

function LabelBadges({ ids, labels, add }: { ids: string[]; labels: Label[]; add?: EditorRequest }) {
  useLanguage();
  const ed = useLabelEditing();
  return (
    <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
      {ids.length === 0 && !add && <span className="subtle">—</span>}
      {ids.map((id) => {
        const l = labels.find((x) => x.id === id);
        const kindText = l?.target.kind === 'session' ? translate("会话标签") : translate("时间段标签");
        const cls = `badge ${l?.target.kind === 'range' ? 'dark' : ''}`;
        return ed.writable && l ? (
          <button key={id} type="button" className={`${cls} badge-btn`} title={translate("{0} · 点击编辑", kindText)} onClick={() => ed.open({ mode: 'edit', labelId: id })}>
            {l.name}
          </button>
        ) : (
          <span key={id} className={cls} title={kindText}>
            {l?.name ?? translate("（不在当前范围的标签）")}
          </span>
        );
      })}
      {add && (
        <AddLabelButton request={add} small>
          {translate("＋ 标签")}
        </AddLabelButton>
      )}
    </span>
  );
}

function compositionText(b: Pick<UsageBucket, 'components' | 'components_complete' | 'total_status' | 'total_tokens'>): string {
  if (b.total_tokens === null) return '—';
  const parts = describeComponents(b.components);
  if (canStack(b)) return parts ?? '—';
  return parts ? translate("部分已知：{0}", parts) : translate("分项未知");
}

export function DetailSection({ history, sources, clock, provider, products, onClearSelection }: Props) {
  useLanguage();
  if (!history) return null;
  // 有选区时明细只用选区那一批数据（同范围、同筛选重新请求的）
  const sel = history.selection;
  const { series, events, labels, sessions } = sel ?? history;
  const conn = selectionConnection(sources, provider, products, PRODUCTS_BY_PROVIDER);
  const cal = history.kind === 'calendar' ? history.calendar : null;
  const rowDate = !!sel || (!!cal && cal.view !== 'day');
  const shownTo = Math.min(clock.asOfMs, Date.parse(history.to));
  const heading = sel
    ? fmtRangeLabel(sel.from, sel.to, clock.tz)
    : cal
      ? fmtRangeLabel(history.from, shownTo, clock.tz, cal.view !== 'day')
      : `${fmtTime(history.from, clock.tz)} – ${fmtTime(shownTo, clock.tz)}`;
  const scopeText = sel
    ? null
    : history.kind === 'recent5h'
      ? translate("范围：最近五小时（非额度窗口）")
      : cal
        ? translate("范围：这个自然{0}中已过去的部分", cal.view === 'day' ? translate("日") : cal.view === 'week' ? translate("周") : translate("月"))
        : translate("范围：所选额度窗口中已发生的部分");
  const labelList = labels.ok ? labels.data : [];
  const eventList = events.ok ? events.data : [];
  const sourceLabel = (id: string) => {
    const s = sources.find((x) => x.id === id);
    if (!s) return translate("未知来源");
    return `${sourceName(s, provider === 'gpt' ? 'GPT' : 'Claude')}${s.device_label ? ` · ${translate(s.device_label)}` : ''}`;
  };

  return (
    <section className="section" aria-labelledby="detail-h" style={{ gap: 16 }}>
      <div className="section-head">
        <div>
          <div className="eyebrow">{translate("03 · 时间段明细")}</div>
          <h2 id="detail-h">
            <span className="num" style={{ fontSize: 24, color: 'var(--text)', fontWeight: 700 }}>
              {heading}
            </span>
          </h2>
        </div>
        {sel ? (
          <span className="badge" style={{ fontSize: 13, padding: '6px 12px' }}>
            {translate("筛选：来自图表点选")}
            <button type="button" aria-label={translate("清除筛选")} onClick={onClearSelection} style={{ border: 0, background: 'transparent', color: 'inherit', cursor: 'pointer', font: 'inherit', padding: '0 0 0 4px' }}>
              ✕
            </button>
          </span>
        ) : (
          <span className="badge" style={{ fontSize: 13, padding: '6px 12px' }}>
            {scopeText}
          </span>
        )}
      </div>

      {!series.ok ? (
        <FetchProblem result={series} what={translate("时间段明细")} />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{translate("时间段")}</th>
                <th>{translate("产品")}</th>
                <th>{translate("token 合计")}</th>
                <th>{translate("构成")}</th>
                <th>{translate("标签")}</th>
                <th>{translate("来源与覆盖")}</th>
              </tr>
            </thead>
            <tbody>
              {rowsFrom(series.data.buckets).map((r) => {
                const b = r.buckets[0]!;
                const k = classifyBucket(b);
                const evs = eventsIn(eventList, r.from, r.to);
                const ids = [...new Set(evs.flatMap((e) => e.label_ids))];
                const products = [...new Set(evs.map((e) => e.product))];
                const muted = k.startsWith('no_records');
                return (
                  <tr key={r.from} className={muted ? 'row-muted' : undefined}>
                    <td className="num">
                      {fmtRangeLabel(r.from, r.to, clock.tz, rowDate)}
                      {b.is_partial_bucket && <span className="small subtle"> {translate("不完整")}</span>}
                    </td>
                    <td>{products.length ? products.map(productName).join(' / ') : <span className="subtle">—</span>}</td>
                    <td className="num">
                      {k === 'known_total' && fmtTokens(b.total_tokens!)}
                      {k === 'partial_total' && (
                        <>
                          ≥ {fmtTokens(b.total_tokens!)} <span className="small muted">{translate("已知小计")}</span>
                        </>
                      )}
                      {k === 'unknown_total' && <span className="muted">{translate("用量未知（")}{b.unknown_total_count} {translate("条记录）")}</span>}
                      {k === 'no_records_unknown' && <span className="muted">{translate("无记录")}</span>}
                      {k === 'no_records_gap' && <span className="muted">{translate("采集缺口")}</span>}
                      {k === 'no_records_covered' && <span className="muted">{translate("无活动")}</span>}
                    </td>
                    <td className="note">{compositionText(b)}</td>
                    <td>
                      <LabelBadges ids={muted ? [] : ids} labels={labelList} add={{ mode: 'create-range', from: r.from, to: r.to }} />
                    </td>
                    <td className="note">
                      {muted ? (
                        k === 'no_records_covered'
                          ? translate("已覆盖")
                          : b.coverage_reasons.includes('selected_products_not_configured')
                            ? conn === 'none_configured'
                              ? translate("所选产品未接入 · 不计为 0")
                              : translate("部分所选产品未接入 · 覆盖未知 · 不计为 0")
                            : translate("覆盖未知 · 不计为 0")
                      ) : (
                        <>
                          <StatusDot kind={b.coverage_status === 'complete' ? 'ok' : 'part'} /> {b.source_ids.map(sourceLabel).join('、')}
                          {b.coverage_reasons.length > 0 && (
                            <>
                              {' · '}
                              <ReasonList codes={b.coverage_reasons} />
                            </>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <h3 style={{ margin: '8px 0 0', fontSize: 16 }}>{translate("按会话")}</h3>
      {!sessions.ok ? (
        <FetchProblem result={sessions} what={translate("会话")} />
      ) : sessions.data.length === 0 ? (
        <p className="small muted" style={{ margin: 0 }}>{translate("这个范围内没有会话记录（不等于没有使用）。")}</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{translate("会话")}</th>
                <th>{translate("产品")}</th>
                <th>{translate("范围内记录（大致）")}</th>
                <th>{translate("记录数")}</th>
                <th>{translate("token（范围内）")}</th>
                <th>{translate("标签")}</th>
              </tr>
            </thead>
            <tbody>
              {sessions.data.map((x) => (
                <tr key={x.id}>
                  <td className="num small">{x.id}</td>
                  <td>{productName(x.product)}</td>
                  <td className="num" title={translate("范围内首末记录时间，不是会话的精确起止")}>
                    {fmtDateTimeRel(x.first_record_in_range_at, clock.asOfMs, clock.tz)}
                    {x.last_record_in_range_at !== x.first_record_in_range_at && `–${fmtDateTimeRel(x.last_record_in_range_at, clock.asOfMs, clock.tz)}`}
                  </td>
                  <td className="num">
                    {x.event_count_in_range}
                    {x.unknown_total_count > 0 && <span className="small muted">（{x.unknown_total_count} {translate("条用量未知）")}</span>}
                  </td>
                  <td className="num">
                    {x.total_tokens_in_range === null ? (
                      <span className="muted">{translate("未知")}</span>
                    ) : (
                      <>
                        {x.unknown_total_count > 0 && '≥ '}
                        {fmtTokens(x.total_tokens_in_range)}
                        {x.unknown_total_count > 0 && <span className="small muted"> {translate("已知小计")}</span>}
                      </>
                    )}
                  </td>
                  <td>
                    <LabelBadges ids={x.label_ids} labels={labelList} add={{ mode: 'create-session', sessionId: x.id }} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 style={{ margin: '8px 0 0', fontSize: 16 }}>{translate("用量记录")}</h3>
      {!events.ok ? (
        <FetchProblem result={events} what={translate("用量记录")} />
      ) : eventList.length === 0 ? (
        <p className="small muted" style={{ margin: 0 }}>{translate("这个范围内没有已记录事件（不等于没有使用）。")}</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{translate("时间")}</th>
                <th>{translate("产品")}</th>
                <th>{translate("会话")}</th>
                <th>{translate("token 合计")}</th>
                <th>{translate("构成")}</th>
                <th>{translate("其中推理输出")}</th>
                <th>{translate("标签")}</th>
              </tr>
            </thead>
            <tbody>
              {[...eventList].reverse().map((e) => (
                <tr key={e.id}>
                  <td className="num">{fmtDateTimeRel(e.occurred_at, clock.asOfMs, clock.tz)}</td>
                  <td>{productName(e.product)}</td>
                  <td className="num small">{e.session_id ?? '—'}</td>
                  <td className="num">
                    {e.total_tokens === null ? <span className="muted">{translate("未知")}</span> : fmtTokens(e.total_tokens)}
                    {e.total_basis === 'derived' && <span className="small muted"> {translate("推导")}</span>}
                  </td>
                  <td className="note">{compositionText({ ...e, total_status: e.total_tokens === null ? 'unknown' : 'known' })}</td>
                  <td className="num note" title={translate("输出的子集，不另加入合计")}>
                    {e.reasoning_output_tokens === null ? '—' : translate("{0}（⊂ 输出）", fmtTokens(e.reasoning_output_tokens))}
                  </td>
                  <td>
                    <LabelBadges ids={e.label_ids} labels={labelList} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="small subtle" style={{ margin: 0 }}>
        {translate("标签可重叠；按标签汇总时同一条用量记录只计一次，各标签小计不能再相加。")}
      </p>
    </section>
  );
}
