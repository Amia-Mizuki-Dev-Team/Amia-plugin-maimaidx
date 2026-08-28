# Amia-plugin-maimaidx

Amia / MizukiBot 的舞萌 DX 综合插件。NoneBot 插件标识符保留为 `lxns_b50`，整合 LXNS 与 DivingFish 数据源，提供玩家查分、曲库检索、图片渲染、进度统计、群聊互动和 `MaimaiDataProvider`。

## 来源与修改边界

本项目借鉴 [`Yuri-YuzuChaN/nonebot-plugin-maimaidx`](https://github.com/Yuri-YuzuChaN/nonebot-plugin-maimaidx) 的公开接口、资源布局和实现方向，审查参考提交：

```text
83a1bee46fad81ad4436b6fba5863ac4d2abb976
```

本仓库没有整包复制上游；Amia 自有的双数据源、Provider、身份、错误码、诊断文件、按钮和业务扩展继续独立维护。第三方资源及设计署名见 `RESOURCE_ATTRIBUTION.md`，不得删除原作者或美术设计署名。

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
切换数据源 <水鱼|落雪>
mai曲线
mai最近
mai热度
```

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

启动和每天凌晨的同步会自动刷新 LXNS、水鱼曲库以及柚子公共别名库；
定数表图片属于本地生成资源，曲库更新后需要私聊 `更新定数表` 重新生成，避免在启动阶段阻塞 Bot。

### 群聊互动

```text
猜歌
猜曲绘
开启mai猜歌
关闭mai猜歌
重置猜歌
```

群猜歌按群隔离，监听器不能抢占其他插件的普通命令。

### DX Pass

`dxpass`、`名片`、`生成名片` 和 `金卡` 提供角色、外框、背景选择与 HTML/PIL 渲染。涉及经济扣费时必须保留确认、操作者校验、幂等和失败退款。

## `mai帮助` 按钮

默认按钮只保留常用且安全的入口：

- 生成我的 B50；
- 个人状态大盘；
- 默认切换至落雪；
- 默认切换至水鱼。

付费名片不会出现在默认快捷按钮中，但对应文字指令仍可按权限和确认流程使用。

## Release010 身份与错误处理

- Gensokyo 的 `self_id`、`user_id` 保持字符串/OpenID，不直接传给需要真实 QQ 的数据源；
- 账号绑定由 `maimai_sync` / qbind 负责，maimaidx 不建立第二套绑定系统；
- 参数、绑定和未游玩等预期情况只显示原因与下一步；上游/内部异常才显示简短 `HX-MAI-*` 错误码；
- 不把长 traceback、Token、HTTP 响应正文或数据库错误直接发给用户；
- 失败时生成脱敏诊断文件，并提示移交开发者群 `1053964431`；
- 诊断文件发送失败时仍保留错误码和日志时间，不能伪装为成功。

### 水鱼 OAuth

水鱼的 `Developer-Token` 已停止签发，旧的 `/dev/*` 和 `/query/plate` 接口将在
2026-10-01 00:00（UTC+8）停止服务。B50 使用公开的 `/query/player`，不需要 OAuth；
单曲成绩、完整成绩、牌子和进度等功能使用 OAuth Bearer 令牌。

首次使用完整成绩功能时发送 `水鱼授权`，本人打开设备码链接并确认授权；在启用
`USE_MARKDOWN=true` 或配置了 `OFFICIAL_BOT_IDS` 的官方 Bot 上，回复会提供“打开水鱼授权页”
和“检查授权状态”按钮；其他适配器保留带链接的纯文本降级。完成后发送 `水鱼授权状态`
或重新执行原查询。Bot 不保存用户令牌，重启后会按 qbind 的真实身份重新换取短期令牌。
授权状态检查以及成功的单曲、进度、筛选和 Provider 查询都会尽力刷新共享授权标记；若数据库暂时不可用，
查询本身仍按 OAuth 结果处理，而“水鱼授权状态”会明确提示其他插件可能尚未看到这次授权。

授权成功后会把一条**不含凭据的授权元数据**写入现有
`maimai_sync.user_binds.diving_fish_oauth` 字段，供其他插件复用同一用户授权状态：

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

其他插件应通过 `maimai_sync.get_user_bind_async(真实QQ)` 读取这个字段，确认
`provider/status/scope` 后，使用**同一个 OAuth 应用的 `client_id`** 和服务端密钥换取短期令牌。
`subject_ref` 与 `client_id` 绑定；如果另一个插件使用的是不同 OAuth 应用，就不能直接复用这条
授权记录，必须为该应用重新授权。数据库中不会保存
`client_secret`、`access_token`、`device_code` 或 refresh token；旧的 `fish_token` 仍保留给
成绩上传 Import-Token 使用，不能拿来存 OAuth JSON。这样授权状态可以共享，而每个插件的令牌
仍保持进程内隔离。

服务端筛选示例：

```text
水鱼筛选 level_index=3 ds=13.5.. fc=fc,fcp,ap,app
水鱼筛选 version="宴会場" achievements=100.5.. page=2
水鱼筛选 title="雨露霜雪"
```

筛选只查询发送者本人；未知字段、无效范围和过长参数会在本地拒绝。水鱼响应的
`filters` 回显缺失时会按数据格式异常处理，避免误把未过滤的全量成绩发出。

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

## amia-core Provider

稳定 Provider 名称：

```python
core.MAIMAI_DATA_PROVIDER  # "maimai.data"
```

提供玩家摘要、完整成绩、曲库、谱面信息和 B50 扩展。统一谱面键由基础 `song_id + chart_type + difficulty_index` 组成；消费者不能自行 `% 10000` 或读取 maimaidx 私有数据文件。

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

部署时必须完整复制该目录的顶层 Python 文件，包括
`release010_import.py`。`command/` 下的多个命令通过 `..release010_import` 使用统一的
错误文案和脱敏诊断；只复制 `command/`、`libraries/` 或旧版 `site-packages` 副本会在启动
时出现 `No module named ...release010_import`。更新源码后要同步安装目录并完整重启 Bot。

加载依赖使用 `nonebot.require()`，避免重复导入两份 `amia_core`、qbind 或 maimai_sync。

## 配置

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `PROBER_SOURCE` | 默认数据源：`lxns` 或 `diving-fish` | `lxns` |
| `LXNS_TOKEN` | LXNS 开发者 API Token | 空 |
| `DIVING_FISH_OAUTH_CLIENT_ID` | 水鱼 OAuth 应用 Client ID | 空 |
| `DIVING_FISH_OAUTH_CLIENT_SECRET` | 水鱼 OAuth 应用 Client Secret，只能放在服务端环境变量 | 空 |
| `DIVING_FISH_OAUTH_SCOPE` | OAuth 权限范围 | `prober.records.read` |
| `LXNS_B50_PATH` | 曲绘、字体和渲染资源目录 | `data/lxns_b50` |
| `MAI_SYNC_DATA_PATH` | 同步数据库目录 | `data/mai_sync_data` |
| `USE_MARKDOWN` | 启用 Markdown/Keyboard | `false` |
| `OFFICIAL_BOT_IDS` | 官方 Bot ID 列表 | 部署端配置 |
| `SAVEINMEM` | 启动时预加载图片资源 | `true` |
| `MAIMAIDX_ALIAS_PROXY` | 通过 `www.yuzuchan.cn` 访问柚子别名库（境内网络不稳定时开启） | `false` |

旧 `MAIMAIDX_TOKEN` 只用于提示迁移，不会再被发送到水鱼接口。真实 OAuth Secret 只能通过本地环境或 NoneBot 配置提供，不能写入代码、README、截图、日志、诊断文件或 Git 历史；如果 Secret 曾经在聊天、Issue 或日志中出现，必须在水鱼控制台重新生成。

## 资源

仓库保留既有 `data/lxns_b50` 资源。本轮增量更新 `UI_NUM_Drating_0.png` 至 `UI_NUM_Drating_9.png`，来源为 `Resource CN1.56 UPDATE`，同步时已进行 SHA-256 校验和原子替换。

资源许可证和美术署名不等同于代码许可证；发布、二次分发或商用前必须分别确认资源授权。

## 测试

```powershell
python -m compileall -q src/plugins/Amia-plugin-maimaidx
python -m unittest discover -s src/plugins/Amia-plugin-maimaidx/tests -v
ruff check --select F821,F811,E9 src/plugins/Amia-plugin-maimaidx
git diff --check
```

Release010 回归测试覆盖错误映射和最低加载路径。由上游衍生的 B50、minfo、谱面详情和进度图片统一保留以下署名：

```text
Designed by Yuri-YuzuChaN & BlueDeer233. Adapted by Amia_晓山瑞希. Data from {source}.
```

真实 LXNS/DivingFish API、B50/AP50 图片、特殊谱面 ID、DX Pass 扣费退款、Markdown/Keyboard、诊断文件上传和生产资源完整性未运行时必须保持 `NOT RUN`。

## 发布边界

不得提交真实 Token、用户绑定、生产数据库、原始日志、缓存或未脱敏诊断文件。Release010 自动化通过不能替代真实 QQ/Gensokyo 验证。
