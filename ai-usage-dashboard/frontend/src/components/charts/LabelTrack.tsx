import type { Label, Session } from '../../api/types';
import { fmtDateTimeRel, fmtRangeLabel } from '../../time/tz';
import type { Clock } from '../common';
import { useLabelEditing } from '../labelEditing';
import type { TimeScale } from './scale';

interface Props {
  labels: Label[];
  sessions: Session[];
  scale: TimeScale;
  clock: Clock;
}

interface Bar {
  id: string;
  name: string;
  kind: 'range' | 'session';
  from: number;
  to: number;
  text: string;
  title: string;
}

/** 只读标签轨道：时间段按区间；会话按“范围内首末记录”，标“大致记录范围”，不伪造持续时长。 */
export function LabelTrack({ labels, sessions, scale, clock }: Props) {
  const bars: Bar[] = [];
  for (const l of labels) {
    if (l.target.kind === 'range') {
      const from = Date.parse(l.target.from);
      const ongoing = l.target.to === null;
      const to = ongoing ? clock.asOfMs : Date.parse(l.target.to!);
      if (to <= scale.from || from >= scale.to) continue;
      bars.push({
        id: l.id,
        name: l.name,
        kind: 'range',
        from,
        to,
        text: ongoing ? `${fmtDateTimeRel(from, clock.asOfMs, clock.tz)}–进行中` : fmtRangeLabel(from, to, clock.tz),
        title: `时间段标签：${l.name}`,
      });
    } else {
      const sessionId = l.target.session_id;
      const s = sessions.find((x) => x.id === sessionId);
      if (!s) continue;
      const from = Date.parse(s.first_record_in_range_at);
      const to = Date.parse(s.last_record_in_range_at);
      bars.push({
        id: l.id,
        name: l.name,
        kind: 'session',
        from,
        to,
        text: `会话 · 大致记录范围 ${fmtDateTimeRel(from, clock.asOfMs, clock.tz)}–${fmtDateTimeRel(to, clock.asOfMs, clock.tz)}`,
        title: `会话标签：${l.name}（范围内首末记录时间，不是精确起止）`,
      });
    }
  }

  const ed = useLabelEditing();
  if (bars.length === 0) return <p className="small muted" style={{ margin: 0 }}>这个范围内没有标签。</p>;

  const rowH = 36;
  return (
    <div className="label-track" style={{ height: bars.length * rowH + 4 }}>
      {bars.map((b, i) => {
        const left = scale.pct(b.from);
        const width = Math.max(scale.pct(b.to) - left, 0.8);
        const top = i * rowH + 4;
        // 条太窄时文字放在条外侧，条宽仍只代表记录范围，不为放字而加长。
        const inside = width >= 22;
        const textOnLeft = left + width > 60;
        return (
          <div key={b.id}>
            <div
              className={`label-bar ${b.kind}${ed.writable ? ' clickable' : ''}`}
              title={ed.writable ? `${b.title}\n点击编辑` : b.title}
              style={{ left: `${left}%`, width: `${width}%`, top }}
              role={ed.writable ? 'button' : undefined}
              tabIndex={ed.writable ? 0 : undefined}
              onClick={() => ed.open({ mode: 'edit', labelId: b.id })}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && ed.open({ mode: 'edit', labelId: b.id })}
            >
              {inside && (
                <>
                  {b.name}
                  <span className="num">{b.text}</span>
                </>
              )}
            </div>
            {!inside && (
              <div
                className="label-outside small"
                title={b.title}
                style={{
                  top,
                  ...(textOnLeft ? { right: `${100 - left + 0.6}%` } : { left: `${left + width + 0.6}%` }),
                }}
              >
                {b.name} <span className="num muted">{b.text}</span>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
