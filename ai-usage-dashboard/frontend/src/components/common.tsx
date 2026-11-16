import type { Fetched } from '../api/adapter';
import { isKnownReason, reasonText } from '../domain/sources';

export interface Clock {
  tz: string;
  asOfMs: number;
}

/** 读取失败时的说明。fixture_missing 明确是“样本未提供”，不画成空数据。 */
export function FetchProblem({ result, what }: { result: Fetched<unknown> & { ok: false }; what: string }) {
  const q = Object.entries(result.request.query)
    .map(([k, v]) => `${k}=${v}`)
    .join('&');
  if (result.kind === 'fixture_missing') {
    return (
      <div className="notice missing" role="status">
        模拟数据未提供{what}的这个查询（fixture_missing），所以这里不显示任何数值，也不代表没有用量。
        <br />
        <code>
          {result.request.path}
          {q ? `?${q}` : ''}
        </code>
      </div>
    );
  }
  if (result.kind === 'incomplete') {
    return (
      <div className="notice error" role="alert">
        {what}没有读完（已读 {result.loadedRows} 条，仍有后续分页）。为避免把截断数据当成完整合计，这里不显示。请缩小时间范围后重试。
      </div>
    );
  }
  if (result.kind === 'unauthorized') {
    return <div className="notice missing">本应用的浏览器会话已失效，需要重新配对后才能读取{what}。</div>;
  }
  if (result.kind === 'unreachable') {
    return (
      <div className="notice error" role="alert">
        本地服务不可达，暂时读不到{what}。请确认后端已经启动（不能据此判断进程一定已停止）。
      </div>
    );
  }
  if (result.kind === 'http_error') {
    const hint =
      result.status === 422
        ? '查询参数不被接受，可能是范围太大，请缩小时间范围。'
        : result.status === 404
          ? '后端没有找到这个对象，可能已被重建。'
          : result.status === 409
            ? '数据在读取过程中发生了变化，请刷新。'
            : '后端没能完成这个请求。';
    return (
      <div className="notice error" role="alert">
        {what}读取失败：{hint}
        <br />
        <code>
          HTTP {result.status} · {result.code}
        </code>
      </div>
    );
  }
  return (
    <div className="notice error" role="alert">
      {what}的响应无法使用：{result.detail}
    </div>
  );
}

export function StatusDot({ kind }: { kind: 'ok' | 'off' | 'part' | 'err' }) {
  return <span className={`dot d-${kind}`} aria-hidden="true" />;
}

/** 覆盖原因列表：已知代码显示中文；未知代码显示“未识别的覆盖原因”，原始代码只放在悬停详情里。 */
export function ReasonList({ codes, sep = '、' }: { codes: string[]; sep?: string }) {
  const uniq = [...new Set(codes)];
  return (
    <>
      {uniq.map((c, i) => (
        <span key={c} title={isKnownReason(c) ? undefined : `原始代码：${c}`}>
          {i > 0 && sep}
          {reasonText(c)}
        </span>
      ))}
    </>
  );
}
