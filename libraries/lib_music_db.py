# lib_music_db.py - 集成曲目数据处理与更新管理器（基于时间文件的同步逻辑）
# 由 lib_musicDB.py 适配集成到本项目的版本

import json
import asyncio
import aiofiles
from curl_cffi import requests as cffi_requests
from typing import Optional, Dict, Any, List
from pathlib import Path
from loguru import logger as log

# ==========================================
# 版本常量表（与 config.py 的 plate_to_dx_version 保持一致的双备份）
# ==========================================
VERSIONS = [
    {"id": 0, "title": "maimai", "name1": "", "version": 10000, "name2": "舞"},
    {"id": 1, "title": "maimai PLUS", "name1": "真", "version": 11000, "name2": "舞"},
    {"id": 2, "title": "GreeN", "name1": "超", "version": 12000, "name2": "舞"},
    {"id": 3, "title": "GreeN PLUS", "name1": "檄", "version": 13000, "name2": "舞"},
    {"id": 4, "title": "ORANGE", "name1": "橙", "version": 14000, "name2": "舞"},
    {"id": 5, "title": "ORANGE PLUS", "name1": "曉", "version": 15000, "name2": "舞"},
    {"id": 6, "title": "PiNK", "name1": "桃", "version": 16000, "name2": "舞"},
    {"id": 7, "title": "PiNK PLUS", "name1": "櫻", "version": 17000, "name2": "舞"},
    {"id": 8, "title": "MURASAKi", "name1": "紫", "version": 18000, "name2": "舞"},
    {"id": 9, "title": "MURASAKi PLUS", "name1": "堇", "version": 18500, "name2": "舞"},
    {"id": 10, "title": "MiLK", "name1": "白", "version": 19000, "name2": "舞"},
    {"id": 11, "title": "MiLK PLUS", "name1": "雪", "version": 19500, "name2": "舞"},
    {"id": 12, "title": "FiNALE", "name1": "輝", "version": 19900, "name2": "舞"},
    {"id": 13, "title": "舞萌DX", "name1": "熊", "version": 20000},
    {"id": 15, "title": "舞萌DX 2021", "name1": "爽", "version": 21000},
    {"id": 17, "title": "舞萌DX 2022", "name1": "宙", "version": 22000},
    {"id": 19, "title": "舞萌DX 2023", "name1": "祭", "version": 23000},
    {"id": 21, "title": "舞萌DX 2024", "name1": "双", "version": 24000},
    {"id": 23, "title": "舞萌DX 2025", "name1": "镜", "version": 25000},
]

LXNS_BASE = "https://maimai.lxns.net"
LXNS_ASSETS = "https://assets2.lxns.net/maimai"
FISH_COVERS = "https://www.diving-fish.com/covers"


def get_version_title(version_num: int) -> str:
    """根据版本号获取版本标题"""
    for i, ver in enumerate(VERSIONS):
        start = ver["version"]
        end = VERSIONS[i+1]["version"] if i+1 < len(VERSIONS) else float('inf')
        if start <= version_num < end:
            return ver['title']
    return "未知版本"


# ==========================================
# musicDB.json 异步缓存管理器（单例）
# musicDB.json 结构: {"lxns_song_id": {"name": "...", "version": int}, ...}
# 键 = 落雪原始 song_id（如 "8"），或 SD/DX 分离后的 ID（如 "10008" 表示 DX 谱面）
# ==========================================

