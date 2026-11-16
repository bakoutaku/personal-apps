# 本机自动采集设置接口（collector-settings v1）

2026-10-29。**不属于 v0.2.0 数据契约**：`openapi.json`、17 项操作、mock revision=6、252 份 mock 都未改；`meta.api_version` 仍为 `0.2.0`。这两个操作只由实际后端提供（`backend/usage_dashboard/app.py` 的 `LOCAL_OPERATIONS`），mock 前端不调用。前端类型手写在 `frontend/src/api/collectorSettings.ts`。

鉴权与现有接口一致：严格 Host/Origin；浏览器用 HttpOnly Cookie；POST 需要 `X-CSRF-Token`（与标签写入相同）；非浏览器本机客户端可用 `aud_` Bearer。不接受查询参数；PUT/PATCH/DELETE 返回 404。

## GET /api/v1/collector-settings

```json
{"data":{
  "mode":"settings",            // settings | startup_config（--collector-config，只读）| disabled（--no-collection 或无服务）
  "configured":true,            // 私有数据目录中已有有效设置文件
  "settings_error":null,        // "invalid_settings_file" 时本次不采集
  "interval_seconds":60,
  "running":true,               // 采集线程在运行（至少一个来源启用）
  "sources":[{
    "provider":"gpt","product":"codex","enabled":true,
    "location":"standard",      // standard | custom | startup_config
    "display_path":"~/.codex/sessions",          // 主目录内只显示 ~/…；从不返回绝对主目录
    "standard_display_path":"~/.codex/sessions",
    "history":"from_enable",    // from_enable | import_history
    "enabled_at":"2026-10-29T09:05:25.000Z",
    "boundary_status":"ready",  // not_applicable | pending | ready | missing
    "source_id":"src_…",
    "connection_status":"available","error_code":null,"consecutive_failure_count":0,"retry_mode":"automatic",
    "last_attempt_at":"…","last_success_at":"…","last_record_at":"…","next_attempt_at":"…"
  }, {"provider":"claude", …}]
},"meta":{…}}
```

时间字段与 `/sources` 同源同义：`last_success_at` 是检查成功，不代表新记录；`last_record_at` 是已入库记录的最大来源时间；`next_attempt_at` 只是计划。

## POST /api/v1/collector-settings

启用（每次只改一个供应商）：

```json
{"provider":"gpt","enabled":true,"location":"standard","history":"from_enable","confirm_scope":"~/.codex/sessions"}
{"provider":"claude","enabled":true,"location":"custom","custom_path":"~/Logs/claude","history":"import_history","confirm_scope":"~/Logs/claude"}
```

停用：`{"provider":"gpt","enabled":false}`。成功返回与 GET 相同的 `data`。

- `confirm_scope` 必须等于页面展示给用户的范围：标准目录的 `~/…` 形式；自定义目录可以是用户输入原文或其 `~/…` 形式。否则 422 `scope_not_confirmed`。
- 自定义目录必须是已存在的实际目录（非符号链接），不能是磁盘/顶层目录、主目录或其任何上级、包含或位于本应用数据目录。
- 已启用来源只允许：完全相同的请求（无操作，保留边界）、或同一范围 `from_enable → import_history`（“补入已有历史”）。其余改动先停用再启用（`disable_first`）。
- 停用、重新启用都不删除已有记录。重新以 `from_enable` 启用会在那一刻建立新边界，停用期间写入的记录不补入（可改选 `import_history`）。

错误统一为 422 `invalid_body`，`details[0]` 为 `{field, reason}`；页面只翻译 reason，不显示 message 或路径：

| reason | 含义 |
|---|---|
| scope_not_confirmed | 未确认或确认的范围不一致 |
| path_too_broad / path_not_directory / path_symlink / not_absolute / path_unreadable | 目录不符合要求或启用时无法读取（未启用） |
| disable_first | 已启用来源需先停用 |
| unknown_field / invalid / not_allowed | 请求字段不合法 |
| locked_by_startup_config / collection_disabled_for_this_run | 本次启动方式下页面设置只读 |

## 私有设置文件

`<数据目录>/collector-settings.json`（Mac 默认 `~/Library/Application Support/AI Usage Dashboard/`），0600，原子写入（临时文件 + fsync + rename）。由应用管理，不需要手改；字段：`version=1`、`interval_seconds`、`file_key_secret`（文件路径哈希用 HMAC 密钥）、`sources.{gpt,claude}.{enabled,location,path,history,boundary_id,enabled_ms}`。只有这里保存来源绝对路径（仅自定义目录）。加载时严格校验，无效则 `settings_error` 且不采集；下次保存时原文件改名为 `collector-settings.invalid-<ms>.json` 保留。

## SQLite 附加表（无 schema_version 变化）

与 `app_state`、`account_source_bindings` 相同方式在启动时 `CREATE TABLE IF NOT EXISTS`，001 初始结构校验不变，旧库自动补表、不改已有数据：

- `collector_boundaries(source_id, boundary_id, boundary_ms, status pending|ready, ready_ms)`
- `collector_boundary_files(source_id, file_key, signature, size)` —— 启用确认时每个文件的身份与字节数
- `collector_history_exclusions(source_id, key_hash)` —— 边界内已存在记录的稳定身份哈希
- `collector_file_checkpoints(source_id, file_key, signature)` —— 已处理到的文件签名，与入库同一事务写入

`file_key` 是 HMAC(设置文件中的密钥, provider + 路径) 的截断十六进制；SQLite 中没有路径或内容。
