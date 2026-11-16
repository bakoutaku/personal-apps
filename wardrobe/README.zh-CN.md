# Wardrobe · 个人数字衣橱

[English](README.md) · 简体中文 · [日本語](README.ja.md)

管理衣物、商品、穿搭和购买记录，支持照片、筛选、标签、导入预览和 REST API。本地计算的建议需审核后才应用。技术栈为 Vue、TypeScript、FastAPI 和 SQLite，GPT 与 Claude 参与开发和审查。

## 用虚构数据试用

在 macOS 准备 uv、Python 3.12 和 Node.js 24+，从仓库根目录运行。打开 http://127.0.0.1:18765。演示使用独立目录和端口，只向空数据库写入示例。

```sh
cd wardrobe
export WARDROBE_DATA_DIR="$PWD/data/demo" WARDROBE_PORT=18765
./wardrobe start --no-open
./wardrobe seed-demo
```

从 wardrobe 目录运行以下命令停止演示。

```sh
WARDROBE_DATA_DIR="$PWD/data/demo" WARDROBE_PORT=18765 ./wardrobe stop
```