class MusicDBCache:
    """musicDB.json 的异步缓存管理器，保证并发安全"""
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache: Dict[str, dict] = {}
            cls._instance._loaded = False
        return cls._instance

    async def load(self, db_path: Path, force: bool = False):
        async with self._lock:
            if self._loaded and not force:
                return
            if not db_path.exists():
                log.debug(f"musicDB.json 不存在 ({db_path})，将在同步后自动生成")
                self._cache = {}
                self._loaded = True
                return
            try:
                async with aiofiles.open(db_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    self._cache = json.loads(content)
                self._loaded = True
                log.info(f"已加载 {len(self._cache)} 首歌曲到 musicDB 缓存")
            except Exception as e:
                log.error(f"加载 musicDB.json 失败: {e}")
                self._cache = {}
                self._loaded = False

    async def get(self, music_id: str) -> Optional[dict]:
        if not self._loaded:
            return None
        async with self._lock:
            return self._cache.get(str(music_id))

    async def get_all_ids(self) -> List[str]:
        """获取所有落雪 song_id 列表（用于全量下载曲绘）"""
        if not self._loaded:
            return []
        async with self._lock:
            return list(self._cache.keys())

    async def reload(self, db_path: Path):
        await self.load(db_path, force=True)


music_db_cache = MusicDBCache()


# ==========================================
# musicDB.json 生成器
# 从落雪 API 返回的曲目列表中提取 song_id → {name, version} 映射
# 每次双源同步后自动更新，确保曲绘下载使用最新权威列表
# ==========================================

async def generate_music_db(lxns_music_list: list, save_path: Path) -> None:
    """
    从落雪 API 曲目列表生成 musicDB.json。

    musicDB.json 结构:
    {"lxns_song_id": {"name": "曲名", "version": 版本号_int}, ...}

    Args:
        lxns_music_list: 落雪 /song/list 接口返回的曲目列表
        save_path: musicDB.json 的保存路径
    """
    if not lxns_music_list:
        log.warning("落雪曲目列表为空，跳过 musicDB.json 生成")
        return

    music_db = {}
    for song in lxns_music_list:
        if isinstance(song, dict) and 'id' in song:
            sid = str(song['id'])
            music_db[sid] = {
                "name": song.get('title', ''),
                "version": song.get('version', 0)
            }

    save_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(save_path, 'w', encoding='utf-8') as f:
        await f.write(json.dumps(music_db, ensure_ascii=False, indent=2))

    log.info(f"已生成 musicDB.json ({len(music_db)} 首歌曲) → {save_path}")


# ==========================================
# 曲绘下载管理器（严格遵循 LX.py 方式：同步 + 单线程 + 无并发）
# ==========================================

def _download_one_cover(download_id: int, save_id: str, cover_dir: Path, headers: dict) -> bool:
    """
    下载单张曲绘并保存为原始 ID 文件名。

    Args:
        download_id: 用于拼接下载 URL（已取模后的 ID）
        save_id:     用于保存文件名（musicDB.json 中的原始键名）
        cover_dir:   曲绘保存目录
        headers:     请求头

    Returns: True=成功, False=失败
    """
    cover_path = cover_dir / f'{save_id}.png'
    url = f"https://assets2.lxns.net/maimai/jacket/{download_id}.png"

    # 已有有效文件则跳过
    if cover_path.exists() and cover_path.stat().st_size > 5000:
        from .image import is_valid_image
        try:
            if is_valid_image(cover_path.read_bytes()[:16]):
                return True
        except:
            pass

    try:
        resp = cffi_requests.get(url, headers=headers, impersonate="edge131")
    except Exception:
        try:
            resp = cffi_requests.get(url, headers=headers, impersonate="edge101")
        except Exception as e:
            log.warning(f"下载曲绘 {save_id}({download_id}) 失败: {e}")
            return False

    try:
        resp.raise_for_status()
        with open(cover_path, 'wb') as f:
            f.write(resp.content)
        log.info(f"曲绘 {save_id}.png({download_id}) 下载成功")
        return True
    except Exception as e:
        log.warning(f"下载曲绘 {save_id}({download_id}) 失败: {e}")
        return False


_LXNS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://maimai.lxns.net/",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "same-site",
    "DNT": "1",
}


_COVER_SYNC_MARKER = '.cover_sync_done'


async def _is_cover_synced(cover_dir: Path, all_ids: list) -> bool:
    """检查曲绘是否已全量下载完毕（本地固化标记 + 文件数量校验）"""
    marker = cover_dir / _COVER_SYNC_MARKER
    if not marker.exists():
        return False
    try:
        expected = int(marker.read_text().strip())
        actual = len(list(cover_dir.glob('*.png')))
        if actual >= expected:
            return True
    except (ValueError, OSError):
        pass
    return False


