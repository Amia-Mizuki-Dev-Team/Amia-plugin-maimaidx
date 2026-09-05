# Changelog

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
