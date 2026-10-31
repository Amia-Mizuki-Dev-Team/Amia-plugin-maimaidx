import asyncio
import contextlib
import json
import os
import random
import tempfile
import httpx
import aiofiles
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional
from loguru import logger as log
from ..config import maiconfig, static, music_file, coverdir, guess_file, music_db_path
from .lib_music_db import music_db_cache, download_all_covers, _download_one_cover, _LXNS_HEADERS
from .maimaidx_api_data import maiApi
from .image import music_picture
from .maimaidx_alias_sync import alias_values, fetch_yuzu_aliases

class Music(dict):
    """支持递归属性访问的 dict 子类，嵌套 dict 和列表中的 dict 也可通过属性访问"""
    def __getattr__(self, item):
        val = self.get(item)
        if isinstance(val, dict):
            return Music(val)
        if isinstance(val, list):
            return [Music(v) if isinstance(v, dict) else v for v in val]
        return val
    def __setattr__(self, key, value):
        self[key] = value

class MusicList(list):
    def by_id(self, music_id: str) -> Optional[Music]:
        for music in self:
            if str(music.id) == str(music_id):
                return music
        return None

    def by_title(self, title: str) -> Optional[Music]:
        for music in self:
            if music.title == title:
                return music
        return None

    def by_id_list(self, music_ids: List[str]) -> "MusicList":
        ids = {str(music_id) for music_id in music_ids}
        return MusicList(music for music in self if str(music.id) in ids)

    def by_plan(self, level: str) -> "MusicList":
        return self.filter(level=level)

    def random(self) -> Optional[Music]:
        return random.choice(self) if self else None

    def filter(
        self,
        *,
        title_search: Optional[str] = None,
        level: Optional[str] = None,
        ds: Optional[float | tuple[float, float]] = None,
        bpm: Optional[int | tuple[int, int]] = None,
        artist_search: Optional[str] = None,
        charter_search: Optional[str] = None,
        genre: Optional[str] = None,
        version: Optional[str | List[str]] = None,
        type: Optional[str] = None,
    ) -> "MusicList":
        """Compatibility filter for the commands inherited from maimaidx."""

        def in_range(value: float, condition: float | tuple[float, float]) -> bool:
            low, high = condition if isinstance(condition, tuple) else (condition, condition)
            return low <= value <= high

        result = MusicList()
        for music in self:
            basic_info = music.get("basic_info", {}) or {}
            title = str(music.get("title", ""))
            if title_search and title_search.casefold() not in title.casefold():
                continue
            if level is not None and str(level) not in {str(item) for item in music.get("level", [])}:
                continue
            if ds is not None:
                values = music.get("ds", []) or []
                if not any(in_range(float(value), ds) for value in values):
                    continue
            if bpm is not None:
                value = basic_info.get("bpm", music.get("bpm"))
                try:
                    if value is None or not in_range(float(value), bpm):
                        continue
                except (TypeError, ValueError):
                    continue
            if artist_search:
                artist = str(basic_info.get("artist", music.get("artist", "")))
                if artist_search.casefold() not in artist.casefold():
                    continue
            if charter_search:
                charters = [str(chart.get("charter", "")) for chart in music.get("charts", []) or []]
                if not any(charter_search.casefold() in charter.casefold() for charter in charters):
                    continue
            if genre and str(basic_info.get("genre", music.get("genre", ""))) != str(genre):
                continue
            if version is not None:
                versions = version if isinstance(version, list) else [version]
                music_version = str(basic_info.get("from", music.get("version", "")))
                if music_version not in {str(item) for item in versions}:
                    continue
            if type and str(music.get("type", "")).upper() != str(type).upper():
                continue
            result.append(music)
        return result


