# lib_music_db.py - 集成曲目数据处理与更新管理器（基于时间文件的同步逻辑）
# 由 lib_musicDB.py 适配集成到本项目的版本

import json
import asyncio
import os
import tempfile
import aiofiles
import anyio
from curl_cffi import requests as cffi_requests
from typing import Awaitable, Callable, Iterable, Optional, Dict, Any, List, Union
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
#
# musicDB.json 结构 —— **写入方是 Mizuki-plugin-Maimai-sync 的
# lib_musicDB.convert_to_music_db**（本插件只读，勿在本插件内改写）：
#   双命名空间、谱面级存储：
#     原生键  "lxns_song_id"        = SD 谱面版本（≈歌曲版本）
#     +10000 键 "lxns_song_id+10000" = DX 谱面版本（水鱼命名空间）
#   {"<str(song_id)>": {"name": "...", "version": int}, ...}
#
# 消费方（含 coach 的 core/version_map.py）按**歌曲级**使用：B15/B35 版本
# 判定只查原生键/歌曲版本，+10000 键仅作 DX-only 歌曲原生键缺失时的兜底
# —— B15/B35 按歌曲版本判定，与谱面类型（DX/SD）完全无关，
# 禁止按 chart_type 分流查找（勿据旧注释「修复」回去）。
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
# 曲绘下载管理器（严格遵循 LX.py 方式：同步 + 单线程 + 无并发）
# ==========================================

# 宴会场曲目 ID 下界。这些歌在落雪资产里没有独立曲绘——``id % 10000`` 会命中
# 另一首歌的图（110114 → jacket/114.png，HTTP 200），必须走水鱼精确
# ``covers/{id}.png``。
_BANQUET_ID_BASE = 100000


def _is_banquet_id(song_id: int) -> bool:
    """是否为宴会场曲目（id >= 100000）。"""
    try:
        return int(song_id) >= _BANQUET_ID_BASE
    except (TypeError, ValueError):
        return False


def _cover_file_ok(path: Path) -> bool:
    """本地曲绘是否可直接使用（文件存在 + 魔数有效）。"""
    from .image import is_valid_image

    try:
        if not path.is_file():
            return False
        with open(path, 'rb') as f:
            return is_valid_image(f.read(16))
    except OSError:
        return False


def _atomic_write_cover(path: Path, data: bytes) -> bool:
    """临时文件 + 魔数校验 + ``os.replace`` 原子落盘。

    直接 ``open(path, 'wb')`` 在并发/中断时会把半截 PNG 留在最终路径上：PNG
    头 16 字节本来就合法，之后所有校验都会把它当健康文件。这里先写同目录临时
    文件，校验通过才原子替换——最终路径要么是旧的完整文件，要么是新的完整
    文件；任何失败都清掉临时文件。

    Returns: True=已写入有效文件, False=内容无效或落盘失败
    """
    tmp_path: Optional[Path] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f'.{path.name}.', suffix='.tmp', dir=str(path.parent)
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if not _cover_file_ok(tmp_path):
            log.warning(f"曲绘 {path.name} 内容不是有效图片（魔数校验失败），丢弃")
            return False
        os.replace(tmp_path, path)
        tmp_path = None  # 已被 replace 移走，无需清理
        return True
    except OSError as e:
        log.warning(f"曲绘 {path.name} 落盘失败: {e}")
        return False
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


def _download_one_cover(
    download_id: int, save_id: str, cover_dir: Path, headers: dict, force: bool = False
) -> bool:
    """
    下载单张曲绘并保存为原始 ID 文件名。

    Args:
        download_id: 用于拼接下载 URL（已取模后的 ID）
        save_id:     用于保存文件名（musicDB.json 中的原始键名）
        cover_dir:   曲绘保存目录
        headers:     请求头
        force:       True 时跳过「已有有效文件」早退，强制重新下载

    Returns: True=成功, False=失败
    """
    cover_path = cover_dir / f'{save_id}.png'
    url = f"https://assets2.lxns.net/maimai/jacket/{download_id}.png"

    # 已有有效文件则跳过（force 时必须绕过：否则修正命令永远下不了新图）
    if not force and cover_path.exists() and cover_path.stat().st_size > 5000:
        from .image import is_valid_image, forget_corrupted_cover
        try:
            if is_valid_image(cover_path.read_bytes()[:16]):
                forget_corrupted_cover(save_id)
                return True
        except Exception:
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
    except Exception as e:
        log.warning(f"下载曲绘 {save_id}({download_id}) 失败: {e}")
        return False

    if not _atomic_write_cover(cover_path, resp.content):
        return False
    # 下载成功即解除损坏记录：有效文件不能再被 image 层当坏文件删掉
    from .image import forget_corrupted_cover
    forget_corrupted_cover(save_id)
    log.info(f"曲绘 {save_id}.png({download_id}) 下载成功")
    return True


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

