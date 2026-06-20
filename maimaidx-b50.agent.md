---
description: "Use when: working on MizukiBot maimai DX B50 project, maimai score checking, NoneBot2 plugin development, lxns API integration, diving-fish API integration, maimai DX best 50 rendering, PIL image generation for maimai scores."
tools: [read, edit, search, execute, web]
name: "MaimaiDX B50 Agent"
---

# MaimaiDX B50 Agent — MizukiBot 舞萌查分项目

你是一个专注于 **MizukiBot 舞萌 DX 查分系统** 的专家。这个项目基于 NoneBot2 框架构建，是一套完整的舞萌 DX 查分服务 Bot 插件。

## 项目架构

### 目录结构

```
lxns_b50/
├── __init__.py          # 插件入口 & 生命周期钩子
├── config.py            # 配置项 & 游戏常量字典
├── mai_sync_data/       # 自动生成的缓存数据（musicDB.json 等）
├── command/
│   ├── __init__.py      # 导出所有命令模块
│   ├── mai_alias.py     # 别名查询/更新命令
│   ├── mai_base.py      # 基础命令（帮助/状态/数据源切换/mai曲线）
│   ├── mai_guess.py     # 猜歌/猜曲绘游戏命令
│   ├── mai_score.py     # 查分命令（b50/ap50/minfo/ginfo/分数线）
│   ├── mai_search.py    # 搜索命令（查歌/定数查歌/bpm查歌/曲师查歌/谱师查歌）
│   └── mai_table.py     # 定数表/完成表/进度/上分推荐命令
├── libraries/
│   ├── maimaidx_api_data.py     # API 路由 & 鉴权（MaiApi 类）
│   ├── maimaidx_best_50.py      # B50 图片渲染核心（ScoreBaseImage/DrawBest）
│   ├── maimaidx_error.py        # 自定义异常类
│   ├── maimaidx_model.py        # Pydantic 数据模型
│   ├── maimaidx_music.py        # 曲库管理（MaiMusic 类 / 双源同步 / 曲绘下载）
│   ├── maimaidx_music_info.py   # 单曲游玩详情/定数表/完成表绘制
│   ├── maimaidx_player_score.py # 玩家成绩数据处理（上分/牌子进度/等级进度）
│   ├── maimaidx_update_plate.py # 定数表/完成表图片生成工具
│   ├── lib_music_db.py          # musicDB 管理器（落雪 song_id 权威列表/曲绘下载）
│   ├── tool.py                  # 工具函数（Playwright截图/文件读写）
│   └── image.py                 # 图片处理工具（DrawText/渐变/圆角/Base64/曲绘查找/图片验证）
```

### 核心依赖
- **NoneBot2** (nonebot-plugin-apscheduler)
- **PIL/Pillow** — 图片渲染
- **httpx / curl_cffi** — HTTP 请求
- **Pydantic** — 数据模型
- **pyecharts** — 图表生成
- **Playwright** — HTML 转图片

## 🆔 Song ID 双体系（核心难点）

**落雪 (LXNS)** 和 **水鱼 (Diving-Fish)** 使用完全不同的 song_id 体系，这是本项目的核心难点。

| 项目 | 落雪 LXNS | 水鱼 Diving-Fish |
|------|-----------|-----------------|
| 原生 ID | 小整数（如 `8`, `38`, `799`） | SD 谱面同落雪，DX 谱面 = 落雪ID + 10000 |
| 示例 | `8` → True Love Song | `10008` → True Love Song (DX) |
| 宴会场 | ID > 100000（如 `100044`） | 同落雪 |
| 曲绘 URL | `https://assets2.lxns.net/maimai/jacket/{id}.png` | `https://www.diving-fish.com/covers/{id:05d}.png`（补零到5位） |
| 曲绘文件 | 以 **落雪原生 ID** 命名 (`8.png`) | 回退查找 `{id-10000}.png` |

**查找策略 (`music_picture()`)**:
1. 直接查找 `{music_id}.png`（自动检测损坏并删除）
2. 若 ID > 100000（宴会场），尝试 `{music_id - 100000}.png`
3. 若 ID 是落雪原生小数字，尝试 `{id+10000}.png`（水鱼DX）
4. 若 ID 是水鱼 DX 格式，尝试 `{id-10000}.png`（落雪SD）
5. 回退到 `0.png` → `11000.png` 占位图

