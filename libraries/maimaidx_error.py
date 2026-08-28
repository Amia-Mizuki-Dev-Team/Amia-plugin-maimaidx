"""Stable, user-readable Maimai errors for Release010."""

from __future__ import annotations


class MaimaiError(Exception):
    hx_code = "HX-MAI-009"
    hx_reason = "舞萌查分插件处理失败。"
    hx_suggestion = "请稍后重试；如果连续失败，请提交诊断日志。"
    hx_cause = "插件未分类异常。"
    user_expected = False

    def __str__(self) -> str:
        return self.hx_reason


class UserNotFoundError(MaimaiError):
    hx_code = "HX-MAI-005"
    hx_reason = "没有找到对应的舞萌玩家数据。"
    hx_suggestion = "请确认好友码、绑定关系或查询名称后重试。"
    hx_cause = "数据源返回用户不存在或查询条件没有匹配项。"
    user_expected = True

    def __init__(self, source: str | None = None):
        """Keep a selected-source miss distinguishable from a bind failure.

        B50 deliberately does not fall back to the other provider: a user may
        have different records or privacy settings on LXNS and Diving-Fish.
        Carrying the provider into the expected error makes that choice clear
        instead of making a successful qbind lookup look like a broken bind.
        Callers outside the source-aware B50 path keep the original wording.
        """
        super().__init__()
        source_key = str(source or "").strip().lower().replace("_", "-")
        self.source = source_key or None
        labels = {
            "lxns": ("落雪（LXNS）", "水鱼"),
            "diving-fish": ("水鱼（Diving-Fish）", "落雪"),
        }
        label_data = labels.get(source_key)
        if label_data:
            label, other_name = label_data
            self.hx_reason = f"{label}没有找到对应的舞萌玩家数据。"
            self.hx_suggestion = (
                f"当前只查询{label}；如果成绩在{other_name}，请先发送「切换数据源 "
                f"{other_name}」后重试。"
            )


class UserNotBindLXNSError(MaimaiError):
    hx_code = "HX-MAI-001"
    hx_reason = "当前用户还没有绑定落雪查分器账号。"
    hx_suggestion = "请先在落雪查分器完成授权和成绩同步。"
    hx_cause = "落雪数据源没有找到当前身份对应的绑定记录。"
    user_expected = True

    def __init__(self, is_official_bot: bool = True):
        self.is_official = is_official_bot


class UserNotBindFishError(MaimaiError):
    hx_code = "HX-MAI-001"
    hx_reason = "当前用户还没有绑定水鱼查分器账号。"
    hx_suggestion = "请先在水鱼查分器完成导入和 QQ 绑定。"
    hx_cause = "水鱼数据源没有找到当前身份对应的绑定记录。"
    user_expected = True

    def __init__(self, is_official_bot: bool = True):
        self.is_official = is_official_bot


class UserDisabledQueryError(MaimaiError):
    hx_code = "HX-MAI-005"
    hx_reason = "该用户未同意其他人获取成绩数据，或查询权限已关闭。"
    hx_suggestion = "请让用户开启可查询权限后重试。"
    hx_cause = "上游数据源拒绝了当前查询权限。"
    user_expected = True


class TokenNotFoundError(MaimaiError):
    hx_code = "HX-MAI-002"
    hx_reason = "未配置舞萌查分器所需的开发者凭证。"
    hx_suggestion = "请在本地配置对应数据源凭证；不要把 Token 发到群里或提交到 Git。"
    hx_cause = "插件启动时没有读取到必需的开发者配置。"


class OAuthConsentRequiredError(MaimaiError):
    """The target user has not authorized this application (or is unknown)."""

    hx_code = "HX-MAI-005"
    hx_reason = "这位玩家还没有授权水鱼查分。"
    hx_suggestion = "请让要查询的玩家发送「水鱼授权」，完成后再试。"
    hx_cause = "OAuth 授权服务器返回 consent_required。"
    user_expected = True


class OAuthConfigurationError(MaimaiError):
    """The bot's OAuth application is missing or not accepted by Diving-Fish."""

    hx_code = "HX-MAI-002"
    hx_reason = "水鱼 OAuth 配置还没有准备好。"
    hx_suggestion = "请管理员检查 OAuth 应用资料、client_id、client_secret 和权限范围。"
    hx_cause = "OAuth 应用凭据缺失、无效或申请了未批准的权限。"


class OAuthScopeError(OAuthConfigurationError):
    """The token exists but does not contain the requested records scope."""

    hx_reason = "水鱼授权范围不包含查分所需的成绩权限。"
    hx_suggestion = "请管理员在水鱼开发者控制台启用 prober.records.read，并让用户重新授权。"
    hx_cause = "OAuth access token 缺少 prober.records.read scope。"


