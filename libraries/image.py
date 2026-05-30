import base64
from io import BytesIO
from typing import Tuple, Union

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..config import SHANGGUMONO, Path, coverdir, log

# 全局缓存：已知损坏或服务端返回无效内容的曲绘 ID，避免反复尝试下载/打开
_corrupted_cover_ids: set = set()


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


def _check_and_clean_corrupted(path: Path) -> bool:
    """
    检查文件是否为有效图片，若损坏则删除。
    Returns: True=文件有效, False=已损坏被删除
    """
    if not path.exists():
        return False
    sid = path.stem  # 文件名（不含扩展名）
    if sid in _corrupted_cover_ids:
        path.unlink(missing_ok=True)
        return False
    try:
        data = path.read_bytes()[:16]
        if not is_valid_image(data):
            log.warning(f"曲绘 {path.name} 已损坏（魔数不正确），自动删除并降级")
            _corrupted_cover_ids.add(sid)
            path.unlink(missing_ok=True)
            return False
        return True
    except Exception:
        _corrupted_cover_ids.add(sid)
        path.unlink(missing_ok=True)
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
        multiline: bool = False
    ) -> None:
        font = ImageFont.truetype(self._font, size)
        if multiline:
            self._img.multiline_text(
                (pos_x, pos_y), 
                str(text), 
                color, 
                font, 
                anchor, 
                stroke_width=stroke_width, 
                stroke_fill=stroke_fill
            )
        else:
            self._img.text(
                (pos_x, pos_y), 
                str(text), 
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
    4. 若 10000 < music_id <= 11000（可能是水鱼DX），尝试 {music_id - 10000}.png（落雪SD）
    5. 回退到默认占位图 0.png → 11000.png
    
    损坏自动修复: 每次访问都会用魔数校验文件有效性，损坏文件自动删除并继续查找。
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
    
    # 策略4: 水鱼 DX ID（10000~11000）→ 尝试落雪原生 ID (ID-10000)
    if 10000 < music_id <= 11000:
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


def image_to_base64(img: Image.Image, format='PNG') -> str:
    output_buffer = BytesIO()
    img.save(output_buffer, format)
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