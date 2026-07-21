import asyncio
import json
import random
import httpx
import aiofiles
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from loguru import logger as log
from ..config import maiconfig, static, music_file, coverdir, guess_file, music_db_path
from .lib_music_db import music_db_cache, download_all_covers, _download_one_cover, _LXNS_HEADERS
from .maimaidx_api_data import maiApi
from .image import music_picture

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


def _normalize_lxns_song(song: Dict[str, Any]) -> Music:
    """Convert the public LXNS song shape to the Fish-compatible shape.

    The command modules consume ``level``/``ds``/``charts`` and
    ``basic_info``.  Keeping this conversion at the provider boundary lets
    either public source work when the other one is unavailable.
    """
    difficulties = song.get("difficulties") or []
    levels = []
    ds_values = []
    charts = []
    for difficulty in difficulties:
        if not isinstance(difficulty, dict):
            continue
        levels.append(str(difficulty.get("level", "?")))
        ds_values.append(difficulty.get("level_value", 0))
        charts.append(
            {
                "notes": difficulty.get("notes") or [],
                "charter": difficulty.get("note_designer", ""),
            }
        )

    raw_type = str(song.get("type", "")).lower()
    music_type = "DX" if raw_type in {"dx", "deluxe"} else "standard"
    return Music(
        {
            "id": song.get("id"),
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

            try:
                res = await client.get("https://www.diving-fish.com/api/maimaidxprober/music_data")
                if res.status_code == 200:
                    res_json = res.json()
                    fish_music = res_json if isinstance(res_json, list) else []
                
                alias_res = await client.get("https://www.diving-fish.com/api/maimaidxprober/side_api/alias")
                if alias_res.status_code == 200:
                    alias_json = alias_res.json()
                    fish_aliases = alias_json if isinstance(alias_json, dict) else {}
            except Exception as e:
                log.error(f"同步拉取水鱼数据源发生异常: {e}")

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

        combined_music = {}
        for m in fish_music:
            if isinstance(m, dict) and 'id' in m:
                combined_music[str(m['id'])] = Music(m)
                
        for m in lxns_music:
            if isinstance(m, dict) and 'id' in m:
                sid = str(m['id'])
                if sid not in combined_music:
                    combined_music[sid] = _normalize_lxns_song(m)

        self.total_list = MusicList(combined_music.values())
        self.total_alias_list = {}
        self.guess_data = [
            music for music in self.total_list
            if music.get("id") is not None and music.get("title")
        ]

        all_sids = set(lxns_aliases.keys()) | set(fish_aliases.keys()) | set(combined_music.keys())
        for sid in all_sids:
            numeric_sid = int(sid) if sid.isdigit() else None
            related_lxns_ids = {sid}
            if numeric_sid is not None and numeric_sid >= 10000:
                related_lxns_ids.add(str(numeric_sid - 10000))
            lx_list = [
                alias
                for related_sid in related_lxns_ids
                for alias in lxns_aliases.get(related_sid, [])
            ]
            fi_list = fish_aliases.get(sid, [])
            
            merged_set = set()
            for alias in (lx_list + fi_list):
                if alias:
                    merged_set.add(str(alias).strip().lower())
            
            if not merged_set and sid in combined_music:
                title = combined_music[sid].get('title')
                if title:
                    merged_set.add(title.lower())
                
            self.total_alias_list[sid] = list(merged_set)

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
                self.total_alias_list[sid] = list(existing)
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
                async with aiofiles.open(local_alias_file, 'w', encoding='utf-8') as f:
                    await f.write(json.dumps(alias_save, ensure_ascii=False, indent=2))
                log.info(f'别名库已持久化保存，共 {len(alias_save)} 条记录（本地加载 {local_aliases_loaded} 条 + API 补充）')
            except Exception as e:
                log.warning(f'别名库持久化保存失败: {e}')

        try:
            async with aiofiles.open(music_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(self.total_list, ensure_ascii=False, indent=4))
        except Exception:
            pass

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
            from .lib_music_db import _download_one_cover_fish
            import shutil
            processed = 0
            # 先构建 download_id → [原始ID] 映射
            id_map = {}
            for music in self.total_list:
                raw_id = int(music.get('id', 0))
                sid = str(raw_id)
                # 落雪文档：所有 >= 10000 的 ID 统一 % 10000，宴会场也不例外
                if raw_id >= 10000:
                    did = raw_id % 10000
                else:
                    did = raw_id
                if did not in id_map:
                    id_map[did] = []
                id_map[did].append(sid)
            for download_id, original_ids in id_map.items():
                # 跳过已知损坏的
                tmp_path = coverdir / f'__tmp_{download_id}.png'
                tmp_save = f'__tmp_{download_id}'
                if _download_one_cover_fish(download_id, tmp_save, coverdir):
                    for oid in original_ids:
                        dst = coverdir / f'{oid}.png'
                        if not dst.exists() or dst.stat().st_size < 5000:
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
