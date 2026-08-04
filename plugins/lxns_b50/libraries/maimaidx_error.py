"""Stable, user-readable Maimai errors for Release010."""

from __future__ import annotations


class MaimaiError(Exception):
    hx_code = "HX-MAI-009"
    hx_reason = "舞萌查分插件处理失败。"
    hx_suggestion = "请稍后重试；如果连续失败，请提交诊断日志。"
    hx_cause = "插件未分类异常。"

    def __str__(self) -> str:
        return self.hx_reason


class UserNotFoundError(MaimaiError):
    hx_code = "HX-MAI-005"
    hx_reason = "没有找到对应的舞萌玩家数据。"
    hx_suggestion = "请确认好友码、绑定关系或查询名称后重试。"
    hx_cause = "数据源返回用户不存在或查询条件没有匹配项。"


class UserNotBindLXNSError(MaimaiError):
    hx_code = "HX-MAI-001"
    hx_reason = "当前用户还没有绑定落雪查分器账号。"
    hx_suggestion = "请先在落雪查分器完成授权和成绩同步。"
    hx_cause = "落雪数据源没有找到当前身份对应的绑定记录。"

    def __init__(self, is_official_bot: bool = True):
        self.is_official = is_official_bot


class UserNotBindFishError(MaimaiError):
    hx_code = "HX-MAI-001"
    hx_reason = "当前用户还没有绑定水鱼查分器账号。"
    hx_suggestion = "请先在水鱼查分器完成导入和 QQ 绑定。"
    hx_cause = "水鱼数据源没有找到当前身份对应的绑定记录。"

    def __init__(self, is_official_bot: bool = True):
        self.is_official = is_official_bot


class UserDisabledQueryError(MaimaiError):
    hx_code = "HX-MAI-005"
    hx_reason = "该用户未同意其他人获取成绩数据，或查询权限已关闭。"
    hx_suggestion = "请让用户开启可查询权限后重试。"
    hx_cause = "上游数据源拒绝了当前查询权限。"


class TokenNotFoundError(MaimaiError):
    hx_code = "HX-MAI-002"
    hx_reason = "未配置舞萌查分器所需的开发者凭证。"
    hx_suggestion = "请在本地配置对应数据源凭证；不要把 Token 发到群里或提交到 Git。"
    hx_cause = "插件启动时没有读取到必需的开发者配置。"


class UserNotExistsError(MaimaiError):
    hx_code = "HX-MAI-005"
    hx_reason = "数据源中不存在该用户。"
    hx_suggestion = "请确认绑定账号和查询身份后重试。"
    hx_cause = "上游接口返回用户不存在。"


class MusicNotPlayError(MaimaiError):
    hx_code = "HX-MAI-005"
    hx_reason = "没有找到这首歌对应的游玩记录。"
    hx_suggestion = "请确认曲目、难度和查询账号后重试。"
    hx_cause = "本地曲库或上游成绩中没有对应谱面记录。"


class ServerError(MaimaiError):
    hx_code = "HX-MAI-004"
    hx_reason = "舞萌数据源暂时不可用。"
    hx_suggestion = "请稍后重试；如果连续失败，请提交诊断日志。"
    hx_cause = "上游服务返回错误或网络连接失败。"


class UnknownError(MaimaiError):
    hx_code = "HX-MAI-009"
    hx_reason = "舞萌查分插件内部处理失败。"
    hx_suggestion = "请稍后重试，并把错误码和诊断文件交给开发者。"
    hx_cause = "程序捕获到未分类异常。"
