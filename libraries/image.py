import base64
import hashlib
from io import BytesIO
from typing import Optional, Tuple, Union

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..config import SHANGGUMONO, Path, coverdir, log

# 全局缓存：已知损坏或服务端返回无效内容的曲绘 ID，避免反复尝试下载/打开
_corrupted_cover_ids: set = set()




# ==========================================
# 占位图签名黑名单（曲绘下载 / 有效性判定共用）
# ==========================================
# 上游 CDN（落雪 assets2 / 水鱼 covers）在新曲未解禁时会返回占位图（滚木/蓝
# maimai logo）。占位图是合法 PNG、大小也正常，魔数与文件大小都分辨不出来，
# 一旦被当有效封面缓存就永不重下。这里以本地占位资源文件（0.png / 11000.png）
# 的整文件 SHA-256 作黑名单：
#   下载侧 _atomic_write_cover 命中即不落盘；缓存侧 _cover_file_ok /
#   _check_and_clean_corrupted 命中即判无效并允许删除，由既有补下链路重拉。
# 删除严格限定为哈希精确命中的文件。签名在模块加载时从 coverdir 计算并进程内
# 缓存（替换占位文件后调 refresh_placeholder_signatures() 重算）；签名文件不存
# 在则跳过对应签名，全部缺失时黑名单为空，判定行为与改动前完全一致（零误伤）。
_PLACEHOLDER_SOURCES: Tuple[str, ...] = ('0.png', '11000.png')
_PLACEHOLDER_SIGNATURES: frozenset = frozenset()


def _compute_placeholder_signatures() -> frozenset:
    """从占位资源文件计算整文件 SHA-256 签名集合；缺失/读取失败逐个跳过。"""
    hashes = set()
    for name in _PLACEHOLDER_SOURCES:
        try:
            src = coverdir / name
            if src.is_file():
                hashes.add(hashlib.sha256(src.read_bytes()).hexdigest())
        except OSError:
            pass
    return frozenset(hashes)


def refresh_placeholder_signatures() -> None:
    """按当前 coverdir 重算并缓存签名（进程内黑名单的唯一写入点）。"""
    global _PLACEHOLDER_SIGNATURES
    _PLACEHOLDER_SIGNATURES = _compute_placeholder_signatures()


def is_placeholder_bytes(data: bytes) -> bool:
    """字节流是否精确命中占位图黑名单（整文件 SHA-256，不做模糊匹配）。"""
    if not data or not _PLACEHOLDER_SIGNATURES:
        return False
    return hashlib.sha256(data).hexdigest() in _PLACEHOLDER_SIGNATURES


def is_placeholder_cover_file(path: Path, data: Optional[bytes] = None) -> bool:
    """本地曲绘是否为已落盘的占位图。

    签名来源文件本身（0.png / 11000.png）除外：它们是 ``music_picture`` 故意
    回退的兜底占位图，删掉会打断回退链、并把黑名单的签名来源清空。
    """
    if path.name in _PLACEHOLDER_SOURCES:
        return False
    if data is None:
        try:
            data = path.read_bytes()
        except OSError:
            return False
    return is_placeholder_bytes(data)


refresh_placeholder_signatures()


def forget_corrupted_cover(song_id: Union[int, str]) -> None:
    """解除某曲绘的损坏记录。

    下载器写出有效文件、或校验发现本地文件已恢复有效时调用——损坏记录
    只用于「本次运行内少做无用功」，绝不能变成永久拉黑（否则重新下载的
    有效文件会在下次读取时被无条件删掉）。
    """
    _corrupted_cover_ids.discard(str(song_id))


def _check_and_clean_corrupted(path: Path) -> bool:
    """
    检查文件是否为有效图片，若损坏则删除。
    Returns: True=文件有效, False=已损坏被删除
    """
    if not path.exists():
        return False
    sid = path.stem  # 文件名（不含扩展名）
    # 先按内容判断：文件可能已被重新下载修复，命中过黑名单不代表它现在还是坏的
    stat_at_read = None
    try:
        stat_at_read = path.stat()
        data = path.read_bytes()
    except OSError:
        data = b''
    # is_placeholder_cover_file 走 globals() 软解析：按函数名抽取本定义的测试
    # 命名空间里没有黑名单设施时退回「仅魔数」的旧行为，不抛 NameError。
    placeholder_hit = globals().get("is_placeholder_cover_file")
    if is_valid_image(data[:16]) and not (placeholder_hit and placeholder_hit(path, data)):
        forget_corrupted_cover(sid)
        return True
    if sid not in _corrupted_cover_ids:
        log.warning(f"曲绘 {path.name} 已损坏或为占位图（魔数/签名黑名单校验失败），自动删除并降级")
    _corrupted_cover_ids.add(sid)
    try:
        # TOCTOU 收窄：mtime/size 与读字节时不一致说明文件在读检之间被其他
        # 进程改写或删除（可能刚重新下好有效曲绘），本次跳过删除，下轮再处理。
        if stat_at_read is not None:
            now = path.stat()
            if (now.st_mtime_ns, now.st_size) != (stat_at_read.st_mtime_ns, stat_at_read.st_size):
                return False
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return False


