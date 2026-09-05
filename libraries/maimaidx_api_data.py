import asyncio
import httpx
import re
from typing import List, Optional, Any, Mapping
from loguru import logger as log
from ..config import maiconfig
from .maimaidx_types import SourceName, lxns_song_target, normalize_source
from .maimaidx_error import (
    MaimaiDataFormatError,
    MaimaiTimeoutError,
    MaimaiRequestError,
    ServerError,
    TokenNotFoundError,
    UserDisabledQueryError,
    UserNotFoundError,
    MusicNotPlayError,
    SourceNotSupportedError,
)
from .maimaidx_model import ChartInfo
from .diving_fish_oauth import DivingFishOAuth
from .maimaidx_oauth_binding import (
    OAUTH_BINDING_KEY,
    build_oauth_binding,
    is_authorized_oauth_binding,
)

# ==========================================
# 落雪 / 水鱼 API 共享常量
# ==========================================
LXNS_BASE = "https://maimai.lxns.net/api/v0"
FISH_BASE = "https://www.diving-fish.com/api/maimaidxprober"


def _mask_identity(value: str) -> str:
    """Return a short, non-sensitive label for an OAuth device page."""
    value = str(value or "")
    if len(value) <= 4:
        return "用户 " + "*" * len(value)
    return f"QQ {value[:2]}{'*' * max(2, len(value) - 4)}{value[-2:]}"


def _log_score_breakpoint(
    stage: str,
    detail: str,
    *,
    status: int | None = None,
    qqid: Any = None,
    username: str | None = None,
    subject: str | None = None,
    error: BaseException | None = None,
) -> None:
    """无法获取成绩时把断点信息打印到控制台；成功取数的路径保持静默。"""
    if qqid is not None:
        identity = f"qq={qqid}"
    elif username:
        identity = f"username={username}"
    else:
        identity = f"subject={subject or '未知'}"
    outcome = f"HTTP {status}" if status is not None else "请求未完成"
    line = f"[{stage}] 成绩获取失败断点: {identity} | {detail} -> {outcome}"
    if error is not None:
        line += f" | {type(error).__name__}: {error}"
    log.error(line)


def _chart_info(payload: dict, *, source: SourceName, default_type: str) -> ChartInfo:
    """Normalize the small naming differences between LXNS and Diving-Fish."""
    return ChartInfo(
        song_id=int(payload.get("song_id", payload.get("id", payload.get("music_id", 0)))),
        title=str(payload.get("title", payload.get("song_name", ""))),
        level_index=int(payload.get("level_index", payload.get("difficulty", 0))),
        level=str(payload.get("level", "")),
        achievements=float(payload.get("achievements", 0) or 0),
        dxScore=int(payload.get("dxScore", payload.get("dx_score", 0)) or 0),
        rate=str(payload.get("rate", "") or ""),
        fc=str(payload.get("fc", "") or ""),
        fs=str(payload.get("fs", "") or ""),
        type=str(payload.get("type", default_type) or default_type),
        level_label=str(payload.get("level_label", "")),
        ds=float(payload.get("ds", 0) or 0),
        source=source,
        ra=int(payload.get("ra", payload.get("dx_rating", 0)) or 0),
    )


class RecordsResult(list[ChartInfo]):
    """Normalized full records with the server filter echo attached.

    It remains a normal list for existing provider consumers while exposing
    the optional ``filters`` mapping needed to detect a silently ignored
    server-side condition.
    """

    def __init__(self, records: list[ChartInfo], filters: Mapping[str, Any] | None = None):
        super().__init__(records)
        self.filters = filters


