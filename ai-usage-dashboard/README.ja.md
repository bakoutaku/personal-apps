# AI Usage Dashboard

[English](README.en.md) · [简体中文](README.md) · 日本語

トークン使用量、直近の活動、カレンダー履歴、ログに記録されたCodexの利用枠を確認できます。ClaudeがReactとTypeScriptのフロントエンドを、GPTがPythonとSQLiteのバックエンドを支援しました。上流の白い竜のイラストと旧インストーラーは同梱していません。Windows実機では未検証です。

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

## キャラクター素材の出典

ローカル版では、独自の素材利用声明が付く [T7moris/GPT-Niang の白い竜のキャラクター](https://github.com/T7moris/GPT-Niang/tree/b6f5eb8972d1802821006b7208d20a834fa6a08b/gpt-niang-usage/assets)と、上流の素材ライセンスが CC BY-NC-SA 4.0 の [aklnaaw/dsh-xiaoke-widget の Claude「小克」](https://github.com/aklnaaw/dsh-xiaoke-widget/tree/8e2a207bfc9ae3983168dcc847e54734771bce67) を使用しました。現在は新たに生成した2枚を表示します。GPT画面の白い竜は文章から生成し、Claude画面の読書キャラクターは白い竜の画風を参照して生成しました。「小克」は以前の公開プレビューで使用していました。[素材の出典と生成プロンプト](frontend/public/characters/SOURCE.md)を参照してください。