### musicDB.json — 落雪 song_id 权威列表

`musicDB.json` 是落雪 song_id 的权威缓存列表，**存放在插件目录下**：
```
{插件目录}/mai_sync_data/musicDB.json
```
例如 `lxns_b50/mai_sync_data/musicDB.json`

#### 自动生成机制
- **生成时机**：每次执行双源同步（`MaiMusic.get_music()`）且成功拉取落雪数据后，自动调用 `generate_music_db()` 生成
- **生成函数**：`lib_music_db.py::generate_music_db(lxns_music_list, save_path)`
- **触发时机**：插件启动时 + 每日凌晨 04:00 定时任务
- **结构**：
```json
{"8": {"name": "True Love Song", "version": 10000}, ...}
```
- 键（key）= 落雪原生 song_id（字符串）
- 值（value）= `{name: 曲名, version: 版本号}`
- 包含 SD、DX 分离后的 ID（DX 谱面键为 `{原ID+10000}`）

#### 配置路径
在 `config.py` 中定义（目录自动创建）：
```python
music_db_path: Path = Root / 'mai_sync_data' / 'musicDB.json'
music_db_path.parent.mkdir(parents=True, exist_ok=True)  # 自动创建 mai_sync_data/
# Root = Path(__file__).parent.absolute()  # 即 lxns_b50/ 目录
```

### 曲绘全量下载流程

1. **首次启动**：双源同步 → 生成 `musicDB.json` → 读取所有 ID → 调用 `download_all_covers()` → 下载全部曲绘到 `{coverdir}/`
2. **后续启动**：加载 `musicDB.json` 缓存 → **清理损坏曲绘**（< 5KB 或魔数不正确） → 检查 `cover/` 目录中缺失的曲绘 → 增量补充
3. **ID 映射**：落雪曲绘 URL 只认**原生 song_id**，下载前自动转换：
   - `10001~99999`（DX 谱面）→ `id % 10000`
   - `≥ 100000`（宴会场）→ `id % 100000`
   - `≤ 10000`（原生）→ 直接使用
4. **双源下载**：优先落雪（`curl_cffi` 模拟 Chrome 指纹绕过 Cloudflare），失败时自动切换水鱼（`httpx`）
5. **内容验证**：下载时使用 `image.is_valid_image()` 检查 PNG/JPEG/WebP 魔数，防止 Cloudflare 反爬页面被存为 `.png`
6. **损坏自愈**：`music_picture()` 每次访问都会用魔数校验文件，损坏文件自动删除并降级到 `0.png` 占位图；同时记录到 `_corrupted_cover_ids` 全局集合，避免反复重试
7. **降级策略**：若 `musicDB.json` 不存在（如落雪 API 失败），则回退使用 `total_list` 遍历下载

## 双数据源架构

### 1. 落雪 (LXNS) — 主数据源

| 属性 | 值 |
|------|-----|
| 基础 URL | `https://maimai.lxns.net/api/v0/` |
| 鉴权方式 | Header: `Authorization: {开发者密钥}` |
| 开发者密钥 | `gAtzZcA6iXdihYhBtbw8VeXUtnFsMUI-Iwdyd-_ZvKM=` |
| 游戏资源 URL | `https://assets2.lxns.net/maimai/` |

#### 核心 API 端点
| 端点 | 方法 | 说明 |
|------|------|------|
| `/maimai/song/list` | GET | 获取曲目列表（含别名） |
| `/maimai/song/{song_id}` | GET | 获取单曲信息 |
| `/maimai/alias/list` | GET | 获取曲目标签列表 |
| `/maimai/player/{friend_code}` | GET | 获取玩家信息 |
| `/maimai/player/qq/{qq}` | GET | 通过 QQ 获取玩家信息 |
| `/maimai/player/{fc}/bests` | GET | 获取 Best 50 |
| `/maimai/player/{fc}/bests/ap` | GET | 获取 AP 50 |
| `/maimai/player/{fc}/recents` | GET | 获取 Recent 50 |
| `/maimai/player/{fc}/scores` | GET | 获取所有成绩（简化） |
| `/maimai/player/{fc}/trend` | GET | 获取 Rating 趋势 |
| `/maimai/player/{fc}/heatmap` | GET | 获取上传热力图 |
| `/maimai/{collection_type}/list` | GET | 获取收藏品列表 |
| `/maimai/{collection_type}/{id}` | GET | 获取收藏品信息 |
| `POST /maimai/player/{fc}/scores` | POST | 上传玩家成绩 |
| `POST /maimai/player` | POST | 创建/修改玩家信息 |

