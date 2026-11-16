# 浏览器鉴权决议（契约 v0.2.0）

本机 MVP 已实现并完成 Cookie/CSRF 与前端联调；以下记录协议决议，不等于独立安全审计。Cookie 仅属于本机 Dashboard，与 OpenAI / Claude 登录无关。

## 固定流程

1. 本地启动器绑定固定的 `http://127.0.0.1:<配置端口>`，打开该 origin 下的静态前端。前端资源可未配对加载，数据 API 不公开。
2. 页面启动先 `GET /api/v1/auth/session`，使用 `credentials: 'same-origin'`。
3. 200：有效的 HttpOnly 应用 Cookie 已恢复，响应包含 CSRF token、绝对到期时间和空闲超时。CSRF token 只存内存，随后请求数据。
4. 401：显示一次本机配对界面；这是正常的未配对状态，不是供应商登录失效。网络不通则提示本地服务不可达，不反复请求供应商。
5. 用户从本地启动器界面/交互终端取得一次性配对码；前端 `POST /api/v1/auth/session`，JSON body `{pairing_code}`，请求头 `X-Dashboard-Pairing: 1`。
6. 验证成功返回 201、BrowserSessionResponse 和 Set-Cookie。成功后前端立即清空输入中的码。刷新再从步骤 2 开始，**有效会话不需要重新配对**。
7. 关闭/重启服务仍可在同一来源与数据库下恢复未过期会话；无痕窗口、清理 Cookie、过期、主动注销后需重新配对。
8. `DELETE /api/v1/auth/session` 撤销当前浏览器会话，要求 Cookie + X-CSRF-Token。返回 204，并以同一 Path 清除 Cookie。不能用它退出供应商账号。

配对码至少 128 位随机熵，5 分钟有效、一次性；不能是六位数字。只显示在用户主动启动的本机控制界面，不放 URL、日志文件、SQLite 或供应商配置。进程内只保留用于验证的摘要和有效期。
失败尝试按实例限速：每 5 分钟最多 5 次（无论是否换 IP）；第 6 次起 429，返回 Retry-After。非法/过期码统一不透露更多账户信息。
替换/关闭配对流程立即废弃旧码；已用、过期或无效码不得创建会话。以上限速不是防御有本机同用户执行权限恶意程序的完整边界。

## Cookie 和凭据

HTTP 回环配置：

```http
Set-Cookie: aud_session=<random-256-bit-secret>; HttpOnly; SameSite=Strict; Path=/api/v1; Max-Age=604800
Cache-Control: no-store
```

- 不设置 Domain，是 host-only Cookie；“仅限回环”由服务绑定地址、Host / Origin 检查共同实现，不是 Cookie 的一个特殊属性。
- 固定使用 127.0.0.1；不要在 localhost 与 IP 间跳转。Cookie 不按端口隔离，不能声称它能防御同机恶意服务。不要在应用 origin 托管不可信网页。
- 仅 HTTP 回环版本不设置 Secure，也不用 __Host- / __Secure- 前缀。不能依赖所有浏览器对 localhost Secure Cookie 的例外行为；未来若使用 HTTPS 必须设置 Secure。Safari 等浏览器的具体行为需实施时验收。[MDN Cookie 指南](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Cookies)
- 最长 7 天，空闲 24 小时。每个有效的已鉴权请求更新 last_seen，不延长绝对到期时间；API 响应中的 expires_at 是绝对到期时间，可能先因空闲超时失效。
- 后端只存 `SHA256("session-v1:" + raw_secret)` 摘要及 origin、有效期、撤销信息。原始 Cookie 值不存 SQLite、不回显 JSON、不写日志。
- CSRF 值可稳定采用 `HMAC-SHA256(key=raw_secret, message="aud-csrf-v1")`。从当前 Cookie 计算，不存数据库；刷新/多标签页恢复不改变它。验证用常量时间比较。实现应使用成熟密码库，不自制签名格式。
- 浏览器 JavaScript 不保存 Bearer 令牌。已有 Bearer 方式保留给显式配置的非浏览器本地客户端；未提供发行/管理该令牌的 HTTP 端点。两种凭据同时出现时拒绝，避免含糊的优先级。
- 应用会话摘要及供应商令牌不是一回事。供应商凭据仍不进入本应用数据库。

## 请求保护

生产浏览器只允许同源。开发时前端开发服务代理 `/api/v1`，保留 Cookie/Set-Cookie，后端仅接受明确登记的开发 origin。不要启用 `Access-Control-Allow-Origin: *` 或任意凭据跨域。
Host 按完整地址/端口允许列表检查，不信任客户端自行提交的 X-Forwarded-*。Origin 存在时必须精确匹配登记来源（含 scheme/host/port），拒绝 null Origin。
Cookie 请求读取敏感数据（包括恢复 CSRF）时，缺少 Origin 必须由同源 Fetch Metadata 或同源 Referer 验证；两个都缺失则拒绝。Bearer 非浏览器客户端可无 Origin，但仍需合法 Host。

Cookie 鉴权的 POST/PATCH/DELETE：要求合法 Origin、`X-CSRF-Token` 与会话匹配；有 body 时只接受 application/json。配对尚无会话，改用严格 Origin、一次性码与固定 X-Dashboard-Pairing 头。
GET/HEAD 不修改标签、用量、配对状态或计划任务；GET session 只允许内部会话 last_seen 更新。
SameSite 防御的是跨站，不能替代同源检查和 CSRF 校验；这也是两个同机不同端口仍需精确 Origin 校验的原因。[OWASP CSRF 指南](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)

所有 API 和鉴权响应设置 `Cache-Control: no-store`，不被 Service Worker 缓存。日志移除 Cookie、Authorization、配对码、CSRF 及请求原文。
认证维护不增加用量的 data_revision，避免前端仅因恢复/刷新会话就重读整个历史。

静态 auth fixture 不会设置实际 Cookie，其中任何 MOCK 值都不能用于真实鉴权。本机 MVP 已实现此流程，并测试 Cookie/CSRF、过期、恢复、退出、Host/Origin 与配对限制；真实浏览器及开发代理联调尚待验证，自动测试不能称为安全审计。
