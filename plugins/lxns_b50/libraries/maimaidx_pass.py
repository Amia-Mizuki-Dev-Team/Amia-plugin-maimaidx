import os
import sys
import time
import base64
import datetime
import hashlib
import html
import random
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Tuple, Optional
from PIL import Image, ImageDraw, ImageFont, ImageChops

# 缓存的 Chara 映射
_chara_id_to_name = None
_chara_name_to_id = None

def init_chara_mappings():
    global _chara_id_to_name, _chara_name_to_id
    if _chara_id_to_name is not None:
        return
    from ..config import static
    xml_path = static / "dxpass" / "CharaSort.xml"
    _chara_id_to_name = {}
    _chara_name_to_id = {}
    if not xml_path.exists():
        return
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        for string_id in root.findall(".//StringID"):
            id_node = string_id.find("id")
            str_node = string_id.find("str")
            if id_node is not None and str_node is not None and str_node.text:
                c_id = id_node.text.strip()
                c_name = str_node.text.strip()
                chara_id = c_id.zfill(6)
                _chara_id_to_name[chara_id] = c_name
                _chara_name_to_id[c_name.lower()] = chara_id
    except Exception as e:
        print(f"Failed to load CharaSort.xml: {e}")

def get_chara_id_by_name(name: str) -> Optional[str]:
    init_chara_mappings()
    if not _chara_name_to_id:
        return None
    name_clean = name.replace(" ", "").lower().strip()
    if not name_clean:
        return None
    
    # 1. 尝试完全匹配（忽略空格）
    for k, v in _chara_name_to_id.items():
        if name_clean == k.replace(" ", ""):
            return v
            
    # 2. 尝试模糊匹配（忽略空格）
    for k, v in _chara_name_to_id.items():
        if name_clean in k.replace(" ", ""):
            return v
    return None

