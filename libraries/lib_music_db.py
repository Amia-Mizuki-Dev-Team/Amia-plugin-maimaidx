# lib_music_db.py - 集成曲目数据处理与更新管理器（基于时间文件的同步逻辑）
# 由 lib_musicDB.py 适配集成到本项目的版本

import json
import asyncio
import os
import tempfile
import time
import aiofiles
import anyio
from curl_cffi import requests as cffi_requests
from typing import Awaitable, Callable, Iterable, Optional, Dict, Any, List, Union
from pathlib import Path
from loguru import logger as log

# 运行时数据目录（`LXNS_B50_PATH` / `LXNSPATH` 可覆盖），与 image.py 同一取法：
# 插件源码树只读，任何持久化都不能写回 ``libraries/../static``。
from ..config import static

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

# 宴会场曲目 ID 下界。宴会场曲目**没有专属曲绘资产**：落雪对 6 位 id 直接 404，
# ``id % 10000`` 命中的正是父曲曲绘（实测 41/41 全部 200：110121 → jacket/121.png，
# 字节与该父曲一致；111069 → 1069.png 字节一致）。所以宴会 id 与普通 id 一样按
# ``id % 10000`` 取图——那不是「另一首歌」，也不是脏数据。
# 该下界判定仍然保留：``music_picture`` 对宴会 id 有 ``id - 100000`` 回退，判缺时
# 必须只认 ``{id}.png``（见 ``_cover_candidates``）。
_BANQUET_ID_BASE = 100000


def _is_banquet_id(song_id: int) -> bool:
    """是否为宴会场曲目（id >= 100000）。"""
    try:
        return int(song_id) >= _BANQUET_ID_BASE
    except (TypeError, ValueError):
        return False


def _cover_download_id(song_id: Union[int, str]) -> Optional[int]:
    """曲目 ID → 落雪/水鱼的图片 ID（``% 10000``）；整万位 id 返回 ``None``。

    ``10000`` / ``100000`` 这类 id 的 ``% 10000 == 0``：上游没有 ``0.png``，拼出来
    的 ``jacket/0.png`` 是那张占位 logo——状态 200 但会被占位黑名单拒收，于是
    既下不成也进不了负缓存，每次启动都重试同一张不存在的图。归一化后不是
    ``1..9999`` 的一律按「上游确实没有」处理：跳过请求、记负缓存。
    """
    try:
        did = int(song_id) % 10000
    except (TypeError, ValueError):
        return None
    return did if 0 < did < 10000 else None


def _cover_file_ok(path: Path) -> bool:
    """本地曲绘是否可直接使用（文件存在 + 魔数有效 + 未命中占位图签名黑名单）。

    占位图（滚木/蓝 maimai logo）是合法 PNG，魔数分辨不出来；命中黑名单即判
    无效，让逐键补缺 / ensure_covers 重新拉取。整文件哈希精确匹配，真封面判定
    与改动前完全一致。
    """
    from .image import is_placeholder_cover_file, is_valid_image

    try:
        if not path.is_file():
            return False
        with open(path, 'rb') as f:
            if not is_valid_image(f.read(16)):
                return False
    except OSError:
        return False
    return not is_placeholder_cover_file(path)


def _atomic_write_cover(path: Path, data: bytes) -> bool:
    """临时文件 + 魔数校验 + ``os.replace`` 原子落盘。

    直接 ``open(path, 'wb')`` 在并发/中断时会把半截 PNG 留在最终路径上：PNG
    头 16 字节本来就合法，之后所有校验都会把它当健康文件。这里先写同目录临时
    文件，校验通过才原子替换——最终路径要么是旧的完整文件，要么是新的完整
    文件；任何失败都清掉临时文件。

    Returns: True=已写入有效文件, False=内容无效（含占位图）或落盘失败
    """
    from .image import is_placeholder_bytes

    if is_placeholder_bytes(data):
        # 上游对新曲未解禁返回占位图：不落盘、不标记完成，走既有失败路径，
        # 下次逐键补缺 / ensure_covers 会重新拉取（解禁后即恢复正常）。
        log.warning(f"曲绘 {path.name} 内容是占位图（签名黑名单命中），不落盘，等待解禁重下")
        return False

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


