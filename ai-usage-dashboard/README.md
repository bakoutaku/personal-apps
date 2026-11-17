# AI Usage Dashboard

简体中文 · [日本語](README.ja.md) · [English](README.en.md)

在本机查看 Codex 和 Claude Code 的使用记录。可以区分最近活动、按日／周／月汇总的历史，以及 Codex 日志实际记录的额度快照。当前提供 macOS 源码预览，Windows 尚未实机验证。前端为 React 与 TypeScript，由 Claude 辅助开发。后端为 Python 与 SQLite，由 GPT 辅助开发。

## 能看到什么

- **用量**按时间段查看 token 记录。缺失时段会标记为未知，日志中的 token 数量无法直接换算为订阅额度。
- **额度**根据 Codex 日志中已有的快照展示历史观测，数据可能晚于账户页面的变化。目前没有 Claude 额度数据。
- **历史与明细**支持按时间范围看活动、事件与会话。连接本机后端后可给时间段或会话加标签。
- **数据来源**显示来源状态与采集设置。当前覆盖支持格式的本机 Codex 和 Claude Code 日志。ChatGPT 聊天、Claude 聊天及 Cowork 未接入。

## 先体验模拟数据

需要 Python 3.9+、Node.js 24+ 和 npm。以下命令从仓库根目录执行。第一步生成虚构记录和接口描述文件。

```sh
cd ai-usage-dashboard
python3 backend/tools/build_contract.py
cd frontend
npm ci
npm run dev
```

打开 [127.0.0.1:5174](http://127.0.0.1:5174/)。页面上的「模拟数据」提示表示图表使用虚构记录。演示无需账号或 API Key，也不会读取本机 AI 日志。终端按 Ctrl+C 可停止。

## 使用本机后端

以下命令同样从仓库根目录执行。构建后，后端在独立目录创建 SQLite 数据库，并打开浏览器完成一次性本机配对。

```sh
cd ai-usage-dashboard
python3 backend/tools/build_contract.py
(cd frontend && npm ci && npm run build)
cd backend
python3 -m usage_dashboard --data-dir ./local/public-demo serve --frontend-dist ../frontend/dist --open-browser --no-collection
```

默认地址为 [127.0.0.1:49173](http://127.0.0.1:49173/)。上面的命令明确关闭采集，适合先看空库。要使用自动采集时，结束该进程，再去掉 `--no-collection` 重新启动，并在「数据来源」页明确启用并选择日志位置。按 Ctrl+C 可停止后台服务及采集。

数据保存在本机，SQLite 数据库未加密。程序以白名单提取用量相关字段，无需供应商 API Key，也不把完整对话保存到数据库。服务监听回环地址，供本机使用。

## 角色素材来源

早期**本机版**用过两张未经本项目改绘的第三方角色图。GPT 白龙娘来自 [T7moris/GPT-Niang 的角色素材与声明](https://github.com/T7moris/GPT-Niang/tree/b6f5eb8972d1802821006b7208d20a834fa6a08b/gpt-niang-usage/assets)，角色图适用单独声明。Claude「小克」来自 [aklnaaw/dsh-xiaoke-widget](https://github.com/aklnaaw/dsh-xiaoke-widget/tree/8e2a207bfc9ae3983168dcc847e54734771bce67)，上游在 [LICENSE-ARTWORK](https://github.com/aklnaaw/dsh-xiaoke-widget/blob/8e2a207bfc9ae3983168dcc847e54734771bce67/LICENSE-ARTWORK) 下标注 CC BY-NC-SA 4.0。

当前公开版没有打包这两张立绘或旧安装包。界面仍保留用于识别数据来源的供应商图标，出处见应用的「关于」页。