#### 响应结构
```json
{
  "success": true,
  "code": 200,
  "data": { ... }
}
```

### 2. 水鱼 (Diving-Fish) — 辅助数据源

| 属性 | 值 |
|------|-----|
| 基础 URL | `https://www.diving-fish.com/api/maimaidxprober/` |
| 鉴权方式 | Header: `Developer-Token: {token}` 或 `Import-Token: {token}` |

#### 核心 API 端点
| 端点 | 方法 | 鉴权 | 说明 |
|------|------|------|------|
| `/music_data` | GET | 无需 | 获取全部歌曲数据 |
| `/query/player` | POST | 无需 | 获取用户简略成绩（B50） |
| `/query/plate` | POST | 无需 | 按版本获取用户成绩 |
| `/chart_stats` | GET | 无需 | 获取谱面拟合难度等数据 |
| `/dev/player/records` | GET | Developer-Token | 获取用户完整成绩 |
| `/dev/player/record` | POST | Developer-Token | 获取用户单曲成绩 |
| `/rating_ranking` | GET | 无需 | 获取公开用户-rating排名 |
| `/player/profile` | GET/POST | 登录验证 | 获取/更新用户资料 |
| `/side_api/alias` | GET | 无需 | 获取别名数据 |

#### 请求示例 (query/player)
```json
POST /api/maimaidxprober/query/player
Body: { "qq": "123456", "b50": "1" }
```

## 配置项 (config.py)

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `prober_source` | 默认数据源 (lxns/diving-fish) | `lxns` |
| `lxnstoken` | 落雪开发者密钥 | `gAtzZcA6iXdihYhBtbw8VeXUtnFsMUI-Iwdyd-_ZvKM=` |
| `lxnspath` | 落雪资源路径 | `static` |
| `maimaidxtoken` | 水鱼开发者密钥 | `""` |
| `maimaidxpath` | 水鱼资源路径 | `static` |
| `saveinmem` | 是否缓存图片到内存 | `True` |
| `use_markdown` | 启用 Markdown+按钮模式（官方Bot） | `False` |
| `official_bot_ids` | 官方机器人ID列表 | `["3889004352", "3889047402"]` |

### 导出的路径常量

| 常量名 | 路径 | 说明 |
|--------|------|------|
| `Root` | `lxns_b50/` | 插件根目录（`Path(__file__).parent.absolute()`） |
| `static` | 由 `lxnspath`/`maimaidxpath` 决定 | 静态资源根目录（曲绘/字体/牌子等） |
| `music_db_path` | `{Root}/mai_sync_data/musicDB.json` | 落雪 song_id 权威列表，自动生成 |

## 可用指令

