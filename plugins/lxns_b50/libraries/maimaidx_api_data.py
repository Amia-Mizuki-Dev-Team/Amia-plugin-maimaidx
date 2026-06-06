import httpx
from typing import List, Optional, Any
from loguru import logger as log
from ..config import maiconfig

# 内存路由字典，用于动态切置默认查分端
user_source_route = {}

# ==========================================
# 落雪 / 水鱼 API 共享常量
# ==========================================
LXNS_BASE = "https://maimai.lxns.net/api/v0"
FISH_BASE = "https://www.diving-fish.com/api/maimaidxprober"


class MaiApi:
    def __init__(self):
        self.headers = {}
        self.token: Optional[str] = maiconfig.maimaidxtoken or None

    def load_token_proxy(self):
        """生命周期钩子：加载落雪开发者凭证"""
        if maiconfig.lxnstoken:
            self.headers = {"Authorization": maiconfig.lxnstoken}
            log.info("落雪开放平台 API 凭证加载成功。")

    # ==========================================
    # 落雪 API 方法
    # ==========================================

    async def _get_db_bind_status(self, qqid: int) -> dict:
        """从 maimai_sync 数据库查询用户绑定状态（不自行创建，单纯使用其远程库与本地库）"""
        status = {}
        try:
            from maimai_sync.lib_db import get_user_bind_async
            binds = await get_user_bind_async(str(qqid))
            if binds:
                status["db_fish"] = bool(binds.get("fish"))
                status["db_lxns"] = bool(binds.get("lxns"))
                status["db_user_type"] = binds.get("Type")
        except Exception:
            pass
        return status

    async def check_bind_status(self, qqid: int) -> dict:
        """
        检测指定 QQ 账户在落雪和水鱼平台的绑定注册状态。
        优先远程 API 实时查询，远程失败时回退 maimai_sync 数据库。
        """
        status = {"lxns": False, "diving_fish": False}
        
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
        if not status["lxns"] or not status["diving_fish"]:
            try:
                db_status = await self._get_db_bind_status(qqid)
                if db_status.get("db_lxns") and not status["lxns"]:
                    status["lxns"] = True
                if db_status.get("db_fish") and not status["diving_fish"]:
                    status["diving_fish"] = True
            except Exception:
                pass
        
        return status

    async def get_lxns_rating_curves(self, qqid: int) -> list:
        """获取落雪平台玩家的历史 Rating 变动轨迹数据"""
        if not maiconfig.lxnstoken:
            return []
        try:
            # 先通过 QQ 获取 friend_code
            async with httpx.AsyncClient(timeout=15) as client:
                profile_res = await client.get(
                    f"{LXNS_BASE}/maimai/player/qq/{qqid}",
                    headers=self.headers
                )
            if profile_res.status_code != 200:
                return []
            pdata = profile_res.json().get("data", {})
            friend_code = pdata.get("friend_code")
            if not friend_code:
                return []

            # 用 friend_code 查询 rating 趋势
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.get(
                    f"{LXNS_BASE}/maimai/player/{friend_code}/trend",
                    headers=self.headers
                )
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return data.get("data", data.get("trend", []))
            return []
        except Exception as e:
            log.error(f"拉取落雪 Rating 变动历史记录失败: {e}")
            return []

    async def query_user_song_score(self, qqid: int, music_id: str) -> "Optional[List[ChartInfo]]":
        """
        使用落雪 API 查询玩家单曲成绩（所有难度）。

        Params:
            `qqid`: 用户QQ
            `music_id`: 曲目ID
        Returns:
            `Optional[List[ChartInfo]]`
        """
        from .maimaidx_model import ChartInfo
        if not maiconfig.lxnstoken:
            return None
        try:
            # 先通过 QQ 获取 friend_code
            async with httpx.AsyncClient(timeout=15) as client:
                profile_res = await client.get(
                    f"{LXNS_BASE}/maimai/player/qq/{qqid}",
                    headers=self.headers
                )
            if profile_res.status_code != 200:
                return None
            pdata = profile_res.json().get("data", {})
            friend_code = pdata.get("friend_code")
            if not friend_code:
                return None

            # 查询单曲所有谱面成绩
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.get(
                    f"{LXNS_BASE}/maimai/player/{friend_code}/bests",
                    params={"song_id": int(music_id)},
                    headers=self.headers
                )
            if res.status_code != 200:
                return None
            scores = res.json()
            if isinstance(scores, dict):
                scores = scores.get("data", scores)
            if not isinstance(scores, list):
                return None

            result = []
            for s in scores:
                result.append(ChartInfo(
                    song_id=s.get("id", 0),
                    title=s.get("song_name", ""),
                    level_index=s.get("level_index", 0),
                    level=s.get("level", ""),
                    achievements=s.get("achievements", 0),
                    dxScore=s.get("dx_score", 0),
                    rate=s.get("rate", ""),
                    fc=s.get("fc") or "",
                    fs=s.get("fs") or "",
                    type=s.get("type", "standard"),
                    level_label="",
                    ds=0,
                    ra=int(s.get("dx_rating", 0))
                ))
            return result
        except Exception as e:
            log.warning(f"落雪单曲成绩查询失败(qqid={qqid}, music_id={music_id}): {e}")
            return None

    async def query_user_b50(self, qqid: Optional[int] = None, username: Optional[str] = None, is_ap: bool = False) -> Any:
        """
        获取用户 Best 50 数据。
        优先使用落雪 API（通过 QQ 查询），回退到水鱼 API（通过 username 或 QQ 查询）。
        """
        from .maimaidx_model import UserInfo, Data, ChartInfo

        # 策略一：落雪 API（需要 lxnstoken）
        if maiconfig.lxnstoken and qqid:
            try:
                profile = {}
                # 先通过 QQ 获取 friend_code 和资料（用于头像框渲染）
                async with httpx.AsyncClient(timeout=15) as client:
                    profile_res = await client.get(
                        f"{LXNS_BASE}/maimai/player/qq/{qqid}",
                        headers=self.headers
                    )
                if profile_res.status_code == 200:
                    pdata = profile_res.json().get("data", {})
                    friend_code = pdata.get("friend_code")
                    profile = pdata
                else:
                    friend_code = None

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
                        sd_list.append(ChartInfo(
                            song_id=c.get("id", 0), title=c.get("song_name", ""),
                            level_index=c.get("level_index", 0), level=c.get("level", ""),
                            achievements=c.get("achievements", 0), dxScore=c.get("dx_score", 0),
                            rate=c.get("rate", ""), fc=c.get("fc") or "", fs=c.get("fs") or "",
                            type=c.get("type", "standard"), level_label="",
                            ds=0, ra=int(c.get("dx_rating", 0))
                        ))
                    for c in data.get("dx", []):
                        dx_list.append(ChartInfo(
                            song_id=c.get("id", 0), title=c.get("song_name", ""),
                            level_index=c.get("level_index", 0), level=c.get("level", ""),
                            achievements=c.get("achievements", 0), dxScore=c.get("dx_score", 0),
                            rate=c.get("rate", ""), fc=c.get("fc") or "", fs=c.get("fs") or "",
                            type=c.get("type", "dx"), level_label="",
                            ds=0, ra=int(c.get("dx_rating", 0))
                        ))
                    return UserInfo(
                        nickname=profile.get("name", username or str(qqid)),
                        rating=data.get("total", data.get("standard_total", 0) + data.get("dx_total", 0)),
                        additional_rating=profile.get("course_rank", 0),
                        plate=str(profile.get("name_plate", {}).get("id", "")) if profile.get("name_plate") else "",
                        username=str(profile.get("icon", {}).get("id", "")) if profile.get("icon") else "",
                        charts=Data(sd=sd_list[:35], dx=dx_list[:15])
                    )
            except Exception as e:
                log.warning(f"落雪 B50 查询失败(qqid={qqid})，将回退水鱼: {e}")

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
            res = await client.post(f"{FISH_BASE}/query/player", json=body)
        if res.status_code == 200:
            raw = res.json()
            sd_list = []
            dx_list = []
            for c in raw.get("charts", {}).get("sd", []):
                sd_list.append(ChartInfo(**c))
            for c in raw.get("charts", {}).get("dx", []):
                dx_list.append(ChartInfo(**c))
            return UserInfo(
                nickname=raw.get("nickname", username or str(qqid)),
                rating=raw.get("rating", 0),
                additional_rating=raw.get("additional_rating", 0),
                plate=raw.get("plate", ""),
                username=raw.get("username", ""),
                charts=Data(sd=sd_list, dx=dx_list)
            )
        elif res.status_code == 400:
            from .maimaidx_error import UserNotFoundError
            raise UserNotFoundError()
        elif res.status_code == 403:
            from .maimaidx_error import UserDisabledQueryError
            raise UserDisabledQueryError()
        else:
            from .maimaidx_error import UnknownError
            raise UnknownError()

    async def query_user_plate(self, qqid: int, version: list, username: Optional[str] = None) -> list:
        """
        按版本获取用户的成绩信息（水鱼 query/plate）
        """
        body = {"qq": str(qqid), "version": version}
        if username:
            body = {"username": username, "version": version}
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(f"{FISH_BASE}/query/plate", json=body)
        if res.status_code == 200:
            raw_list = res.json()
            from .maimaidx_model import PlayInfoDefault
            result = []
            for item in raw_list:
                result.append(PlayInfoDefault(**item))
            return result
        elif res.status_code == 400:
            from .maimaidx_error import UserNotFoundError
            raise UserNotFoundError()
        elif res.status_code == 403:
            from .maimaidx_error import UserDisabledQueryError
            raise UserDisabledQueryError()
        return []

    async def query_user_post_dev(self, qqid: int, music_id: str) -> Optional[list]:
        """
        使用水鱼 Developer-Token 查询用户单曲成绩（POST /dev/player/record）
        """
        if not self.token:
            return None
        headers = {"Developer-Token": self.token}
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                f"{FISH_BASE}/dev/player/record",
                headers=headers,
                json={"qq": str(qqid), "music_id": int(music_id)}
            )
        if res.status_code == 200:
            raw_list = res.json()
            from .maimaidx_model import PlayInfoDev
            return [PlayInfoDev(**item) for item in raw_list] if isinstance(raw_list, list) else []
        return []

    async def query_user_get_dev(self, qqid: Optional[int] = None, username: Optional[str] = None) -> Any:
        """
        使用水鱼 Developer-Token 获取用户完整成绩（GET /dev/player/records）
        """
        if not self.token:
            from .maimaidx_error import TokenNotFoundError
            raise TokenNotFoundError()
        headers = {"Developer-Token": self.token}
        params = {}
        if qqid:
            params["qq"] = str(qqid)
        elif username:
            params["username"] = username
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.get(f"{FISH_BASE}/dev/player/records", headers=headers, params=params)
        if res.status_code == 200:
            return res.json()
        elif res.status_code == 400:
            from .maimaidx_error import UserNotFoundError
            raise UserNotFoundError()
        return None

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

# ==========================================
# 官方 Bot 判断 & Markdown 键盘构建工具
# ==========================================

    async def qqlogo(self, qqid: int) -> bytes:
        """通过 QQ 头像 CDN 获取用户头像"""
        url = f"https://q1.qlogo.cn/g?b=qq&nk={qqid}&s=640"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content


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


    async def qqlogo(self, qqid: int) -> bytes:
        """获取 QQ 头像"""
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"https://q1.qlogo.cn/g?b=qq&nk={qqid}&s=100")
        return res.content


maiApi = MaiApi()
