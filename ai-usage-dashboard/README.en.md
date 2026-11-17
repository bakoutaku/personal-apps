# AI Usage Dashboard

English · [简体中文](README.md) · [日本語](README.ja.md)

Local token usage, recent activity, calendar history, and observed Codex quota. Claude assisted on the React and TypeScript frontend and GPT on the Python and SQLite backend. The macOS source preview omits the GPT dragon artwork and old installers. Windows has yet to be verified on a physical machine.

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

## Character artwork credits

The local edition used the [GPT dragon mascot by T7moris/GPT-Niang](https://github.com/T7moris/GPT-Niang/tree/b6f5eb8972d1802821006b7208d20a834fa6a08b/gpt-niang-usage/assets) subject to its separate character notice, and [Claude Xiao Ke by aklnaaw/dsh-xiaoke-widget](https://github.com/aklnaaw/dsh-xiaoke-widget/tree/8e2a207bfc9ae3983168dcc847e54734771bce67) under the upstream artwork license (CC BY-NC-SA 4.0). This public preview bundles Xiao Ke unchanged and displays it in the Claude view. See the [bundled artwork credits](frontend/public/characters/SOURCE.md). The GPT dragon illustration is not bundled.