# marker 版本：v1（旧）只有文件数；v2 起带前缀。旧版用 ``id % 10000`` 下载宴会
# 场曲绘，写出的 110114.png 里其实是 jacket/114.png（另一首歌，合法 PNG），
# 魔数校验分辨不出来——只能靠 marker 版本做一次性迁移。
_COVER_MARKER_VERSION = 'v2'


def _write_cover_marker(cover_dir: Path, count: int) -> None:
    """记录同步元信息（`v2:<文件数>`；迁移判据，但不用于跳过补缺）。"""
    try:
        (cover_dir / _COVER_SYNC_MARKER).write_text(f'{_COVER_MARKER_VERSION}:{count}')
    except OSError:
        pass


def _read_cover_marker(cover_dir: Path) -> str:
    try:
        return (cover_dir / _COVER_SYNC_MARKER).read_text(encoding='utf-8').strip()
    except (OSError, UnicodeDecodeError):
        return ''


def _marker_is_current(marker: str) -> bool:
    return marker.startswith(f'{_COVER_MARKER_VERSION}:')


def _purge_banquet_covers(cover_dir: Path) -> int:
    """删除所有宴会场曲绘（id >= 100000），返回删除数量。

    旧版本用 ``% 10000`` 下载宴会场曲绘，写出的文件内容是**另一首歌**的合法
    PNG，只能整批清掉让逐键补缺按水鱼精确 id 重下。
    """
    removed = 0
    try:
        entries = list(cover_dir.iterdir())
    except OSError as e:
        log.warning(f"扫描曲绘目录失败（{cover_dir}）: {e}")
        return 0
    for path in entries:
        if path.suffix.lower() != '.png':
            continue
        try:
            sid = int(path.stem)
        except ValueError:
            continue
        if not _is_banquet_id(sid):
            continue
        try:
            path.unlink(missing_ok=True)
            removed += 1
        except OSError as e:
            log.warning(f"删除旧宴会场曲绘 {path.name} 失败: {e}")
    return removed


