# Changelog

## [2026-10-06] - b50 锐评附录 P5b（身份键 / 节流转述 / m1 / m3 / m5）

### Added

- **ctx 身份键**（`libraries/maimaidx_best_50.py`）：`_build_appendix_context()` 现在
  填 `identity`（`amia_core.B50AppendixContext` 的末位默认值字段）——
  `_appendix_identity()` 按 QQ 查给 `qqid` 十进制串、按昵称查给上游返回的昵称；
  旧版契约用 `_ctx_accepts()` 判定后**不传**该关键字（多传一个关键字会 TypeError →
  整条附录白丢）。coach 侧据此触发全量回退、并把它当节流键。
- **`take_notice` 转述**（`_take_provider_notice`）：`render_appendix` 返回 `None` 时
  问渲染侧要一句可转述的话（节流 / 排队中）；旧版 coach 没有这个方法、或它自己抛
  异常 → 回落默认降级话术。
- **m1 缺席话术**：`_APPENDIX_ABSENT_NOTICE` + `appendix_absent_notice()` ——
  用户主动打了锐评标记但 coach 不在场时，由**调用方**（`command/mai_score.py`）补一句。
  `generate()` 对缺席仍然静默（硬线：缺席路径逐字节相等、零话术），所以这句只能由
  调用方在拿到空 notice 后自己判定后补上。
- `tests/test_b50_appendix.py` 新增 9 用例：ctx.identity 取 qqid / 昵称、旧契约不塞
  新字段、`take_notice` 转述与异常回落、m1 缺席话术（在场时为空）、`generate()` 缺席
  仍静默、`_paste_appendix` 与 `image_to_base64` 都进线程。

### Fixed

- **m3 非锚定标记**（`command/mai_score.py`）：`b50 锐评 谢谢` / `b50锐评一下` /
  `b50 锐评b50` 的 CommandArg 以前整串当 username 去查分 → 「没有找到玩家数据」
  报错卡。新增 `_B50_LEADING_MARKER_RE`：**以标记开头**的整串按标记处理（标记吃掉、
  尾巴不猜意图），username 恒为空串。`tests/test_b50_critique_guard.py` 新增
  `LEADING_MARKER_ARGS` 矩阵。
- **m5 事件循环阻塞**：`_paste_appendix`（整画布 RGBA 复制 + 更高画布重编码）与
  `image_to_base64`（PNG 编码 + base64）都是同步阻塞，现在都经
  `anyio.to_thread.run_sync` 进线程。

### Notes

- 硬线仍绿：`test_no_provider_is_byte_identical`、`test_provider_absent_and_present_same_bytes`。
  全套 112 → **121 OK (skipped=2)**。

## [2026-10-05] - b50 锐评附录 P3（调色板采样）

### Added

- **出图侧把实际背景色交给 coach**（`libraries/maimaidx_best_50.py`）：新增只读采样
  `_mean_rgb_over`（网格步长取样，上限 ~1024 点）与 `_sample_background_palette`，
  组装 ctx 时多带一个 `palette`（`amia_core.B50AppendixPalette`）——
  `base_rgb` = 本仓库实际当画布用的 `maidir/b50_bg.png` 素材均色，
  `seam_rgb` = 当前画布最下方 24px 那条带的均色（锐评附录就接在这条边下面）。
  coach 侧据此把附录条画成**浅色同族**，不再自创深色底；
- `tests/test_b50_appendix.py` 新增 8 用例：接缝采样值可被**独立算出**（替身画布底部
  就是纯色）、换一张素材采样值跟着变（**禁止硬编码色值**的直接证据）、素材缺失时
  `base_rgb` 为 None 且附录照常出、采样前后画布逐像素相等、provider 缺席时**一次采样
  都不触发**、旧版 amia_core 无 `B50AppendixPalette` 导出不影响 ctx、区域不合/全透明
  一律返回 None。全套 104 → 112 仍绿。