class DrawText:

    def __init__(self, image: ImageDraw.ImageDraw, font: Path) -> None:
        self._img = image
        self._font = str(font)

    def get_box(self, text: str, size: int) -> Tuple[float, float, float, float]:
        return ImageFont.truetype(self._font, size).getbbox(text)

    def draw(
        self,
        pos_x: int,
        pos_y: int,
        size: int,
        text: Union[str, int, float],
        color: Tuple[int, int, int, int] = (255, 255, 255, 255),
        anchor: str = 'lt',
        stroke_width: int = 0,
        stroke_fill: Tuple[int, int, int, int] = (0, 0, 0, 0),
        multiline: bool = False,
        char_spacing: int = 0,
    ) -> None:
        font = ImageFont.truetype(self._font, size)
        text = str(text)
        if char_spacing:
            # 逐字绘制以控制字间距
            font = ImageFont.truetype(self._font, size)
            x, y = pos_x, pos_y
            # 计算字符串实际 bbox，确定基线到中心的偏移
            full_bbox = font.getbbox(text)
            # bbox[1] 为负（基线以上），bbox[3] 为正（基线以下）
            baseline_offset = -(full_bbox[1] + full_bbox[3]) // 2 + 7
            if anchor == 'lt':
                pass  # lt → ls 无需偏移
            elif anchor in ('lm',):
                y -= baseline_offset
            elif anchor == 'mm':
                total_w = sum(font.getbbox(c)[2] for c in text) + char_spacing * (len(text) - 1)
                x -= total_w // 2
                y -= baseline_offset
            for c in text:
                self._img.text((x, y), c, color, font, anchor='ls',
                               stroke_width=stroke_width, stroke_fill=stroke_fill)
                x += font.getbbox(c)[2] + char_spacing
        elif multiline:
            self._img.multiline_text(
                (pos_x, pos_y), 
                text, 
                color, 
                font, 
                anchor, 
                stroke_width=stroke_width, 
                stroke_fill=stroke_fill
            )
        else:
            self._img.text(
                (pos_x, pos_y), 
                text, 
                color, 
                font, 
                anchor, 
                stroke_width=stroke_width, 
                stroke_fill=stroke_fill
            )


def tricolor_gradient(
    width: int, 
    height: int, 
    color1: Tuple[int, int, int] = (124, 129, 255), 
    color2: Tuple[int, int, int] = (193, 247, 225), 
    color3: Tuple[int, int, int] = (255, 255, 255)
) -> Image.Image:
    """绘制渐变色"""
    array = np.zeros((height, width, 3), dtype=np.uint8)
    
    for y in range(height):
        if y < height * 0.4:
            ratio = y / (height * 0.4)
            color = (1 - ratio) * np.array(color1) + ratio * np.array(color2)
        else:
            ratio = (y - height * 0.4) / (height * 0.6)
            color = (1 - ratio) * np.array(color2) + ratio * np.array(color3)
        array[y, :] = np.clip(color, 0, 255)
    
    image = Image.fromarray(array).convert('RGBA')
    return image


def rounded_corners(
    image: Image.Image,
    radius: int, 
    corners: Tuple[bool, bool, bool, bool] = (False, False, False, False)
) -> Image.Image:
    """
    绘制圆角
    
    Params:
        `image`: `PIL.Image.Image`
        `radius`: 圆角半径
        `corners`: 四个角是否绘制圆角，分别是左上、右上、右下、左下
    Returns:
        `PIL.Image.Image`
    """
    mask = Image.new('L', image.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, image.size[0], image.size[1]), radius, fill=255, corners=corners)

    new_im = ImageOps.fit(image, mask.size)
    new_im.putalpha(mask)

    return new_im


