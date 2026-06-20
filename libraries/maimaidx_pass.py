import os
import hashlib
import datetime
import httpx
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from typing import Optional, Union
from loguru import logger as log

from ..config import static, maidir, SIYUAN, TBFONT, maiconfig

# 资源路径配置
CARD_DIR = static / 'card'
BASE_DIR = CARD_DIR / 'CardBase'
CHARA_DIR = CARD_DIR / 'CardChara'
FRAME_DIR = CARD_DIR / 'CardFrame'

# LXNS 资产 CDN
LXNS_ASSET_BASE = "https://assets2.lxns.net/maimai/card"


def _ensure_asset(asset_type: str, filename_no_ext: str) -> Optional[Path]:
    """
    确保本地存在指定的卡面资产文件。
    优先尝试本地工作区已有的文件（优先高清，标清_S兜底），然后从 CDN 下载。
    """
    type_dir = CARD_DIR / asset_type
    type_dir.mkdir(parents=True, exist_ok=True)

    hd_path = type_dir / f"{filename_no_ext}.png"
    sd_path = type_dir / f"{filename_no_ext}_S.png"

    # --- 阶段 1：高清（HD）资产检索与下载 ---
    # 1.1 检索本地缓存目录下的 HD 资产
    if hd_path.exists() and hd_path.stat().st_size > 1000:
        return hd_path

    # 1.2 检索本地工作区素材目录下的 HD 资产
    workspace_card_dir = Path(__file__).parent.parent.parent.parent / "CardBase等3项文件"
    if workspace_card_dir.exists():
        ws_type_dir = workspace_card_dir / asset_type
        ws_hd = ws_type_dir / f"{filename_no_ext}.png"
        if ws_hd.exists() and ws_hd.stat().st_size > 1000:
            return ws_hd

    # 1.3 尝试从 CDN 检索并下载 HD 资产
    hd_url = f"{LXNS_ASSET_BASE}/{asset_type}/{filename_no_ext}.png"
    try:
        resp = httpx.get(hd_url, timeout=15, follow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > 1000:
            hd_path.write_bytes(resp.content)
            log.info(f"下载卡面高清（HD）资产成功: {hd_path.name}")
            return hd_path
    except Exception as e:
        log.warning(f"下载卡面高清（HD）资产失败 ({hd_url}): {e}")

    # --- 阶段 2：标清（SD）资产检索与下载（作为高清缺失或下载失败时的兜底） ---
    # 2.1 检索本地缓存目录下的 SD 资产
    if sd_path.exists() and sd_path.stat().st_size > 1000:
        return sd_path

    # 2.2 检索本地工作区素材目录下的 SD 资产
    if workspace_card_dir.exists():
        ws_type_dir = workspace_card_dir / asset_type
        ws_sd = ws_type_dir / f"{filename_no_ext}_S.png"
        if ws_sd.exists() and ws_sd.stat().st_size > 1000:
            return ws_sd

    # 2.3 尝试从 CDN 检索并下载 SD 资产
    sd_url = f"{LXNS_ASSET_BASE}/{asset_type}/{filename_no_ext}_S.png"
    try:
        resp = httpx.get(sd_url, timeout=15, follow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > 1000:
            sd_path.write_bytes(resp.content)
            log.info(f"下载卡面标清（SD）资产成功: {sd_path.name}")
            return sd_path
    except Exception as e:
        log.warning(f"下载卡面标清（SD）资产失败 ({sd_url}): {e}")

    return None



def _find_local_asset(directory: Path, pattern: str) -> Optional[Path]:
    """按 glob 模式在目录下搜索资产文件"""
    import glob
    files = glob.glob(str(directory / pattern))
    if files:
        return Path(files[0])
    return None


class DrawPass:
    # 合成画幅（高分辨率工作区）
    CANVAS_W = 768
    CANVAS_H = 1052
    # 最终输出尺寸
    OUTPUT_W = 750
    OUTPUT_H = 1031

    def __init__(
        self,
        nickname: str,
        rating: int,
        qqid: int,
        friend_code: Optional[Union[int, str]] = None,
        chara_id: Optional[Union[int, str]] = None,
        frame_id: Optional[Union[int, str]] = None,
        base_id: Optional[Union[int, str]] = None,
        draw_stamps: Optional[bool] = None,
    ) -> None:
        self.nickname = nickname
        self.rating = rating
        self.qqid = qqid
        self.friend_code = str(friend_code) if friend_code else None

        # 角色 ID → 6 位补零
        self.chara_id = str(chara_id).zfill(6) if chara_id else "000101"

        # 卡框 ID → 7 位补零
        if frame_id is not None:
            try:
                self.frame_id = f"{int(frame_id):07d}"
            except (ValueError, TypeError):
                self.frame_id = str(frame_id).zfill(7)
        else:
            self.frame_id = "0000006"

        # 底板 ID：命名格式为 UI_CardBase_{frame_id}_{plate_id}_S.png
        # plate_id 来自 name_plate.id，6 位补零
        if base_id is not None:
            try:
                self.plate_id = f"{int(base_id):06d}"
            except (ValueError, TypeError):
                self.plate_id = str(base_id).zfill(6)
        else:
            self.plate_id = "000001"

        # 特权印章开关：如果是金卡框（"0000005"）默认开启，或手动强开
        self.draw_stamps = draw_stamps if draw_stamps is not None else (self.frame_id == "0000005")


    def _find_rating_plate(self) -> str:
        """根据 rating 决定段位底板文件名后缀"""
        r = self.rating
        if r < 1000:   return '01'
        if r < 2000:   return '02'
        if r < 4000:   return '03'
        if r < 7000:   return '04'
        if r < 10000:  return '05'
        if r < 12000:  return '06'
        if r < 13000:  return '07'
        if r < 14000:  return '08'
        if r < 14500:  return '09'
        if r < 15000:  return '10'
        return '11'

    def _load_layer(self, asset_type: str, filename_no_ext: str, fallback_pattern: Optional[str] = None) -> Optional[Image.Image]:
        """加载并 resize 到画幅尺寸的图层（如果是低清标清小素材，进行放大+反虚/锐化超分辨率处理）"""
        path = _ensure_asset(asset_type, filename_no_ext)
        if not path and fallback_pattern:
            type_dir = CARD_DIR / asset_type
            path = _find_local_asset(type_dir, fallback_pattern)
        if path and path.exists():
            try:
                img = Image.open(path).convert("RGBA")
                w, h = img.size
                if w < self.CANVAS_W or h < self.CANVAS_H:
                    from PIL import ImageFilter
                    img = img.resize((self.CANVAS_W, self.CANVAS_H), Image.Resampling.LANCZOS)
                    # 应用轻微的 UnsharpMask 来让放大的边缘更加清晰锐利，接近高清原图效果
                    img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=130, threshold=2))
                else:
                    img = img.resize((self.CANVAS_W, self.CANVAS_H), Image.Resampling.LANCZOS)
                return img
            except Exception as e:
                log.warning(f"加载图层失败 ({path}): {e}")
        return None

    def _draw_stamp_layer(self, border_color: tuple, stamp_type: int, angle: float) -> Image.Image:
        """
        绘制高精度的圆角矩形特权印章并微倾斜旋转。
        stamp_type: 1 (LV.UP), 2 (MASTER), 3 (Red Folder)
        """
        import math
        stamp_sz = 100
        stamp_img = Image.new("RGBA", (stamp_sz, stamp_sz), (0, 0, 0, 0))
        draw = ImageDraw.Draw(stamp_img)

        # 1. 绘制外部双重圆角矩形边框（白底）
        # 外框：(5, 5, 95, 95)
        draw.rounded_rectangle((5, 5, 95, 95), radius=16, fill=(255, 255, 255, 255), outline=border_color, width=4)
        # 内框：(10, 10, 90, 90)
        draw.rounded_rectangle((10, 10, 90, 90), radius=12, outline=border_color, width=1)

        # 2. 根据印章类型绘制内部矢量图形
        font_tb = str(TBFONT)

        if stamp_type == 1:
            # ── Stamp 1: LV.UP ──
            # A. 顶部文字 "LV.UP"
            try:
                font = ImageFont.truetype(font_tb, 18)
                bbox = draw.textbbox((0, 0), "LV.UP", font=font)
                tw = bbox[2] - bbox[0]
                draw.text(((stamp_sz - tw) // 2, 16), "LV.UP", font=font, fill=border_color)
            except Exception as e:
                log.warning(f"绘制印章 LV.UP 文本失败: {e}")

            # B. 左侧向上箭头：X=25，Y 从 80 指向 46
            draw.line((25, 80, 25, 46), fill=border_color, width=5)
            draw.line((18, 56, 25, 46), fill=border_color, width=5)
            draw.line((32, 56, 25, 46), fill=border_color, width=5)

            # C. 右侧齿轮与笑脸：中心 (62, 63)，齿轮外径 15
            cx, cy = 62, 63
            for angle_deg in range(0, 360, 45):
                rad = math.radians(angle_deg)
                tx = cx + 15 * math.cos(rad)
                ty = cy + 15 * math.sin(rad)
                draw.ellipse((tx - 3, ty - 3, tx + 3, ty + 3), fill=border_color)
            draw.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), fill=border_color)
            draw.ellipse((cx - 11, cy - 11, cx + 11, cy + 11), fill=(255, 255, 255, 255))
            # 笑眼与微笑
            draw.ellipse((cx - 5, cy - 3, cx - 3, cy - 1), fill=border_color)
            draw.ellipse((cx + 3, cy - 3, cx + 5, cy - 1), fill=border_color)
            draw.arc((cx - 4, cy + 1, cx + 4, cy + 7), start=0, end=180, fill=border_color, width=2)

        elif stamp_type == 2:
            # ── Stamp 2: MASTER ──
            # A. 中央锁头主体（圆角矩形）：X=30~70, Y=48~75
            draw.rounded_rectangle((30, 48, 70, 75), radius=5, fill=(255, 255, 255, 255), outline=border_color, width=3)
            # 锁扣（圆弧）：中心X=50, 半径=13
            draw.arc((37, 26, 63, 48), start=180, end=360, fill=border_color, width=3)
            draw.line((37, 37, 37, 48), fill=border_color, width=3)
            draw.line((63, 37, 63, 48), fill=border_color, width=3)
            # 锁孔
            draw.ellipse((48, 56, 52, 60), fill=border_color)
            draw.line((50, 60, 50, 68), fill=border_color, width=2)

            # B. 两侧开锁流光装饰线
            draw.line((20, 50, 15, 45), fill=border_color, width=2)
            draw.line((20, 58, 14, 58), fill=border_color, width=2)
            draw.line((20, 66, 15, 71), fill=border_color, width=2)
            draw.line((80, 50, 85, 45), fill=border_color, width=2)
            draw.line((80, 58, 86, 58), fill=border_color, width=2)
            draw.line((80, 66, 85, 71), fill=border_color, width=2)

            # C. 底部文字 "MASTER"
            try:
                font = ImageFont.truetype(font_tb, 14)
                bbox = draw.textbbox((0, 0), "MASTER", font=font)
                tw = bbox[2] - bbox[0]
                draw.text(((stamp_sz - tw) // 2, 78), "MASTER", font=font, fill=border_color)
            except Exception as e:
                log.warning(f"绘制印章 MASTER 文本失败: {e}")

        elif stamp_type == 3:
            # ── Stamp 3: Red Folder ──
            # A. 文件夹顶部突出卡榫（Tab）
            draw.polygon([(28, 38), (38, 28), (56, 28), (62, 38)], fill=border_color)
            # B. 文件夹主体
            draw.rounded_rectangle((22, 38, 78, 78), radius=6, fill=(255, 255, 255, 255), outline=border_color, width=4)
            # C. 文件夹中央绘制一颗完美的五角星（中心 50, 58，外径 10）
            points = []
            cx, cy = 50, 58
            for i in range(10):
                r = 10 if i % 2 == 0 else 4
                angle_rad = math.radians(i * 36 - 90)
                points.append((cx + r * math.cos(angle_rad), cy + r * math.sin(angle_rad)))
            draw.polygon(points, fill=border_color)

        # 旋转图层
        rotated = stamp_img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)
        return rotated

    def draw(self) -> Image.Image:
        img = Image.new("RGBA", (self.CANVAS_W, self.CANVAS_H), color=(0, 0, 0, 0))

        # ── 1. 底板图层 (CardBase) ──
        base_filename = f"UI_CardBase_{self.frame_id}_{self.plate_id}"
        base_layer = self._load_layer("CardBase", base_filename, f"*_{self.plate_id}*.*")
        if not base_layer:
            base_layer = self._load_layer("CardBase", "UI_CardBase_0000006_000001", "*_000001*.*")
        if base_layer:
            img.alpha_composite(base_layer, (0, 0))
        else:
            ImageDraw.Draw(img).rectangle((0, 0, self.CANVAS_W, self.CANVAS_H), fill=(30, 30, 40, 255))

        # ── 2. 角色图层 (CardChara) ──
        chara_filename = f"UI_CardChara_{self.chara_id}"
        chara_layer = self._load_layer("CardChara", chara_filename, f"*_{self.chara_id}*.*")
        if not chara_layer:
            chara_layer = self._load_layer("CardChara", "UI_CardChara_000101", "*_000101*.*")
        if chara_layer:
            img.alpha_composite(chara_layer, (0, 0))

        # ── 3. 卡框图层 (CardFrame) ──
        frame_filename = f"UI_CardFrame_{self.frame_id}"
        frame_layer = self._load_layer("CardFrame", frame_filename, f"*_{self.frame_id}*.*")
        if not frame_layer:
            frame_layer = self._load_layer("CardFrame", "UI_CardFrame_0000006", "*_0000006*.*")
        if frame_layer:
            img.alpha_composite(frame_layer, (0, 0))

        # ── 4. 昵称白卡底板 + DX 标志 ──
        nick_plate = Image.new("RGBA", (268, 40), (0, 0, 0, 0))
        nick_draw = ImageDraw.Draw(nick_plate)
        nick_draw.rounded_rectangle((0, 0, 268, 40), radius=6, fill=(255, 255, 255, 255))
        dx_logo_path = maidir / 'DX.png'
        if dx_logo_path.exists():
            try:
                dx_logo = Image.open(dx_logo_path).convert("RGBA").resize((54, 24), Image.Resampling.LANCZOS)
                nick_plate.paste(dx_logo, (208, 8), dx_logo)
            except Exception as e:
                log.warning(f"加载 DX.png 失败: {e}")
        img.alpha_composite(nick_plate, (462, 110))

        # ── 5. 黄色横幅 ──
        banner = Image.new("RGBA", (295, 58), (0, 0, 0, 0))
        banner_draw = ImageDraw.Draw(banner)
        banner_draw.rounded_rectangle((-20, 0, 295, 58), radius=20, fill=(244, 180, 26, 255))
        img.alpha_composite(banner, (0, 797))

        # ── 6. 好友码白卡背景 ──
        if self.friend_code:
            fc_plate = Image.new("RGBA", (268, 28), (0, 0, 0, 0))
            fc_draw = ImageDraw.Draw(fc_plate)
            fc_draw.rounded_rectangle((0, 0, 268, 28), radius=5, fill=(255, 255, 255, 255))
            img.alpha_composite(fc_plate, (460, 149))

        # ── 7. 绘制全部文字 ──
        draw = ImageDraw.Draw(img)
        font_siyuan = str(SIYUAN)
        font_tb = str(TBFONT)

        # A. 昵称（将全角字符转换为半角字符以防止排版松散与溢出，并支持自适应缩放）
        nickname_cleaned = ""
        for char in self.nickname:
            code = ord(char)
            if 0xFF01 <= code <= 0xFF5E:
                nickname_cleaned += chr(code - 0xfee0)
            elif code == 0x3000:
                nickname_cleaned += " "
            else:
                nickname_cleaned += char

        max_nick_width = 200
        nick_font_size = 28
        try:
            while nick_font_size >= 12:
                nick_font = ImageFont.truetype(font_siyuan, nick_font_size)
                bbox = draw.textbbox((0, 0), nickname_cleaned, font=nick_font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                if tw <= max_nick_width:
                    break
                nick_font_size -= 1
            # 水平居中于 464~664（200px 可用宽度），垂直居中于 110~150（40px 高度）
            x_pos = 464 + (max_nick_width - tw) // 2
            y_pos = 110 + (40 - th) // 2
            draw.text((x_pos, y_pos), nickname_cleaned, font=nick_font, fill=(0, 0, 0, 255))
        except Exception as e:
            log.warning(f"绘制昵称文本失败: {e}")

        # B. 好友码（居中显示）
        if self.friend_code:
            try:
                fc_font = ImageFont.truetype(font_tb, 18)
                fc_str = str(self.friend_code)
                bbox = draw.textbbox((0, 0), fc_str, font=fc_font)
                tw = bbox[2] - bbox[0]
                x_pos = 531 + (728 - 531 - tw) // 2
                draw.text((x_pos, 153), fc_str, font=fc_font, fill=(0, 0, 0, 255))
            except Exception as e:
                log.warning(f"绘制好友码文本失败: {e}")

        # C. 黄色横幅文字: "Generate @MizukiBot" + "ブースト期限 YYYY/MM/DD"
        try:
            label_font = ImageFont.truetype(font_siyuan, 16)
            date_font = ImageFont.truetype(font_tb, 20)
            bot_name = getattr(maiconfig, 'botName', 'MizukiBot')
            draw.text((30, 808), f"Generate @{bot_name}", font=label_font, fill=(101, 68, 5, 255))
            expire_date = (datetime.datetime.now() + datetime.timedelta(days=15)).strftime("%Y/%m/%d")
            draw.text((41, 836), "ブースト期限", font=label_font, fill=(101, 68, 5, 255))
            draw.text((152, 834), expire_date, font=date_font, fill=(101, 68, 5, 255))
        except Exception as e:
            log.warning(f"绘制横幅文本失败: {e}")

        # D. 底部卡号：好友码补零到 20 位 + [MizukiBot] YYYY.M.D
        fc_digits = str(self.friend_code).replace(" ", "") if self.friend_code else ""
        if not fc_digits:
            # 如果没有好友码，用 QQ 生成虚拟卡号
            h = hashlib.sha256(str(self.qqid).encode()).hexdigest()
            fc_digits = "".join(str(int(c, 16) % 10) for c in h)[:20]
        fc_digits = fc_digits.ljust(20, "0")[:20]
        formatted_aime = " ".join(fc_digits[i:i+4] for i in range(0, 20, 4))
        now = datetime.datetime.now()
        date_stamp = f"{now.year}.{now.month}.{now.day}"
        bot_name = getattr(maiconfig, 'botName', 'MizukiBot')
        formatted_footer = f"{formatted_aime}    [{bot_name}] {date_stamp}"
        try:
            aime_font = ImageFont.truetype(font_tb, 17)
            draw.text((130, 1003), formatted_footer, font=aime_font, fill=(255, 255, 255, 255))
        except Exception as e:
            log.warning(f"绘制卡号版本号失败: {e}")

        # ── 8. Rating 战力板块 ──
        rating_plate_idx = self._find_rating_plate()
        rating_plate_file = maidir / f"UI_CMN_DXRating_{rating_plate_idx}.png"
        if rating_plate_file.exists():
            try:
                rt_bg = Image.open(rating_plate_file).convert("RGBA").resize((268, 35), Image.Resampling.LANCZOS)
                img.alpha_composite(rt_bg, (462, 34))
            except Exception as e:
                log.warning(f"绘制 Rating 背景框失败: {e}")

        # Rating 数字
        rating_str = str(self.rating)
        rating_list = [int(d) for d in rating_str]
        num_padding = 5 - len(rating_list)
        num_x = [574, 603, 632, 661, 689]
        num_y = 41
        try:
            zero_path = maidir / "UI_NUM_Drating_0.png"
            if zero_path.exists():
                zero_img = Image.open(zero_path).convert("RGBA")
                zero_img = zero_img.resize(
                    (int(zero_img.width * 0.95), int(zero_img.height * 0.95)),
                    Image.Resampling.LANCZOS,
                )
                for idx in range(num_padding):
                    img.alpha_composite(zero_img, (num_x[idx], num_y))
            for idx, digit in enumerate(rating_list):
                dp = maidir / f"UI_NUM_Drating_{digit}.png"
                if dp.exists():
                    di = Image.open(dp).convert("RGBA")
                    di = di.resize(
                        (int(di.width * 0.95), int(di.height * 0.95)),
                        Image.Resampling.LANCZOS,
                    )
                    img.alpha_composite(di, (num_x[num_padding + idx], num_y))
        except Exception as e:
            log.warning(f"绘制 Rating 数值失败: {e}")
        # ── 9. 二维码 ──
        try:
            import qrcode
            qr_url = "https://help.mizuki.top"
            qr = qrcode.QRCode(border=2)
            qr.add_data(qr_url)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
            qr_img = qr_img.resize((130, 130), Image.Resampling.LANCZOS)
            img.alpha_composite(qr_img, (569, 854))
        except ImportError:
            draw.rectangle((569, 854, 699, 984), fill=(255, 255, 255, 255))
            draw.text((579, 894), "QR Code", font=ImageFont.load_default(), fill=(0, 0, 0, 255))
        except Exception as e:
            log.warning(f"生成二维码失败: {e}")

        # ── 9b. 金卡特权印章 (Stamps) ──
        if self.draw_stamps:
            try:
                # 尝试优先加载本地图片资源
                stamp_lvup_path = maidir / 'stamp_lvup.png'
                stamp_master_path = maidir / 'stamp_master.png'
                stamp_red_path = maidir / 'stamp_red.png'

                positions = [(110, 874), (240, 874), (370, 874)]

                # Stamp 1: LV.UP
                if stamp_lvup_path.exists():
                    s1 = Image.open(stamp_lvup_path).convert("RGBA").resize((90, 90), Image.Resampling.LANCZOS)
                    img.alpha_composite(s1, positions[0])
                else:
                    # 动态绘制金色 LV.UP 升级印章
                    s1 = self._draw_stamp_layer((230, 162, 60, 255), 1, -8.0)
                    s1 = s1.resize((90, 90), Image.Resampling.LANCZOS)
                    img.alpha_composite(s1, positions[0])

                # Stamp 2: MASTER
                if stamp_master_path.exists():
                    s2 = Image.open(stamp_master_path).convert("RGBA").resize((90, 90), Image.Resampling.LANCZOS)
                    img.alpha_composite(s2, positions[1])
                else:
                    # 动态绘制紫色 MASTER 印章
                    s2 = self._draw_stamp_layer((142, 68, 173, 255), 2, 5.0)
                    s2 = s2.resize((90, 90), Image.Resampling.LANCZOS)
                    img.alpha_composite(s2, positions[1])

                # Stamp 3: Red Folder
                if stamp_red_path.exists():
                    s3 = Image.open(stamp_red_path).convert("RGBA").resize((90, 90), Image.Resampling.LANCZOS)
                    img.alpha_composite(s3, positions[2])
                else:
                    # 动态绘制红色五角星文件夹印章
                    s3 = self._draw_stamp_layer((231, 76, 60, 255), 3, -12.0)
                    s3 = s3.resize((90, 90), Image.Resampling.LANCZOS)
                    img.alpha_composite(s3, positions[2])
            except Exception as e:
                log.warning(f"绘制特权印章失败: {e}")

        # ── 10. 最终输出 ──
        final_img = img.resize((self.OUTPUT_W, self.OUTPUT_H), Image.Resampling.LANCZOS)
        return final_img