### Changed

- **降级纪律不变**：采样只在 `_build_appendix_context` 里发生（即 capability 查表
  命中之后），只调 `getpixel` / `size`，不 crop、不 paste、不 draw、不返回图像对象，
  也不碰编码路径 —— `test_no_provider_is_byte_identical` 与
  `test_provider_absent_and_present_same_bytes` 两条硬线仍绿；旧版 ctx 签名（没有
  `palette` 字段）下**不传该关键字**，附录照常拼，不会因多传参数把整条附录丢掉。

## [2026-10-05]

### Added

- **B50 锐评附录（任务 b50-critique-merge · P1b）**：`generate()` 出完 B50 图后
  **调用时**查 `core.registry.get_capability_provider(B50_APPENDIX_PROVIDER)`
  （call-time，解耦 import 顺序；契约在 `amia_core/b50_appendix.py`），拿到 coach
  渲染的 RGBA PNG 就拼在原图**下方**，再走原有 `image_to_base64` —— 画布所有权与
  编码仍留在本仓库，coach 不参与出图。
- **绘制顺序由出图侧交出（唯一真源）**：`ScoreBaseImage.whiledraw` 新增可选
  `bucket=` 参数，在实际绘制循环里就地记账 `(bucket, 桶内 1-based 序号, info)`；
  `DrawBest.draw()` 以 `sd→"b35"` / `dx→"b15"` 调用它（语义依据
  `libraries/maimaidx_merge.py:11-12`：按**版本**划分，不是 SD/DX 谱面类型），
  `DrawBest.b50_cards()` 按记账顺序产出 `B50CardPosition` 元组。coach 侧不得重排：
  P0 实测 `song_id=1736《プリズム△▽リズム》` 版本码 25504，两源都归上半区，而
  coach 的 25500 阈值会判成 b15。`constant` 传的是 `generate()` 里按本地曲库
  **回填之后**的 `ds`（补不上 → `None`，由消费侧跳过并记日志）。
- `tests/test_b50_appendix.py`：卡序逐项等于生产 `whiledraw` 的合成坐标序
  （5 列行优先，`x=16`、列距 276、`num % 5` 换行）、1736 落 `b35` 第 8 格、
  `constant` 取回填后的值，以及降级矩阵（查表异常 / 未注册 / 总闸关 / 返回 None /
  渲染抛异常 / 8s 超时 / 宽度不等于 `ctx.width` / 字节解不开 / 返回类型不合 /
   旧版 `amia_core` 缺契约导出 / 组装 ctx 抛异常 →
  一律原图）。

### Changed

- **`b50锐评` 一类入口并入 `b50`**（用户拍板「全删，只留 b50」）：昨天挂在
  `best50` 上的 `rule=_not_coach_critique` 守卫**退役**，`b50锐评` / `b50 锐评` /
  `B50锐评` / `b50点评` / `/b50锐评` 现在由 best50 认领、行为等同 `b50`；尾部标记
  由 `_parse_b50_arg()` 吃掉，`username` 恒为空串（★ 认领它是对的，**把它当
  username 去查分**才是昨天那张「落雪（LXNS）没有找到对应的舞萌玩家数据」报错卡，
  所以「解析先于出图」与「username 只来自解析函数」都有断言钉着）。
  不以 b50 开头的裸 `锐评` / `点评`（含倒序 `锐评b50`）与 best50 无关，由 coach 的
  matcher 回引导语；`tests/test_b50_critique_guard.py` 用「best50 认领 ∪ coach
  pattern 命中 = 全集」排除谁都不理的静默洞。
- **`b50 无锐评` / `b50 无点评`**：一次性修饰词，本次不接附录，**不做群内持久
  状态**（下一条裸 `b50` 照旧接）。
