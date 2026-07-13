# Amia-plugin-maimaidx

`Amia-plugin-maimaidx` 是 Amia / MizukiBot 生态中的舞萌 DX 综合插件，实际 NoneBot 插件标识符为 `lxns_b50`。

插件面向 Gensokyo Release007 + OneBot V11 运行环境，整合落雪（LXNS）与水鱼（Diving-Fish）双数据源，提供玩家查分、曲库检索、图片渲染、进度统计、群聊猜歌以及供其他插件消费的 `MaimaiDataProvider`。

本仓库不是单纯的 B50 插件。`lxns_b50` 是历史插件标识符，为保持现有部署兼容暂不修改。

## 当前状态

当前 `main` 已包含：

- LXNS 与水鱼双数据源查询及回退逻辑；
- B50、AP50、单曲成绩、全服谱面统计和分数线；
- Rating 曲线、最近成绩、成绩热力图；
- 曲库、定数、BPM、曲师、谱师与双数据源别名检索；
- 定数表、完成表、牌子进度、等级进度和上分建议；
- 群内猜歌与猜曲绘；
- `MaimaiDataProvider` 及统一谱面身份归一化；
- DX Pass 选择、玩家信息查询及 HTML/PIL 双渲染实现。

账号绑定统一由 `maimai_sync` / qbind 负责，maimaidx 不再提供第二套 `lxbind` 或 OAuth 绑定入口。

## 功能概览

### 玩家查分与资料

| 指令 | 说明 |
| --- | --- |
| `b50` | 生成玩家 Best 50 成绩图 |
| `ap50` | 生成玩家 AP 50 成绩图 |
| `minfo <曲名或 ID>` | 查询个人单曲成绩与谱面信息 |
| `ginfo <曲名或 ID>` | 查询谱面全服统计信息 |
| `分数线 <曲目> <目标达成率>` | 计算目标达成率对应的容错 |
| `mai状态` / `详细信息` / `mai个人中心` | 查看绑定状态、默认数据源和玩家概况 |
| `切换数据源 <落雪或水鱼>` | 修改当前用户默认查询数据源 |
| `mai曲线` | 生成 LXNS Rating 历史曲线 |
| `mai最近` | 生成最近成绩图 |
| `mai热度` | 生成近 30 天成绩上传热力图 |

### 曲库、别名与查歌

| 指令 | 说明 |
| --- | --- |
| `查歌 <关键词>` | 按曲名模糊搜索 |
| `id <曲目 ID>` | 查询曲目和谱面详情 |
| `定数查歌 <定数或范围>` | 按定数搜索曲目 |
| `bpm查歌 <BPM或范围>` | 按 BPM 搜索曲目 |
| `曲师查歌 <关键词>` | 按曲师搜索曲目 |
| `谱师查歌 <关键词>` | 按谱师搜索曲目 |
| `<别名>是什么歌` / `<别名>是啥歌` | 通过别名反查歌曲 |
| `<曲名或 ID>有什么别名` | 查看歌曲别名 |
| `添加本地别名 <ID> <别名>` | 添加本地补充别名 |
| `更新别名库` | 超级用户私聊手动更新曲库与别名 |

别名来源为：

```text
LXNS 别名 + 水鱼别名 + 本地补充别名
```

插件以并集方式聚合并去重。出现同名或同别名冲突时，应返回候选结果，不能静默选择第一首歌曲。

本项目不采用别名投票、社区审核或别名推送体系。

### 定数表、完成表与进度

| 指令格式 | 说明 |
| --- | --- |
| `<等级>定数表` | 查询指定等级定数表 |
| `<等级><目标>完成表` | 查询指定等级 AP、FC 等完成情况 |
| `<版本><目标>完成表` | 查询指定版本牌子完成情况 |
| `<版本><目标>进度` | 查询版本牌子进度 |
| `<等级><评价>进度` | 查询等级目标进度 |
| `我要上<分数>` | 根据现有成绩生成上分建议 |
| `<达成率>分数列表` | 查询指定达成率相关成绩列表 |

`我要上XX分` 属于当前插件已有的查询与推荐逻辑，不等同于后续独立的 Coach 功能。

### 群聊互动