| 指令 | 说明 | 文件 |
|------|------|------|
| `b50` | 生成 Best 50 成绩图 | `mai_score.py` |
| `ap50` | 生成 AP 50 成绩图 | `mai_score.py` |
| `minfo <ID>` | 查询单曲游玩详情 | `mai_score.py` |
| `ginfo <难度><ID>` | 全服统计图 | `mai_score.py` |
| `分数线 <难度><ID> <分数>` | 查询分数线 | `mai_score.py` |
| `mai状态` | 诊断双端绑定状态 | `mai_base.py` |
| `切换数据源 <水鱼/落雪>` | 切换默认输出端 | `mai_base.py` |
| `mai帮助` | 查看帮助菜单 | `mai_base.py` |
| `mai曲线` | 绘制 Rating 历史趋势 | `mai_base.py` |
| `mai最近` | 【落雪特供】查看最近 50 条游玩记录 | `mai_base.py` |
| `mai热度` | 【落雪特供】成绩上传热力图 (GitHub日历图) | `mai_base.py` |
| `mai名片` / `mai信息` | 生成个人名片大图 | `mai_score.py` |
| `mai排行` / `战力排行` | 全服 Rating 排行榜 | `mai_score.py` |
| `mai分析` / `战力分析` | 多维战力构成深度分析 | `mai_score.py` |
| `mai速报` / `mai打卡` | 最近成绩打卡速报卡片 | `mai_score.py` |
| `查歌 <关键词>` | 模糊检索歌曲 | `mai_search.py` |
| `id <ID>` | 查看谱面底标 | `mai_search.py` |
| `定数查歌 <定数>` | 按定数查歌 | `mai_search.py` |
| `bpm查歌 <bpm>` | 按BPM查歌 | `mai_search.py` |
| `曲师查歌 <曲师>` | 按曲师查歌 | `mai_search.py` |
| `谱师查歌 <谱师>` | 按谱师查歌 | `mai_search.py` |
| `xxx是什么歌` | 按别名查歌 | `mai_search.py` |
| `猜歌` | 开始猜歌游戏 | `mai_guess.py` |
| `猜曲绘` | 开始猜曲绘游戏 | `mai_guess.py` |
| `听歌猜歌` / `听歌猜曲` | 开始语音听歌猜曲游戏 | `mai_guess.py` |
| `别名猜歌` | 开始别名猜歌梗小游戏 | `mai_guess.py` |
| `更新别名库` | 更新别名库 (超管) | `mai_alias.py` |
| `添加本地别名` | 添加本地别名 | `mai_alias.py` |
| `更新定数表` | 更新定数表 (超管) | `mai_table.py` |
| `更新完成表` | 更新完成表 (超管) | `mai_table.py` |
| `<定数>定数表` | 查看定数表 | `mai_table.py` |
| `<版本><目标>完成表` | 查看牌子完成情况 | `mai_table.py` |
| `我要上<分>` | 上分推荐 | `mai_table.py` |
| `<版本><目标>进度` | 牌子进度查询 | `mai_table.py` |
| `<等级><评价>进度` | 等级进度查询 | `mai_table.py` |
| `<定数>分数列表` | 分数列表查询 | `mai_table.py` |
| `mai对决` / `战力PK` | 对比两玩家B50/AP50并生成PK对决海报 | `mai_duel.py` |
| `今日课题` / `mai挑战` | 查看今日群随机挑战歌曲及成绩排行榜大图 | `mai_challenge.py` |
| `提交课题` / `同步课题` | 从落雪最近游玩记录拉取验证成绩并提交课题打榜 | `mai_challenge.py` |
| `mai底力` / `底力分析` | 统计分析高难成绩 (Lv>=13) 获得积分与段位评定，生成大图 | `mai_score.py` |


## 核心数据模型

### ChartInfo (谱面成绩)
- `song_id`, `title`, `type` (SD/DX), `level_index` (0-4)
- `achievements` (达成率), `dxScore`, `ra` (Rating)
- `rate` (评级: d/c/b/bb/bbb/a/aa/aaa/s/sp/ss/ssp/sss/sssp)
- `fc` (FC类型: fc/fcp/ap/app), `fs` (FS类型: fs/fsp/fsd/fsdp)
- `ds` (定数)

### UserInfo (用户信息)
- `nickname`, `rating`, `additional_rating`, `plate`, `username`
- `charts.sd` (旧版本 Best 35), `charts.dx` (新版本 Best 15)

### Music (曲目)
- `id`, `title`, `type`, `ds[]`, `level[]`, `charts[]`, `basic_info`

## Rating 计算公式

```
baseRa = 达成率对应的基础系数 (7.0 ~ 22.4)
ra = floor(ds * min(100.5, achievements) / 100 * baseRa)
```

| 达成率范围 | baseRa | 评级 |
|-----------|--------|------|
| 50~60% | 7.0 | D |
| 60~70% | 8.0 | C |
| 70~75% | 9.6 | B |
| 75~80% | 11.2 | BB |
| 80~90% | 12.0 | BBB |
| 90~94% | 13.6 | A |
| 94~97% | 15.2 | AA |
| 97~98% | 16.8 | AAA |
| 98~99% | 20.0 | S |
| 99~99.5% | 20.3 | S+ |
| 99.5~100% | 20.8 | SS |
| 100~100.5% | 21.1 | SS+ |
| 100.5%+ | 22.4 | SSS+ |