async def _atomic_write_text(path: Path, text: str) -> None:
    """先写同目录临时文件再 ``os.replace`` 原子落盘。

    直接覆盖写一旦中途失败（进程退出、磁盘写满）就会留下半截 JSON，
    下次启动回退缓存时解析失败；``os.replace`` 在 NTFS 上是原子替换。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    os.close(fd)
    try:
        async with aiofiles.open(tmp_name, "w", encoding="utf-8") as f:
            await f.write(text)
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


_UTAGE_TYPE_ALIASES = {"utage", "宴会场", "宴会場"}
_DX_TYPE_ALIASES = {"dx", "deluxe"}


def _classify_lxns_chart_type(
    key: Any, item: Dict[str, Any], song: Dict[str, Any]
) -> str:
    """判定单张谱面的类型，返回 ``standard`` / ``DX`` / ``utage``。

    条目自带的 ``type`` 最可信，其次外层 key，最后才是歌曲级别的 ``type``。
    """
    raw = str(item.get("type") or key or song.get("type") or "").strip().lower()
    if raw in _UTAGE_TYPE_ALIASES:
        return "utage"
    if raw in _DX_TYPE_ALIASES:
        return "DX"
    return "standard"


def _lxns_chart_entries(song: Dict[str, Any]) -> List[tuple[str, Dict[str, Any]]]:
    """展平 ``difficulties`` 为 (谱面类型, 谱面) 列表，保持上游顺序。"""
    raw_difficulties = song.get("difficulties") or {}
    entries: List[tuple[str, Dict[str, Any]]] = []
    if isinstance(raw_difficulties, dict):
        for key, value in raw_difficulties.items():
            items = value if isinstance(value, list) else [value]
            entries.extend(
                (_classify_lxns_chart_type(key, item, song), item)
                for item in items
                if isinstance(item, dict)
            )
    elif isinstance(raw_difficulties, list):
        entries.extend(
            (_classify_lxns_chart_type(None, item, song), item)
            for item in raw_difficulties
            if isinstance(item, dict)
        )
    return entries


def _normalize_lxns_song(
    song: Dict[str, Any], *, chart_type: Optional[str] = None
) -> Optional[Music]:
    """Convert the public LXNS song shape to the Fish-compatible shape.

    The command modules consume ``level``/``ds``/``charts`` and
    ``basic_info``.  Keeping this conversion at the provider boundary lets
    either public source work when the other one is unavailable.

    ``difficulties`` has two shapes upstream: the older flat list, and the
    current ``{"standard": [...], "dx": [...]}`` mapping returned by
    ``song/list``.  Each chart carries its own ``type`` in the mapping shape;
    that field wins over the enclosing key when present.

    ``chart_type`` 强制按某一谱种归一化（``"standard"`` / ``"DX"``）：混合歌
    靠它稳定产出 SD、DX 两条条目，不依赖歌曲 ``type`` 字段或 JSON 键序。
    宴会场（utage）谱面返回 ``None``：它的字段形态（notes 为 dict、level 形如
    ``"12?"``、ds 恒为 0）与 SD/DX 不同，混进曲库会直接抛异常。
    """
    entries = _lxns_chart_entries(song)

    # 宴会场与 SD/DX 不是同一命名空间。歌曲级别声明 utage 时整首跳过；
    # 谱面级别的 utage 只丢弃那部分，同曲的 SD/DX 照常处理。
    if str(song.get("type") or "").strip().lower() in _UTAGE_TYPE_ALIASES:
        return None
    non_utage = [entry for entry in entries if entry[0] != "utage"]
    if entries and not non_utage:
        return None
    entries = non_utage

    def difficulty_order(entry: tuple[str, Dict[str, Any]]) -> int:
        try:
            return int(entry[1].get("difficulty"))
        except (TypeError, ValueError):
            return len(entries)

    # dict 展平后 SD/DX 各自有序，但两类交错；按 difficulty 索引重排，
    # 让 level/ds/charts 的下标始终是 0=Basic … 4=Re:Master。
    entries.sort(key=difficulty_order)

    # 单一 type 字段无法表达 SD/DX 双谱种：调用方显式指定优先（混合歌靠它
    # 稳定产出 SD/DX 两条），否则按 has_standard 优先——同一 id 同时有 SD 与
    # DX 时基础条目固定是 SD，不随 difficulties 的键序漂移；再否则才看歌曲
    # 声明，最后取首张（difficulty 最小）谱面的类型。
    requested = str(chart_type or "").strip().lower()
    raw_type = str(song.get("type") or "").strip().lower()
    has_standard = any(entry[0] == "standard" for entry in entries)
    has_dx = any(entry[0] == "DX" for entry in entries)
    if requested in _DX_TYPE_ALIASES:
        music_type = "DX"
    elif requested in {"standard", "sd"}:
        music_type = "standard"
    elif has_standard:
        music_type = "standard"
    elif has_dx:
        music_type = "DX"
    elif raw_type in _DX_TYPE_ALIASES:
        music_type = "DX"
    elif entries:
        music_type = entries[0][0]
    else:
        music_type = "standard"

    # 排序只解决顺序、不解决归属：同一 id 的 SD/DX 两套谱面会互相顶替
    # 下标（id=70 的 Master 位会显示 DX 定数），所以确定 music_type 后
    # 必须先按它裁剪。未显式指定时裁剪后为空说明上游 type 与谱面矛盾，
    # 保留原样以免整首歌丢谱；显式指定却无对应谱面时宁可不产出条目，
    # 也不能拿另一谱面的定数顶替这个 id。
    selected = [entry for entry in entries if entry[0] == music_type]
    if selected:
        entries = selected
    elif chart_type is not None:
        return None

    levels = []
    ds_values = []
    charts = []
    for _, difficulty in entries:
        levels.append(str(difficulty.get("level", "?")))
        # level_value 可能缺失、为 null 或为字符串；统一成 float 才能和
        # total_level_data 的定数分桶键（str(float)）对得上。
        try:
            level_value = float(difficulty.get("level_value") or 0)
        except (TypeError, ValueError):
            level_value = 0.0
        ds_values.append(level_value)
        charts.append(
            {
                "notes": difficulty.get("notes") or [],
                "charter": difficulty.get("note_designer", ""),
            }
        )

    # DX 条目在水鱼/成绩体系里是 id+10000，保留原 id 会让封面、B50 记录对不上。
    # ``0 < id < 10000`` 的守卫消掉两类误伤：宴会场（>= 100000）会被改写成不存在的
    # 十万级 id；本来就是偏移命名的 id（>= 10000）再加一次会撞到别的歌。
    song_id = song.get("id")
    if music_type == "DX":
        numeric_id = str(song_id if song_id is not None else "").strip()
        if numeric_id.isdigit() and 0 < int(numeric_id) < 10000:
            song_id = str(int(numeric_id) + 10000)

    return Music(
        {
            "id": song_id,
            "title": song.get("title", ""),
            "type": music_type,
            "ds": ds_values,
            "level": levels,
            "charts": charts,
            "basic_info": {
                "artist": song.get("artist", ""),
                "genre": song.get("genre", ""),
                "bpm": song.get("bpm", 0),
                "from": song.get("version", ""),
                "is_new": False,
            },
        }
    )


def _merge_song_sources(
    lxns_music: List[Dict[str, Any]], fish_music: List[Dict[str, Any]]
) -> Dict[str, Music]:
    """合流两源曲库，键一律是**归一化后**的 id。

    水鱼本身就是「SD、DX 各一条记录」的命名空间，所以先入表；落雪条目用
    ``setdefault`` 补缺，于是「是否已存在」只看归一化后的键——水鱼只给了
    SD 1001 时，落雪混合歌的 DX 11001 仍然要写进去（旧实现按落雪原始 id
    跳过，DX 条目会整条丢失）。

    混合歌（同一 id 同时有 SD 与 DX 谱面）必须产出两条：先 SD 后 DX 的顺序
    写死，基础条目由 ``has_standard`` 决定，不看歌曲 ``type`` 也不看 JSON 键序。
    """
    combined: Dict[str, Music] = {}
    for m in fish_music:
        if isinstance(m, dict) and "id" in m:
            combined[str(m["id"])] = Music(m)

    for m in lxns_music:
        if not isinstance(m, dict) or "id" not in m:
            continue
        chart_types = {entry[0] for entry in _lxns_chart_entries(m)}
        mixed = {"standard", "DX"} <= chart_types
        music = _normalize_lxns_song(m, chart_type="standard" if mixed else None)
        if music is not None:
            combined.setdefault(str(music.id), music)
        if mixed:
            dx_music = _normalize_lxns_song(m, chart_type="DX")
            if dx_music is not None:
                combined.setdefault(str(dx_music.id), dx_music)
    return combined


class MaiMusic:
    def __init__(self) -> None:
        self.total_list: MusicList = MusicList()
        self.total_alias_list: Dict[str, List[str]] = {}
        self.guess_data: List[Music] = []

    # ==========================================
    # 动态生成按定数等级分类的歌曲字典，兼容定数表调用
    # ==========================================
    @property
    def total_level_data(self) -> Dict[str, Dict[str, MusicList]]:
        """按定数等级分组：{等级: {定数值: MusicList}}
        每组内为单谱面条目，每个条目有 id, ds, lv(难度索引), type, title"""
        res: Dict[str, Dict[str, MusicList]] = {}
        for music in self.total_list:
            for idx, lv in enumerate(music.get('level', [])):
                if lv not in res:
                    res[lv] = {}
                ds = str(music.ds[idx]) if idx < len(music.ds) else '0'
                if ds not in res[lv]:
                    res[lv][ds] = MusicList()
                # 构建单谱面条目，包含 lv 难度索引
                entry = Music({
                    'id': music.id,
                    'title': music.title,
                    'type': music.type,
                    'ds': music.ds[idx] if idx < len(music.ds) else 0,
                    'lv': str(idx),
                })
                if entry not in res[lv][ds]:
                    res[lv][ds].append(entry)
        return res

    async def get_music(self) -> bool:
        log.info("开始拉取双数据源进行强同步合流...")
        lxns_music: List[Dict] = []
        fish_music: List[Dict] = []
        lxns_aliases: Dict[str, List[str]] = {}
        fish_aliases: Dict[str, List[str]] = {}
        yuzu_aliases: Dict[str, List[str]] = {}

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                # LXNS 的曲目列表是公共 API；Token 只作为可选请求头，不能
                # 因为未配置 Token 就跳过这个数据源。
                headers = {"Authorization": maiconfig.lxnstoken} if maiconfig.lxnstoken else {}
                res = await client.get("https://maimai.lxns.net/api/v0/maimai/song/list", headers=headers)
                if res.status_code == 200:
                    res_json = res.json()
                    if isinstance(res_json, dict):
                        lxns_music = res_json.get("songs") or res_json.get("data") or []
                    elif isinstance(res_json, list):
                        lxns_music = res_json
            except Exception as e:
                log.error(f"同步拉取落雪数据源发生异常: {e}")

            # 落雪别名端点是公共 API，无需 token，始终拉取
            try:
                res = await client.get("https://maimai.lxns.net/api/v0/maimai/alias/list")
                if res.status_code == 200:
                    alias_data = res.json()
                    aliases_list = alias_data.get("aliases", []) if isinstance(alias_data, dict) else alias_data
                    for entry in aliases_list:
                        if isinstance(entry, dict) and 'song_id' in entry:
                            sid = str(entry['song_id'])
                            lxns_aliases[sid] = entry.get('aliases', [])
            except Exception as e:
                log.error(f"拉取落雪别名数据源发生异常: {e}")

            # 落雪同样为空时「仅使用落雪数据（落雪 0 首）」的措辞会自相矛盾，
            # 按落雪条数切换文案；控制流不变。
            lxns_note = (
                f"本次仅使用落雪数据（落雪 {len(lxns_music)} 首）"
                if lxns_music
                else "落雪 0 首、水鱼 0 条，稍后将回退本地缓存"
            )
            try:
                res = await client.get("https://www.diving-fish.com/api/maimaidxprober/music_data")
                if res.status_code != 200:
                    log.warning(
                        f"水鱼曲库请求失败：status_code={res.status_code}，"
                        f"类型/条数不可用，{lxns_note}"
                    )
                else:
                    res_json = res.json()
                    if not isinstance(res_json, list):
                        log.warning(
                            f"水鱼曲库返回格式异常：类型={type(res_json).__name__}（期望 list），"
                            f"{lxns_note}"
                        )
                    elif not res_json:
                        log.warning(
                            "水鱼曲库返回空列表：条数=0，"
                            f"{lxns_note}"
                        )
                    else:
                        fish_music = res_json

                alias_res = await client.get("https://www.diving-fish.com/api/maimaidxprober/side_api/alias")
                if alias_res.status_code == 200:
                    alias_json = alias_res.json()
                    fish_aliases = alias_json if isinstance(alias_json, dict) else {}
            except Exception as e:
                log.error(f"同步拉取水鱼数据源发生异常: {e}")

            # The upstream plugin's alias database is maintained by Yuzu and
            # contains user-reviewed aliases that are not guaranteed to exist
            # in either public score-data endpoint.  Merge it as a third alias
            # source while keeping LXNS/Fish as the score-data sources.
            yuzu_aliases = await fetch_yuzu_aliases(
                client,
                proxy=bool(
                    getattr(maiconfig, "maimaidx_alias_proxy", False)
                    or getattr(maiconfig, "maimaidxaliasproxy", False)
                ),
            )
            if yuzu_aliases:
                log.info(f"已拉取柚子别名数据，共 {len(yuzu_aliases)} 条")
            else:
                log.warning("柚子公共别名库暂时不可用，将保留本地、落雪和水鱼别名")

        local_alias_file = static / "common" / "music_alias.json"
        if not fish_music and not lxns_music:
            log.error("双路数据源全部同步失败！正在回退本地历史缓存资产。")
            try:
                async with aiofiles.open(music_file, "r", encoding="utf-8") as f:
                    cached_music = json.loads(await f.read())
                if not isinstance(cached_music, list):
                    raise ValueError("本地歌曲缓存格式错误")
                self.total_list = MusicList(
                    Music(item) for item in cached_music if isinstance(item, dict)
                )
                self.guess_data = [
                    music for music in self.total_list
                    if music.get("id") is not None and music.get("title")
                ]

                async with aiofiles.open(local_alias_file, "r", encoding="utf-8") as f:
                    cached_aliases = json.loads(await f.read())
                self.total_alias_list = {
                    str(item.get("SongID")): [
                        str(alias).strip().lower()
                        for alias in item.get("Alias", [])
                        if str(alias).strip()
                    ]
                    for item in cached_aliases
                    if isinstance(item, dict) and item.get("SongID") is not None
                }
                log.warning(
                    f"已回退本地歌曲/别名缓存：歌曲 {len(self.total_list)} 首，"
                    f"别名记录 {len(self.total_alias_list)} 条"
                )
            except Exception as e:
                log.error(f"本地歌曲缓存回退失败：{e}")
            return False

        combined_music = _merge_song_sources(lxns_music, fish_music)

        self.total_list = MusicList(combined_music.values())
        self.total_alias_list = {}
        self.guess_data = [
            music for music in self.total_list
            if music.get("id") is not None and music.get("title")
        ]

        all_sids = (
            set(lxns_aliases.keys())
            | set(fish_aliases.keys())
            | set(yuzu_aliases.keys())
            | set(combined_music.keys())
        )
        for sid in all_sids:
            numeric_sid = int(sid) if sid.isdigit() else None
            related_ids = {sid}
            if numeric_sid is not None and numeric_sid >= 10000:
                related_ids.add(str(numeric_sid - 10000))
            lx_list = [
                alias
                for related_sid in related_ids
                for alias in alias_values(lxns_aliases.get(related_sid, []))
            ]
            fi_list = alias_values(fish_aliases.get(sid, []))
            yu_list = [
                alias
                for related_sid in related_ids
                for alias in alias_values(yuzu_aliases.get(related_sid, []))
            ]
            
            merged_set = set()
            for alias in (lx_list + fi_list + yu_list):
                if alias:
                    merged_set.add(str(alias).strip().lower())
            
            if not merged_set and sid in combined_music:
                title = combined_music[sid].get('title')
                if title:
                    merged_set.add(title.lower())
                
            self.total_alias_list[sid] = sorted(merged_set)

        # 加载本地 music_alias.json 作为基础，再用 API 数据补充
        local_aliases_loaded = 0
        try:
            async with aiofiles.open(local_alias_file, 'r', encoding='utf-8') as f:
                content = await f.read()
            local_aliases = json.loads(content)
            for entry in local_aliases:
                sid = str(entry.get('SongID'))
                aliases = entry.get('Alias', [])
                if sid not in self.total_alias_list:
                    self.total_alias_list[sid] = []
                existing = set(self.total_alias_list[sid])
                for alias in aliases:
                    if alias:
                        existing.add(str(alias).strip().lower())
                self.total_alias_list[sid] = sorted(existing)
            local_aliases_loaded = len(local_aliases)
        except Exception:
            pass

        # 将合并后的别名持久化保存到 music_alias.json
        if self.total_alias_list:
            try:
                alias_save = [
                    {"SongID": int(sid), "Name": "", "Alias": aliases}
                    for sid, aliases in self.total_alias_list.items()
                    if aliases
                ]
                await _atomic_write_text(
                    local_alias_file,
                    json.dumps(alias_save, ensure_ascii=False, indent=2),
                )
                log.info(f'别名库已持久化保存，共 {len(alias_save)} 条记录（本地加载 {local_aliases_loaded} 条 + API 补充）')
            except Exception as e:
                log.error(f'别名库持久化保存失败: {e}')

        try:
            await _atomic_write_text(
                music_file,
                json.dumps(self.total_list, ensure_ascii=False, indent=4),
            )
        except Exception as e:
            log.error(f'音乐库持久化保存失败: {e}')

        asyncio.create_task(self.download_missing_covers())
        return True

    async def download_missing_covers(self):
        """
        基于 musicDB.json 全量同步落雪曲绘。
        
        落雪曲绘 URL: https://assets2.lxns.net/maimai/jacket/{song_id}.png
        水鱼曲绘 URL: https://www.diving-fish.com/covers/{cover_id:05d}.png
        
        song_id 体系差异:
        - 落雪: 使用原生 ID (如 8, 38, 799)
        - 水鱼: DX 谱面 ID = 落雪 ID + 10000 (如 10008, 10038)
        
        曲绘文件统一以 落雪原生 song_id.png 命名存储在 coverdir 中。
        当查询水鱼 ID (10008) 时, music_picture() 会回退查找 10008-10000=8.png。
        """
        # 优先用 musicDB.json 作为权威来源下载全量曲绘
        if music_db_path.exists():
            await music_db_cache.load(music_db_path)
            count = await download_all_covers(coverdir, maiconfig.lxnstoken, concurrency=5)
            log.info(f"musicDB 全量曲绘同步完成，下载 {count} 张")
        else:
            # 降级：从 total_list 逐一下载（使用水鱼 API）
            log.warning("musicDB.json 不存在，降级使用水鱼 API 下载曲绘")
            from ..libraries.image import is_valid_image, _corrupted_cover_ids
            from .lib_music_db import _download_one_cover_fish, _cover_file_ok
            import shutil
            processed = 0
            # 先构建 原始ID → [原始ID] 映射（下载器内部再做归一化）
            id_map = {}
            for music in self.total_list:
                raw_id = int(music.get('id', 0))
                sid = str(raw_id)
                # 归一化交给 _download_one_cover_fish → fish_cover_id()：
                # 10000..99999 减 10000、宴会场 >=100000 原样。这里必须传原始 ID，
                # % 10000 会把不同宴会场曲目压到同一张图上。
                id_map.setdefault(raw_id, []).append(sid)
            for download_id, original_ids in id_map.items():
                # 跳过已知损坏的
                tmp_path = coverdir / f'__tmp_{download_id}.png'
                tmp_save = f'__tmp_{download_id}'
                if _download_one_cover_fish(download_id, tmp_save, coverdir):
                    for oid in original_ids:
                        dst = coverdir / f'{oid}.png'
                        # 体积过阈值 ≠ 健康：占位图也是合法 PNG 且 >5KB，必须过
                        # _cover_file_ok（魔数 + 占位签名黑名单）才允许跳过重下。
                        if not dst.exists() or dst.stat().st_size < 5000 or not _cover_file_ok(dst):
                            shutil.copy2(tmp_path, dst)
                    processed += 1
                tmp_path.unlink(missing_ok=True)

mai = MaiMusic()

async def update_daily():
    log.info("触发每日凌晨定时双源强同步合流任务...")
    await mai.get_music()

async def update_local_alias(*args, **kwargs):
    song_id = str(args[0]) if args else str(kwargs.get("song_id", ""))
    alias_name = str(args[1]).strip() if len(args) > 1 else str(kwargs.get("alias_name", "")).strip()
    if not song_id or not alias_name:
        return False

    local_alias_file = static / "common" / "music_alias.json"
    local_alias_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with aiofiles.open(local_alias_file, "r", encoding="utf-8") as f:
            entries = json.loads(await f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []

    entry = next((item for item in entries if str(item.get("SongID")) == song_id), None)
    if entry is None:
        entry = {"SongID": int(song_id), "Name": "", "Alias": []}
        entries.append(entry)
    aliases = entry.setdefault("Alias", [])
    if alias_name.lower() not in {str(item).lower() for item in aliases}:
        aliases.append(alias_name)
    current = mai.total_alias_list.setdefault(song_id, [])
    if alias_name.lower() not in {str(item).lower() for item in current}:
        current.append(alias_name.lower())

    async with aiofiles.open(local_alias_file, "w", encoding="utf-8") as f:
        await f.write(json.dumps(entries, ensure_ascii=False, indent=2))
    log.info(f"本地别名已保存：song_id={song_id}")
    return True

@dataclass
class GuessGame:
    music: Music
    answer: set[str]
    options: List[str]
    img: Any
    pic: bool = False
    end: bool = False


class Guess:
    Group: Dict[str, GuessGame] = {}

    def __init__(self) -> None:
        self.disabled: set[str] = set()
        if guess_file.exists():
            for line in guess_file.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line.startswith("disabled:"):
                    self.disabled.add(line.removeprefix("disabled:"))

        class _Switch:
            enable: set[str] = set()

        self.switch = _Switch()

    def _persist(self) -> None:
        guess_file.parent.mkdir(parents=True, exist_ok=True)
        guess_file.write_text(
            "\n".join(f"disabled:{gid}" for gid in sorted(self.disabled)),
            encoding="utf-8",
        )

    def is_enabled(self, gid: str | int) -> bool:
        return str(gid) not in self.disabled

    def _pick_music(self) -> Optional[Music]:
        candidates = mai.guess_data or mai.total_list
        candidates = [music for music in candidates if music.get("id") and music.get("title")]
        return random.choice(candidates) if candidates else None

    def _build_game(self, music: Music, *, pic: bool = False) -> GuessGame:
        basic = music.get("basic_info", {}) or {}
        aliases = mai.total_alias_list.get(str(music.get("id")), [])
        answer = {str(music.get("id")), str(music.get("title", "")).lower()}
        answer.update(str(alias).lower() for alias in aliases if alias)
        levels = "、".join(str(item) for item in music.get("level", [])[:5]) or "未知"
        options = [
            f"曲面类型：{music.get('type', '未知')}",
            f"曲师：{basic.get('artist', music.get('artist', '未知'))}",
            f"分类：{basic.get('genre', music.get('genre', '未知'))}",
            f"BPM：{basic.get('bpm', music.get('bpm', '未知'))}",
            f"收录版本：{basic.get('from', music.get('version', '未知'))}",
            f"难度：{levels}",
        ]
        return GuessGame(
            music=music,
            answer=answer,
            options=options,
            img=music_picture(music.get("id")),
            pic=pic,
        )

    def start(self, gid: str | int, music: Any = None, cycle: int = 0, pic: bool = False):
        selected = music or self._pick_music()
        if selected is None:
            return False
        self.Group[str(gid)] = self._build_game(selected, pic=pic)
        return True

    def startpic(self, gid: str | int):
        return self.start(gid, pic=True)

    def end(self, gid: str):
        self.Group.pop(str(gid), None)

    async def on(self, gid: str | int) -> str:
        self.disabled.discard(str(gid))
        self._persist()
        return "已开启本群猜歌功能"

    async def off(self, gid: str | int) -> str:
        self.end(str(gid))
        self.disabled.add(str(gid))
        self._persist()
        return "已关闭本群猜歌功能"

guess = Guess()