def music_picture(music_id: Union[int, str]) -> Path:
    """
    获取谱面图片路径（兼容落雪/水鱼双 ID 体系）
    
    ID 体系说明:
    - 落雪 LXNS:   原生 song_id（如 8, 38, 799）→ 曲绘存为 {id}.png
    - 水鱼 DivingFish: DX 谱面 ID = 落雪ID + 10000（如 10008）
    - 宴会场曲目: ID > 100000
    
    查找策略:
    1. 直接查找 {music_id}.png（自动检测损坏并删除）
    2. 若 music_id > 100000（宴会场），尝试 {music_id - 100000}.png
    3. 若 0 < music_id < 10000（可能是落雪SD），尝试 {music_id + 10000}.png（水鱼DX）
    4. 若 10000 < music_id < 100000（可能是水鱼DX），尝试 {music_id - 10000}.png（落雪SD）
    5. 回退到默认占位图 0.png → 11000.png
    
    损坏自动修复: 每次访问都会用魔数 + 占位图签名黑名单校验文件有效性，
    损坏或占位图文件自动删除并继续查找（占位图被删后由补下链路重新拉取）。
    """
    music_id = int(music_id)
    
    # 策略1: 直接匹配（自动检测损坏）
    path1 = coverdir / f'{music_id}.png'
    if _check_and_clean_corrupted(path1):
        return path1
    
    # 策略2: 宴会场曲目 (ID > 100000) 取模
    if music_id > 100000:
        mod_id = music_id - 100000
        path2 = coverdir / f'{mod_id}.png'
        if _check_and_clean_corrupted(path2):
            return path2
        music_id = mod_id
    
    # 策略3: 落雪原生 ID → 尝试水鱼 DX ID (ID+10000)
    if 0 < music_id < 10000:
        fish_dx_id = music_id + 10000
        path3 = coverdir / f'{fish_dx_id}.png'
        if _check_and_clean_corrupted(path3):
            return path3
    
    # 策略4: 水鱼 DX ID（10000 < ID < 100000）→ 尝试落雪原生 ID (ID-10000)
    # 上限曾写死 11000，曲库扩容（水鱼 DX ID 已到 11817+）后新曲直接掉到占位图；
    # 宴会场（> 100000）已在策略 2 处理，故安全区间到 100000 为止。
    if 10000 < music_id < 100000:
        lxns_sd_id = music_id - 10000
        path4 = coverdir / f'{lxns_sd_id}.png'
        if _check_and_clean_corrupted(path4):
            return path4
    
    # 策略5: 回退占位图（优先 0.png，其次 11000.png）
    for fallback in ['0.png', '11000.png']:
        fb_path = coverdir / fallback
        if _check_and_clean_corrupted(fb_path):
            return fb_path
    
    # 策略6: 实在没有占位图，返回 0.png 路径（让调用方处理）
    return coverdir / '0.png'


def text_to_image(text: str) -> Image.Image:
    font = ImageFont.truetype(str(SHANGGUMONO), 24)
    padding = 10
    margin = 4
    lines = text.strip().split('\n')
    max_width = 0
    b = 0
    for line in lines:
        l, t, r, b = font.getbbox(line)
        max_width = max(max_width, r)
    wa = max_width + padding * 2
    ha = b * len(lines) + margin * (len(lines) - 1) + padding * 2
    im = Image.new('RGB', (wa, ha), color=(255, 255, 255))
    draw = ImageDraw.Draw(im)
    for index, line in enumerate(lines):
        draw.text((padding, padding + index * (margin + b)), line, font=font, fill=(0, 0, 0))
    return im


def text_to_bytes_io(text: str) -> BytesIO:
    bio = BytesIO()
    text_to_image(text).save(bio, format='PNG')
    bio.seek(0)
    return bio


def image_to_base64(img: Image.Image, format='PNG', **save_kwargs) -> str:
    if format == 'JPEG' and img.mode in ('RGBA', 'LA', 'P'):
        # JPEG 无 alpha：铺白底后编码（调用方传来的仍是原画布对象）
        flat = Image.new('RGB', img.size, (255, 255, 255))
        rgba = img.convert('RGBA')
        flat.paste(rgba, mask=rgba.split()[3])
        img = flat
    output_buffer = BytesIO()
    img.save(output_buffer, format, **save_kwargs)
    byte_data = output_buffer.getvalue()
    base64_str = base64.b64encode(byte_data).decode()
    return 'base64://' + base64_str


def is_valid_image(data: bytes) -> bool:
    """
    验证字节数据是否为有效的图片文件。
    检查 PNG/JPEG/GIF/WebP 魔数（Magic Number），
    避免 Cloudflare 反爬页面/错误页面被当作图片保存。
    """
    if len(data) < 16:
        return False
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return True
    # JPEG: FF D8 FF
    if data[:3] == b'\xff\xd8\xff':
        return True
    # GIF: 47 49 46 38 37 61 or 47 49 46 38 39 61
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return True
    # WebP: RIFF .... WEBP
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return True
    return False