## 关键业务流程

### B50 生成流程
1. `generate()` → `maiApi.query_user_b50()` 获取用户数据
2. 为每首曲目匹配 `mai.total_list` 中的定数
3. `DrawBest` 类加载背景资源，渲染用户信息、段位、Rating
4. `whiledraw()` 循环绘制 SD 和 DX 的谱面卡片

### 双源数据同步流程 (启动/每日定时)
1. `mai.get_music()` 同时请求落雪和水鱼的数据
2. 合并两个数据源的曲目、别名
3. 保存到本地 JSON 缓存 (`music_data.json`)
4. 若落雪数据拉取成功，调用 `generate_music_db()` 生成 `mai_sync_data/musicDB.json`
5. 异步下载缺失的曲绘资源（优先基于 musicDB.json 全量下载，降级使用 total_list）

### 官方 Bot 按钮/Markdown 消息机制

**判断逻辑** (`maimaidx_api_data.py`):
- `is_official_bot(bot_self_id)` → 检查 bot ID 是否在 `config.official_bot_ids` 列表中，或 `use_markdown=True`
- 默认官方 bot IDs: `["3889004352", "3889047402"]`

**按钮构建** (`maimaidx_api_data.py`):
- `build_markdown_keyboard(rows_config)` → 构建 Gensokyo 兼容键盘按钮
- 在 `mai_base.py` 中通过 `extra={"markdown": True, "keyboard": ...}` 发送

**使用前提**：
- Gensokyo 框架必须启用 `native_md: true`
- 官方 Bot 需要在 QQ 开放平台配置 MD 模板

## 重要常量

- `diffs = ['Basic', 'Advanced', 'Expert', 'Master', 'Re:Master']`
- `levelList = ['1','2',...,'14+','15']`
- `achievementList = [50.0, 60.0, 70.0, 75.0, 80.0, 90.0, 94.0, 97.0, 98.0, 99.0, 99.5, 100.0, 100.5]`
- 版本对照表: `plate_to_dx_version` 包含从"初"到"彩"的所有版本

## 常见错误码 (落雪 API)
| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 401 | 鉴权失败 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 429 | 请求过于频繁 |
| 500 | 服务器内部错误 |

---

## ⚠️ 已知问题 (Known Issues)

### 3.1 多实例环境下的功能表现不一致

**现象**: 在同一个群聊中触发 `b50` 指令时，部分机器人实例正常渲染，另一些抛出兜底提示 `⚠️ 查询遭遇技术阻塞，请确认输入的账户正确或稍后再试。`

**控制台表现**: 报错实例无红色 ERROR / Traceback，仅显示 `[SUCCESS]`。原因是异常被 `command/mai_score.py` 中的宽泛 `except Exception:` 捕获并吞咽，没有日志输出。

**已修复**: 
- ✅ `mai_score.py` — 所有 `except Exception:` 块已注入 `log.error(traceback.format_exc())`
- ✅ `maimaidx_best_50.py` — 所有 `except Exception: pass` 已改为 `log.warning()`

### 3.2 MaiApi 缺失关键方法（高概率根因）

`libraries/maimaidx_api_data.py` 中的 `MaiApi` 类原版仅定义了 3 个方法，但全项目在 10+ 处调用以下不存在的方法，导致 `AttributeError`：

| 缺失方法 | 调用方 | 说明 |
|---------|--------|------|
| `query_user_b50()` | `best_50.py` / `music_info.py` / `player_score.py` | B50 数据获取 |
| `query_user_plate()` | `music_info.py` / `player_score.py` | 按版本查成绩 |
| `query_user_post_dev()` | `music_info.py` | 水鱼开发版单曲查询 |
| `query_user_get_dev()` | `player_score.py` | 水鱼开发版完整成绩 |
| `qqlogo()` | `best_50.py` | QQ 头像获取 |
| `get_songs()` | `mai_search.py` | 别名搜索 |
| `rating_ranking()` | `player_score.py` | Rating 排名 |
| `self.token` | `player_score.py` | 水鱼 Developer-Token |

