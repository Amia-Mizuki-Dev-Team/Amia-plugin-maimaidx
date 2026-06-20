import asyncio
import json
import httpx
import aiofiles
import random
from PIL import Image
from typing import Dict, Any, List, Optional
from loguru import logger as log
from ..config import maiconfig, static, music_file, coverdir, guess_file, music_db_path
from .lib_music_db import music_db_cache, download_all_covers, _download_one_cover, _LXNS_HEADERS
from .maimaidx_api_data import maiApi

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

    async def get_music(self) -> None:
        log.info("开始拉取双数据源进行强同步合流...")
        lxns_music: List[Dict] = []
        fish_music: List[Dict] = []
        lxns_aliases: Dict[str, List[str]] = {}
        fish_aliases: Dict[str, List[str]] = {}

        async with httpx.AsyncClient(timeout=30) as client:
            if maiconfig.lxnstoken:
                try:
                    headers = {"Authorization": maiconfig.lxnstoken}
                    res = await client.get("https://maimai.lxns.net/api/v0/maimai/song/list", headers=headers)
                    if res.status_code == 200:
                        res_json = res.json()
                        if isinstance(res_json, dict) and "data" in res_json:
                            lxns_music = res_json["data"]
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

        if not fish_music and not lxns_music:
            log.error("双路数据源全部同步失败！正在紧急维持本地历史缓存资产。")
            return

        combined_music = {}
        for m in fish_music:
            if isinstance(m, dict) and 'id' in m:
                combined_music[str(m['id'])] = Music(m)
                
        for m in lxns_music:
            if isinstance(m, dict) and 'id' in m:
                sid = str(m['id'])
                if sid not in combined_music:
                    combined_music[sid] = Music(m)

        self.total_list = MusicList(combined_music.values())

        all_sids = set(lxns_aliases.keys()) | set(fish_aliases.keys()) | set(combined_music.keys())
        for sid in all_sids:
            lx_list = lxns_aliases.get(sid, [])
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
        local_alias_file = static / 'common' / 'music_alias.json'
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

    def guess(self) -> None:
        """从本地歌曲列表中挑选含有有效本地曲绘且 ID < 100000 的歌曲加载至 guess_data"""
        self.guess_data = []
        from .image import music_picture
        for music in self.total_list:
            try:
                music_id = int(music.id)
            except Exception:
                continue
            if music_id >= 100000:
                continue
            p = music_picture(music_id)
            if p.name in ('0.png', '11000.png'):
                continue
            if p.exists() and p.stat().st_size >= 5000:
                self.guess_data.append(music)

mai = MaiMusic()

async def update_daily():
    log.info("触发每日凌晨定时双源强同步合流任务...")
    await mai.get_music()

async def update_local_alias(*args, **kwargs):
    log.info("检测到老版本别名系统更新请求，已重定向至最新双源强同步通道...")
    await mai.get_music()
    return True

def slice_mp3(data: bytes, start_sec: float, duration_sec: float) -> bytes:
    """纯 Python 解析 Layer III MP3 帧结构并按时间进行切片，不依赖 ffmpeg/pydub"""
    frames = []
    i = 0
    n = len(data)
    
    # ID3v2 tag skipping
    if data.startswith(b'ID3'):
        if len(data) >= 10:
            size_bytes = data[6:10]
            tag_size = ((size_bytes[0] & 0x7F) << 21) | \
                       ((size_bytes[1] & 0x7F) << 14) | \
                       ((size_bytes[2] & 0x7F) << 7) | \
                       (size_bytes[3] & 0x7F)
            i = tag_size + 10

    bitrates_v1 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
    bitrates_v2 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
    samplerates = {
        3: [44100, 48000, 32000, 0], # MPEG V1
        2: [22050, 24000, 16000, 0], # MPEG V2
        0: [11025, 12000, 8000, 0],  # MPEG V2.5
    }
    
    while i < n - 4:
        # Frame sync: 11 bits (header[0] == 0xFF and (header[1] & 0xE0) == 0xE0)
        if data[i] == 0xFF and (data[i+1] & 0xE0) == 0xE0:
            h = data[i:i+4]
            version = (h[1] >> 3) & 3
            layer = (h[1] >> 1) & 3
            if layer != 1:  # Not Layer III
                i += 1
                continue
                
            bitrate_idx = (h[2] >> 4) & 15
            sr_idx = (h[2] >> 2) & 3
            padding = (h[2] >> 1) & 1
            
            if version == 3:
                br = bitrates_v1[bitrate_idx] * 1000
            elif version in (0, 2):
                br = bitrates_v2[bitrate_idx] * 1000
            else:
                i += 1
                continue
                
            v_rates = samplerates.get(version)
            if not v_rates or sr_idx >= 3 or br == 0:
                i += 1
                continue
            sr = v_rates[sr_idx]
            
            # Frame size for Layer III
            frame_size = 144 * br // sr + padding
            if frame_size <= 4:
                i += 1
                continue
                
            samples = 1152 if version == 3 else 576
            duration = samples / sr
            
            frames.append((i, frame_size, duration))
            i += frame_size
        else:
            i += 1
            
    if not frames:
        return data
        
    current_time = 0.0
    selected_frames = []
    end_sec = start_sec + duration_sec
    
    for start_offset, size, dur in frames:
        if current_time >= start_sec and current_time < end_sec:
            selected_frames.append(data[start_offset:start_offset+size])
        current_time += dur
        if current_time >= end_sec:
            break
            
    if not selected_frames:
        return data[:int(len(data) * 0.2)]
        
    return b"".join(selected_frames)