async def download_all_covers(
    cover_dir: Path,
    lxns_token: str = "",
    concurrency: int = 1,
    force_redownload: bool = False
) -> int:
    """
    基于 musicDB.json 全量下载落雪曲绘到 cover_dir。
    已同步过的目录会跳过（通过 .cover_sync_done 标记文件固化）。
    
    下载时 URL 使用取模后的 download_id，保存文件时使用 musicDB.json 中的原始键名。
    """
    all_ids = await music_db_cache.get_all_ids()
    if not all_ids:
        log.warning("musicDB 缓存为空，无法下载曲绘")
        return 0

    # 本地固化检查：已同步过则跳过
    if not force_redownload and await _is_cover_synced(cover_dir, all_ids):
        log.info(f"曲绘已全量同步，跳过下载（{cover_dir}）")
        return 0

    # 构建映射：download_id → [original_id, ...]
    # 同一 download_id 只需下载一次，再复制给所有原始 ID
    # 落雪文档：所有 >= 10000 的 ID 统一 % 10000，宴会场也不例外
    #   44     → 下载 /44.png,   保存 44.png    （原生 ID）
    #   10044  → 下载 /44.png,   保存 10044.png（水鱼 DX = 落雪 SD + 10000）
    #   110114 → 下载 /114.png,  保存 110114.png（宴会场）
    # 保存文件名保持原始 ID，music_picture() 查找时能命中
    import shutil
    id_map: Dict[int, List[str]] = {}
    for sid in all_ids:
        num_id = int(sid)
        did = num_id % 10000
        if did not in id_map:
            id_map[did] = []
        id_map[did].append(sid)

    log.info(f"开始顺序下载曲绘（{len(id_map)} 个唯一图片，共 {len(all_ids)} 个文件名）...")
    downloaded = 0

    for download_id, original_ids in id_map.items():
        # 先下载到临时文件名
        tmp_path = cover_dir / f'__tmp_{download_id}.png'
        tmp_save_id = f'__tmp_{download_id}'
        if _download_one_cover(download_id, tmp_save_id, cover_dir, _LXNS_HEADERS):
            # 下载成功，复制给所有原始 ID
            for oid in original_ids:
                dst = cover_dir / f'{oid}.png'
                if not dst.exists() or dst.stat().st_size < 5000:
                    shutil.copy2(tmp_path, dst)
            downloaded += 1
        # 清理临时文件
        tmp_path.unlink(missing_ok=True)

    # 写入本地固化标记
    try:
        (cover_dir / _COVER_SYNC_MARKER).write_text(str(len(all_ids)))
    except OSError:
        pass

    log.info(f"曲绘全量同步完成，新增下载 {downloaded} 张（共需 {len(all_ids)} 个文件）")
    return downloaded


# ==========================================
# 水鱼曲绘 URL 构建（5 位补零）
# ==========================================

def get_fish_cover_url(song_id: int) -> str:
    """
    构建水鱼曲绘 URL。
    
    水鱼文档要求：ID 不足 5 位数需要前面补 0。
    对于 ID 在 10001~11000 范围内的 DX 谱面，需要减去 10000。
    
    Args:
        song_id: 落雪风格的 song_id（如 8, 38, 799）
    
    Returns:
        完整的水鱼曲绘 URL
    """
    # 水鱼文档特殊处理：ID 区间 10001~11000 的曲目，请求其 ID - 10000
    cover_id = song_id
    if 10001 <= song_id <= 11000:
        cover_id = song_id - 10000
    return f"{FISH_COVERS}/{cover_id:05d}.png"


def _download_one_cover_fish(download_id: int, save_id: str, cover_dir: Path) -> bool:
    """
    使用水鱼 API 下载单张曲绘。
    水鱼封面 URL: https://www.diving-fish.com/covers/{id:05d}.png
    ID 区间 10001~11000 需先减 10000 再 5 位补零。
    """
    cover_path = cover_dir / f'{save_id}.png'
    
    # 已有有效文件则跳过
    if cover_path.exists() and cover_path.stat().st_size > 5000:
        from .image import is_valid_image
        try:
            if is_valid_image(cover_path.read_bytes()[:16]):
                return True
        except:
            pass
    
    url = get_fish_cover_url(download_id)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    try:
        resp = cffi_requests.get(url, headers=headers, impersonate="edge131")
    except Exception:
        try:
            resp = cffi_requests.get(url, headers=headers, impersonate="edge101")
        except Exception as e:
            log.warning(f"水鱼曲绘 {save_id}({download_id}) 下载失败: {e}")
            return False
    
    try:
        resp.raise_for_status()
        with open(cover_path, 'wb') as f:
            f.write(resp.content)
        log.info(f"水鱼曲绘 {save_id}.png({download_id}) 下载成功")
        return True
    except Exception as e:
        log.warning(f"水鱼曲绘 {save_id}({download_id}) 下载失败: {e}")
        return False


def lxns_id_to_fish_id(lxns_id: int) -> int:
    """落雪 song_id → 水鱼 song_id（DX 谱面 +10000，SD 谱面不变）"""
    return lxns_id + 10000


def fish_id_to_lxns_id(fish_id: int) -> int:
    """水鱼 song_id → 落雪 song_id（减去 10000 还原）"""
    if fish_id > 10000:
        return fish_id - 10000
    return fish_id
