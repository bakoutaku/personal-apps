import { consumeLaunchFragment, LaunchConnector } from './api/launchPairing';
import { StrictMode, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { Root } from './App';
import { AuthGate } from './components/AuthGate';
import './styles/tokens.css';
import './styles/base.css';

// 数据来源在构建时确定（.env.*），同一页面只用一种：
// - npm run dev → mock（只读 contracts/mocks）
// - npm run dev:live / npm run build → http（同源 /api/v1，先配对）
// mock 分支用动态导入，HTTP 构建中被常量折叠掉，模拟数据不进产物。
// 一键启动的 #launch_pairing 在挂载、路由解析和任何请求之前同步取出并从地址栏清掉；码只留在内存。
const launch = new LaunchConnector(consumeLaunchFragment());
// 已打开的页面里 hash 变成启动 fragment（不重新加载）：同样先清掉。先于 App 的 hashchange 监听注册，路由看不到它。
window.addEventListener('hashchange', () => launch.offer(consumeLaunchFragment()));

async function start(): Promise<ReactNode> {
  if (import.meta.env.VITE_DATA_ADAPTER === 'http') return <AuthGate launch={launch} />;
  const { MockAdapter } = await import('./api/mockAdapter');
  // 两套演示：默认是额度窗口 / 最近五小时（gpt-observed / claude-tokens）；
  // npm run dev:history 是日 / 周 / 月（gpt-history / claude-history）。两套不在同一页面混用。
  const history = import.meta.env.VITE_MOCK_SET === 'history';
  const adapter = new MockAdapter({
    scenarioId: history ? 'gpt-history' : 'gpt-observed',
    scenarioByProvider: history
      ? { gpt: 'gpt-history', claude: 'claude-history' }
      : { gpt: 'gpt-observed', claude: 'claude-tokens' },
  });
  return <Root adapter={adapter} />;
}

const root = createRoot(document.getElementById('root')!);
void start().then((node) => root.render(<StrictMode>{node}</StrictMode>));