class GuessGame:
    def __init__(self, music: Any, img: str, answer: List[str], options: List[str] = None):
        self.music = music
        self.img = img
        self.answer = answer
        self.options = options or []
        self.end = False


class GuessSwitch:
    def __init__(self, parent: "Guess"):
        self.parent = parent
    @property
    def enable(self) -> List[int]:
        return self.parent.config


class Guess:
    def __init__(self) -> None:
        self.Group: Dict[int, GuessGame] = {}
        self.switch = GuessSwitch(self)
        if guess_file.exists():
            try:
                with open(guess_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        enable_list = data.get("enable", [])
                    else:
                        enable_list = data
                    self.config = [int(x) for x in enable_list]
            except Exception:
                self.config = []
        else:
            self.config = []

    def save_config(self):
        try:
            guess_file.parent.mkdir(parents=True, exist_ok=True)
            with open(guess_file, 'w', encoding='utf-8') as f:
                json.dump({"enable": self.config}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f"保存猜歌开关配置失败: {e}")

    async def on(self, gid: int) -> str:
        gid = int(gid)
        if gid not in self.config:
            self.config.append(gid)
            self.save_config()
        return "已开启该群猜歌功能"

    async def off(self, gid: int) -> str:
        gid = int(gid)
        if gid in self.config:
            self.config.remove(gid)
            self.save_config()
        return "已关闭该群猜歌功能"

    def start(self, gid: int):
        gid = int(gid)
        if not mai.guess_data:
            mai.guess()
        if not mai.guess_data:
            raise ValueError("曲库中没有有效的猜歌候选歌曲")
        music = random.choice(mai.guess_data)
        
        answers = {str(music.id), music.title.lower()}
        aliases = mai.total_alias_list.get(str(music.id), [])
        for alias in aliases:
            if alias:
                answers.add(alias.lower())
        
        from .image import music_picture, image_to_base64
        p = music_picture(music.id)
        img_b64 = ""
        try:
            with Image.open(p) as img:
                img = img.convert('RGBA')
                width, height = img.size
                crop_w = random.randint(70, min(120, width))
                crop_h = random.randint(70, min(120, height))
                x = random.randint(0, width - crop_w)
                y = random.randint(0, height - crop_h)
                cropped = img.crop((x, y, x + crop_w, y + crop_h))
                img_b64 = image_to_base64(cropped)
        except Exception as e:
            log.warning(f"裁剪图片 {p} 失败: {e}")
        
        basic_info = music.get('basic_info', {})
        genre = basic_info.get('genre', '未知')
        bpm = basic_info.get('bpm', '未知')
        version = basic_info.get('from', '未知')
        levels = music.get('level', [])
        music_type = music.get('type', '未知')
        artist = basic_info.get('artist', '未知')
        
        clues = [
            f"的分类是 {genre}",
            f"的BPM是 {bpm}",
            f"的首发版本是 {version}",
            f"的所有难度等级为 {', '.join(levels)}",
            f"的谱面类型是 {music_type}",
            f"的曲师是 {artist}"
        ]
        random.shuffle(clues)
        
        self.Group[gid] = GuessGame(music, img_b64, list(answers), clues)

    def startpic(self, gid: int):
        gid = int(gid)
        if not mai.guess_data:
            mai.guess()
        if not mai.guess_data:
            raise ValueError("曲库中没有有效的猜图候选歌曲")
        music = random.choice(mai.guess_data)
        
        answers = {str(music.id), music.title.lower()}
        aliases = mai.total_alias_list.get(str(music.id), [])
        for alias in aliases:
            if alias:
                answers.add(alias.lower())
        
        from .image import music_picture, image_to_base64
        p = music_picture(music.id)
        img_b64 = ""
        try:
            with Image.open(p) as img:
                img = img.convert('RGBA')
                width, height = img.size
                crop_w = random.randint(70, min(120, width))
                crop_h = random.randint(70, min(120, height))
                x = random.randint(0, width - crop_w)
                y = random.randint(0, height - crop_h)
                cropped = img.crop((x, y, x + crop_w, y + crop_h))
                img_b64 = image_to_base64(cropped)
        except Exception as e:
            log.warning(f"裁剪图片 {p} 失败: {e}")
        
        self.Group[gid] = GuessGame(music, img_b64, list(answers))

    def end(self, gid: int):
        gid = int(gid)
        if gid in self.Group:
            del self.Group[gid]

    async def start_voice(self, gid: int) -> bytes:
        gid = int(gid)
        if not mai.guess_data:
            mai.guess()
        if not mai.guess_data:
            raise ValueError("曲库中没有有效的听歌猜歌候选歌曲")
        music = random.choice(mai.guess_data)
        
        answers = {str(music.id), music.title.lower()}
        aliases = mai.total_alias_list.get(str(music.id), [])
        for alias in aliases:
            if alias:
                answers.add(alias.lower())
                
        native_id = int(music.id) % 10000 if int(music.id) < 100000 else int(music.id) % 100000
        url = f"https://assets2.lxns.net/maimai/music/{native_id}.mp3"
        
        from .safe_requests import SafeRequests as cffi_requests
        sliced_audio = None
        headers = {}
        if maiconfig.lxnstoken:
            headers["Authorization"] = maiconfig.lxnstoken
            
        try:
            async with cffi_requests.AsyncSession(impersonate="chrome110") as session:
                res = await session.get(url, headers=headers, timeout=15)
                if res.status_code == 200:
                    audio_data = res.content
                    sliced_audio = slice_mp3(audio_data, start_sec=random.randint(10, 45), duration_sec=10.0)
                else:
                    log.error(f"Failed to fetch audio for {music.id} from {url}, status code {res.status_code}")
        except Exception as e:
            log.error(f"curl_cffi download failed for audio {music.id}: {e}")
                
        if not sliced_audio:
            raise ValueError("无法获取或切片音频资源")
            
        self.Group[gid] = GuessGame(music, "", list(answers))
        return sliced_audio

    def start_alias(self, gid: int) -> str:
        gid = int(gid)
        if not mai.guess_data:
            mai.guess()
            
        candidates = []
        for music in mai.guess_data:
            aliases = mai.total_alias_list.get(str(music.id), [])
            filtered_aliases = [a for a in aliases if a.strip().lower() != music.title.lower()]
            if len(filtered_aliases) >= 2:
                candidates.append((music, filtered_aliases))
                
        if not candidates:
            for music in mai.guess_data:
                aliases = mai.total_alias_list.get(str(music.id), [])
                filtered_aliases = [a for a in aliases if a.strip().lower() != music.title.lower()]
                if len(filtered_aliases) >= 1:
                    candidates.append((music, filtered_aliases))
                    
        if not candidates:
            raise ValueError("别名库中没有足够的候选歌曲")
            
        music, filtered_aliases = random.choice(candidates)
        chosen_alias = random.choice(filtered_aliases)
        
        answers = {str(music.id), music.title.lower()}
        aliases = mai.total_alias_list.get(str(music.id), [])
        for alias in aliases:
            if alias:
                answers.add(alias.lower())
                
        self.Group[gid] = GuessGame(music, "", list(answers))
        return chosen_alias

guess = Guess()