class MaiApi:
    def __init__(self):
        self.headers = {}
        self.oauth = DivingFishOAuth.from_config(maiconfig)

    def load_token_proxy(self):
        """加载落雪开放平台请求头；水鱼侧仅使用 OAuth，不使用任何静态 Token。"""
        if maiconfig.lxnstoken:
            self.headers = {"Authorization": maiconfig.lxnstoken}
            log.info("落雪开放平台 API 凭证加载成功。")

    @property
    def oauth_configured(self) -> bool:
        return self.oauth.configured

    @staticmethod
    def _raise_lxns_auth_error(status_code: int) -> None:
        """Split LXNS 401 from 403 instead of blaming the queried player.

        LXNS answers 401 when the developer token is missing or invalid
        (administrator credential problem) and 403 when the queried player
        disabled third-party score access (user privacy).  Collapsing both
        into ``UserDisabledQueryError`` misreports credential failures as
        "user closed the query permission".
        """
        if status_code == 401:
            raise TokenNotFoundError()
        raise UserDisabledQueryError()

    def oauth_subject(self, qqid: Optional[int] = None, username: Optional[str] = None) -> str:
        """Build the subject without changing the legacy external identifier."""
        if username:
            # The migration digest must use exactly the username value that
            # the old public/developer request submitted.  Adding a local
            # prefix would create a different subject and strand existing
            # authorizations from their imported records.
            return self.oauth.subject_ref(str(username).strip())
        if qqid is None:
            raise UserNotFoundError()
        return self.oauth.subject_ref(str(qqid))

    async def request_device_authorization(self, external_id: str | int) -> Any:
        subject = self.oauth.subject_ref(str(external_id))
        label = _mask_identity(str(external_id))
        return await self.oauth.request_device_authorization(subject, label)

    async def check_oauth_authorization(self, qqid: int) -> bool:
        subject = self.oauth_subject(qqid=qqid)
        await self.oauth.get_access_token(subject)
        await self.remember_oauth_authorization(str(qqid))
        return True

    async def remember_oauth_authorization(
        self, external_id: str, *, authorized: bool = True
    ) -> bool:
        """Share consent metadata through the existing maimai_sync row.

        The access token itself remains in ``DivingFishOAuth``'s process-local
        cache.  This method is intentionally best-effort for normal queries:
        a temporary DB outage must not turn an otherwise successful score
        response into a second user-facing error.  The explicit status
        command uses the returned value to tell the user when another plugin
        may not see the authorization yet.
        """

        try:
            from ..dependencies import get_user_bind_async, save_user_bind

            value = (
                build_oauth_binding(self.oauth, str(external_id))
                if authorized
                else None
            )
            await save_user_bind(str(external_id), OAUTH_BINDING_KEY, value)
            if not authorized:
                return True
            binds = await get_user_bind_async(str(external_id))
            return is_authorized_oauth_binding(binds.get(OAUTH_BINDING_KEY))
        except Exception:
            return False

    # ==========================================
    # 落雪 API 方法
    # ==========================================

    async def _get_db_bind_status(self, qqid: int) -> dict:
        """从 maimai_sync 数据库查询用户绑定状态（不自行创建，单纯使用其远程库与本地库）"""
        status = {}
        try:
            from ..dependencies import get_user_bind_async
            binds = await get_user_bind_async(str(qqid))
            if binds:
                status["db_fish"] = bool(binds.get("fish"))
                status["db_lxns"] = bool(binds.get("lxns"))
                status["db_fish_oauth"] = is_authorized_oauth_binding(
                    binds.get(OAUTH_BINDING_KEY)
                )
                status["db_user_type"] = binds.get("Type")
        except Exception:
            pass
        return status

    async def check_bind_status(self, qqid: int) -> dict:
        """
        检测指定 QQ 账户在落雪和水鱼平台的绑定注册状态。
        优先远程 API 实时查询，远程失败时回退 maimai_sync 数据库。
        """
        status = {
            "lxns": False,
            "diving_fish": False,
            # This is deliberately separate from the public B50 endpoint:
            # public availability does not imply that the current user has
            # granted OAuth access to protected records.
            "diving_fish_oauth": False,
        }
        
        # 策略一：远程 API 实时查询
        async with httpx.AsyncClient(timeout=10) as client:
            if maiconfig.lxnstoken:
                try:
                    res = await client.get(f"{LXNS_BASE}/maimai/player/qq/{qqid}", headers=self.headers)
                    if res.status_code == 200:
                        status["lxns"] = True
                except Exception as e:
                    log.error(f"中继探测落雪绑定状态发生网络断流: {e}")
            try:
                res = await client.post(f"{FISH_BASE}/query/player", json={"qq": str(qqid)})
                if res.status_code == 200:
                    status["diving_fish"] = True
            except Exception as e:
                log.error(f"中继探测水鱼绑定状态发生网络断流: {e}")
        
        # 策略二：远程 API 未查到时，回退 maimai_sync 数据库
        # Always read the shared row once.  The OAuth marker is independent
        # from public waterfish availability, so it must not be skipped when
        # both public probes happen to succeed.
        try:
            db_status = await self._get_db_bind_status(qqid)
            if db_status.get("db_lxns") and not status["lxns"]:
                status["lxns"] = True
            if db_status.get("db_fish") and not status["diving_fish"]:
                status["diving_fish"] = True
            status["diving_fish_oauth"] = bool(db_status.get("db_fish_oauth"))
        except Exception:
            pass
        
        return status

    async def get_lxns_rating_curves(self, qqid: int) -> list:
        """获取落雪平台玩家的历史 Rating 变动轨迹数据"""
        if not maiconfig.lxnstoken:
            raise TokenNotFoundError()
        try:
            # 先通过 QQ 获取 friend_code
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    profile_res = await client.get(
                        f"{LXNS_BASE}/maimai/player/qq/{qqid}",
                        headers=self.headers
                    )
            except httpx.TimeoutException as e:
                _log_score_breakpoint("rating趋势/落雪", "网络请求超时", qqid=qqid, error=e)
                raise MaimaiTimeoutError() from e
            except httpx.HTTPError as e:
                _log_score_breakpoint("rating趋势/落雪", "网络请求失败", qqid=qqid, error=e)
                raise ServerError() from e
            if profile_res.status_code in {400, 404}:
                _log_score_breakpoint("rating趋势/落雪资料", f"GET {LXNS_BASE}/maimai/player/qq/{qqid}", status=profile_res.status_code, qqid=qqid)
                raise UserNotFoundError()
            if profile_res.status_code in {401, 403}:
                _log_score_breakpoint("rating趋势/落雪资料", f"GET {LXNS_BASE}/maimai/player/qq/{qqid}", status=profile_res.status_code, qqid=qqid)
                self._raise_lxns_auth_error(profile_res.status_code)
            if profile_res.status_code == 429 or profile_res.status_code >= 500:
                _log_score_breakpoint("rating趋势/落雪资料", f"GET {LXNS_BASE}/maimai/player/qq/{qqid}", status=profile_res.status_code, qqid=qqid)
                raise ServerError()
            if profile_res.status_code != 200:
                _log_score_breakpoint("rating趋势/落雪资料", f"GET {LXNS_BASE}/maimai/player/qq/{qqid}", status=profile_res.status_code, qqid=qqid)
                raise ServerError()
            try:
                profile_payload = profile_res.json()
            except (ValueError, TypeError) as exc:
                raise MaimaiDataFormatError() from exc
            if not isinstance(profile_payload, dict):
                raise MaimaiDataFormatError()
            pdata = profile_payload.get("data", profile_payload)
            if not isinstance(pdata, dict):
                raise MaimaiDataFormatError()
            friend_code = pdata.get("friend_code")
            if not friend_code:
                log.warning(f"[rating趋势/落雪] 断点: qq={qqid} 资料接口没有返回 friend_code")
                raise UserNotFoundError()

            # 用 friend_code 查询 rating 趋势（趋势数据量大，给 60s 超时）
            async with httpx.AsyncClient(timeout=60) as client:
                res = await client.get(
                    f"{LXNS_BASE}/maimai/player/{friend_code}/trend",
                    headers=self.headers
                )
            if res.status_code in {400, 404}:
                _log_score_breakpoint("rating趋势/落雪trend", f"GET {LXNS_BASE}/maimai/player/{friend_code}/trend", status=res.status_code, qqid=qqid)
                raise UserNotFoundError()
            if res.status_code in {401, 403}:
                _log_score_breakpoint("rating趋势/落雪trend", f"GET {LXNS_BASE}/maimai/player/{friend_code}/trend", status=res.status_code, qqid=qqid)
                self._raise_lxns_auth_error(res.status_code)
            if res.status_code == 429 or res.status_code >= 500:
                _log_score_breakpoint("rating趋势/落雪trend", f"GET {LXNS_BASE}/maimai/player/{friend_code}/trend", status=res.status_code, qqid=qqid)
                raise ServerError()
            if res.status_code != 200:
                _log_score_breakpoint("rating趋势/落雪trend", f"GET {LXNS_BASE}/maimai/player/{friend_code}/trend", status=res.status_code, qqid=qqid)
                raise ServerError()
            try:
                data = res.json()
            except (ValueError, TypeError) as exc:
                raise MaimaiDataFormatError() from exc
            if isinstance(data, list):
                return data
            if not isinstance(data, dict):
                raise MaimaiDataFormatError()
            raw_list = data.get("data", data.get("trend"))
            if not isinstance(raw_list, list):
                raise MaimaiDataFormatError()
            # 转换为渲染器期望的格式
            import time as _time
            converted = []
            for item in raw_list:
                if not isinstance(item, dict):
                    raise MaimaiDataFormatError()
                date_str = item.get("date", "")
                try:
                    ts = int(_time.mktime(_time.strptime(date_str, "%Y-%m-%d"))) if date_str else 0
                except (TypeError, ValueError, OverflowError) as exc:
                    raise MaimaiDataFormatError() from exc
                converted.append({
                    "rating": item.get("total", 0),
                    "time": ts,
                })
            return converted
        except (MaimaiTimeoutError, TokenNotFoundError, UserNotFoundError,
                UserDisabledQueryError, ServerError, MaimaiDataFormatError):
            raise
        except Exception as e:
            log.error(f"拉取落雪 Rating 变动历史记录失败: [{type(e).__name__}] {e}")
            raise

    async def query_user_song_score(self, qqid: int, music_id: str) -> "Optional[List[ChartInfo]]":
        """
        使用落雪 API 查询玩家单曲成绩（所有难度）。

        Params:
            `qqid`: 用户QQ
            `music_id`: 曲目ID
        Returns:
            `Optional[List[ChartInfo]]`
        """
        if not maiconfig.lxnstoken:
            raise TokenNotFoundError()
        try:
            from .maimaidx_music import mai
            music = mai.total_list.by_id(str(music_id))
            remote_id, song_type = lxns_song_target(music_id, music)
            # 先通过 QQ 获取 friend_code
            async with httpx.AsyncClient(timeout=15) as client:
                profile_res = await client.get(
                    f"{LXNS_BASE}/maimai/player/qq/{qqid}",
                    headers=self.headers
                )
            if profile_res.status_code in {401, 403}:
                _log_score_breakpoint("单曲成绩/落雪资料", f"GET {LXNS_BASE}/maimai/player/qq/{qqid}", status=profile_res.status_code, qqid=qqid)
                self._raise_lxns_auth_error(profile_res.status_code)
            if profile_res.status_code in {404, 400}:
                _log_score_breakpoint("单曲成绩/落雪资料", f"GET {LXNS_BASE}/maimai/player/qq/{qqid}", status=profile_res.status_code, qqid=qqid)
                raise UserNotFoundError()
            if profile_res.status_code != 200:
                _log_score_breakpoint("单曲成绩/落雪资料", f"GET {LXNS_BASE}/maimai/player/qq/{qqid}", status=profile_res.status_code, qqid=qqid)
                raise ServerError()
            pdata = profile_res.json().get("data", {})
            friend_code = pdata.get("friend_code")
            if not friend_code:
                log.warning(f"[单曲成绩/落雪] 断点: qq={qqid} 资料接口没有返回 friend_code")
                return None

            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.get(
                    f"{LXNS_BASE}/maimai/player/{friend_code}/bests",
                    params={"song_id": remote_id, "song_type": song_type},
                    headers=self.headers,
                )
            if res.status_code == 429:
                _log_score_breakpoint("单曲成绩/落雪bests", f"GET {LXNS_BASE}/maimai/player/{friend_code}/bests", status=res.status_code, qqid=qqid)
                raise ServerError()
            if res.status_code in {401, 403}:
                _log_score_breakpoint("单曲成绩/落雪bests", f"GET {LXNS_BASE}/maimai/player/{friend_code}/bests", status=res.status_code, qqid=qqid)
                self._raise_lxns_auth_error(res.status_code)
            if res.status_code in {400, 404}:
                _log_score_breakpoint("单曲成绩/落雪bests", f"GET {LXNS_BASE}/maimai/player/{friend_code}/bests", status=res.status_code, qqid=qqid)
                raise UserNotFoundError()
            if res.status_code >= 500:
                _log_score_breakpoint("单曲成绩/落雪bests", f"GET {LXNS_BASE}/maimai/player/{friend_code}/bests", status=res.status_code, qqid=qqid)
                raise ServerError()
            if res.status_code != 200:
                _log_score_breakpoint("单曲成绩/落雪bests", f"GET {LXNS_BASE}/maimai/player/{friend_code}/bests", status=res.status_code, qqid=qqid)
                raise ServerError()
            scores = res.json()
            if isinstance(scores, dict):
                scores = scores.get("data", scores)
            if not isinstance(scores, list):
                raise ValueError("LXNS 单曲成绩响应结构不正确")
            result = []
            for s in scores:
                    item = _chart_info(s, source="lxns", default_type=song_type)
                    if music is not None:
                        item.song_id = int(music.id)
                    result.append(item)
            return result
        except (MaimaiTimeoutError, TokenNotFoundError, UserDisabledQueryError, UserNotFoundError, ServerError):
            raise
        except (httpx.TimeoutException, TimeoutError) as e:
            _log_score_breakpoint("单曲成绩/落雪", "网络请求超时", qqid=qqid, error=e)
            raise MaimaiTimeoutError() from e
        except httpx.HTTPError as e:
            _log_score_breakpoint("单曲成绩/落雪", "网络请求失败", qqid=qqid, error=e)
            raise ServerError() from e
        except Exception as e:
            log.warning(f"落雪单曲成绩查询失败(qqid={qqid}, music_id={music_id}): {e}")
            raise

    async def query_user_song_score_merged(self, qqid: int, music_id: str) -> "tuple[List[ChartInfo], dict]":
        """
        并发查询落雪单曲成绩与水鱼 OAuth 单曲成绩，逐谱面汇总。

        水鱼 OAuth 未授权（OAuthConsentRequiredError）时自动降级为仅落雪，
        并在 meta 中注明；两源全部失败时抛落雪侧错误（未配置 lxnstoken 时
        抛水鱼侧错误），水鱼明确报“未游玩”时优先保留该语义。
        返回 ``(list[ChartInfo], meta)``。
        """
        from .maimaidx_merge import (
            LABEL_FISH,
            LABEL_LXNS,
            merge_chart_infos,
            summarize_error,
        )

        async def _fetch_lxns():
            return await self.query_user_song_score(qqid, str(music_id))

        async def _fetch_fish():
            subject = self.oauth_subject(qqid=qqid)
            records = await self.query_player_record(subject, str(music_id))
            await self.remember_oauth_authorization(str(qqid))
            return records

        lxns_res, fish_res = await asyncio.gather(
            _fetch_lxns(), _fetch_fish(), return_exceptions=True
        )
        lxns_exc = lxns_res if isinstance(lxns_res, BaseException) else None
        fish_exc = fish_res if isinstance(fish_res, BaseException) else None
        lxns_records = [] if (lxns_exc is not None or not lxns_res) else list(lxns_res)
        fish_records = [] if (fish_exc is not None or not fish_res) else list(fish_res)

        if lxns_exc is not None and fish_exc is not None:
            # 两源全失败：优先抛落雪错误；落雪未配置凭证时抛水鱼错误。
            if isinstance(lxns_exc, TokenNotFoundError):
                raise fish_exc
            raise lxns_exc
        if not lxns_records and not fish_records:
            # 两源都没有可用成绩：优先回放明确的“未游玩”语义，否则抛落雪错误。
            if isinstance(fish_exc, MusicNotPlayError):
                raise fish_exc
            if lxns_exc is not None:
                raise lxns_exc
            if fish_exc is not None:
                raise fish_exc

        meta = {
            LABEL_LXNS: {
                "ok": bool(lxns_records),
                "error": None,
                "error_type": None,
            },
            LABEL_FISH: {
                "ok": bool(fish_records),
                "error": None,
                "error_type": None,
            },
        }
        if lxns_exc is not None:
            meta[LABEL_LXNS].update(
                error=summarize_error(lxns_exc), error_type=type(lxns_exc).__name__
            )
        elif not lxns_res:
            meta[LABEL_LXNS].update(error="未返回成绩数据", error_type="NoData")
        if fish_exc is not None:
            meta[LABEL_FISH].update(
                error=summarize_error(fish_exc), error_type=type(fish_exc).__name__
            )
        elif not fish_res:
            meta[LABEL_FISH].update(error="未返回成绩数据", error_type="NoData")
        return merge_chart_infos(lxns_records, fish_records), meta

    async def query_player_simple_scores(self, qqid: int) -> List[ChartInfo]:
        """
        拉取落雪全量 SimpleScore 成绩。

        该接口没有 achievements 字段，只有 fc/fs 徽章等摘要信息，
        因此只能作为水鱼全量成绩的徽章补充源，不能作为达成率数据源。
        """
        if not maiconfig.lxnstoken:
            raise TokenNotFoundError()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                profile_res = await client.get(
                    f"{LXNS_BASE}/maimai/player/qq/{qqid}",
                    headers=self.headers
                )
            if profile_res.status_code in {401, 403}:
                self._raise_lxns_auth_error(profile_res.status_code)
            if profile_res.status_code in {400, 404}:
                raise UserNotFoundError()
            if profile_res.status_code != 200:
                raise ServerError()
            pdata = profile_res.json().get("data", {})
            friend_code = pdata.get("friend_code")
            if not friend_code:
                log.warning(f"[SimpleScore/落雪] 断点: qq={qqid} 资料接口没有返回 friend_code")
                raise UserNotFoundError()

            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.get(
                    f"{LXNS_BASE}/maimai/player/{friend_code}/scores",
                    headers=self.headers,
                )
            if res.status_code == 429:
                raise ServerError()
            if res.status_code in {401, 403}:
                self._raise_lxns_auth_error(res.status_code)
            if res.status_code in {400, 404}:
                raise UserNotFoundError()
            if res.status_code != 200:
                raise ServerError()
            scores = res.json()
            if isinstance(scores, dict):
                scores = scores.get("data", scores)
            if not isinstance(scores, list):
                raise MaimaiDataFormatError()
            result: List[ChartInfo] = []
            for s in scores:
                if not isinstance(s, dict):
                    continue
                chart_type = str(s.get("type", "") or "").strip().lower()
                result.append(
                    ChartInfo(
                        song_id=int(s.get("id", s.get("song_id", 0)) or 0),
                        title="",
                        level="",
                        level_index=int(s.get("level_index", 0) or 0),
                        achievements=0.0,
                        dxScore=0,
                        rate="",
                        fc=str(s.get("fc", "") or ""),
                        fs=str(s.get("fs", "") or ""),
                        type=chart_type or "standard",
                        level_label="",
                        ds=0.0,
                        source="lxns",
                        ra=0,
                    )
                )
            return result
        except (MaimaiTimeoutError, TokenNotFoundError, UserDisabledQueryError, UserNotFoundError, ServerError, MaimaiDataFormatError):
            raise
        except (httpx.TimeoutException, TimeoutError) as e:
            raise MaimaiTimeoutError() from e
        except httpx.HTTPError as e:
            raise ServerError() from e

    async def query_user_b50(
        self,
        qqid: Optional[int] = None,
        username: Optional[str] = None,
        *,
        source: SourceName | str,
        is_ap: bool = False,
    ) -> Any:
        """
        获取用户 Best 50 数据。
        ``source`` 是调用方选择的唯一数据源；这里不会静默回退到另一端。
        """
        from .maimaidx_model import UserInfo, Data, ChartInfo

        selected = normalize_source(source)
        stage = "ap50" if is_ap else "b50"
        if is_ap and selected == "diving-fish":
            raise SourceNotSupportedError()
        if selected == "lxns":
            if not maiconfig.lxnstoken:
                _log_score_breakpoint(f"{stage}/落雪", "LXNS 开发者凭证未配置", qqid=qqid, username=username)
                raise TokenNotFoundError()
            if not qqid:
                _log_score_breakpoint(f"{stage}/落雪", "缺少可查询的 QQ 身份", username=username)
                raise UserNotFoundError(source=selected)
            try:
                profile = {}
                # 先通过 QQ 获取 friend_code 和资料（用于头像框渲染）
                async with httpx.AsyncClient(timeout=15) as client:
                    profile_res = await client.get(
                        f"{LXNS_BASE}/maimai/player/qq/{qqid}",
                        headers=self.headers
                    )
                if profile_res.status_code in {400, 404}:
                    _log_score_breakpoint(f"{stage}/落雪资料", f"GET {LXNS_BASE}/maimai/player/qq/{qqid}", status=profile_res.status_code, qqid=qqid)
                    raise UserNotFoundError(source=selected)
                if profile_res.status_code in {401, 403}:
                    _log_score_breakpoint(f"{stage}/落雪资料", f"GET {LXNS_BASE}/maimai/player/qq/{qqid}", status=profile_res.status_code, qqid=qqid)
                    self._raise_lxns_auth_error(profile_res.status_code)
                if profile_res.status_code == 429 or profile_res.status_code >= 500:
                    _log_score_breakpoint(f"{stage}/落雪资料", f"GET {LXNS_BASE}/maimai/player/qq/{qqid}", status=profile_res.status_code, qqid=qqid)
                    raise ServerError()
                if profile_res.status_code == 200:
                    pdata = profile_res.json().get("data", {})
                    friend_code = pdata.get("friend_code")
                    profile = pdata
                else:
                    friend_code = None
                    log.warning(f"[{stage}/落雪资料] 断点: qq={qqid} 资料接口返回 HTTP {profile_res.status_code}，改用 QQ 端点查询 bests")

                # AP 查询需要 friend_code 端点（/qq/{qq}/bests/ap 不存在）
                if is_ap:
                    if not friend_code:
                        raise ValueError("未获取到 friend_code，无法查询 AP50")
                    endpoint = f"{LXNS_BASE}/maimai/player/{friend_code}/bests/ap"
                else:
                    # B50 优先用 friend_code 端点（头像框资料更完整）
                    if friend_code:
                        endpoint = f"{LXNS_BASE}/maimai/player/{friend_code}/bests"
                    else:
                        endpoint = f"{LXNS_BASE}/maimai/player/qq/{qqid}/bests"

                async with httpx.AsyncClient(timeout=15) as client:
                    res = await client.get(endpoint, headers=self.headers)

                if res.status_code == 200:
                    data = res.json().get("data", {})
                    sd_list = []
                    dx_list = []
                    for c in data.get("standard", []):
                        sd_list.append(_chart_info(c, source="lxns", default_type="standard"))
                    for c in data.get("dx", []):
                        dx_list.append(_chart_info(c, source="lxns", default_type="dx"))
                    return UserInfo(
                        nickname=profile.get("name", username or str(qqid)),
                        rating=data.get("total", data.get("standard_total", 0) + data.get("dx_total", 0)),
                        additional_rating=profile.get("course_rank", 0),
                        plate=str(profile.get("name_plate", {}).get("id", "")) if profile.get("name_plate") else "",
                        username=str(profile.get("icon", {}).get("id", "")) if profile.get("icon") else "",
                        charts=Data(sd=sd_list[:35], dx=dx_list[:15])
                    )
                if res.status_code in {400, 404}:
                        _log_score_breakpoint(f"{stage}/落雪bests", f"GET {endpoint}", status=res.status_code, qqid=qqid)
                        raise UserNotFoundError(source=selected)
                if res.status_code in {401, 403}:
                    _log_score_breakpoint(f"{stage}/落雪bests", f"GET {endpoint}", status=res.status_code, qqid=qqid)
                    self._raise_lxns_auth_error(res.status_code)
                if res.status_code >= 500 or res.status_code == 429:
                    _log_score_breakpoint(f"{stage}/落雪bests", f"GET {endpoint}", status=res.status_code, qqid=qqid)
                    raise ServerError()
                _log_score_breakpoint(f"{stage}/落雪bests", f"GET {endpoint}", status=res.status_code, qqid=qqid)
                raise ServerError()
            except (TokenNotFoundError, UserNotFoundError, UserDisabledQueryError, ServerError):
                raise
            except (httpx.TimeoutException, TimeoutError) as e:
                _log_score_breakpoint(f"{stage}/落雪", "网络请求超时", qqid=qqid, error=e)
                raise MaimaiTimeoutError() from e
            except httpx.HTTPError as e:
                _log_score_breakpoint(f"{stage}/落雪", "网络请求失败", qqid=qqid, error=e)
                raise ServerError() from e
            except Exception as e:
                log.warning(f"落雪 B50 查询失败(qqid={qqid}): {e}")
                raise

        # 策略二：水鱼 API
        body = {}
        if username:
            body["username"] = username
        elif qqid:
            body["qq"] = str(qqid)
        else:
            raise ValueError("必须提供 username 或 qqid")
        body["b50"] = "1"

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                res = await client.post(f"{FISH_BASE}/query/player", json=body)
            except (httpx.TimeoutException, TimeoutError) as e:
                _log_score_breakpoint(f"{stage}/水鱼", f"POST {FISH_BASE}/query/player", qqid=qqid, username=username, error=e)
                raise MaimaiTimeoutError() from e
            except httpx.HTTPError as e:
                _log_score_breakpoint(f"{stage}/水鱼", f"POST {FISH_BASE}/query/player", qqid=qqid, username=username, error=e)
                raise ServerError() from e
        if res.status_code == 200:
            raw = res.json()
            sd_list = []
            dx_list = []
            for c in raw.get("charts", {}).get("sd", []):
                sd_list.append(_chart_info(c, source="diving-fish", default_type="standard"))
            for c in raw.get("charts", {}).get("dx", []):
                dx_list.append(_chart_info(c, source="diving-fish", default_type="dx"))
            return UserInfo(
                nickname=raw.get("nickname", username or str(qqid)),
                rating=raw.get("rating", 0),
                additional_rating=raw.get("additional_rating", 0),
                plate=raw.get("plate", ""),
                username=raw.get("username", ""),
                charts=Data(sd=sd_list, dx=dx_list)
            )
        elif res.status_code in {401, 403}:
            _log_score_breakpoint(f"{stage}/水鱼", f"POST {FISH_BASE}/query/player", status=res.status_code, qqid=qqid, username=username)
            raise UserDisabledQueryError()
        elif res.status_code in {404, 400}:
                    _log_score_breakpoint(f"{stage}/水鱼", f"POST {FISH_BASE}/query/player", status=res.status_code, qqid=qqid, username=username)
                    raise UserNotFoundError(source=selected)
        elif res.status_code == 429 or res.status_code >= 500:
            _log_score_breakpoint(f"{stage}/水鱼", f"POST {FISH_BASE}/query/player", status=res.status_code, qqid=qqid, username=username)
            raise ServerError()
        _log_score_breakpoint(f"{stage}/水鱼", f"POST {FISH_BASE}/query/player", status=res.status_code, qqid=qqid, username=username)
        raise ServerError()

    async def query_user_b50_merged(
        self,
        qqid: Optional[int] = None,
        username: Optional[str] = None,
        *,
        is_ap: bool = False,
    ) -> "tuple[Any, dict]":
        """
        并发拉取落雪与水鱼 B50，逐谱面汇总后返回。

        单源 MaimaiError/异常自动降级为另一源单源结果（is_ap 时水鱼侧直接
        不参与，水鱼公开 B50 没有 AP50 数据）；两源全部失败时抛落雪侧错误，
        未配置 lxnstoken 时抛水鱼侧错误，保持既有错误语义。
        返回 ``(UserInfo, meta)``，meta 描述每源成功与否及失败原因摘要。
        """
        from .maimaidx_merge import LABEL_FISH, LABEL_LXNS, merge_b50, summarize_error

        async def _fetch_lxns():
            return await self.query_user_b50(qqid=qqid, username=username, source=LABEL_LXNS, is_ap=is_ap)

        async def _fetch_fish():
            if is_ap:
                return None
            return await self.query_user_b50(qqid=qqid, username=username, source=LABEL_FISH)

        lxns_res, fish_res = await asyncio.gather(
            _fetch_lxns(), _fetch_fish(), return_exceptions=True
        )
        lxns_exc = lxns_res if isinstance(lxns_res, BaseException) else None
        fish_exc = fish_res if isinstance(fish_res, BaseException) else None

        if (lxns_exc is not None or lxns_res is None) and (fish_exc is not None or fish_res is None):
            if isinstance(lxns_exc, TokenNotFoundError) and fish_exc is not None:
                raise fish_exc
            if lxns_exc is not None:
                raise lxns_exc
            if fish_exc is not None:
                raise fish_exc
            raise ServerError()

        userinfo, meta = merge_b50(
            None if lxns_exc is not None else lxns_res,
            None if fish_exc is not None else fish_res,
        )
        for label, result in ((LABEL_LXNS, lxns_res), (LABEL_FISH, fish_res)):
            entry = meta.get(label)
            if entry is None:
                continue
            if isinstance(result, BaseException):
                entry.update(
                    ok=False,
                    error=summarize_error(result),
                    error_type=type(result).__name__,
                )
            elif result is None:
                # is_ap 时水鱼侧主动不参与，标注为“不适用”而非“失败”
                entry.update(ok=False, error=None, error_type="not_applicable")
        return userinfo, meta

    @staticmethod
    def _record_items(payload: Any) -> list[dict]:
        """Accept the list and keyed response forms used by Fish endpoints."""
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            raise MaimaiDataFormatError()
        for key in ("records", "data", "charts"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = [item for item in value.values() if isinstance(item, dict)]
                if nested:
                    return nested
        # A single-record response is valid for /player/record.  Do not treat
        # the envelope's metadata fields as a record unless it has a chart key.
        if any(key in payload for key in ("id", "song_id", "level_index", "achievements")):
            return [payload]
        raise MaimaiDataFormatError()

    @staticmethod
    def _bad_request_error(response: httpx.Response) -> MaimaiRequestError:
        """Turn a Fish 400 into a safe field-level hint without echoing body."""
        field = None
        try:
            payload = response.json()
            message = str(payload.get("message", "")) if isinstance(payload, dict) else ""
            match = re.search(r"(?:参数|parameter)\s+([A-Za-z_][A-Za-z0-9_]*)", message, re.I)
            if match:
                field = match.group(1)
        except (ValueError, TypeError):
            pass
        return MaimaiRequestError(field)

    @staticmethod
    def _play_info_default(item: dict):
        from .maimaidx_model import PlayInfoDefault

        data = dict(item)
        if "id" not in data:
            data["id"] = data.get("song_id", data.get("music_id", 0))
        data.setdefault("level", "")
        data.setdefault("title", "")
        data.setdefault("type", "standard")
        data.setdefault("achievements", 0)
        data.setdefault("level_index", 0)
        return PlayInfoDefault.model_validate(data)

    async def query_player_records(
        self,
        subject: str,
        filters: Optional[Mapping[str, Any] | list[tuple[str, Any]]] = None,
    ) -> RecordsResult:
        """Fetch complete records with a Bearer token and optional filters."""
        response = await self.oauth.request_api(
            "GET", "/player/records", subject, params=filters
        )
        if response.status_code == 400:
            _log_score_breakpoint("水鱼成绩/OAuth", "GET /player/records", status=response.status_code, subject=subject)
            raise self._bad_request_error(response)
        if response.status_code == 404:
            _log_score_breakpoint("水鱼成绩/OAuth", "GET /player/records", status=response.status_code, subject=subject)
            raise UserNotFoundError()
        if response.status_code == 410:
            _log_score_breakpoint("水鱼成绩/OAuth", "GET /player/records", status=response.status_code, subject=subject)
            raise ServerError()
        if response.status_code != 200:
            _log_score_breakpoint("水鱼成绩/OAuth", "GET /player/records", status=response.status_code, subject=subject)
            raise ServerError()
        try:
            payload = response.json()
            items = self._record_items(payload)
        except (ValueError, TypeError) as exc:
            raise MaimaiDataFormatError() from exc
        filters_echo = payload.get("filters") if isinstance(payload, Mapping) else None
        if filters_echo is not None and not isinstance(filters_echo, Mapping):
            raise MaimaiDataFormatError()
        return RecordsResult(
            [_chart_info(item, source="diving-fish", default_type="standard") for item in items],
            filters_echo,
        )

    async def query_player_record(self, subject: str, music_id: str) -> list[ChartInfo]:
        """Fetch one song's records; the Bearer token determines the player."""
        try:
            music_id_value = int(music_id)
        except (TypeError, ValueError) as exc:
            _log_score_breakpoint("水鱼单曲/OAuth", f"POST /player/record (music_id={music_id})", subject=subject, error=exc)
            raise UserNotFoundError() from exc
        response = await self.oauth.request_api(
            "POST", "/player/record", subject, json={"music_id": music_id_value}
        )
        if response.status_code == 400:
            _log_score_breakpoint("水鱼单曲/OAuth", "POST /player/record", status=response.status_code, subject=subject)
            raise self._bad_request_error(response)
        if response.status_code == 404:
            _log_score_breakpoint("水鱼单曲/OAuth", "POST /player/record", status=response.status_code, subject=subject)
            # The subject is already authenticated; a missing single-record
            # resource means this song has not been played, not that the QQ
            # account disappeared.
            raise MusicNotPlayError()
        if response.status_code == 410:
            _log_score_breakpoint("水鱼单曲/OAuth", "POST /player/record", status=response.status_code, subject=subject)
            raise ServerError()
        if response.status_code != 200:
            _log_score_breakpoint("水鱼单曲/OAuth", "POST /player/record", status=response.status_code, subject=subject)
            raise ServerError()
        try:
            items = self._record_items(response.json())
        except (ValueError, TypeError) as exc:
            raise MaimaiDataFormatError() from exc
        return [_chart_info(item, source="diving-fish", default_type="standard") for item in items]

    async def query_player_plate(self, subject: str, version: list) -> list:
        """Fetch version progress using the OAuth replacement endpoint."""
        response = await self.oauth.request_api(
            "POST", "/player/plate", subject, json={"version": version}
        )
        if response.status_code == 400:
            _log_score_breakpoint("水鱼牌子/OAuth", "POST /player/plate", status=response.status_code, subject=subject)
            raise self._bad_request_error(response)
        if response.status_code == 404:
            _log_score_breakpoint("水鱼牌子/OAuth", "POST /player/plate", status=response.status_code, subject=subject)
            raise UserNotFoundError()
        if response.status_code == 410:
            _log_score_breakpoint("水鱼牌子/OAuth", "POST /player/plate", status=response.status_code, subject=subject)
            raise ServerError()
        if response.status_code != 200:
            _log_score_breakpoint("水鱼牌子/OAuth", "POST /player/plate", status=response.status_code, subject=subject)
            raise ServerError()
        try:
            items = self._record_items(response.json())
        except (ValueError, TypeError) as exc:
            raise MaimaiDataFormatError() from exc
        return [self._play_info_default(item) for item in items]

    # Compatibility wrappers retain existing consumers' call signatures while
    # routing every protected request through OAuth-only endpoints.
    async def query_user_plate(self, qqid: int, version: list, username: Optional[str] = None) -> list:
        subject = self.oauth_subject(qqid=qqid, username=username)
        records = await self.query_player_plate(subject, version)
        if username is None:
            await self.remember_oauth_authorization(str(qqid))
        return records

    async def query_user_post_dev(self, qqid: int, music_id: str) -> Optional[list]:
        subject = self.oauth_subject(qqid=qqid)
        records = await self.query_player_record(subject, music_id)
        await self.remember_oauth_authorization(str(qqid))
        return records

    async def query_user_get_dev(self, qqid: Optional[int] = None, username: Optional[str] = None) -> Any:
        subject = self.oauth_subject(qqid=qqid, username=username)
        raw = await self.query_player_records(subject)
        if qqid is not None and username is None:
            await self.remember_oauth_authorization(str(qqid))
        if isinstance(raw, list):
            return list(raw)
        return [
            _chart_info(item, source="diving-fish", default_type="standard")
            for item in self._record_items(raw)
        ]

    async def rating_ranking(self) -> list:
        """获取水鱼公开 Rating 排名数据"""
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.get(f"{FISH_BASE}/rating_ranking")
        if res.status_code == 200:
            return res.json()
        return []

    async def get_songs(self, name: str) -> Optional[list]:
        """
        通过水鱼 API 查询曲目标签（别名搜索）
        """
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.get(f"{FISH_BASE}/side_api/alias")
            if res.status_code == 200:
                alias_dict = res.json()
                matched = []
                for song_id, aliases in alias_dict.items():
                    if any(name.lower() == a.lower() for a in aliases):
                        from .maimaidx_model import Alias
                        matched.append(Alias(SongID=int(song_id), Name="", Alias=aliases))
                return matched if matched else None
        except Exception as e:
            log.warning(f"获取别名数据失败: {e}")
        return None

    async def qqlogo(self, qqid: int) -> bytes:
        """通过 QQ 头像 CDN 获取用户头像。"""
        url = f"https://q1.qlogo.cn/g?b=qq&nk={qqid}&s=640"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content

# ==========================================
# 官方 Bot 判断 & Markdown 键盘构建工具
# ==========================================

def is_official_bot(bot_self_id: str) -> bool:
    """判断当前 Bot 是否为官方机器人（支持 Markdown+按钮）"""
    if maiconfig.use_markdown:
        return True
    return str(bot_self_id) in maiconfig.official_bot_ids


def build_markdown_keyboard(rows_config: list) -> dict:
    """
    构建 Gensokyo 兼容的 Markdown 键盘按钮。
    
    rows_config 格式:
    [
        [{"label": "按钮1", "data": "指令1"}, {"label": "按钮2", "data": "指令2"}],
        [{"label": "跳转", "data": "https://...", "type": 0}],
    ]
    
    每个按钮字段:
    - label: 显示文字 (必填)
    - data: 指令文本或跳转URL (必填)
    - type: 2=指令 (默认), 0=跳转
    - style: 1=蓝色 (默认), 0=灰色, 2=绿色
    - enter: True=点击直接发送指令 (默认False)
    - reply: True=带引用回复 (仅type=2)
    - specify_user_ids: True=仅当前用户可点击
    """
    rows = []
    for row_btns in rows_config:
        buttons = []
        for btn in row_btns:
            b = {
                "render_data": {
                    "label": btn.get("label", "按钮"),
                    "style": btn.get("style", 1),
                },
                "action": {
                    "type": btn.get("type", 2),
                    "data": btn.get("data", ""),
                    "permission": {"type": 2},
                },
            }
            # visited_label
            if "visited_label" in btn:
                b["render_data"]["visited_label"] = btn["visited_label"]
            # 指令按钮专属
            if b["action"]["type"] == 2:
                b["action"]["enter"] = btn.get("enter", False)
                b["action"]["reply"] = btn.get("reply", False)
            # 权限控制
            if btn.get("specify_user_ids") is True:
                b["action"]["permission"]["type"] = 0
                b["action"]["permission"]["specify_user_ids"] = ["__USER_ID__"]
            # ID
            b["id"] = btn.get("id", f"btn_{abs(hash(b['render_data']['label'])) & 0xffff}")
            buttons.append(b)
        rows.append({"buttons": buttons})
    return {"content": {"rows": rows}}


maiApi = MaiApi()