async def download_all_covers(
    cover_dir: Path,
    lxns_token: str = "",
    concurrency: int = 1,
    force_redownload: bool = False
) -> int:
    """
    按 musicDB.json 的曲目键**逐键**校验并补齐曲绘。

    旧实现拿 `.cover_sync_done` 里的文件数量做短路：曲库更新后目录里的文件
    数早已 >= marker，于是新增曲目永远补不上（B50 直接掉占位图）。现在 marker
    只作为附带信息写入，是否下载完全取决于「这个键对应的本地文件是否有效」。

    普通曲目的落雪资产 URL 用 ``id % 10000``（DX 键与 SD 键共用同一张图），
    宴会场（id >= 100000）落雪没有对应资产，只走水鱼精确 ``covers/{id}.png``
    —— ``% 10000`` 会把 110114 下成 jacket/114.png（另一首歌，HTTP 200）。
    保存文件名始终是 musicDB.json 中的原始键名。

    marker 版本迁移：marker 不是 ``v2:`` 时先清掉所有宴会场曲绘（旧版写脏的
    文件是合法 PNG，魔数校验救不了），本次按精确 id 重下；随后写入 ``v2:``
    标记，迁移只发生一次。``force_redownload=True`` 时忽略「已有有效文件」早退。
    """
    all_ids = await music_db_cache.get_all_ids()
    if not all_ids:
        log.warning("musicDB 缓存为空，无法下载曲绘")
        return 0

    try:
        cover_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning(f"创建曲绘目录失败（{cover_dir}）: {e}")
        return 0

    if not _marker_is_current(_read_cover_marker(cover_dir)):
        purged = _purge_banquet_covers(cover_dir)
        if purged:
            log.warning(
                f"曲绘标记为旧版本（%10000 时代），已清理 {purged} 张宴会场曲绘，"
                f"本次按水鱼精确 id 重下"
            )

    missing_ids: List[str] = []
    for sid in all_ids:
        if force_redownload or not _cover_file_ok(cover_dir / f'{sid}.png'):
            missing_ids.append(sid)

    if not missing_ids:
        log.info(f"曲绘已全部就绪（{len(all_ids)} 个曲目键），跳过下载（{cover_dir}）")
        _write_cover_marker(cover_dir, len(all_ids))
        return 0

    # 构建映射：download_id → [original_id, ...]
    # 同一 download_id 只需下载一次，再写入所有原始 ID
    # 落雪文档：非宴会场 ID 统一 % 10000
    #   44     → 下载 /44.png,   保存 44.png    （原生 ID）
    #   10044  → 下载 /44.png,   保存 10044.png（水鱼 DX = 落雪 SD + 10000）
    #   110114 → 水鱼 covers/110114.png，保存 110114.png（宴会场，禁 % 10000）
    # 保存文件名保持原始 ID，music_picture() 查找时能命中
    from .image import forget_corrupted_cover

    id_map: Dict[int, List[str]] = {}
    banquet_ids: List[int] = []
    for sid in missing_ids:
        try:
            num_id = int(sid)
        except (TypeError, ValueError):
            continue
        if _is_banquet_id(num_id):
            # 落雪没有宴会场曲绘：% 10000 下到的是另一首歌，只能走水鱼精确 id
            banquet_ids.append(num_id)
            continue
        id_map.setdefault(num_id % 10000, []).append(sid)

    log.info(
        f"曲绘缺 {len(missing_ids)}/{len(all_ids)} 个曲目键，"
        f"开始顺序补齐（{len(id_map) + len(banquet_ids)} 个唯一图片）..."
    )
    downloaded = 0

    for download_id, original_ids in id_map.items():
        # 先下载到临时文件名；成功/失败/异常都必须清掉，曲绘目录里不留 __tmp_*.png
        tmp_path = cover_dir / f'__tmp_{download_id}.png'
        tmp_save_id = f'__tmp_{download_id}'
        try:
            if not _download_one_cover(
                download_id, tmp_save_id, cover_dir, _LXNS_HEADERS, force=force_redownload
            ):
                continue
            if not _cover_file_ok(tmp_path):
                # 200 but HTML/反爬页：不能直接复制给曲目键
                log.warning(f"曲绘 {download_id} 下载内容不是有效图片，丢弃")
                continue
            try:
                data = tmp_path.read_bytes()
            except OSError as e:
                log.warning(f"曲绘临时文件 {tmp_path.name} 读取失败: {e}")
                continue
            # 下载成功，原子写入所有原始 ID
            for oid in original_ids:
                if not _atomic_write_cover(cover_dir / f'{oid}.png', data):
                    continue
                forget_corrupted_cover(oid)
            downloaded += 1
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    # 宴会场逐曲精确下载：水鱼 covers/{id}.png（_download_one_cover_fish 对
    # >= 100000 保持原 ID，自身即原子落盘 + 魔数校验）
    for num_id in banquet_ids:
        if not _download_one_cover_fish(
            num_id, str(num_id), cover_dir, force=force_redownload
        ):
            continue
        forget_corrupted_cover(num_id)
        downloaded += 1

    # 写入本地固化标记（仅附带信息）
    _write_cover_marker(cover_dir, len(all_ids))

    log.info(f"曲绘同步完成，本次补齐 {downloaded} 张唯一图片（共需 {len(all_ids)} 个文件）")
    return downloaded


# ==========================================
# 水鱼曲绘 URL 构建（5 位补零）
# ==========================================

