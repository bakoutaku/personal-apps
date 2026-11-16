# AI Usage Dashboard

English · [简体中文](README.zh-CN.md) · [日本語](README.ja.md)

Local token usage, recent activity, calendar history, and observed Codex quota. Claude assisted on the React and TypeScript frontend and GPT on the Python and SQLite backend. The macOS source preview omits the original character art and installers. Windows has yet to be verified on a physical machine.

## Synthetic demo

From the repository root, with Python 3.9+ and Node.js 24+. Open http://127.0.0.1:5174. The demo does not read local AI logs.

```sh
cd ai-usage-dashboard
python3 backend/tools/build_contract.py
cd frontend
npm ci
npm run dev
```

## Local backend

Run from the repository root. Automatic collection is off by default. It runs on loopback and only imports chosen logs. ChatGPT and Claude chat, Cowork, and Claude quota are outside current coverage.

```sh
cd ai-usage-dashboard
python3 backend/tools/build_contract.py
(cd frontend && npm ci && npm run build)
cd backend
python3 -m usage_dashboard --data-dir ./local/public-demo serve --frontend-dist ../frontend/dist --open-browser
```