def _set_status(status: Optional[List[str]], value: str) -> None:
    """把下载结果类别追加给调用方（'ok' / 'not_found' / 'error'）。

    只有 ``not_found``（上游确实 404）才允许写负缓存：网络抖动、反爬 200 HTML
    都不是「上游没这张图」，写进去会让曲绘被压 7 天不重试。
    """
    if status is not None:
        status.append(value)


def _download_one_cover(
    download_id: int,
    save_id: str,
    cover_dir: Path,
    headers: dict,
    force: bool = False,
    status: Optional[List[str]] = None,
) -> bool:
    """
    下载单张曲绘并保存为原始 ID 文件名。

    Args:
        download_id: 用于拼接下载 URL（已取模后的 ID）
        save_id:     用于保存文件名（musicDB.json 中的原始键名）
        cover_dir:   曲绘保存目录
        headers:     请求头
        force:       True 时跳过「已有有效文件」早退，强制重新下载
        status:      可选，收集结果类别（见 ``_set_status``）

    Returns: True=成功, False=失败
    """
    cover_path = cover_dir / f'{save_id}.png'
    # 整万位 id（10000 / 100000 …）归一化后是 0 → jacket/0.png 是占位 logo。
    # 不发请求：上游确实没有这张图，直接按 not_found 记负缓存。
    if _cover_download_id(download_id) is None:
        _set_status(status, 'not_found')
        log.debug(f"曲绘 {save_id}({download_id}) 归一化后为 0，上游无此资产")
        return False
    url = f"https://assets2.lxns.net/maimai/jacket/{download_id}.png"

    # 已有有效文件则跳过（force 时必须绕过：否则修正命令永远下不了新图）
    # 用 _cover_file_ok 而非裸魔数：已缓存的占位图不能被当成「已完成」
    if not force and cover_path.exists() and cover_path.stat().st_size > 5000:
        from .image import forget_corrupted_cover
        try:
            if _cover_file_ok(cover_path):
                forget_corrupted_cover(save_id)
                _set_status(status, 'ok')
                return True
        except Exception:
            pass

    try:
        resp = cffi_requests.get(url, headers=headers, impersonate="edge131")
    except Exception:
        try:
            resp = cffi_requests.get(url, headers=headers, impersonate="edge101")
        except Exception as e:
            _set_status(status, 'error')
            log.warning(f"下载曲绘 {save_id}({download_id}) 失败: {e}")
            return False

    try:
        resp.raise_for_status()
    except Exception as e:
        if getattr(resp, 'status_code', 0) in (404, 410):
            # 上游确实没有这张图：降为 DEBUG，由调用方汇总一行 + 记负缓存
            _set_status(status, 'not_found')
            log.debug(f"曲绘 {save_id}({download_id}) 不存在: {e}")
        else:
            _set_status(status, 'error')
            log.warning(f"下载曲绘 {save_id}({download_id}) 失败: {e}")
        return False

    if not _atomic_write_cover(cover_path, resp.content):
        _set_status(status, 'error')
        return False

    # 下载成功即解除损坏记录：有效文件不能再被 image 层当坏文件删掉
    from .image import forget_corrupted_cover
    forget_corrupted_cover(save_id)
    _set_status(status, 'ok')
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

# marker 版本前缀：只表示「新格式」（``v2:<文件数>``），**不再是迁移判据**。
# 旧版曾据此外加一次「%10000 写脏」的整批清理，前提是错的——宴会 id 的
# ``%10000`` 命中的就是父曲曲绘（见 ``_BANQUET_ID_BASE`` 处说明），那样清理
# 只会把正确的图删掉再重下 404，于是每次启动「缺 N → 补 → 又缺」循环。
_COVER_MARKER_VERSION = 'v2'