**已修复**: ✅ 所有缺失方法已完整实现，包含落雪直连 + 水鱼回退的双策略 B50 查询。

### 3.3 潜在原因 （多实例排查清单）

- **环境不同步**: 报错实例的 `maimaidx_api_data.py` 等核心文件未拉取最新版本
- **环境变量缺失**: `.env` 中缺少 `LXNSTOKEN`，导致落雪鉴权失败返回空数据
- **静态资产缺失**: `static/mai/pic/` 下缺少字体文件(`ResourceHanRoundedCN-Bold.ttf`)、UI 图层或曲绘缓存，在 PIL 渲染阶段崩溃
- **curl_cffi 兼容性**: `DrawBest.draw()` 使用 `curl_cffi` 下载牌子和头像，某些 Python 环境可能缺少编译依赖

### 3.4 排查 Action Items

1. 在报错实例触发 `b50` 后，检查控制台是否有 `[b50] 查询遭遇未捕获异常:` 开头的日志行
2. 检查 `.env` 中的 `LXNSTOKEN=gAtzZcA6iXdihYhBtbw8VeXUtnFsMUI-Iwdyd-_ZvKM=` 是否存在
3. 检查 `static/mai/pic/` 目录下是否存在 `b50_bg.png`、`ResourceHanRoundedCN-Bold.ttf` 等关键资源
4. 运行 `pip list | findstr curl_cffi` 确认 curl_cffi 已安装

---

## ✅ 已修复问题清单 (2026-05-23)

| # | 严重度 | 文件 | 问题 | 修复方式 |
|---|--------|------|------|----------|
| 1 | 🔴 | `__init__.py` | `ScoreBaseImage._load_image()` 调用不存在的方法（`load_image` 无下划线），导致 `saveinmem` 预加载永远不生效 | 修正为 `load_image()`，同时将 `load_image` 改为 `@classmethod`，支持类级别预加载 |
| 2 | 🔴 | `maimaidx_best_50.py` | `load_image()` 是实例方法，无法被类直接调用；且每次 `__init__` 都重复加载图片 | 改为 `@classmethod`，增加 `_class_loaded` 标志，仅首次加载一次 |
| 3 | 🔴 | `maimaidx_update_plate.py` | `sbi = ScoreBaseImage if saveinmem else ScoreBaseImage()` — 当 `saveinmem=True` 时 `sbi` 是类本身，但类属性 `aurora_bg` 等为 `None`，导致 `alpha_composite(None)` 崩溃 | 简化为始终 `sbi = ScoreBaseImage()`，借助 `@classmethod` 的 `_class_loaded` 确保仅加载一次 |
| 4 | 🟡 | `maimaidx_music_info.py` | `draw_music_info()` 中 `except Exception: calc = False` 静默吞异常 | 注入 `log.warning(traceback.format_exc())` |
| 5 | 🟡 | `maimaidx_player_score.py` | `ChartInfo = Any` 用 `Any` 覆盖真实模型，彻底丧失类型安全 | 改为直接从 `maimaidx_model` 导入 `ChartInfo`，删除 `Any` hack |
| 6 | 🟢 | `maimaidx_player_score.py` | `draw_rise()` 文档注释中 `sd` 参数名被写了两次（第二个应为 `dx`） | 修正为 `dx` |
| 7 | 🟢 | `mai_score.py` | b50/ap50/ginfo 的 `except Exception` 无日志输出 | 注入 `log.error(traceback.format_exc())` |
| 8 | 🟢 | `maimaidx_best_50.py` | `DrawBest.draw()` 中 6 处 `except Exception: pass` 静默吞噬错误 | 改为 `log.warning("描述信息: {e}")` |

---

## 🚀 新增功能与技术实现细节 (2026-06-10)

### 1. 猜歌与猜曲绘游戏引擎重构
- **开关状态读写 (`group_guess_switch.json`)**：
  - 小游戏开关使用群组级别的黑白名单管理，数据持久化保存在插件根目录下的 `group_guess_switch.json`。
  - 数据格式为：`{"enable": [group_id1, group_id2, ...]}`，群聊中可发送 `猜歌启用` / `猜歌禁用` 动态调整状态。
