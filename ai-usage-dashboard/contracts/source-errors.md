# 来源状态与错误码（v0.2.0）

`SourceErrorCode` 是采集状态的枚举，不是 HTTP Error.code。供应商原始错误不直接出现在前端。
无法归类的情况返回 unknown_error；未来新版本也应有通用中文回退，不把 message 原文当作可执行建议。

| error_code | 中文提示 | 建议操作 |
| --- | --- | --- |
| source_unreadable | 无法读取来源 | 检查来源是否仍可访问，查看本机诊断 |
| source_missing | 来源文件或目录不存在 | 在本机设置中重新选择来源 |
| permission_denied | 没有读取权限 | 检查所选来源的读取权限，不建议一键授予全磁盘权限 |
| unsupported_format | 当前版本无法识别记录格式 | 更新适配器；保留已有历史，不清库 |
| auth_required | 来源尚未登录 | 通过对应官方客户端登录；不在网页填供应商密码 |
| auth_expired | 来源登录状态已失效 | 在官方客户端重新登录 |
| rate_limited | 来源暂时限制查询 | 按计划等待；不以密集重试绕过限制 |
| network_unavailable | 暂时无法连接来源服务 | 检查网络，保留本机历史 |
| source_timeout | 来源响应超时 | 稍后重试，显示原有历史 |
| collector_internal_error | 采集过程发生错误 | 查看已脱敏的本机诊断 |
| unknown_error | 暂时无法更新来源 | 保留现有数据，查看本机诊断 |

## 重试字段

- `consecutive_failure_count`：已知连续失败次数；未开始采集/无法确定时为 null。一次成功采集清零。
- `retry_mode=automatic`：采集器支持且当前已启用自动计划；next_attempt_at 是计划时间，不保证睡眠/关机期间执行。
- `retry_mode=manual`：没有自动重试，next_attempt_at=null；只给出手动恢复说明，契约暂不提供 HTTP“立即重试”端点。
- `retry_mode=disabled`：来源未配置或停用，next_attempt_at=null。
- automatic 也可 next_attempt_at=null，表示尚无下一次计划；前端不能自行加上固定分钟数。
- 当前只有模拟例子。真实第一版未实现调度时必须返回 manual，不能为了对应线框图虚构下次重试时间。

## “更新较久”与“服务停止”

last_attempt_at 只是最近一次采集尝试，last_success_at 只是最近一次成功。
前者很旧可能是手动模式、暂停、休眠、尚未到计划时间；**不能单凭它断言服务没有运行**。
用 connection_status=error 及 error_code 表示最近失败；历史数据继续显示。
只有前端对本地服务本身的连接失败，才提示“本地服务不可达”，也不要断言进程一定已停止。
meta.stale_after_seconds 是额度观测的新鲜度阈值，不是所有来源都必须按这个间隔轮询。

## 空历史

- last_record_at 是这个来源已确认的有效用量/额度记录的最大来源时间，不是扫描文件的时间。保留历史时不因失败清空。
- last_record_at=null **只表示尚无已确认的有效记录时间**，不证明从未使用或日志没有内容。
- history_status=has_records：已确认存在可纳入本应用的有效记录，last_record_at 非 null。
- history_status=empty：成功完成一次完整的本机选定来源发现/解析，没有有效记录，也没有跳过尚无法判断的用量记录；last_success_at 非 null、last_record_at=null。
- history_status=unknown：尚未完整扫描、格式或时间不明、未配置等，不能判空。

只有被选产品的已配置用量来源均确认 empty、至少有一个成功来源且没有 has_records/unknown 来源时，才显示“已接入来源暂无历史记录”。
未接入产品仍保留单独提示；这不是“整个供应商账户从未使用”。来源 error 时优先显示错误状态，不用整页空状态遮住失败。
某个查询范围 `no_records` 只说明该范围没有已记录事件；不能把日期筛选的空结果提升为整个来源的 empty。
来源重建/账户归属变更应建立新命名空间，不通过偷偷清空 last_record_at 改写历史含义。