- `generate()` 返回 `(MessageSegment, notice)`（不再用模块级状态），`notice` 承载
  降级话术；调用点 `command/mai_score.py` 的 best50 / ap50 同步更新。best50 只在
  用户主动打了锐评标记时才播报 `notice`，所以裸 `b50` 的文字与图片都不变；
  **ap50 显式 `appendix=False`，连 capability 表都不查**。
- 附录路径整体包 `try` + `anyio.fail_after(8.0)`：任何异常、超时、`None`、尺寸
  不合都只降级为原图，b50 主功能不受影响。

### Fixed

- **旧版 `amia_core` 不再把 b50 打成错误卡**（`libraries/maimaidx_best_50.py`）：
  附录只挡了 `core is None`，却硬访问 `core.B50CardPosition`（`b50_cards()`）与
  `core.B50AppendixContext`（`_build_appendix_context()`）。姊妹层装得上、但还没
  导出这两个契约类型时（旧版 amia_core），`AttributeError` 一路冒到
  `generate()`，主功能 b50 退化成报错卡 —— 附录是附加区，不该有这个权力。现在
  两处都改 `getattr(core, "...", None)`，取不到即静默降级（cards 返回 `()`、
  ctx 返回 `None`，与 coach 缺席同一条路径，输出仍与接入前逐字节相等）；
  `_render_appendix_png()` 里的 `_build_appendix_context(draw_best)` 也纳入
  `try`，组装上下文抛任何异常（旧版签名不合、内部炸）都只是没有附录，
  记 `log.debug` 后按原图发出、不加话术。

### Notes

- coach 缺席时 b50 输出与接入前**逐字节相等**（`tests/test_b50_appendix.py` 打印
  两条路径的 base64 长度与首 8 字节比对：缺席路径 == 控制值，且编码的对象就是原
  画布本体，没有重建画布、没有二次绘制）。
- 只动 `best50` / `ap50` 的注册与调用行、`maimaidx_best_50.py` 的出图尾部；
  `whiledraw` 的像素操作零改动（新增的只有记账一行）。

## [2026-10-04]

### Fixed

- **`b50锐评` 不再被 `b50` 指令抢走**（`command/mai_score.py`）：`.env` 的
  `COMMAND_START=["/", ""]` 含空前缀，nonebot 的 `on_command('b50')` 对本机
  2.5.0 实测会认领粘连写法 `b50锐评`（`CommandArg` 于是拿到「锐评」当
  `username`），叠加 `priority=0` + `block=True`，
  `Amia-plugin-maimai-coach/matchers/critique.py` 的锐评 matcher（`priority=5`）
  被截死，群里回「落雪（LXNS）没有找到对应的舞萌玩家数据」。
  现在 `best50` 通过 `rule=` 挂一条守卫规则（nonebot 会把它与命令规则 AND，
  `plugin/on.py:344`）：整条消息纯文本恰好是锐评指令时返回 `False`，matcher
  不被选中、事件下传给 coach；其余一律按原样认领。
  取文本出现任何异常都 **fail-open 回「照旧认领 b50」** —— 守卫失效最多退回旧的
  报错卡，反向误判会把整条 b50 指令打哑，那更糟。
- 有意**不用** `force_whitespace=True`：它会连带废掉 `b50张三` 这类粘连昵称查询
  （回归面大于 bug），而且对带空格的 `b50 锐评` 根本不触发，两个 case 都修不了。

### Added

- `tests/test_b50_critique_guard.py`：守卫的行为矩阵（锐评写法不认领 /
  `b50`、`b50 小明`、`b50张三`、`b50 <QQ>` 照常认领）、`@机器人` 前缀下的真实
  onebot v11 事件 + `Rule` 依赖注入路径、异常 fail-open、段间 `"\\n"` 拼接与
  跨段融合两条口径用例，外加**事故前提回归**（不挂守卫时 `on_command('b50')`
  确实会认领 `b50锐评` —— nonebot 若改了命令语义，这条先红，提醒守卫可退役）；
