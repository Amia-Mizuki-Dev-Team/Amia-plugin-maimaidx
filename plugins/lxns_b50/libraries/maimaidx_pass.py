import os
import sys
import time
import hashlib
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
        watermark: bool = False
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

    def _draw_watermark(self, img: Image.Image) -> Image.Image:
        watermark_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark_layer)
        font = ImageFont.truetype(self.font_zh, 32)
        text = "MizukiBot Preview  " * 3
        
        for y in range(-200, img.height + 200, 150):
            draw.text((-100, y), text, font=font, fill=(128, 128, 128, 40))
            
        rotated = watermark_layer.rotate(25, resample=Image.Resampling.BICUBIC)
        return Image.alpha_composite(img, rotated)

    def preview_chara(self) -> Image.Image:
        """仅对角色立绘加水印，返回 512x512 水印图"""
        chara_img = self._get_chara_image()
        return self._draw_watermark(chara_img)

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
        
        # 4.2 绘制玩家昵称白色圆角矩形 (x: 462 to 717, y: 108 to 159, DX badge at x=650, y=126, w=56, h=20)
        overlay = Image.new("RGBA", large_card.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle(
            [462, 108, 717, 159],
            radius=8,
            fill=(255, 255, 255, 255)
        )
        large_card.alpha_composite(overlay)
        
        # 绘制 DX badge (同向右平移对齐)
        dx_path = self.pic_dir / "DX.png"
        if dx_path.exists():
            dx_img = Image.open(dx_path).convert("RGBA").resize((56, 20), Image.Resampling.LANCZOS)
            large_card.alpha_composite(dx_img, (650, 126))
            
        # 绘制昵称文本 (在 [462, 650] 区域水平居中, y=134 垂直居中)
        name_font_size = 24
        nickname_font = ImageFont.truetype(self.font_zh_bd, name_font_size)
        while name_font_size >= 12:
            nickname_font = ImageFont.truetype(self.font_zh_bd, name_font_size)
            bbox = draw.textbbox((0, 0), self.nickname, font=nickname_font)
            text_w = bbox[2] - bbox[0]
            if text_w <= 170:
                break
            name_font_size -= 2
            
        bbox = draw.textbbox((0, 0), self.nickname, font=nickname_font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        draw.text(
            (556 - text_w // 2 - bbox[0], 134 - text_h // 2 - bbox[1]), 
            self.nickname, 
            font=nickname_font, 
            fill=(0, 0, 0, 255)
        )
        
        # 4.3 绘制左下角签名黄色底座 [20, 762, 291, 850] (向下平移 15px)
        yellow_overlay = Image.new("RGBA", large_card.size, (0, 0, 0, 0))
        y_draw = ImageDraw.Draw(yellow_overlay)
        y_draw.rounded_rectangle(
            [20, 762, 291, 850],
            radius=10,
            fill=(251, 212, 73, 255)
        )
        large_card.alpha_composite(yellow_overlay)
        
        text_color_gold = (90, 75, 40, 255)
        
        gen_str = "Generate @Amia_晓山瑞希"
        gold_font = ImageFont.truetype(self.font_zh_bd, 16)
        bbox = draw.textbbox((0, 0), gen_str, font=gold_font)
        text_h = bbox[3] - bbox[1]
        draw.text((40, 787 - text_h // 2 - bbox[1]), gen_str, font=gold_font, fill=text_color_gold)
        
        # 动态计算从今日起往后延 15 天的期限
        from datetime import datetime, timedelta
        expiry_date = datetime.now() + timedelta(days=15)
        expiry_str = expiry_date.strftime("%Y/%m/%d")
        boost_str = f"ブースト期限  {expiry_str}"
        boost_font = ImageFont.truetype(self.font_zh_bd, 15)
        bbox = draw.textbbox((0, 0), boost_str, font=boost_font)
        text_h = bbox[3] - bbox[1]
        draw.text((40, 821 - text_h // 2 - bbox[1]), boost_str, font=boost_font, fill=text_color_gold)
        
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
        
        # 4.5 绘制底部灰色条：画圆角矩形胶囊并居中对齐卡号和署名 (移至 y=1000)
        if self.friend_code:
            raw_code = str(self.friend_code)
        else:
            raw_code = hashlib.md5(str(self.qqid).encode()).hexdigest()[:20]
            
        raw_code = raw_code.ljust(20, "0")[:20].upper()
        formatted_code = " ".join([raw_code[i:i+4] for i in range(0, 20, 4)])
        
        bottom_str = f"{formatted_code}  Amia_晓山瑞希"
        bottom_font = ImageFont.truetype(self.font_zh_bd, 16)
        
        capsule_overlay = Image.new("RGBA", large_card.size, (0, 0, 0, 0))
        c_draw = ImageDraw.Draw(capsule_overlay)
        # y轴 1000-1040 区域，圆角半径 20
        c_draw.rounded_rectangle(
            [134, 1000, 634, 1040],
            radius=20,
            fill=(31, 41, 55, 217)
        )
        large_card.alpha_composite(capsule_overlay)
        
        bbox = draw.textbbox((0, 0), bottom_str, font=bottom_font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        draw.text(
            (384 - text_w // 2 - bbox[0], 1020 - text_h // 2 - bbox[1]), 
            bottom_str, 
            font=bottom_font, 
            fill=(255, 255, 255, 255)
        )
        
        # 4.6 绘制二维码白底容器 (大小 135x135, 贴在 x=562, y=843) 与二维码 (居中贴在 x=570, y=851, 大小 119x119)
        white_overlay = Image.new("RGBA", large_card.size, (0, 0, 0, 0))
        w_draw = ImageDraw.Draw(white_overlay)
        w_draw.rounded_rectangle(
            [562, 843, 697, 978],
            radius=10,
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
            qr_img = qr_img.resize((119, 119), Image.Resampling.LANCZOS)
            large_card.alpha_composite(qr_img, (570, 851))
        except Exception as e:
            print(f"Failed to generate QR code: {e}")
        return large_card