- **梗玩法「别名猜歌」**：
  - 从 `total_alias_list` 自动提取拥有 2 个或以上社区别名的歌曲，作为谜题，要求玩家在限时内猜出官方中文名，增强群内趣味互动。
- **语音玩法「听歌猜歌」**：
  - 随机从有效曲库中选择歌曲，异步请求落雪 CDN 音乐预览文件 `https://assets2.lxns.net/maimai/music/{song_id}.mp3`。
  - 获取 MP3 二进制流后，使用自定义的纯 Python 切片器提取其中 10~15 秒的声音段，以 `MessageSegment.record` 形式向群内下发。

### 2. 纯 Python MP3 帧切片算法 (`slice_mp3`)
为了保证在老配置或无 `ffmpeg`/`pydub` 二进制的环境中依然可以秒级裁剪音频，设计并实现了纯 Python 层的 MP3 Frame 级别字节剪切：
- **ID3v2 头部跳过**：读取前 3 字节，若为 `ID3`，通过解析 6-9 字节的 Synchsafe 整数获取 Tag 长度，指针直接向后偏移跳过元数据。
- **帧同步与包头解析**：
  - 遍历字节流，寻找以 `0xFF` 且下一字节高 3 位为 1 的 11 位同步字（Sync Word: `0xFFE0` 掩码匹配）。
  - 根据协议规范读取 MPEG 版本、Layer（必须为 Layer III）、比特率索引、采样率索引和 Padding 标志。
- **帧大小动态计算**：
  - 对于 MPEG-1 Layer III：`FrameSize = 144 * Bitrate // SamplingRate + Padding`
  - 对于 MPEG-2/2.5 Layer III：`FrameSize = 72 * Bitrate // SamplingRate + Padding`
- **高精切片**：
  - 根据采样率（如 44100Hz，每帧包含 1152 个采样点，单帧时长约为 26ms），将目标起始秒数和持续秒数换算为帧数区间。
  - 精确截取对应帧范围的原始字节，并拼接上合法的 MP3 帧头后直接返回，免去任何音频解码与二次重采样。

### 3. 曲绘墙网格进度表 (`draw_plate_grid_image`)
- **指令格式**：`<版本><目标>进度` (例如：`霸者将进度` / `舞舞极进度`)
- **视觉排版**：
  - 宽度固定，每行排布 10 列曲绘卡片（单格 90x90 像素，间隔 15 像素）。
  - 背景采用星空渐变质感，配以 `pattern.png` 蜂窝网格装饰图层。
- **状态渲染与排序**：
  - 排序算法：**未完成曲目排在前列**（按“最高未完成难度层级”降级排序，若最高难度相同则按定数从高到低排序，已完成曲目统一沉底）。
  - 已达标（完成）曲目：曲绘使用 `RGBA` 的 `a.point` 运算进行 40% 半透明淡化，并右上角戳印绿色的 `complete_bg_2.png` 对勾标志。
  - 未达标（未完成）曲目：曲绘完整高亮，外框描以未完成等级的官方难度色（Basic 绿 / Advanced 黄 / Expert 红 / Master 紫 / Re:Master 粉白），且左下角浮现歌曲的唯一数字 ID。

### 4. 其它高级查分图表
- **`mai热度` (GitHub 日历日历图)**：
  - 重构后不再返回 ASCII 纯文本。它根据用户近一年在落雪上传成绩的次数，使用 Pillow 绘制绿色的日历贡献格子图，支持颜色明暗分级与多指标状态统计。
- **`mai名片`**：
  - 自动联合落雪（头像、全服段位、游玩场次、好友码）与水鱼查分器，生成一体化街机风格玩家名片。
- **`mai排行`**：
  - 实时抓取 `/rating_ranking` 排行榜，通过 Pillow 绘制带排位奖章的全服 TOP 20 战力图。
- **`mai分析`**：
  - 图表化展示玩家的 Best 50 构成，包含评级占比直方图、分类贡献饼图与定数游玩散点分布。
- **`mai速报`**：
  - 在打出 FC/AP/大涨分后，生成推特样式的打卡速报小卡片，便于社交分享。