| 指令 | 权限 | 说明 |
| --- | --- | --- |
| `猜歌` | 群成员 | 开启文字提示猜歌 |
| `猜曲绘` | 群成员 | 开启局部曲绘猜歌 |
| `开启mai猜歌` | 超级用户、群主或管理员 | 开启本群猜歌 |
| `关闭mai猜歌` | 超级用户、群主或管理员 | 关闭本群猜歌 |
| `重置猜歌` | 超级用户、群主或管理员 | 清理本群当前游戏状态 |

群猜歌状态按群隔离，回答监听不得影响无关消息或其他插件 Matcher。

## DX Pass 当前实现

仓库内已有：

- 角色、外框、背景选择；
- LXNS 玩家资料和好友码读取；
- HTML 卡片渲染；
- HTML 失败时回退 PIL；
- 官方机器人按钮选择流程；
- 制作前余额检查和确认；
- Economy 原子扣除 200 PC、幂等键和渲染失败退款；
- `dxpass-confirm` / `dxpass-cancel` 仅允许原发起人操作；
- `-p` / `--preview` 角色预览；
- `--type chara|partner` 立绘类型选择。

DX Pass 固定视觉，不受普通主题系统影响。

制作流程为：查询余额 → 显示确认卡 → 原发起人确认 → 原子扣除 200 PC → 渲染；渲染失败自动退款。

## 主题

普通舞萌渲染支持 `default` 与 `mizuki` 两个主题。主题按 canonical 用户身份保存，运行数据写入 `data/lxns_b50/user_themes.json`。

```text
mai主题
mai主题列表
切换mai主题 <default|mizuki>
```

主题不影响 `dxpass`、`名片` 和 `金卡`。

## amia-core Provider

稳定 Provider 名称：

```python
core.MAIMAI_DATA_PROVIDER
# "maimai.data"
```

当前实现：

| 方法 | 语义 |
| --- | --- |
| `get_player_summary()` | 玩家名称、Rating、段位 Rating 和牌子概览 |
| `get_player_records()` | 完整成绩，使用水鱼 Developer API `/dev/player/records` |
| `get_music_catalog()` | 归一化并去重后的歌曲目录 |
| `get_chart_info()` | 按统一谱面键查询谱面信息 |
| `get_player_best_records()` | maimaidx 自有 B50 扩展，不属于 Core 稳定契约 |

统一谱面键：

```text
normalized base song_id + standard/dx + difficulty_index
```

`song_id` 是规范化后的基础歌曲 ID：同一首歌曲的 Standard 与 DX 谱面共享
同一个 ID，通过 `chart_type` 区分。水鱼 DX 偏移 ID 会在 Provider 内归一；消费者
不得自行执行 `% 10000` 或直接读取 maimaidx 私有数据库。

`amia-core` 定义 `MaimaiDataProvider` 契约；`lxns_b50` 实现并注册
`maimai.data`；`maimai-coach` 和 `maimai-rival` 只能通过 Core 获取该进程内
Python 接口，不能读取 maimaidx 数据库。Provider 不是 HTTP API。

消费示例：

```python
from nonebot import require

core = require("amia_core")
require("lxns_b50")

provider = core.get_maimai_provider(core.MAIMAI_DATA_PROVIDER)
```

实际 Python 模块路径由部署方式决定，不属于稳定公共接口。跨插件代码不得硬编码 `src.plugins.*`。

## 依赖关系

插件通过 `nonebot.require()` 使用以下公共依赖：

- `amia_core`：身份模型和 `MaimaiDataProvider` 注册表；
- `maimai_sync`：数据库初始化、绑定、消息构建和同步数据；
- `qbind`：将 Gensokyo Release007 的虚拟用户 ID 解析为 canonical QQ；
- `nonebot_plugin_apscheduler`：每日同步任务；
- `Amia-plugin-economy`：DX Pass 后续使用的余额、扣费和退款公共接口。

QQ 官方机器人场景中，虚拟 `user_id` 不得直接传入 LXNS、水鱼或 Economy。个人数据、主题和付费功能必须使用 canonical 身份。

## 安装与加载

插件不要求 Bot 项目使用固定的 `src` 目录结构。

### 目录插件

将仓库放入任意插件目录，并在 Bot 项目的 `pyproject.toml` 中配置其父目录：

```toml
[tool.nonebot]
plugin_dirs = ["plugins/Amia-plugin-maimaidx/plugins"]
```

### 安装到 Python 环境

也可以将插件打包并安装到当前虚拟环境，再通过插件标识符加载：

```toml
[tool.nonebot]
plugins = ["lxns_b50"]
```

无论代码位于普通插件目录还是 `site-packages`，运行数据都不应写入代码目录。