def fish_cover_id(song_id: int) -> int:
    """曲目 ID → 水鱼 covers 目录里的图片 ID。

    水鱼 DX 谱面 ID = 落雪 ID + 10000，所以 ``10000 <= id < 100000`` 要减回
    10000（旧实现只处理 10001~11000，导致 DX id 11001..99999 拼出
    11008.png 这种不存在的地址）。
    宴会场（>= 100000）保持原 ID 语义——禁止 ``% 10000``，那会把不同宴会场
    曲目压到同一张图上。
    """
    song_id = int(song_id)
    if 10000 <= song_id < 100000:
        return song_id - 10000
    return song_id


def get_fish_cover_url(song_id: int) -> str:
    """
    构建水鱼曲绘 URL。

    水鱼文档要求：ID 不足 5 位数需要前面补 0。

    Args:
        song_id: 落雪风格的 song_id（如 8, 38, 799）或水鱼 DX ID（如 11817）

    Returns:
        完整的水鱼曲绘 URL
    """
    return f"{FISH_COVERS}/{fish_cover_id(song_id):05d}.png"


def _download_one_cover_fish(
    download_id: int, save_id: str, cover_dir: Path, force: bool = False
) -> bool:
    """
    使用水鱼 API 下载单张曲绘。
    水鱼封面 URL: https://www.diving-fish.com/covers/{id:05d}.png
    ID 归一化交给 ``fish_cover_id``：``10000 <= id < 100000`` 减 10000，
    宴会场 ``>= 100000`` 保持原 ID（不能被 ``% 10000`` 压到同一张图）。

    Args:
        force: True 时跳过「已有有效文件」早退，强制重新下载
    """
    cover_path = cover_dir / f'{save_id}.png'
    
    # 已有有效文件则跳过（force 时必须绕过：脏图魔数合法，只能靠重下覆盖）
    if not force and cover_path.exists() and cover_path.stat().st_size > 5000:
        from .image import is_valid_image, forget_corrupted_cover
        try:
            if is_valid_image(cover_path.read_bytes()[:16]):
                forget_corrupted_cover(save_id)
                return True
        except Exception:
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
    except Exception as e:
        log.warning(f"水鱼曲绘 {save_id}({download_id}) 下载失败: {e}")
        return False

    if not _atomic_write_cover(cover_path, resp.content):
        return False
    # 下载成功即解除损坏记录：有效文件不能再被 image 层当坏文件删掉
    from .image import forget_corrupted_cover
    forget_corrupted_cover(save_id)
    log.info(f"水鱼曲绘 {save_id}.png({download_id}) 下载成功")
    return True


def lxns_id_to_fish_id(lxns_id: int) -> int:
    """落雪 song_id → 水鱼 song_id（DX 谱面 +10000，SD 谱面不变）"""
    return lxns_id + 10000


def fish_id_to_lxns_id(fish_id: int) -> int:
    """水鱼 song_id → 落雪 song_id（减去 10000 还原）"""
    if fish_id > 10000:
        return fish_id - 10000
    return fish_id


# ==========================================
# 出图前按需补缺（B50 曲绘自愈）
# ==========================================

def _cover_candidates(song_id: int) -> List[str]:
    """``music_picture`` 可能为该 ID 命中的文件名候选（按查找优先级）。

    宴会场（>= 100000）只承认精确 ``{id}.png``：``music_picture`` 在
    ``{id}.png`` 缺失时会回退到 ``{id - 100000}.png``——那是**另一首歌**的
    曲绘，拿回退结果判断「有没有图」等于把别人的图当健康文件。

    普通 SD/DX 仍按 ``{id}`` / ``{id±10000}`` 的回退集合判断：DX 键 10008
    命中 8.png 是正常的，不能判成缺图反复下载。
    """
    sid = int(song_id)
    if _is_banquet_id(sid):
        return [f'{sid}.png']
    names = [f'{sid}.png']
    if 0 < sid < 10000:
        names.append(f'{sid + 10000}.png')
    elif 10000 < sid < 100000:
        names.append(f'{sid - 10000}.png')
    return names


