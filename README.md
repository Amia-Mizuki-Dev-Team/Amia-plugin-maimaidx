# Amia-plugin-maimaidx

Amia / MizukiBot 的舞萌 DX 综合插件。NoneBot 插件标识符保留为 `lxns_b50`，整合 LXNS 与 DivingFish 数据源，提供玩家查分、曲库检索、图片渲染、进度统计、群聊互动和 `MaimaiDataProvider`。

## 来源与修改边界

本项目借鉴 [`Yuri-YuzuChaN/nonebot-plugin-maimaidx`](https://github.com/Yuri-YuzuChaN/nonebot-plugin-maimaidx) 的公开接口、资源布局和实现方向，审查参考提交：

```text
83a1bee46fad81ad4436b6fba5863ac4d2abb976
```

本仓库没有整包复制上游；Amia 自有的双数据源、Provider、身份、错误码、诊断、按钮、环境加载和业务扩展继续独立维护。第三方资源及设计署名见 `RESOURCE_ATTRIBUTION.md`，不得删除原作者或美术设计署名。

## 主要功能

### 玩家与成绩

```text
b50 / 生成我的B50
ap50
minfo <曲名或 ID>
ginfo <曲名或 ID>
分数线 <曲目> <目标达成率>
水鱼授权
水鱼授权状态
水鱼筛选 <key=value ...>
mai状态 / 个人状态大盘
mai曲线
mai最近
mai热度
```

B50 的 B15/B35 按歌曲所属版本划分：B15 为当前版本歌曲，B35 为其余歌曲；它与 DX/SD 谱面类型不是同一个维度。

## 数据源：落雪 + 水鱼 双源自动汇总

成绩数据没有“默认数据源”开关，也移除了 `切换数据源` 指令：所有成绩查询并发请求落雪与水鱼两个上游，并按同谱面键（归一化原生 song_id + 谱面类型 + 难度序号）逐谱面汇总。

汇总规则（同谱面键在两源都有成绩时）：

- `achievements`、`ra` 取两源最大值；
- `fc` 取两源最优（app > ap > fcp > fc；空串视为无）；
- `fs` 取两源最优（fsdp/fdxp > fsd/fdx > fsp > fs；空串视为无）；
- `dxScore`、`rate` 取达成率较高一条记录（平手取落雪）；
- `ds`、`level` 取非零方，冲突时以落雪为准并记录日志；
- 同谱面出现在两源不同 B50 分组桶时，归入达成率较高一方所在桶；
- 汇总后 rating = B35 + B15 单曲 ra 之和（合计为 0 时回退两源 rating 的最大值）；
- 单源成绩原样保留。

降级与标注：

- 任一源失败时自动降级为另一源单源结果，并在回复中标注（如「仅落雪（水鱼未授权）」「仅水鱼（落雪失败：上游超时）」）；
- 水鱼 OAuth 未授权时：B50 公共接口照常参与汇总；单曲/全量成绩接口不可用，自动降级为仅落雪并提示发送「水鱼授权」；
- AP50 依赖落雪 friend_code 端点，水鱼侧不参与，结果标注「仅落雪」；
- `mai曲线` / `mai最近` / `mai热度` 是落雪特供功能，直接查询落雪，不再要求先切换数据源；
- 落雪 `GET /player/{friend_code}/scores`（SimpleScore）没有达成率字段，只在 Provider 全量成绩中按谱面键补充 fc/fs 徽章，不能作为达成率数据源。

谱面身份归一化：水鱼 DX 谱面 id = 原生 id + 10000，落雪使用原生 id，宴会场 id ≥ 100000 不做偏移；汇总结果统一使用原生 id。

### 曲库与进度

```text
查歌 <关键词>
id <歌曲 ID>
定数查歌 / bpm查歌 / 曲师查歌 / 谱师查歌
<别名>是什么歌
<歌曲>有什么别名
<等级>定数表
<等级><目标>完成表
<版本><目标>进度
我要上<分数>
更新别名库（管理员）
更新定数表（SUPERUSER 私聊）
```

`id` 指令使用词边界匹配，兼容官方 Bot 卡片按钮回发时存在 `@Bot` 前缀的消息场景。

启动和每天凌晨的同步会自动刷新 LXNS、水鱼曲库以及柚子公共别名库。定数表图片属于本地生成资源，曲库更新后需要私聊 `更新定数表` 重新生成，避免在启动阶段阻塞 Bot。

### 群聊互动

```text
猜歌
猜曲绘
开启mai猜歌
关闭mai猜歌
重置猜歌
```

群猜歌按群隔离，监听器不能抢占其他插件的普通命令。`猜曲绘` 使用局部曲绘作为题面，结束后再发送完整答案信息。

### DX Pass

`dxpass`、`名片`、`生成名片` 和 `金卡` 提供角色、外框、背景选择与 HTML/PIL 渲染。涉及经济扣费时必须保留确认、操作者校验、幂等和失败退款。

## `mai帮助` 按钮

默认按钮只保留常用且安全的入口：

- 生成我的 B50；
- 个人状态大盘。

付费名片不会出现在默认快捷按钮中，但对应文字指令仍可按权限和确认流程使用。

## 身份、依赖与运行边界

- Gensokyo 的 `self_id`、`user_id` 保持字符串/OpenID，不直接传给需要真实 QQ 的数据源；
- 真实 QQ 优先通过 qbind 解析，Provider 不能因为 `OFFICIAL_BOT_IDS` 配置误拒绝可正常解析的用户；
- 账号绑定由 `maimai_sync` / qbind 负责，maimaidx 不建立第二套绑定系统；
- 跨插件公共能力优先通过 `Amia-plugin-Maimai-Manage` 门面获取，避免直接依赖其他插件内部实现；
- `load_env_layers` 等共享能力由 Manage → sync 的公共映射提供，避免在 maimaidx 内复制实现后产生漂移；
- 加载依赖使用 `nonebot.require()`，避免重复导入两份 `amia_core`、qbind、maimai_sync 或 maimai_manage。

### NoneBot 环境分层

插件环境加载遵循 NoneBot2 多环境分层：

```text
.env
.env.{ENVIRONMENT}
真实系统环境变量
```

后加载的层级只补充/覆盖允许的项目配置，真实系统环境变量优先。环境文件解析带有路径穿越防护和诊断日志，不应把 Secret 内容写入日志。

## 错误处理与诊断

参数错误、未绑定、未游玩等预期情况只显示原因与下一步；上游或内部异常使用稳定的 `HX-MAI-*` 错误码。

成绩获取失败的诊断已贯通命令层、取数层和回发层；正常成功路径保持静默。任何错误处理都不得把长 traceback、Token、HTTP 响应正文、数据库错误或 OAuth Secret 直接发给用户。

失败时可以生成脱敏诊断文件，并提示移交开发者群 `1053964431`。诊断文件发送失败时仍应保留错误码和日志时间，不能伪装为成功。

常见错误码：

| 错误码 | 含义 |
| --- | --- |
| `HX-MAI-001` | 用户尚未绑定 |
| `HX-MAI-002` | 数据源凭据缺失 |
| `HX-MAI-003` | 上游请求超时 |
| `HX-MAI-004` | 上游数据源失败 |
| `HX-MAI-005` | 用户或数据不存在 |
| `HX-MAI-006` | 本地绘图资源损坏或缺失 |
| `HX-MAI-007` | 上游响应结构不兼容 |
| `HX-MAI-008` | Bot 与 OneBot/Gensokyo 消息通道超时或断开 |
| `HX-MAI-009` | 未分类错误 |

## 水鱼 OAuth

水鱼的 `Developer-Token` 已停止签发，旧的 `/dev/*` 和 `/query/plate` 接口将在 2026-10-01 00:00（UTC+8）停止服务。

B50 使用公开的 `/query/player`，不需要 OAuth；单曲成绩、完整成绩、牌子和进度等功能使用 OAuth Bearer 令牌。

首次使用完整成绩功能时发送 `水鱼授权`，本人打开设备码链接并确认授权。在启用 `USE_MARKDOWN=true` 或配置了 `OFFICIAL_BOT_IDS` 的官方 Bot 上，回复会提供“打开水鱼授权页”和“检查授权状态”按钮；其他适配器保留带链接的纯文本降级。

完成后发送 `水鱼授权状态` 或重新执行原查询。Bot 不保存用户访问令牌，重启后会按 qbind 的真实身份重新换取短期令牌。

授权成功后会把一条不含凭据的授权元数据写入现有 `maimai_sync.user_binds.diving_fish_oauth` 字段，供其他插件复用授权状态：

```json
{
  "version": 1,
  "provider": "diving-fish",
  "status": "authorized",
  "client_id": "<OAuth 应用 Client ID>",
  "subject_ref": "ref:<64 位摘要>",
  "scope": ["prober.records.read"],
  "authorized_at": 1700000000,
  "checked_at": 1700000000
}
```

其他插件应通过 maimai 公共门面读取绑定状态，并确认 `provider/status/scope`。如果另一个插件使用不同 OAuth 应用的 `client_id`，不能直接复用这条授权记录，必须为该应用重新授权。

数据库中不会保存 `client_secret`、`access_token`、`device_code` 或 refresh token；旧的 `fish_token` 仍保留给成绩上传 Import-Token 使用，不能拿来存 OAuth JSON。

服务端筛选示例：

```text
水鱼筛选 level_index=3 ds=13.5.. fc=fc,fcp,ap,app
水鱼筛选 version="宴会場" achievements=100.5.. page=2
水鱼筛选 title="雨露霜雪"
```

筛选只查询发送者本人；未知字段、无效范围和过长参数会在本地拒绝。水鱼响应的 `filters` 回显缺失时按数据格式异常处理，避免误把未过滤的全量成绩发出。

## amia-core Provider

稳定 Provider 名称：

```python
core.MAIMAI_DATA_PROVIDER  # "maimai.data"
```

提供玩家摘要、完整成绩、曲库、谱面信息和 B50 扩展。玩家摘要与 B50 记录来自落雪 + 水鱼双源逐谱面汇总，rating 为合并值；统一谱面键由基础 `song_id + chart_type + difficulty_index` 组成；消费者不能自行 `% 10000` 或读取 maimaidx 私有数据文件。

曲目信息卡涉及 B15/B35 增益计算时，应先按歌曲版本决定所属 Best 分组，再按实际谱面类型读取对应 DX/SD 谱面数据，不能把“Best 分组”和“谱面类型”混为一谈。

## 安装

根目录插件模式：

```toml
[tool.nonebot]
plugin_dirs = ["src/plugins"]
```

实际插件目录为：

```text
src/plugins/Amia-plugin-maimaidx/
```

部署时必须完整复制该目录的顶层 Python 文件，包括 `release010_import.py`。虽然该文件名沿用 Release010 历史命名，但当前仍是插件统一兼容导入的一部分，不能因为名称较旧就省略。

`command/` 下多个命令依赖统一错误文案和脱敏诊断；只复制 `command/`、`libraries/` 或旧版 `site-packages` 副本会造成模块缺失或新旧代码混用。更新源码后应同步整个插件目录并完整重启 Bot。

## 配置

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `LXNS_TOKEN` | LXNS 开发者 API Token | 空 |
| `DIVING_FISH_OAUTH_CLIENT_ID` | 水鱼 OAuth 应用 Client ID | 空 |
| `DIVING_FISH_OAUTH_CLIENT_SECRET` | 水鱼 OAuth 应用 Client Secret，只能放在服务端环境变量 | 空 |
| `DIVING_FISH_OAUTH_SCOPE` | OAuth 权限范围 | `prober.records.read` |
| `LXNS_B50_PATH` | 曲绘、字体和渲染资源目录 | `data/lxns_b50` |
| `MAI_SYNC_DATA_PATH` | 同步数据库目录 | `data/mai_sync_data` |
| `USE_MARKDOWN` | 启用 Markdown/Keyboard | `false` |
| `OFFICIAL_BOT_IDS` | 官方 Bot ID 列表 | 部署端配置 |
| `SAVEINMEM` | 启动时预加载图片资源 | `true` |
| `MAIMAIDX_ALIAS_PROXY` | 通过 `www.yuzuchan.cn` 访问柚子别名库 | `false` |

旧 `PROBER_SOURCE` 与 `MAIMAIDX_TOKEN` 已废弃，不再生效：数据源固定为落雪 + 水鱼双源自动汇总，水鱼受保护接口只接受 OAuth Bearer 令牌。`.env` 中残留的这两个键会被 Config 的 `extra="allow"` 静默忽略，不会再出现迁移警告。

真实 OAuth Secret 只能通过本地环境或 NoneBot 配置提供，不能写入代码、README、截图、日志、诊断文件或 Git 历史。如果 Secret 曾经出现在聊天、Issue、日志或 Git 历史中，应在水鱼控制台重新生成。

## 资源

仓库保留既有 `data/lxns_b50` 资源。资源许可证和美术署名不等同于代码许可证；发布、二次分发或商用前必须分别确认资源授权。

由上游衍生的 B50、minfo、谱面详情和进度图片统一保留：

```text
Designed by Yuri-YuzuChaN & BlueDeer233. Adapted by Amia_晓山瑞希. Data from {source}.
```

## 测试

在 Amia 根目录可执行：

```powershell
python -m compileall -q src/plugins/Amia-plugin-maimaidx
python -m unittest discover -s src/plugins/Amia-plugin-maimaidx/tests -v
ruff check --select F821,F811,E9 src/plugins/Amia-plugin-maimaidx
git diff --check
```

自动化回归不能替代真实 QQ / Gensokyo 验证。真实 LXNS/DivingFish API、B50/AP50 图片、特殊谱面 ID、DX Pass 扣费退款、Markdown/Keyboard、OAuth、诊断文件上传和生产资源完整性，如果未实际执行就必须保持 `NOT RUN`。

## 发布边界

不得提交真实 Token、OAuth Secret、用户绑定、生产数据库、原始日志、缓存或未脱敏诊断文件。

公开组织仓库是 `Amia-plugin-maimaidx` 的正式维护源；Amia 本地工作树或 `Amia-Backup` 中的同名目录可用于生产快照和版本对照，但不能默认认为任意时刻与组织仓库完全同步。