## 数据目录

默认数据目录相对于 Bot 工作目录解析：

```text
<bot-root>/data/lxns_b50
<bot-root>/data/mai_sync_data
```

推荐布局：

```text
<bot-root>/
├── .env
├── data/
│   ├── lxns_b50/
│   └── mai_sync_data/
├── plugins/                  # 可选：目录插件模式
└── .venv/                    # 可选：安装模式
    └── Lib/site-packages/
```

代码目录与运行数据目录必须分离。升级、卸载或重装插件不应删除曲库、曲绘、别名和用户缓存。

## 配置

敏感凭据只能通过环境变量或 NoneBot 配置提供，不能写入代码或提交仓库。

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `PROBER_SOURCE` | 默认数据源：`lxns` 或 `diving-fish` | `lxns` |
| `LXNS_TOKEN` | LXNS 开发者 API 密钥 | 空 |
| `MAIMAIDX_TOKEN` | 水鱼 Developer Token | 空 |
| `LXNS_B50_PATH` | 图片、曲绘、定数表等资源目录 | `data/lxns_b50` |
| `MAI_SYNC_DATA_PATH` | `musicDB.json` 等同步目录 | `data/mai_sync_data` |
| `USE_MARKDOWN` | 启用 Gensokyo Markdown 与按钮 | `false` |
| `OFFICIAL_BOT_IDS` | 官方机器人 Bot ID 列表 | 由部署端配置 |
| `SAVEINMEM` | 启动时预加载部分图片资源 | `true` |

示例：

```dotenv
PROBER_SOURCE=lxns
LXNS_TOKEN=
MAIMAIDX_TOKEN=
LXNS_B50_PATH=data/lxns_b50
MAI_SYNC_DATA_PATH=data/mai_sync_data
USE_MARKDOWN=false
OFFICIAL_BOT_IDS=[]
SAVEINMEM=true
```

不要在日志、截图或 Issue 中输出真实 Token、数据库密码或完整 `Loaded Config`。

## 启动与同步

启动阶段会：

1. 初始化 `maimai_sync` 数据库和绑定服务；
2. 加载 LXNS 与水鱼凭据；
3. 聚合双数据源曲库和别名；
4. 加载 `musicDB.json`；
5. 检查并清理损坏曲绘；
6. 补齐缺失曲绘；
7. 初始化群猜歌状态和可选图片预加载；
8. 注册 `MaimaiDataProvider`；
9. 每日 04:00 执行数据更新。

## Gensokyo Release007 兼容要求

- 统一使用现有 Markdown、按钮和普通文本降级封装；
- 按钮发送失败时必须回退为可复制的普通命令；
- 官方机器人虚拟身份先经 qbind/Core 解析；
- 未绑定提示同一事件最多发送一次；
- `qbind`、`maimai_sync`、`lxns_b50` 在启动日志中均应只加载一次；
- 付费按钮需要确认、幂等和操作者身份校验；
- 群猜歌监听不得抢占其他插件的正常命令。

## 测试

在仓库根目录执行：

```bash
python -m compileall plugins/lxns_b50
python -m unittest discover -s tests -v
```

测试路径与实际部署目录无关，不要求 Bot 项目存在 `src`。

上线前至少验证：

- 插件和依赖各只加载一次；
- B50、AP50、minfo、ginfo、分数线；
- mai状态、数据源切换、曲线、最近成绩和热力图；
- 查歌、ID、定数、BPM、曲师、谱师和别名；
- 定数表、完成表、牌子和进度；
- 猜歌、猜曲绘和群级管理；
- Core Provider 完整成绩数量与 canonical 谱面键；
- Gensokyo Release007 虚拟身份；
- DX Pass 默认加载、200 PC 扣费、失败退款和重复点击幂等。

## 当前已知问题

- `mai_pass.py` 未进入默认导入链，DX Pass 命令当前可能无法注册；
- Economy 公共计费接口已经存在，但 maimaidx 尚未调用；
- 主题系统尚未实现；
- `mai_alias.py` 的数字查询回退分支存在未定义变量风险，需要补充测试；
- 部分帮助文本仍包含尚未实现或未加载的猜歌子模式，应与实际 Matcher 同步；
- 启动日志和 PicMenu 元数据仍需继续清理旧的工程化表述。

## 授权说明

本仓库目前未声明开源许可证。仓库公开可见不代表自动授权复用、再分发、商用或生产部署。
