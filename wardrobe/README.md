# Wardrobe · 个人数字衣橱

简体中文 · [日本語](README.ja.md) · [English](README.en.md)

一个在本机管理衣物、商品、穿搭和购买记录的工具。目前是试用版，主要在 macOS 开发。界面使用中文。技术栈为 Vue、TypeScript、FastAPI 和 SQLite，GPT 与 Claude 参与开发和审查。

## 能做什么

- **我的衣橱**记录衣物、照片、品牌、尺码、颜色和标签，可搜索和筛选。
- **商品与购买记录**分别管理商品资料与实际购买明细。
- **穿搭**将多件衣物整理成可重复使用的组合。
- **导入中心**可先预览 JSON 导入，再决定是否应用。颜色、标签和分类建议在本机计算，审核后才应用。
- **数据管理**支持本机保存、备份和恢复，也提供 REST API。

## 用虚构数据试用

在 macOS 准备 uv、Python 3.12 和 Node.js 24+。从仓库根目录执行：

```sh
cd wardrobe
export WARDROBE_DATA_DIR="$PWD/data/demo" WARDROBE_PORT=18765
./wardrobe start --no-open
./wardrobe seed-demo
```

打开 [127.0.0.1:18765](http://127.0.0.1:18765/)。首次启动会构建网页。演示使用单独的数据目录和端口，只在空数据库中生成虚构衣物和示例图片。接口说明见 [本机 API 文档](http://127.0.0.1:18765/api/docs)。

从 `wardrobe` 目录运行下面的命令停止演示：

```sh
WARDROBE_DATA_DIR="$PWD/data/demo" WARDROBE_PORT=18765 ./wardrobe stop
```

## 开始记录自己的衣物

在未设置演示环境变量的新终端中，进入 `wardrobe` 目录并运行 `./wardrobe start`。默认访问 [127.0.0.1:8765](http://127.0.0.1:8765/)。正常使用的数据位于项目的 `data/`，演示数据则位于 `data/demo/`。从同一目录运行 `./wardrobe stop` 可结束正常使用的服务。

SQLite 数据库、相片和备份都保存在本机。公开仓库仅含源码及生成虚构演示数据所需的文件。