### 5. 战力对决系统 (`mai对决` / `战力PK`) (2026-06-11)
- **格斗海报排版**：
  - 使用 PIL 动态生成 1200 x 800 的 PK 对决图片。背景采用冷暖双色（暗蓝/暗红）流光渐变加蜂窝网格蒙版，中间印以浮雕式“VS”勋章。
  - 左右两侧展示对决双方的圆形头像、全服段位标、大字 Rating 战力。
- **战力维度对比**：
  - **总Rating / 最高单曲Ra**：双向对比条展示，直观凸显实力差距。
  - **新旧版本贡献占比**：比对各自的 B35 (SD) 与 B15 (DX) 战力倾向。
  - **共同游玩曲交手 (Shared Tracks)**：精确检索双方 B50 数据中相同的谱面，逐一比对达成率成绩，展示 `Win - Draw - Loss` 战绩。

### 6. 今日群课题挑战榜 (`今日课题` / `提交课题`) (2026-06-11)
- **每日课题生成**：
  - 数据持久化保存在 `data/mai_sync_data/group_challenge.json`。
  - 每天首次触发时，系统自动在有效歌曲库中随机选取一首歌曲，并随机指派 Expert/Master/Re:Master 挑战难度。
- **成绩提交与榜单**：
  - **成绩同步**：发送 `提交课题` 后，系统实时调用落雪最近成绩 API (`/recents`)，提取近 50 次游玩中与今日课题歌名及难度一致的最高达成率进行校验，判定无误后更新群内今日课题排行榜。
  - **视觉排行榜**：发送 `今日课题` 返回群内今日排名大图，展示精美榜单列表（包含段位头像、昵称、达成率和时间）。


### 7. DXPass 金卡特权印章与超分清晰度重建 (2026-06-20)
- **金卡印章渲染**：
  - 新增 `_draw_stamp_layer` 方法，利用 `ImageDraw` 矢量图形绘制高精度的圆角双层矩形及内部图形（`LV.UP` 金色齿轮笑脸、`MASTER` 紫色锁、红色五角星文件夹三种印章）。
  - 支持印章以不同微斜角（`-8`度、`5`度、`-12`度）进行合成排版，完美复刻官方金卡视觉。
- **超分辨率锐化重建**：
  - 重构 `_load_layer` 逻辑，若检测到加载素材的分辨率较低（如 `256x352` 的标清 `_S` 素材），会自动使用 `LANCZOS` 算法进行放大。
  - 随后采用 Pillow 的 `ImageFilter.UnsharpMask(radius=1.5, percent=130, threshold=2)` 滤镜重构边缘，大幅提升文字与立绘的清晰度，达到高清晰度重建效果。
- **全角字符智能转换与排版防溢出**：
  - 玩家昵称绘制前自动进行全角转半角处理（如 `ＨＸ☆Ｗｒｄｚ` -> `HX☆Wrdz`），解决由于宽体全角字符导致的间距散碎、右侧溢出越过二维码区域的问题。
  - 规范并统一使用官方包附带的 `ResourceHanRoundedCN-Bold.ttf` 字体进行昵称自适应排版。
- **晓山瑞希（mzk）与音游角色别名映射**：
  - 新增 `CHARA_ALIAS_MAP` 别名映射总线，支持用户在指令中使用 `"mzk"`, `"mizuki"`, `"晓山瑞希"`, `"奏"`, `"kanade"` 等多套别名，自动匹配对应的角色立绘（例如晓山瑞希映射到 `050803`，宵崎奏映射到 `050804`），摆脱了原来依靠 profile icon 报错或填数字 ID 的局限。
- **名片底部排版与好友码防溢出居中**：
  - 实现了好友码（`fc_plate`）与底部 Aime 虚拟卡号（`aime_footer`）的动态字号缩小自适应与水平、垂直精密居中算法。
  - 精确计算 CardFrame 底部灰色胶囊条的水平 X 轴真实跨度为 `[145, 622]`，以此计算居中偏移，彻底解决大字号或长字符导致左侧首位字符（如 `7`）被截断、溢出白色背景的 Bug。
- **环境兼容性与依赖修复**：
  - 修复了 `command/mai_pass.py` 中错误的 `is_official_bot` 导入模块路径（由 `..config` 修正为 `..libraries.maimaidx_api_data`），解决插件在独立环境下启动时的 `ImportError`。



