import type { Fetched } from '../api/adapter';
import type { Provider, Source } from '../api/types';
import { fmtDateTimeRel } from '../time/tz';
import { ClaudeIcon, OpenAIIcon } from './BrandIcons';
import { StatusDot, type Clock } from './common';

interface Props {
  provider: Provider;
  onProvider: (p: Provider) => void;
  sources: Fetched<Source[]> | null;
  clock: Clock | null;
  /** 右侧附加操作（live：刷新、退出本机会话） */
  actions?: React.ReactNode;
  /** 数据来源页的链接 */
  sourcesHref: string;
  /** 页面导航（首页 / 二级页面） */
  nav?: React.ReactNode;
}

export function TopBar({ provider, onProvider, sources, clock, actions, sourcesHref, nav }: Props) {
  let summary: React.ReactNode = null;
  if (sources?.ok && clock) {
    const n = (st: Source['connection_status']) => sources.data.filter((s) => s.connection_status === st).length;
    const parts = [
      n('available') && `${n('available')} 可用`,
      n('error') && `${n('error')} 失败`,
      n('not_configured') && `${n('not_configured')} 未配置`,
      n('disabled') && `${n('disabled')} 停用`,
    ].filter(Boolean);
    const lastSuccess = sources.data
      .map((s) => s.last_success_at)
      .filter((x): x is string => !!x)
      .sort()
      .at(-1);
    const dot = n('error') > 0 ? 'err' : n('available') > 0 ? 'part' : 'off';
    // 顶栏只留状态点 + 短标签；数量与检查时间放悬停说明，完整内容在数据来源页
    const detail = [
      `数据来源：${parts.join(' · ')}`,
      lastSuccess ? `最近检查成功 ${fmtDateTimeRel(lastSuccess, clock.asOfMs, clock.tz)}（不代表有新记录或新的额度观测）` : '',
    ]
      .filter(Boolean)
      .join('\n');
    summary = (
      <span className="sources-sum" title={detail}>
        <StatusDot kind={dot} />
        来源{n('error') > 0 && <span> · {n('error')} 失败</span>}
        <span className="sr-only">：{detail}</span>
      </span>
    );
  }

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-name">
          Usage<span>.</span>
        </span>
        <span className="eyebrow">AI 使用记录 · 本机优先</span>
      </div>
      <nav aria-label="切换供应商" className="provider-nav">
        <button type="button" className="provider-btn" aria-label="GPT（OpenAI）" title="GPT · OpenAI" aria-current={provider === 'gpt' ? 'page' : undefined} onClick={() => onProvider('gpt')}>
          <OpenAIIcon />
        </button>
        <button type="button" className="provider-btn" aria-label="Claude" title="Claude · Anthropic" aria-current={provider === 'claude' ? 'page' : undefined} onClick={() => onProvider('claude')}>
          <ClaudeIcon />
        </button>
      </nav>
      <div className="topbar-right">
      {summary && (
        <a className={`sources-btn${sources?.ok && sources.data.some((s) => s.connection_status === 'error') ? ' danger' : ''}`} href={sourcesHref}>
          {summary}
        </a>
      )}
      {actions}
      </div>
      {nav}
    </header>
  );
}