def _cover_needs_download(song_id: int, cover_dir: Optional[Path] = None) -> bool:
    """该曲目是否没有**属于自己的**有效曲绘（需要补下）。

    只看 ``_cover_candidates`` 里是否有有效文件，不经过 ``music_picture`` 的
    回退：否则 110114 会因为 10114.png（另一首歌）存在而被判成「健康」，逐键
    补缺对宴会场形同虚设。
    """
    if cover_dir is None:
        from . import image as image_mod

        cover_dir = Path(image_mod.coverdir)
    cover_dir = Path(cover_dir)
    return not any(
        _cover_file_ok(cover_dir / name) for name in _cover_candidates(song_id)
    )


async def ensure_covers(
    song_ids: Iterable[Union[int, str]],
    cover_dir: Optional[Path] = None,
    *,
    concurrency: int = 5,
    timeout: Optional[float] = 15.0,
    downloader: Optional[Callable[[int], Awaitable[bool]]] = None,
) -> int:
    """对**落到占位图**的曲目做一次有界异步补下，返回补好的张数。

    用于 B50 绘制前：只补这张图真正要画的曲目，不触发全量同步。

    - 并发上限 ``concurrency``；总等待上限 ``timeout`` 秒（``None`` = 不限）；
    - 超时只放弃**尚未完成**的任务，已完成的结果照常保留（不能因为超时
      把已经下好的曲绘一起丢掉）；
    - 单曲 / 整体异常一律吞掉并记日志：补不到就画占位图，绝不连累出图。

    Args:
        song_ids: 曲目 ID（任意可 ``int()`` 的形式，重复自动去重）
        cover_dir: 曲绘目录，缺省取 ``music_picture`` 所在目录
        concurrency: 并发下载上限
        timeout: 总超时秒数
        downloader: 测试注入用，``async (song_id) -> bool``
    """
    from .image import forget_corrupted_cover, music_picture

    ids: List[int] = []
    for raw in song_ids:
        try:
            sid = int(raw)
        except (TypeError, ValueError):
            continue
        if sid not in ids:
            ids.append(sid)

    missing = [sid for sid in ids if _cover_needs_download(sid)]
    if not missing:
        return 0
    if cover_dir is None:
        cover_dir = music_picture(missing[0]).parent
    cover_dir = Path(cover_dir)

    async def _default_download(sid: int) -> bool:
        if _is_banquet_id(sid):
            # 宴会场：落雪资产没有这张图，% 10000 会下到另一首歌（200 也一样错），
            # 只走水鱼精确 covers/{id}.png；下载后仍由 _atomic_write_cover 校验魔数。
            ok = await anyio.to_thread.run_sync(
                _download_one_cover_fish, sid, str(sid), cover_dir
            )
        else:
            # 普通曲目：落雪资产按 %10000 取图，失败再退水鱼（内部再做 10000 回退）
            ok = await anyio.to_thread.run_sync(
                _download_one_cover, sid % 10000, str(sid), cover_dir, _LXNS_HEADERS
            )
            if not ok:
                ok = await anyio.to_thread.run_sync(
                    _download_one_cover_fish, sid, str(sid), cover_dir
                )
        if ok:
            forget_corrupted_cover(sid)
        return ok

    dl = downloader if downloader is not None else _default_download
    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def _one(sid: int) -> bool:
        async with sem:
            try:
                return bool(await dl(sid))
            except Exception as exc:  # noqa: BLE001 - 单曲失败不影响其它曲目
                log.warning(f"曲绘补下 {sid} 失败（忽略）: {exc!r}")
                return False

    tasks = [asyncio.create_task(_one(sid)) for sid in missing]
    if timeout is None:
        done, pending = await asyncio.wait(tasks)
    else:
        done, pending = await asyncio.wait(tasks, timeout=max(0.0, float(timeout)))
    if pending:
        for task in pending:
            task.cancel()
        # 等取消落地，避免任务在事件循环关闭时泄漏
        await asyncio.gather(*pending, return_exceptions=True)
        log.warning(
            f"曲绘补下超过 {timeout}s，放弃 {len(pending)} 张（已完成 {len(done)} 张保留）"
        )

    restored = 0
    for task in done:
        if task.cancelled():
            continue
        try:
            if task.result():
                restored += 1
        except Exception:  # noqa: BLE001 - 与 _one 内的吞异常保持一致
            continue
    if restored:
        log.info(f"B50 曲绘按需补下 {restored}/{len(missing)} 张")
    return restored
