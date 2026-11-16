# AI Usage Dashboard

[English](README.md) · [简体中文](README.zh-CN.md) · 日本語

トークン使用量、直近の活動、カレンダー履歴、ログに記録されたCodexの利用枠を確認できます。ClaudeがReactとTypeScriptのフロントエンドを、GPTがPythonとSQLiteのバックエンドを支援しました。元のイラストと旧インストーラーは同梱していません。Windows実機では未検証です。

## サンプルデータで試す

Python 3.9以上とNode.js 24以上を用意し、リポジトリのルートで実行します。http://127.0.0.1:5174 を開きます。デモは端末上のAIログを読み込みません。

```sh
cd ai-usage-dashboard
python3 backend/tools/build_contract.py
cd frontend
npm ci
npm run dev
```

## ローカルのバックエンドを起動する

リポジトリのルートで実行します。自動収集は初期状態で無効です。サービスは端末内でのみ待ち受け、指定したログを取り込みます。ChatGPTやClaudeのチャット、Cowork、Claudeの利用枠は対象外です。

```sh
cd ai-usage-dashboard
python3 backend/tools/build_contract.py
(cd frontend && npm ci && npm run build)
cd backend
python3 -m usage_dashboard --data-dir ./local/public-demo serve --frontend-dist ../frontend/dist --open-browser
```