- **跨仓库镜像契约**：守卫正则与 coach 的 `CRITIQUE_PATTERN` 逐字符相等，由
  `CrossRepoPatternMirrorTests` 直接读姊妹仓库源码比对（姊妹仓库不在旁边时
  降级 skip）；两侧测试另各硬编码同一组别名字面量互钉。

### Notes

- 只动 `best50` 的注册（`rule=` 一个参数位）；`ap50` / `minfo` / `ginfo` /
  `分数线` 与 `@best50.handle()` 的全部业务逻辑零改动 —— coach 只有锐评一条
  指令与本插件冲突，不存在别的交接。

## [Unreleased] - 2026-09-04

### 双源自动汇总

- 移除“默认数据源”概念与 `切换数据源` 指令：b50 / ap50 / minfo / Provider 摘要与 B50
  全部并发请求落雪与水鱼，并按同谱面键（归一化原生 song_id + 类型 + 难度序号）逐谱面汇总；
- 新增 `libraries/maimaidx_merge.py` 纯函数汇总模块：achievements/ra 取最大、fc/fs 取最优
  （app > ap > fcp > fc；fsdp/fdxp > fsd/fdx > fsp > fs）、dxScore/rate 取达成率较高方
  （平手取落雪）、ds/level 冲突以落雪为准并记录日志、跨桶成绩归入达成率较高一方所在桶；
- `maiApi` 新增 `query_user_b50_merged` / `query_user_song_score_merged` /
  `query_player_simple_scores`：单源失败自动降级并在数据源标注中注明（如
  「仅落雪（水鱼未授权）」），两源全失败时保持既有错误语义；
- 水鱼全量成绩以 OAuth 达成率为权威源，落雪 SimpleScore（无达成率字段）仅按谱面键
  升级 fc/fs 徽章，拉取失败不阻断；
- `mai状态` 改为展示双源状态矩阵（落雪绑定 / 水鱼公开 / 水鱼 OAuth），
  `mai帮助` 文案与按钮同步更新；`mai曲线` / `mai最近` / `mai热度` 不再要求切换数据源。

### 移除

- 彻底删除水鱼 Developer-Token 残留：`maimaidxtoken` 配置字段、`maiApi.token`、
  废弃 Token 迁移警告全部移除；水鱼侧仅保留公开 `POST /query/player` 与 OAuth Bearer；
- 删除 `prober_source` 配置字段与 `user_source_route` 内存路由字典；
  旧 `.env` 残留键由 Config `extra="allow"` 静默忽略。

## Release010 compatibility - 2026-08-01

- pinned the PicMenu-compatible metadata path to the Release010 dependency set;
- imported the official Resource CN1.56 digit assets with four-way staged/atomic sync;
- preserved the upstream artwork attribution notice;
- replaced raw exception text with stable `HX-MAI-*` codes and human-readable reasons;
- added scrubbed diagnostic-file delivery for the main score, recent-record, heatmap,
  DX Pass, and chart-rendering failure paths;
- kept Release010 string/array/CQ card, input_notify, stream, and file-segment handling
  in the shared Amia compatibility helpers.

## [Unreleased] - 2026-07-21

### 猜曲绘

- `猜曲绘` 不再发送完整曲绘，改为随机截取局部正方形并缩放到 320×320。
- 猜对后的结果按“答案是：”在前、完整曲绘/歌曲信息在后的顺序输出。
- 结束、超时和重复开始场景继续使用统一猜歌状态清理逻辑。

### 资源处理

- 保持现有曲绘同步和缓存职责不变；本轮只调整猜曲绘展示，不改变 maimai sync 的实现或数据源。

### 验证

- 相关 Python 文件编译检查通过。
- 猜曲绘的裁切和答案顺序已通过代码路径检查；真实 QQ 客户端仍应再验证图片是否只显示局部及结果消息排版。