def _write_cover_marker(cover_dir: Path, count: int) -> None:
    """记录同步元信息（`v2:<文件数>`）。只作附带信息，不用于跳过补缺。"""
    try:
        (cover_dir / _COVER_SYNC_MARKER).write_text(f'{_COVER_MARKER_VERSION}:{count}')
    except OSError:
        pass


# ==========================================
# 曲绘 404 负缓存（持久化，TTL 7 天）
# ==========================================

# 落雪 + 水鱼都 404 的 id 就是上游确实没有独立资产。每次启动重试只是刷屏，
# 记进负缓存后 7 天内不再发请求；过期自动重试，上游补图后能自愈。
_COVER_NEGATIVE_CACHE_TTL = 7 * 24 * 60 * 60
_COVER_NEGATIVE_CACHE_NAME = 'cover_negative_cache.json'

# 结构：{"<song_id>": <unix_timestamp>}


def _cover_negative_cache_path() -> Path:
    """负缓存落盘位置：``<config.static>/common/cover_negative_cache.json``。

    与 ``music_alias.json`` 同级（运行时静态数据目录）。必须走 ``config.static``
    ——它可被 ``LXNS_B50_PATH`` / ``LXNSPATH`` 覆盖；用 ``Path(__file__)`` 会
    绕过去、在生产首次运行时于 git 工作区里新建未跟踪的 ``static/``，插件
    目录只读时则落盘失败、7 天抑制静默失效。
    """
    return static / 'common' / _COVER_NEGATIVE_CACHE_NAME


def _negative_key(song_id: Union[int, str]) -> str:
    """整数 id 统一成 ``"851"`` 这种形式（musicDB 的键本身就是字符串）。"""
    try:
        return str(int(song_id))
    except (TypeError, ValueError):
        return str(song_id)


def _load_negative_cache(path: Optional[Path] = None) -> Dict[str, float]:
    """读取负缓存，**顺带剔除过期条目**。读不到/解析失败一律当空表。"""
    if path is None:
        path = _cover_negative_cache_path()
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    now = time.time()
    cache: Dict[str, float] = {}
    for key, stamp in raw.items():
        try:
            ts = float(stamp)
        except (TypeError, ValueError):
            continue
        if now - ts < _COVER_NEGATIVE_CACHE_TTL:
            cache[_negative_key(key)] = ts
    return cache


def _save_negative_cache(cache: Dict[str, float], path: Optional[Path] = None) -> None:
    """临时文件 + fsync + ``os.replace`` 原子落盘。

    直接覆盖写会在中断时留下半截 JSON，下一轮全量重试等于负缓存失效。
    """
    if path is None:
        path = _cover_negative_cache_path()
    path = Path(path)
    tmp_path: Optional[Path] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f'.{path.name}.', suffix='.tmp', dir=str(path.parent)
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        tmp_path = None  # 已被 replace 移走
    except OSError as e:
        # WARNING 而非 DEBUG：落盘失败意味着负缓存不生效，7 天抑制会静默失效
        log.warning(f"曲绘负缓存落盘失败（{path}），本次抑制不持久: {e}")
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


def _negative_cache_is_fresh(
    cache: Dict[str, float], song_id: Union[int, str], now: Optional[float] = None
) -> bool:
    """该 id 是否仍在负缓存窗口内（窗口内直接跳过，不发任何请求）。"""
    stamp = cache.get(_negative_key(song_id))
    if stamp is None:
        return False
    return ((time.time() if now is None else now) - stamp) < _COVER_NEGATIVE_CACHE_TTL


