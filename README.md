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
```

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
- 用户可见错误使用简短 `HX-MAI-*` 错误码、原因和建议；
- 不把长 traceback、Token、HTTP 响应正文或数据库错误直接发给用户；
- 失败时生成脱敏诊断文件，并提示移交开发者群 `1053964431`；
- 诊断文件发送失败时仍保留错误码和日志时间，不能伪装为成功。

常见错误码：

| 错误码 | 含义 |
| --- | --- |
| `HX-MAI-001` | 用户尚未绑定 |
| `HX-MAI-002` | 数据源凭据缺失 |
| `HX-MAI-004` | 上游数据源失败 |
| `HX-MAI-005` | 用户或数据不存在 |
| `HX-MAI-009` | 未分类错误 |

## amia-core Provider

稳定 Provider 名称：

```python
core.MAIMAI_DATA_PROVIDER  # "maimai.data"
```

提供玩家摘要、完整成绩、曲库、谱面信息和 B50 扩展。统一谱面键由基础 `song_id + chart_type + difficulty_index` 组成；消费者不能自行 `% 10000` 或读取 maimaidx 私有数据文件。

## 安装

目录插件模式：

```toml
[tool.nonebot]
plugin_dirs = ["plugins/Amia-plugin-maimaidx/plugins"]
```

实际插件目录为：

```text
plugins/lxns_b50/
```

加载依赖使用 `nonebot.require()`，避免重复导入两份 `amia_core`、qbind 或 maimai_sync。

## 配置

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `PROBER_SOURCE` | 默认数据源：`lxns` 或 `diving-fish` | `lxns` |
| `LXNS_TOKEN` | LXNS 开发者 API Token | 空 |
| `MAIMAIDX_TOKEN` | DivingFish Developer Token | 空 |
| `LXNS_B50_PATH` | 曲绘、字体和渲染资源目录 | `data/lxns_b50` |
| `MAI_SYNC_DATA_PATH` | 同步数据库目录 | `data/mai_sync_data` |
| `USE_MARKDOWN` | 启用 Markdown/Keyboard | `false` |
| `OFFICIAL_BOT_IDS` | 官方 Bot ID 列表 | 部署端配置 |
| `SAVEINMEM` | 启动时预加载图片资源 | `true` |

真实 Token 只能通过本地环境或 NoneBot 配置提供，不能写入代码、README、截图、日志、诊断文件或 Git 历史。

## 资源

仓库保留既有 `data/lxns_b50` 资源。本轮增量更新 `UI_NUM_Drating_0.png` 至 `UI_NUM_Drating_9.png`，来源为 `Resource CN1.56 UPDATE`，同步时已进行 SHA-256 校验和原子替换。

资源许可证和美术署名不等同于代码许可证；发布、二次分发或商用前必须分别确认资源授权。

## 测试

```powershell
python -m compileall -q plugins/lxns_b50
python -m unittest discover -s tests -v
git diff --check
```

Release010 回归测试覆盖 HX 错误映射和最低加载路径。真实 LXNS/DivingFish API、B50/AP50 图片、特殊谱面 ID、DX Pass 扣费退款、Markdown/Keyboard、诊断文件上传和生产资源完整性未运行时必须保持 `NOT RUN`。

## 发布边界

不得提交真实 Token、用户绑定、生产数据库、原始日志、缓存或未脱敏诊断文件。Release010 自动化通过不能替代真实 QQ/Gensokyo 验证。
