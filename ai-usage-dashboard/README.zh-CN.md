# AI Usage Dashboard

[English](README.md) · 简体中文 · [日本語](README.ja.md)

查看本机 token 用量、最近活动、日历历史和日志中实际记录的 Codex 额度。前端使用 React 与 TypeScript，由 Claude 辅助开发。后端使用 Python 与 SQLite，由 GPT 辅助开发。macOS 源码预览省略原角色立绘与旧安装包。Windows 尚未实机验证。

## 体验模拟数据

从仓库根目录运行，需要 Python 3.9+ 和 Node.js 24+。打开 http://127.0.0.1:5174。演示不会读取本机 AI 日志。

```sh
cd ai-usage-dashboard
python3 backend/tools/build_contract.py
cd frontend
npm ci
npm run dev
```

## 运行本机后端

从仓库根目录运行。自动采集默认关闭，服务只在本机监听，只导入主动选择的日志。目前未覆盖 ChatGPT 或 Claude 聊天、Cowork 和 Claude 额度。

```sh
cd ai-usage-dashboard
python3 backend/tools/build_contract.py
(cd frontend && npm ci && npm run build)
cd backend
python3 -m usage_dashboard --data-dir ./local/public-demo serve --frontend-dist ../frontend/dist --open-browser
```