class DrawPass:
    def __init__(
        self,
        nickname: str,
        rating: int,
        qqid: int = 0,
        friend_code: str = "",
        chara_id: str = "000101",
        frame_id: str = "6",
        base_id: str = "000001",
        chara_type: str = "chara",
        watermark: bool = False,
        chara_name: str = "",
        icon_id: str = "",
        plate_id: str = "",
    ):
        self.nickname = nickname
        self.rating = rating
        self.qqid = qqid
        self.friend_code = friend_code
        self.chara_id = chara_id
        self.frame_id = frame_id
        self.base_id = base_id
        self.chara_type = chara_type
        self.watermark = watermark
        self.chara_name_override = chara_name
        self.icon_id = icon_id or chara_id
        self.plate_id = plate_id or base_id

        # 智能解析项目内的 data 资源目录
        from ..config import static
        self.dx_pass_dir = static / "dxpass"
        self.card_base_dir = self.dx_pass_dir
        self.pic_dir = static / "pic"
        common_dir = static / "common"
 
        self.font_siyuan = common_dir / "ResourceHanRoundedCN-Bold.ttf"
        self.font_shanggu = common_dir / "ShangguMonoSC-Regular.otf"
        self.font_torus = common_dir / "Torus SemiBold.otf"
 
        self.font_zh = str(self.font_siyuan) if self.font_siyuan.exists() else r"C:\Windows\Fonts\msyh.ttc"
        win_msyh = Path(r"C:\Windows\Fonts\msyh.ttc")
        self.font_wide = str(win_msyh) if win_msyh.exists() else (str(self.font_shanggu) if self.font_shanggu.exists() else self.font_zh)
        self.font_en = str(self.font_torus) if self.font_torus.exists() else r"C:\Windows\Fonts\arial.ttf"
        self.font_zh_bd = str(self.font_siyuan) if self.font_siyuan.exists() else r"C:\Windows\Fonts\msyhbd.ttc"
        self.font_en_bd = str(self.font_torus) if self.font_torus.exists() else r"C:\Windows\Fonts\arialbd.ttf"
        
        if not os.path.exists(self.font_zh):
            self.font_zh = "arial.ttf"
        if not os.path.exists(self.font_en):
            self.font_en = "arial.ttf"
        if not os.path.exists(self.font_zh_bd):
            self.font_zh_bd = self.font_zh
        if not os.path.exists(self.font_en_bd):
            self.font_en_bd = self.font_en

    def _findRaPic(self) -> str:
        if self.rating < 1000: return '01'
        elif self.rating < 2000: return '02'
        elif self.rating < 4000: return '03'
        elif self.rating < 7000: return '04'
        elif self.rating < 10000: return '05'
        elif self.rating < 12000: return '06'
        elif self.rating < 13000: return '07'
        elif self.rating < 14000: return '08'
        elif self.rating < 14500: return '09'
        elif self.rating < 15000: return '10'
        else: return '11'

    def _get_base_image(self) -> Image.Image:
        fid = self.frame_id.zfill(7)
        bid = self.base_id.zfill(6)
        
        fname = f"UI_CardBase_{fid}_{bid}_S.png"
        path = self.card_base_dir / "CardBase" / fname
        if path.exists():
            return Image.open(path).convert("RGBA")
            
        pattern = f"UI_CardBase_*_{bid}_S.png"
        matches = list((self.card_base_dir / "CardBase").glob(pattern))
        if matches:
            return Image.open(matches[0]).convert("RGBA")
            
        default_path = self.card_base_dir / "CardBase" / "UI_CardBase_0000006_000001_S.png"
        if default_path.exists():
            return Image.open(default_path).convert("RGBA")
            
        return Image.new("RGBA", (256, 352), (255, 255, 255, 255))

    def _get_chara_image(self) -> Image.Image:
        r"""获取立绘，强制从 D:\DXPass 寻找高清 512x512 原始立绘"""
        cid = self.chara_id.zfill(6)
        
        if self.chara_type == "chara":
            path1 = self.dx_pass_dir / "Chara" / "Texture2D" / f"UI_Chara_{cid}.png"
            if path1.exists():
                return Image.open(path1).convert("RGBA")
                
            default_cid = "000101"
            path1_def = self.dx_pass_dir / "Chara" / "Texture2D" / f"UI_Chara_{default_cid}.png"
            if path1_def.exists():
                return Image.open(path1_def).convert("RGBA")
                
        elif self.chara_type == "partner":
            path1 = self.dx_pass_dir / "Partner" / "Texture2D" / f"UI_PartnerResult_{cid}.png"
            if path1.exists():
                return Image.open(path1).convert("RGBA")
                
            default_cid = "000000"
            path1_def = self.dx_pass_dir / "Partner" / "Texture2D" / f"UI_PartnerResult_{default_cid}.png"
            if path1_def.exists():
                return Image.open(path1_def).convert("RGBA")
                
        return Image.new("RGBA", (512, 512), (0, 0, 0, 0))

    def _get_frame_image(self) -> Image.Image:
        fid = self.frame_id.zfill(7)
        fname = f"UI_CardFrame_{fid}_S.png"
        path = self.card_base_dir / "CardFrame" / fname
        if path.exists():
            return Image.open(path).convert("RGBA")
            
        default_path = self.card_base_dir / "CardFrame" / "UI_CardFrame_0000006_S.png"
        if default_path.exists():
            return Image.open(default_path).convert("RGBA")
            
        return Image.new("RGBA", (256, 352), (0, 0, 0, 0))

    def _get_base_path(self) -> Path:
        fid = self.frame_id.zfill(7)
        bid = self.base_id.zfill(6)
        exact = self.card_base_dir / "CardBase" / f"UI_CardBase_{fid}_{bid}_S.png"
        if exact.exists():
            return exact
        matches = list((self.card_base_dir / "CardBase").glob(f"UI_CardBase_*_{bid}_S.png"))
        if matches:
            return matches[0]
        return self.card_base_dir / "CardBase" / "UI_CardBase_0000006_000001_S.png"

    def _get_frame_path(self) -> Path:
        fid = self.frame_id.zfill(7)
        exact = self.card_base_dir / "CardFrame" / f"UI_CardFrame_{fid}_S.png"
        if exact.exists():
            return exact
        return self.card_base_dir / "CardFrame" / "UI_CardFrame_0000006_S.png"

    def _get_card_chara_path(self) -> Path:
        cid = self.chara_id.zfill(6)
        card_chara = self.dx_pass_dir / "CardChara" / f"UI_CardChara_{cid}_S.png"
        if card_chara.exists():
            return card_chara
        if self.chara_type == "partner":
            p = self.dx_pass_dir / "Partner" / "Texture2D" / f"UI_PartnerResult_{cid}.png"
            if p.exists():
                return p
        p = self.dx_pass_dir / "Chara" / "Texture2D" / f"UI_Chara_{cid}.png"
        if p.exists():
            return p
        return self.dx_pass_dir / "CardChara" / "UI_CardChara_000101_S.png"

    def _file_to_data_uri(self, path: Path) -> str:
        if not path.exists():
            return ""
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(path.suffix.lower(), "application/octet-stream")
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")

    def _designer_asset_uri(self, image_id: str) -> str:
        path = self.dx_pass_dir / "Designer" / f"{image_id}.png"
        return self._file_to_data_uri(path)

    def _choose_dxpass_background_path(self) -> Path:
        base_dir = self.card_base_dir / "CardBase"
        candidates = sorted(base_dir.glob("UC_BG_*.png"))
        allowed_s = base_dir / "UI_CardBase_0000006_559999_S.png"
        if allowed_s.exists():
            candidates.append(allowed_s)
        selected = self._select_asset_by_token(candidates, self.base_id, "b")
        if selected:
            return selected
        if candidates:
            return random.choice(candidates)

        designer_default = self.dx_pass_dir / "Designer" / "0324f864-8b48-48cf-a63b-a77cf3529150.png"
        if designer_default.exists():
            return designer_default
        return self._get_base_path()

    def _choose_dxpass_frame_path(self) -> Path:
        frame_dir = self.card_base_dir / "CardFrame"
        candidates = sorted(frame_dir.glob("UC_Frame_*.png"))
        selected = self._select_asset_by_token(candidates, self.frame_id, "f")
        if selected:
            return selected
        if candidates:
            return random.choice(candidates)

        designer_default = self.dx_pass_dir / "Designer" / "5b863e4d-b730-4150-804c-23e86c3dca1a.png"
        if designer_default.exists():
            return designer_default
        return self._get_frame_path()

    def _select_asset_by_token(self, candidates: list[Path], token: str, prefix: str) -> Optional[Path]:
        if not token:
            return None
        value = str(token).strip()
        if not value:
            return None
        lowered = value.lower()
        if lowered.startswith(prefix) and lowered[1:].isdigit():
            index = int(lowered[1:]) - 1
            if 0 <= index < len(candidates):
                return candidates[index]
        for path in candidates:
            if value in {path.name, path.stem}:
                return path
        return None

    def _get_pass_chara_path(self) -> Path:
        ids = []
        for raw_id in (self.icon_id, self.chara_id):
            if raw_id:
                ids.append(str(raw_id).zfill(6))

        for cid in ids:
            path = self.dx_pass_dir / "Chara" / "Texture2D" / f"UI_Chara_{cid}.png"
            if path.exists():
                return path

        for cid in ids:
            path = self.dx_pass_dir / "Chara" / "Sprite" / f"UI_Chara_{cid}.png"
            if path.exists():
                return path

        fallback = self.dx_pass_dir / "Chara" / "Texture2D" / "UI_Chara_000101.png"
        if fallback.exists():
            return fallback
        return self.dx_pass_dir / "Chara" / "Sprite" / "UI_Chara_000101.png"

    def _get_name_plate_path(self) -> Path:
        for name in (f"{self.plate_id}_lxns.png", f"{self.base_id}_lxns.png"):
            path = self.pic_dir.parent / "plate" / name
            if path.exists():
                return path
        fallback = self.pic_dir.parent / "plate" / "206002_lxns.png"
        if fallback.exists():
            return fallback
        return self._get_base_path()

    def _font_data_uri(self) -> str:
        for path in (self.font_siyuan, self.font_shanggu, Path(r"C:\Windows\Fonts\msyh.ttc")):
            if path.exists():
                mime = "font/ttf" if path.suffix.lower() in {".ttf", ".ttc"} else "font/otf"
                return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        return ""

    def _draw_watermark(self, img: Image.Image) -> Image.Image:
        watermark_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark_layer)
        font = ImageFont.truetype(self.font_zh, 32)
        text = "Amia_晓山瑞希 Preview  " * 3
        
        for y in range(-200, img.height + 200, 150):
            draw.text((-100, y), text, font=font, fill=(128, 128, 128, 40))
            
        rotated = watermark_layer.rotate(25, resample=Image.Resampling.BICUBIC)
        return Image.alpha_composite(img, rotated)

    def _chara_name(self) -> str:
        if self.chara_name_override:
            return self.chara_name_override
        init_chara_mappings()
        cid = self.chara_id.zfill(6)
        if _chara_id_to_name and cid in _chara_id_to_name:
            return _chara_id_to_name[cid]
        return f"Chara {cid}"

    def _display_name(self) -> str:
        return (self.nickname or "").strip() or "Maimai Player"

    def _amia_chara_name(self) -> str:
        name = unicodedata.normalize("NFKC", self._chara_name()).strip()
        name = name.replace(" ", "").replace("\u3000", "")
        name = name.replace("\u6681", "\u6653")
        return f"Amia_{name or self.icon_id or self.chara_id}"

    def _draw_fit_text(
        self,
        draw: ImageDraw.ImageDraw,
        box: Tuple[int, int, int, int],
        text: str,
        font_path: str,
        max_size: int,
        min_size: int,
        fill: Tuple[int, int, int, int],
        anchor: str = "mm",
    ):
        font_size = max_size
        font = ImageFont.truetype(font_path, font_size)
        max_w = box[2] - box[0]
        max_h = box[3] - box[1]
        while font_size > min_size:
            font = ImageFont.truetype(font_path, font_size)
            bbox = draw.textbbox((0, 0), text, font=font)
            if bbox[2] - bbox[0] <= max_w and bbox[3] - bbox[1] <= max_h:
                break
            font_size -= 1
        x = (box[0] + box[2]) // 2
        y = (box[1] + box[3]) // 2
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        if anchor == "mm":
            pos = (x - text_w // 2 - bbox[0], y - text_h // 2 - bbox[1])
        else:
            pos = (box[0] - bbox[0], box[1] - bbox[1])
        draw.text(pos, text, font=font, fill=fill)

    def preview_chara(self) -> Image.Image:
        """仅对角色立绘加水印，返回 512x512 水印图"""
        chara_img = self._get_chara_image()
        return self._draw_watermark(chara_img)

    def build_usagi_card_html(self, qr_data_uri: str) -> str:
        display_name = html.escape((self.nickname or "Maimai Player").strip())
        chara_name = html.escape(self._amia_chara_name())
        friend_code = html.escape(str(self.friend_code or self.qqid or ""))
        today = datetime.date.today()
        made_date = today.strftime("%Y.%m.%d")
        valid_until = (today + datetime.timedelta(days=15)).strftime("%Y.%m.%d")
        rating = f"{self.rating:05d}" if self.rating else ""
        base_uri = self._file_to_data_uri(self._choose_dxpass_background_path())
        plate_uri = self._file_to_data_uri(self._get_name_plate_path())
        chara_uri = self._file_to_data_uri(self._get_pass_chara_path())
        frame_uri = self._file_to_data_uri(self._choose_dxpass_frame_path())
        dx_uri = self._file_to_data_uri(self.pic_dir / "DX.png")
        rating_plate_uri = self._file_to_data_uri(self.pic_dir.parent / "rating plate" / f"UI_CMN_DXRating_{self._findRaPic()}.png")
        rating_digits = "".join(
            f"<img class='rating-digit digit-{digit}' src='{self._file_to_data_uri(self.pic_dir / f'UI_NUM_Drating_{digit}.png')}'>"
            for digit in rating
        )
        font_uri = self._font_data_uri()
        rating_label = "\u3067\u3089\u3063\u304f\u3059"
        friend_label = "\u30d5\u30ec\u30f3\u30c9"
        code_label = "\u30b3\u30fc\u30c9"
        valid_label = "\u6709\u52b9\u671f\u9650"

        player_info_html = ""
        if display_name or friend_code:
            top_html = ""
            if display_name:
                badge_html = f"<img class='dx-badge' src='{dx_uri}'>" if dx_uri else ""
                top_html = f"<div class='player-top'><div class='name'>{display_name}</div>{badge_html}</div>"
            friend_html = ""
            if friend_code:
                friend_html = (
                    "<div class='friend-row'>"
                    f"<div class='friend-pill'>{friend_label}<br>{code_label}</div>"
                    f"<div class='friend-code'>{friend_code}</div>"
                    "</div>"
                )
            player_info_html = f"<div class='player-info'><div class='player-box'>{top_html}{friend_html}</div></div>"

        rating_html = ""
        if rating:
            rating_html = (
                "<div class='rating-box'>"
                f"<img class='rating-plate' src='{rating_plate_uri}'>"
                f"<div class='rating-digits'>{rating_digits}</div>"
                "</div>"
            )

        return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  {("@font-face { font-family: UsagiCardFont; src: url('" + font_uri + "'); }") if font_uri else ""}
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0;
    padding: 0;
    width: 768px;
    height: 1052px;
    overflow: hidden;
    background: transparent;
    font-family: UsagiCardFont, "Microsoft YaHei", "Segoe UI", sans-serif;
  }}
  #card-root {{
    position: relative;
    width: 768px;
    height: 1052px;
    overflow: hidden;
    background: transparent;
    border-radius: 28px;
  }}
  .cover-image {{
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }}
  .plate-bg {{
    position: absolute;
    top: 22px;
    left: 24px;
    width: 720px;
    height: 116px;
    object-fit: contain;
    opacity: .98;
  }}
  .chara-hero {{
    position: absolute;
    left: 50%;
    top: 57%;
    width: 930px;
    height: 930px;
    transform: translate(-50%, -50%);
    object-fit: contain;
    image-rendering: auto;
    filter: drop-shadow(0 22px 28px rgba(0,0,0,.24));
  }}
  .contain-image {{
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
  }}
  .contain-image.upper {{
    object-position: left top;
    clip-path: polygon(0 0, 100% 0, 100% 50%, 0 50%);
  }}
  .contain-image.under {{
    object-position: left bottom;
    clip-path: polygon(0 50%, 100% 50%, 100% 100%, 0 100%);
  }}
  .rating-box {{
    position: absolute;
    top: 28px;
    right: 42px;
    width: 220px;
    height: 43px;
  }}
  .rating-plate {{
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
  }}
  .rating-digits {{
    position: absolute;
    right: 28px;
    top: 10px;
    display: flex;
    align-items: center;
    gap: 0;
  }}
  .rating-digit {{
    height: 24px;
    width: 19px;
    object-fit: contain;
    margin-left: -1px;
  }}
  .rating-digit.digit-1 {{
    width: 21px;
  }}
  .player-info {{
    position: absolute;
    top: 92px;
    right: 14px;
    width: 360px;
  }}
  .player-box {{
    background: #fff;
    border-radius: 22px;
    overflow: hidden;
    box-shadow: 0 10px 24px rgba(0,0,0,.12);
  }}
  .player-top {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 14px 18px 9px;
  }}
  .name {{
    max-width: 250px;
    font-size: 25px;
    line-height: 1.1;
    font-weight: 800;
    color: #111;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .dx-badge {{
    width: 56px;
    height: 20px;
    object-fit: contain;
  }}
  .friend-row {{
    display: flex;
    align-items: stretch;
  }}
  .friend-pill {{
    width: 100px;
    min-height: 52px;
    padding: 10px 8px;
    background: #405baa;
    color: #fff;
    font-size: 15px;
    line-height: 1.1;
    font-weight: 800;
    text-align: center;
  }}
  .friend-code {{
    flex: 1;
    display: flex;
    align-items: center;
    padding: 0 18px;
    font-size: 24px;
    font-weight: 800;
    color: #111;
    white-space: nowrap;
  }}
  .chara-info {{
    position: absolute;
    left: 0;
    bottom: 194px;
    width: 430px;
  }}
  .chara-top {{
    width: 82%;
    padding: 7px 22px 6px;
    border-radius: 0 12px 0 0;
    background: #fee37c;
    color: #5a4b28;
    font-size: 18px;
    font-weight: 800;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .chara-bottom {{
    display: inline-flex;
    align-items: center;
    gap: 10px;
    min-width: 96%;
    padding: 7px 22px 9px;
    border-radius: 0 12px 12px 0;
    background: #fee37c;
    color: #5a4b28;
    box-shadow: 0 10px 24px rgba(0,0,0,.14);
  }}
  .chara-label {{
    font-size: 17px;
    font-weight: 700;
  }}
  .chara-value {{
    font-size: 23px;
    font-weight: 900;
  }}
  .footer {{
    position: absolute;
    left: 38px;
    right: 38px;
    bottom: 16px;
    display: flex;
    justify-content: center;
  }}
  .footer-inner {{
    width: 90%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 7px 18px;
    border-radius: 999px;
    background: rgba(31, 41, 55, .86);
    color: #fff;
    font-size: 18px;
    font-weight: 800;
  }}
  .footer-left, .footer-right {{
    white-space: nowrap;
  }}
  .qr-wrap {{
    position: absolute;
    right: 38px;
    bottom: 94px;
    width: 126px;
    height: 126px;
    border-radius: 8px;
    background: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 10px 24px rgba(0,0,0,.14);
  }}
  .qr-wrap img {{
    width: 112px;
    height: 112px;
  }}
</style>
</head>
<body>
<div id="card-root">
  <img class="cover-image" src="{base_uri}">
  <img class="plate-bg" src="{plate_uri}">
  <img class="chara-hero" src="{chara_uri}">
  <img class="contain-image upper" src="{frame_uri}">
  <img class="contain-image under" src="{frame_uri}">
  {rating_html}
  {player_info_html}
  <div class="chara-info">
    <div class="chara-top">{chara_name}</div>
    <div class="chara-bottom">
      <div class="chara-label">{valid_label}</div>
      <div class="chara-value">{valid_until}</div>
    </div>
  </div>
  <div class="qr-wrap"><img src="{qr_data_uri}"></div>
  <div class="footer">
    <div class="footer-inner">
      <div class="footer-left">{chara_name}</div>
      <div class="footer-right">{made_date}</div>
    </div>
  </div>
</div>
</body>
</html>"""

    def draw(self) -> Image.Image:
        # 1. 加载三个图层
        base_img = self._get_base_image()
        chara_img = self._get_chara_image()
        frame_img = self._get_frame_image()
        
        # 2. 合成大尺寸图卡（采用 768x1052 官方超清规格）
        large_card = Image.new("RGBA", (768, 1052))
        large_card.alpha_composite(base_img.resize((768, 1052), Image.Resampling.LANCZOS))
        
        # 贴入放大且下移后的角色立绘，w=840, h=840, x=-36, y=175 (微调下移，防悬空)
        chara_layer = Image.new("RGBA", (768, 1052), (0, 0, 0, 0))
        chara_resized = chara_img.resize((840, 840), Image.Resampling.LANCZOS)
        chara_layer.paste(chara_resized, (-36, 175), chara_resized)
        large_card.alpha_composite(chara_layer)
        
        # 贴入卡框（覆盖在立绘上层）
        large_card.alpha_composite(frame_img.resize((768, 1052), Image.Resampling.LANCZOS))
        
        draw = ImageDraw.Draw(large_card)
        
        # 4. 绘制文字与二维码 (像素级精准对齐例图)
        
        # 4.1 绘制右上角 Rating 滚动轮格 (x=505, y=35, w=220, h=43)
        plate_name = f"UI_CMN_DXRating_{self._findRaPic()}.png"
        plate_path = self.pic_dir / plate_name
        if plate_path.exists():
            plate_img = Image.open(plate_path).convert("RGBA").resize((220, 43), Image.Resampling.LANCZOS)
            large_card.alpha_composite(plate_img, (505, 35))
            
            # 绘制 5 位 Rating 数字 (宽 20, 高 24, 垂直居中于 y=44, 横坐标间距 17)
            rating_str = f"{self.rating:05d}"
            for n, char in enumerate(rating_str):
                digit_path = self.pic_dir / f"UI_NUM_Drating_{char}.png"
                if digit_path.exists():
                    digit_img = Image.open(digit_path).convert("RGBA").resize((20, 24), Image.Resampling.LANCZOS)
                    large_card.alpha_composite(digit_img, (605 + n * 17, 44))
        
        # 4.2 右上玩家信息面板：昵称 + DX 标 + 好友码
        overlay = Image.new("RGBA", large_card.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle(
            [420, 100, 734, 196],
            radius=12,
            fill=(255, 255, 255, 255)
        )
        overlay_draw.rectangle([436, 112, 650, 148], fill=(255, 255, 255, 255))
        overlay_draw.rounded_rectangle(
            [420, 154, 508, 194],
            radius=8,
            fill=(64, 91, 170, 255)
        )
        large_card.alpha_composite(overlay)
        
        dx_path = self.pic_dir / "DX.png"
        if dx_path.exists():
            dx_img = Image.open(dx_path).convert("RGBA").resize((64, 23), Image.Resampling.LANCZOS)
            large_card.alpha_composite(dx_img, (654, 120))
            
        self._draw_fit_text(
            draw,
            (436, 118, 648, 152),
            self._display_name(),
            self.font_wide,
            24,
            13,
            (0, 0, 0, 255),
        )
        friend_label_font = ImageFont.truetype(self.font_zh_bd, 14)
        draw.text((464, 174), "フレンド\nコード", font=friend_label_font, fill=(255, 255, 255, 255), anchor="mm", align="center")
        code_text = str(self.friend_code) if self.friend_code else str(self.qqid)
        self._draw_fit_text(
            draw,
            (514, 160, 724, 190),
            code_text,
            self.font_en_bd,
            22,
            12,
            (0, 0, 0, 255),
        )
        
        # 4.3 左下角色名与卡号，参考 UsagiCard 的黄色信息条
        yellow_overlay = Image.new("RGBA", large_card.size, (0, 0, 0, 0))
        y_draw = ImageDraw.Draw(yellow_overlay)
        y_draw.rounded_rectangle(
            [0, 742, 315, 792],
            radius=14,
            fill=(254, 227, 124, 255)
        )
        y_draw.rectangle([0, 742, 24, 792], fill=(254, 227, 124, 255))
        y_draw.rounded_rectangle(
            [0, 792, 380, 858],
            radius=16,
            fill=(254, 227, 124, 255)
        )
        y_draw.rectangle([0, 792, 24, 858], fill=(254, 227, 124, 255))
        large_card.alpha_composite(yellow_overlay)
        
        text_color_gold = (90, 75, 40, 255)
        
        self._draw_fit_text(
            draw,
            (24, 750, 292, 784),
            self._chara_name(),
            self.font_zh_bd,
            20,
            12,
            text_color_gold,
        )
        card_no = str(self.friend_code or self.qqid or hashlib.md5(self.nickname.encode()).hexdigest()[:8])[-6:]
        card_font = ImageFont.truetype(self.font_zh_bd, 20)
        draw.text((52, 825), "カード 番号", font=ImageFont.truetype(self.font_zh_bd, 15), fill=text_color_gold, anchor="lm")
        draw.text((210, 825), card_no, font=card_font, fill=text_color_gold, anchor="lm")
        
        # 4.4 贴上三个透明印章 (仅在卡框本身不包含印章时绘制，以避免重影)
        crop_region = frame_img.crop((32, 850, 272, 930))
        has_built_in_stamps = False
        alpha_channel = crop_region.split()[-1]
        bbox = alpha_channel.getbbox()
        if bbox:
            pixels = list(alpha_channel.getdata())
            avg_alpha = sum(pixels) / len(pixels)
            if avg_alpha > 20:
                has_built_in_stamps = True
                
        if not has_built_in_stamps:
            stamp_names = ["stamp_lvup.png", "stamp_master.png", "stamp_achievement.png"]
            for idx, sname in enumerate(stamp_names):
                spath = self.pic_dir / "stamps" / sname
                if spath.exists():
                    stamp_img = Image.open(spath).convert("RGBA")
                    large_card.alpha_composite(stamp_img, (32 + idx * 80, 850))
        
        # 4.5 底部 footer 胶囊，参考 UsagiCard
        if self.friend_code:
            raw_code = str(self.friend_code)
        else:
            raw_code = hashlib.md5(str(self.qqid).encode()).hexdigest()[:20]
            
        raw_code = raw_code.ljust(20, "0")[:20].upper()
        formatted_code = " ".join([raw_code[i:i+4] for i in range(0, 20, 4)])
        
        bottom_str = "UsagiCard     Welcome to Maimai DX"
        bottom_font = ImageFont.truetype(self.font_en_bd, 18)
        
        capsule_overlay = Image.new("RGBA", large_card.size, (0, 0, 0, 0))
        c_draw = ImageDraw.Draw(capsule_overlay)
        c_draw.rounded_rectangle(
            [154, 990, 614, 1038],
            radius=24,
            fill=(31, 41, 55, 217)
        )
        large_card.alpha_composite(capsule_overlay)
        
        self._draw_fit_text(
            draw,
            (174, 998, 594, 1030),
            bottom_str,
            self.font_en_bd,
            18,
            12,
            (255, 255, 255, 255),
        )
        # 4.6 右下二维码白底容器
        white_overlay = Image.new("RGBA", large_card.size, (0, 0, 0, 0))
        w_draw = ImageDraw.Draw(white_overlay)
        w_draw.rounded_rectangle(
            [596, 830, 724, 958],
            radius=8,
            fill=(255, 255, 255, 255)
        )
        large_card.alpha_composite(white_overlay)
        
        qr_url = "https://help.mizuki.top"
        try:
            import qrcode
            qr = qrcode.QRCode(version=1, border=1, box_size=4)
            qr.add_data(qr_url)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
            qr_img = qr_img.resize((112, 112), Image.Resampling.LANCZOS)
            large_card.alpha_composite(qr_img, (604, 838))
        except Exception as e:
            print(f"Failed to generate QR code: {e}")
        return large_card