def _record_negative(
    song_ids: Iterable[Union[int, str]], path: Optional[Path] = None
) -> int:
    """把「双源均 404」的 id 写入负缓存（一次读-改-写），返回写入条数。"""
    keys = [_negative_key(sid) for sid in song_ids]
    if not keys:
        return 0
    cache = _load_negative_cache(path)
    now = time.time()
    for key in keys:
        cache[key] = now
    _save_negative_cache(cache, path)
    return len(keys)



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

    取图统一：**所有 id**（含宴会场 ``>= 100000``）都走落雪
    ``jacket/{id % 10000}.png``。宴会场没有专属曲绘资产，``% 10000`` 命中的正是
    它父曲的曲绘（实测 41/41 均 200），不是「另一首歌」。水鱼
    ``covers/{id}.png`` 只在落雪失败时作最后兜底。保存文件名始终是
    musicDB.json 中的原始键名。

    负缓存：落雪 + 水鱼都 404 的 id 记进 ``cover_negative_cache.json``（TTL 7
    天），窗口内直接跳过、不发请求，避免每次启动重复刷 404。
    ``force_redownload=True`` 时忽略「已有有效文件」与负缓存两处早退。
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

    missing_ids: List[str] = []
    for sid in all_ids:
        if force_redownload or not _cover_file_ok(cover_dir / f'{sid}.png'):
            missing_ids.append(sid)

    if not missing_ids:
        log.info(f"曲绘已全部就绪（{len(all_ids)} 个曲目键），跳过下载（{cover_dir}）")
        _write_cover_marker(cover_dir, len(all_ids))
        return 0

    # 负缓存过滤：窗口内「双源都没图」的 id 不再发请求
    negative = {} if force_redownload else _load_negative_cache()
    now = time.time()
    pending_ids: List[str] = []
    suppressed = 0
    for sid in missing_ids:
        if _negative_cache_is_fresh(negative, sid, now):
            suppressed += 1
            continue
        pending_ids.append(sid)

    if suppressed:
        log.info(
            f"曲绘缺 {len(missing_ids)} 个曲目键，其中 {suppressed} 个双源均无曲绘"
            f"（负缓存 7 天内），跳过请求"
        )
    if not pending_ids:
        _write_cover_marker(cover_dir, len(all_ids))
        return 0

    # 构建映射：download_id → [original_id, ...]
    # 同一 download_id 只需下载一次，再写入所有原始 ID。落雪资产统一 % 10000：
    #   44     → 下载 /44.png,   保存 44.png    （原生 ID）
    #   10044  → 下载 /44.png,   保存 10044.png（水鱼 DX = 落雪 SD + 10000）
    #   110121 → 下载 /121.png,  保存 110121.png（宴会场 = 父曲曲绘，实测 200）
    # 保存文件名保持原始 ID，music_picture() 查找时能命中
    from .image import forget_corrupted_cover

    id_map: Dict[int, List[str]] = {}
    placeholder_ids: List[str] = []
    for sid in pending_ids:
        did = _cover_download_id(sid)
        if did is None:
            # 整万位 id：% 10000 == 0，上游没有 0.png，按「确实没图」记负缓存
            placeholder_ids.append(sid)
            continue
        id_map.setdefault(did, []).append(sid)

    if placeholder_ids:
        preview = ', '.join(str(x) for x in placeholder_ids[:8])
        if len(placeholder_ids) > 8:
            preview += ' ...'
        log.info(
            f"{len(placeholder_ids)} 个曲目 id 归一化后为 0（整万位），"
            f"上游无对应曲绘，按缺失处理: {preview}"
        )

    log.info(
        f"曲绘缺 {len(pending_ids)}/{len(all_ids)} 个曲目键，"
        f"开始顺序补齐（{len(id_map)} 个唯一图片）..."
    )
    downloaded = 0
    missing_both: List[str] = list(placeholder_ids)

    for download_id, original_ids in id_map.items():
        # 先下载到临时文件名；成功/失败/异常都必须清掉，曲绘目录里不留 __tmp_*.png
        tmp_path = cover_dir / f'__tmp_{download_id}.png'
        tmp_save_id = f'__tmp_{download_id}'
        lxns_status: List[str] = []
        data: Optional[bytes] = None
        try:
            if _download_one_cover(
                download_id, tmp_save_id, cover_dir, _LXNS_HEADERS,
                force=force_redownload, status=lxns_status,
            ):
                if not _cover_file_ok(tmp_path):
                    # 200 but HTML/反爬页：不能直接复制给曲目键
                    log.warning(f"曲绘 {download_id} 下载内容不是有效图片，丢弃")
                else:
                    try:
                        data = tmp_path.read_bytes()
                    except OSError as e:
                        log.warning(f"曲绘临时文件 {tmp_path.name} 读取失败: {e}")
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

        if data is not None:
            # 下载成功，原子写入所有原始 ID
            for oid in original_ids:
                if not _atomic_write_cover(cover_dir / f'{oid}.png', data):
                    continue
                forget_corrupted_cover(oid)
            downloaded += 1
            continue

        # 落雪拿不到 → 水鱼最后兜底。id 归一化在 fish_cover_id 里（同为 % 10000），
        # 宴会 id 因此同样落到父曲那张图，而不是必然 404 的 6 位地址。
        lxns_not_found = lxns_status[-1:] == ['not_found']
        for oid in original_ids:
            fish_status: List[str] = []
            if _download_one_cover_fish(
                int(oid), oid, cover_dir, force=force_redownload, status=fish_status
            ):
                forget_corrupted_cover(oid)
                downloaded += 1
            elif lxns_not_found and fish_status[-1:] == ['not_found']:
                # 只有「上游确实 404」才进负缓存：反爬 / 网络抖动还会重试
                missing_both.append(oid)

    if missing_both:
        # 单曲不再逐条刷 WARNING：一次汇总 + 落负缓存
        _record_negative(missing_both)
        preview = ', '.join(str(x) for x in missing_both[:8])
        if len(missing_both) > 8:
            preview += ' ...'
        log.info(
            f"{len(missing_both)} 个 id 双源均无曲绘，已记入负缓存"
            f"（{_COVER_NEGATIVE_CACHE_TTL // 86400} 天内不再请求）: {preview}"
        )

    # 写入本地固化标记（仅附带信息）
    _write_cover_marker(cover_dir, len(all_ids))

    log.info(f"曲绘同步完成，本次补齐 {downloaded} 张唯一图片（共需 {len(all_ids)} 个文件）")
    return downloaded