class MaimaiRateLimitError(MaimaiError):
    """The upstream service rejected the request because of a quota limit."""

    hx_code = "HX-MAI-004"
    hx_reason = "水鱼查分请求达到频率限制了。"
    hx_suggestion = "请稍后再试，不要连续重复发送同一条查询。"
    hx_cause = "Diving-Fish 返回 HTTP 429。"


class UserNotExistsError(MaimaiError):
    hx_code = "HX-MAI-005"
    hx_reason = "数据源中不存在该用户。"
    hx_suggestion = "请确认绑定账号和查询身份后重试。"
    hx_cause = "上游接口返回用户不存在。"
    user_expected = True


class MusicNotPlayError(MaimaiError):
    hx_code = "HX-MAI-005"
    hx_reason = "没有找到这首歌对应的游玩记录。"
    hx_suggestion = "请确认曲目、难度和查询账号后重试。"
    hx_cause = "本地曲库或上游成绩中没有对应谱面记录。"
    user_expected = True


class MaimaiRequestError(MaimaiError):
    """A user-supplied upstream query was rejected with HTTP 400."""

    hx_code = "HX-MAI-005"
    hx_reason = "水鱼没有接受这组查询条件。"
    hx_suggestion = "请检查筛选字段、范围或牌子写法后再试。"
    hx_cause = "上游接口返回 HTTP 400。"
    user_expected = True

    def __init__(self, field: str | None = None):
        super().__init__()
        self.field = str(field or "").strip()
        if self.field:
            self.hx_reason = f"水鱼没有接受筛选字段「{self.field}」的写法。"
            self.hx_suggestion = f"请检查「{self.field}」的值、范围或格式后再试。"


class PageOutOfRangeError(MaimaiError):
    """A local page argument is outside the available result pages."""

    hx_code = "HX-MAI-005"
    hx_reason = "页码超出了当前成绩范围。"
    hx_suggestion = "请换一个有效页码后重试。"
    hx_cause = "命令请求了不存在的本地结果页。"
    user_expected = True

    def __init__(self, total_pages: int):
        super().__init__()
        self.total_pages = max(1, int(total_pages))
        self.hx_reason = f"页码超出了范围，目前只有 {self.total_pages} 页。"


class ServerError(MaimaiError):
    hx_code = "HX-MAI-004"
    hx_reason = "舞萌数据源暂时不可用。"
    hx_suggestion = "请稍后重试；如果连续失败，请提交诊断日志。"
    hx_cause = "上游服务返回错误或网络连接失败。"


class MaimaiTransportError(MaimaiError):
    """The Bot could not deliver a reply through OneBot/Gensokyo."""

    hx_code = "HX-MAI-008"
    hx_reason = "Bot 消息通道暂时没有回应。"
    hx_suggestion = "请检查 OneBot/Gensokyo 的 WebSocket 连接后再试。"
    hx_cause = "适配器调用 send_msg 超时或消息通道已经断开。"


class MaimaiTimeoutError(ServerError):
    hx_code = "HX-MAI-003"
    hx_reason = "查分器现在有点忙，暂时没有及时回应。"
    hx_suggestion = "等一会儿再试一次；如果一直失败，请把错误编号交给管理员。"
    hx_cause = "上游请求超过了限定时间。"


class MaimaiDataFormatError(MaimaiError):
    hx_code = "HX-MAI-007"
    hx_reason = "查分器返回的数据和当前插件版本对不上。"
    hx_suggestion = "请管理员检查数据源版本和插件资源。"
    hx_cause = "上游响应缺少当前绘图所需的数据。"


class MaimaiResourceError(MaimaiError):
    hx_code = "HX-MAI-006"
    hx_reason = "本地绘图资源没有准备好。"
    hx_suggestion = "请管理员检查资源包路径和文件权限。"
    hx_cause = "读取本地图片或字体时发生错误。"


class SourceNotSupportedError(MaimaiError):
    hx_code = "HX-MAI-005"
    hx_reason = "AP50 目前只支持落雪查分器。"
    hx_suggestion = "请先发送「切换数据源 落雪」，再重新查询 AP50。"
    hx_cause = "水鱼开发者接口不提供 AP50 数据。"
    user_expected = True


class UnknownError(MaimaiError):
    hx_code = "HX-MAI-009"
    hx_reason = "舞萌查分插件内部处理失败。"
    hx_suggestion = "请稍后重试，并把错误码和诊断文件交给开发者。"
    hx_cause = "程序捕获到未分类异常。"