# ==========================================
# 水鱼曲绘 URL 构建（5 位补零）
# ==========================================

def fish_cover_id(song_id: int) -> int:
    """曲目 ID → 水鱼 covers 目录里的图片 ID（与落雪 jacket 同一套归一化）。

    ``>= 10000`` 一律 ``% 10000``：水鱼 DX 谱面 ID = 落雪 ID + 10000，要减回
    10000（旧实现只处理 10001~11000，导致 DX id 11001..99999 拼出 11008.png
    这种不存在的地址）；宴会场（>= 100000）命中的同样是父曲那张图（落雪侧
    实测 41/41 均 200），因此也走 ``% 10000``——保留 6 位原 ID 只会拼出必然
    404 的地址（水鱼没有宴会专属封面）。

    归一化结果为 ``0``（``10000`` / ``100000`` 这类整万位 id）时抛
    ``ValueError``：``00000.png`` 同样不存在，调用方应先经
    ``_cover_download_id`` 判空并按 not_found 处理。
    """
    song_id = int(song_id)
    if song_id >= 10000:
        cover_id = song_id % 10000
        if cover_id == 0:
            raise ValueError(f"曲目 id {song_id} 归一化后为 0，上游无对应曲绘")
        return cover_id
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
    download_id: int,
    save_id: str,
    cover_dir: Path,
    force: bool = False,
    status: Optional[List[str]] = None,
) -> bool:
    """
    使用水鱼 API 下载单张曲绘（只作落雪之后的最后兜底）。
    水鱼封面 URL: https://www.diving-fish.com/covers/{id:05d}.png
    ID 归一化交给 ``fish_cover_id``：``>= 10000`` 统一 ``% 10000``（DX 减
    10000、宴会场落到父曲那张图）。

    404 记 DEBUG：宴会 id 在上游没有专属封面属于预期，逐条 WARNING 只会刷屏；
    调用方会汇总成一行 INFO 并写入负缓存。

    Args:
        force:  True 时跳过「已有有效文件」早退，强制重新下载
        status: 可选，收集结果类别（见 ``_set_status``）
    """
    cover_path = cover_dir / f'{save_id}.png'

    # 已有有效文件则跳过（force 时必须绕过：脏图魔数合法，只能靠重下覆盖）
    # 用 _cover_file_ok 而非裸魔数：已缓存的占位图不能被当成「已完成」
    if not force and cover_path.exists() and cover_path.stat().st_size > 5000:
        from .image import forget_corrupted_cover
        try:
            if _cover_file_ok(cover_path):
                forget_corrupted_cover(save_id)
                _set_status(status, 'ok')
                return True
        except Exception:
            pass

    # 整万位 id（10000 / 100000 …）归一化后为 0 → 00000.png 不存在，不发请求
    if _cover_download_id(download_id) is None:
        _set_status(status, 'not_found')
        log.debug(f"水鱼曲绘 {save_id}({download_id}) 归一化后为 0，上游无此资产")
        return False
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
            _set_status(status, 'error')
            log.warning(f"水鱼曲绘 {save_id}({download_id}) 下载失败: {e}")
            return False

    try:
        resp.raise_for_status()
    except Exception as e:
        if getattr(resp, 'status_code', 0) in (404, 410):
            _set_status(status, 'not_found')
            log.debug(f"水鱼曲绘 {save_id}({download_id}) 不存在: {e}")
        else:
            _set_status(status, 'error')
            log.warning(f"水鱼曲绘 {save_id}({download_id}) 下载失败: {e}")
        return False

    if not _atomic_write_cover(cover_path, resp.content):
        _set_status(status, 'error')
        return False
    # 下载成功即解除损坏记录：有效文件不能再被 image 层当坏文件删掉
    from .image import forget_corrupted_cover
    forget_corrupted_cover(save_id)
    _set_status(status, 'ok')
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

    宴会场（>= 100000）只承认精确 ``{id}.png``：``music_picture`` 会先回退到
    ``{id - 100000}.png``（不够再减 10000），那是**别的键**，可能是别的曲目的
    图；拿回退结果判「有没有图」等于把别人的文件当健康文件。宴会 id 的曲绘
    本来与父曲同图，但必须落到自己的键名上——逐键补缺才会写出它。

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
    回退：否则 110114 会因为 10114.png（另一个键）存在而被判成「健康」，
    ``{id}.png`` 永远补不出来。
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

    # 负缓存命中且未过期 → 直接跳过，不发任何请求（双源都没图的 id 不再重试）
    negative = _load_negative_cache()
    now = time.time()
    missing = [
        sid for sid in ids
        if _cover_needs_download(sid) and not _negative_cache_is_fresh(negative, sid, now)
    ]
    if not missing:
        return 0
    if cover_dir is None:
        cover_dir = music_picture(missing[0]).parent
    cover_dir = Path(cover_dir)

    failed_404: List[int] = []

    async def _default_download(sid: int) -> bool:
        # 所有 id 统一走落雪 ``% 10000``：宴会场取到的就是父曲曲绘（实测 41/41
        # 均 200），不再是「另一首歌」。水鱼只在落雪失败时作最后兜底。
        did = _cover_download_id(sid)
        if did is None:
            # 整万位 id（如 10000）：0.png 是占位 logo，不发请求，直接记负缓存
            failed_404.append(sid)
            return False
        lxns_status: List[str] = []
        ok = await anyio.to_thread.run_sync(
            _download_one_cover, did, str(sid), cover_dir, _LXNS_HEADERS,
            False, lxns_status,
        )
        fish_status: List[str] = []
        if not ok:
            ok = await anyio.to_thread.run_sync(
                _download_one_cover_fish, sid, str(sid), cover_dir, False, fish_status
            )
        if ok:
            forget_corrupted_cover(sid)
        elif lxns_status[-1:] == ['not_found'] and fish_status[-1:] == ['not_found']:
            # 双源都 404 才记负缓存；网络故障、反爬都留着下次重试
            failed_404.append(sid)
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
    if failed_404:
        _record_negative(failed_404)
        log.info(
            f"{len(failed_404)} 个 id 双源均无曲绘，已记入负缓存"
            f"（{_COVER_NEGATIVE_CACHE_TTL // 86400} 天内不再请求）"
        )
    return restored
