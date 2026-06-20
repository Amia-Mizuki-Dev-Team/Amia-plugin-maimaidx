import traceback
from io import BytesIO
from typing import Optional, Union, Tuple
from PIL import Image, ImageDraw

from ..config import *
from .image import DrawText, image_to_base64, rounded_corners, get_asset_image
from .maimaidx_api_data import maiApi
from .maimaidx_best_50 import ScoreBaseImage
from .maimaidx_model import UserInfo

class DrawDuel(ScoreBaseImage):
    def __init__(self, user1: UserInfo, user2: UserInfo, qqid1: Optional[Union[int, str]] = None, qqid2: Optional[Union[int, str]] = None) -> None:
        # We start with a base canvas of 1200 x 800
        super().__init__(Image.new('RGBA', (1200, 800), (20, 22, 32, 255)))
        self.user1 = user1
        self.user2 = user2
        self.qqid1 = qqid1
        self.qqid2 = qqid2

    def _findRaPic(self, rating: int) -> str:
        if rating < 1000: return '01'
        elif rating < 2000: return '02'
        elif rating < 4000: return '03'
        elif rating < 7000: return '04'
        elif rating < 10000: return '05'
        elif rating < 12000: return '06'
        elif rating < 13000: return '07'
        elif rating < 14000: return '08'
        elif rating < 14500: return '09'
        elif rating < 15000: return '10'
        else: return '11'

    async def draw(self) -> Image.Image:
        dr = ImageDraw.Draw(self._im)
        
        # 1. Split gradient background
        for x in range(1200):
            if x < 600:
                ratio = x / 600.0
                # Dark blue gradient for player 1 (left)
                r = int(18 * (1 - ratio) + 30 * ratio)
                g = int(24 * (1 - ratio) + 42 * ratio)
                b = int(55 * (1 - ratio) + 90 * ratio)
            else:
                ratio = (x - 600) / 600.0
                # Dark red gradient for player 2 (right)
                r = int(90 * (1 - ratio) + 30 * ratio)
                g = int(24 * (1 - ratio) + 32 * ratio)
                b = int(30 * (1 - ratio) + 42 * ratio)
            dr.line([(x, 0), (x, 800)], fill=(r, g, b, 255))

        # 2. Grid pattern overlay
        pattern_path = maidir / 'pattern.png'
        if pattern_path.exists():
            try:
                pat = Image.open(pattern_path).convert('RGBA')
                for h in range((800 // pat.height) + 1):
                    for w in range((1200 // pat.width) + 1):
                        self._im.alpha_composite(pat, (w * pat.width, h * pat.height))
            except Exception:
                pass

        # 3. Translucent vertical division line
        dr.line([(600, 0), (600, 800)], fill=(255, 255, 255, 20), width=4)

        # 4. Load & draw avatars
        avatar1 = await self._get_avatar(self.qqid1, self.user1.username)
        avatar2 = await self._get_avatar(self.qqid2, self.user2.username)
        self._im.alpha_composite(avatar1, (255 - 75, 120 - 75))
        self._im.alpha_composite(avatar2, (945 - 75, 120 - 75))

        # 5. Draw nicknames
        self._sy.draw(255, 215, 28, self.user1.nickname, (255, 255, 255, 255), 'mm')
        self._sy.draw(945, 215, 28, self.user2.nickname, (255, 255, 255, 255), 'mm')

        # 6. Draw DX Rating plate & digits
        await self._draw_rating_block(255, 250, self.user1.rating)
        await self._draw_rating_block(945, 250, self.user2.rating)

        # 7. VS badge in the center
        dr.ellipse((545, 85, 655, 195), fill=(30, 35, 55, 255), outline=(255, 255, 255, 255), width=3)
        self._tb.draw(600, 137, 44, "VS", (255, 255, 255, 255), 'mm')

        # 8. Compute stats for comparisons
        sd_ra1 = sum(c.ra for c in self.user1.charts.sd)
        dx_ra1 = sum(c.ra for c in self.user1.charts.dx)
        sd_ra2 = sum(c.ra for c in self.user2.charts.sd)
        dx_ra2 = sum(c.ra for c in self.user2.charts.dx)

        all_charts1 = self.user1.charts.sd + self.user1.charts.dx
        all_charts2 = self.user2.charts.sd + self.user2.charts.dx

        max_ra1 = max((c.ra for c in all_charts1), default=0)
        max_ra2 = max((c.ra for c in all_charts2), default=0)

        ap_count1 = sum(1 for c in all_charts1 if c.fc in ('ap', 'app'))
        fc_count1 = sum(1 for c in all_charts1 if c.fc in ('fc', 'fcp'))
        ap_count2 = sum(1 for c in all_charts2 if c.fc in ('ap', 'app'))
        fc_count2 = sum(1 for c in all_charts2 if c.fc in ('fc', 'fcp'))

        # Shared tracks win/loss comparison
        p1_records = {(c.song_id, c.level_index): c.achievements for c in all_charts1}
        p2_records = {(c.song_id, c.level_index): c.achievements for c in all_charts2}
        shared_keys = set(p1_records.keys()) & set(p2_records.keys())

        p1_wins, p2_wins, draws = 0, 0, 0
        for key in shared_keys:
            ach1 = p1_records[key]
            ach2 = p2_records[key]
            if ach1 > ach2:
                p1_wins += 1
            elif ach2 > ach1:
                p2_wins += 1
            else:
                draws += 1

        # 9. Draw Comparison Rows
        comparisons = [
            # (y, title, val1_str, val2_str, progress1, progress2, color1, color2)
            (350, "B50 总 Rating 战力", str(self.user1.rating), str(self.user2.rating), self.user1.rating / 16500, self.user2.rating / 16500, (100, 150, 255, 255), (255, 120, 120, 255)),
            (430, "最高单曲 Ra 战绩", str(max_ra1), str(max_ra2), max_ra1 / 700, max_ra2 / 700, (100, 180, 255, 255), (255, 140, 140, 255)),
            (510, "新旧版本贡献构成", f"B35:{sd_ra1} | B15:{dx_ra1}", f"B35:{sd_ra2} | B15:{dx_ra2}", dx_ra1 / max(1, dx_ra1 + sd_ra1), dx_ra2 / max(1, dx_ra2 + sd_ra2), (100, 220, 200, 255), (220, 150, 220, 255)),
            (590, "AP / FC 极太全连数", f"{ap_count1} AP | {fc_count1} FC", f"{ap_count2} AP | {fc_count2} FC", ap_count1 / 50, ap_count2 / 50, (100, 255, 180, 255), (255, 180, 100, 255)),
        ]

        for y, title, val1_str, val2_str, prog1, prog2, col1, col2 in comparisons:
            # Row Background
            dr.rounded_rectangle((50, y, 1150, y + 55), radius=8, fill=(35, 42, 60, 150), outline=(60, 75, 105, 255))
            
            # Indicator Label (Middle)
            self._sy.draw(600, y + 27, 18, title, (200, 220, 255, 255), 'mm')

            # Left stats
            self._tb.draw(440, y + 27, 22, val1_str, (255, 255, 255, 255), 'rm')
            # Right stats
            self._tb.draw(760, y + 27, 22, val2_str, (255, 255, 255, 255), 'lm')

            # Left progress bar (extends left from 430)
            dr.rounded_rectangle((100, y + 22, 330, y + 32), radius=3, fill=(45, 55, 75, 255))
            bar_w1 = int(230 * min(1.0, prog1))
            if bar_w1 > 0:
                dr.rounded_rectangle((330 - bar_w1, y + 22, 330, y + 32), radius=3, fill=col1)

            # Right progress bar (extends right from 770)
            dr.rounded_rectangle((870, y + 22, 1100, y + 32), radius=3, fill=(45, 55, 75, 255))
            bar_w2 = int(230 * min(1.0, prog2))
            if bar_w2 > 0:
                dr.rounded_rectangle((870, y + 22, 870 + bar_w2, y + 32), radius=3, fill=col2)

        # 10. Shared tracks win/loss comparison row (Y = 670)
        y_shared = 670
        dr.rounded_rectangle((50, y_shared, 1150, y_shared + 65), radius=8, fill=(30, 50, 80, 180), outline=(80, 110, 160, 255), width=2)
        self._sy.draw(600, y_shared + 32, 18, "同谱面交手胜负手 (B50)", (220, 240, 255, 255), 'mm')

        if shared_keys:
            self._sy.draw(250, y_shared + 32, 22, f"🏆 {p1_wins} 胜", (100, 255, 180, 255), 'mm')
            self._sy.draw(950, y_shared + 32, 22, f"🏆 {p2_wins} 胜", (255, 120, 120, 255), 'mm')
            self._sy.draw(600, y_shared + 50, 14, f"(共同游玩: {len(shared_keys)} 首  |  平局: {draws} 首)", (150, 170, 200, 255), 'mm')
        else:
            self._sy.draw(600, y_shared + 32, 18, "同谱面交手胜负手: 暂无共同游玩曲", (160, 170, 190, 255), 'mm')

        # Footer
        self._sy.draw(600, 770, 16, "Powered By MizukiBot lxns_b50", (130, 140, 160, 255), 'mm')

        return self._im

    async def _get_avatar(self, qqid: Optional[Union[int, str]], lxns_username: Optional[str]) -> Image.Image:
        avatar_img = None
        if lxns_username and lxns_username.isdigit():
            # Try to load cached avatar first
            icon_cache_path = icondir / f"{lxns_username}.png"
            if icon_cache_path.exists():
                try:
                    avatar_img = Image.open(icon_cache_path).convert('RGBA').resize((150, 150))
                except Exception:
                    pass
            else:
                try:
                    from .safe_requests import SafeRequests as cffi_requests
                    async with cffi_requests.AsyncSession(impersonate="chrome110") as client:
                        res = await client.get(f"https://assets2.lxns.net/maimai/icon/{lxns_username}.png", timeout=15)
                    if res.status_code == 200 and not res.content.startswith(b'<'):
                        downloaded = Image.open(BytesIO(res.content)).convert('RGBA')
                        downloaded.save(icon_cache_path, format='PNG')
                        avatar_img = downloaded.resize((150, 150))
                except Exception as e:
                    log.warning(f"下载落雪头像({lxns_username})失败: {e}")

        if not avatar_img and qqid:
            try:
                avatar_bytes = await maiApi.qqlogo(int(qqid))
                avatar_img = Image.open(BytesIO(avatar_bytes)).convert('RGBA').resize((150, 150))
            except Exception as e:
                log.warning(f"获取QQ头像失败(qqid={qqid}): {e}")

        if not avatar_img:
            fallback = maidir / 'UI_Icon_309503.png'
            if fallback.exists():
                avatar_img = Image.open(fallback).convert('RGBA').resize((150, 150))
            else:
                avatar_img = Image.new('RGBA', (150, 150), (100, 100, 100, 255))

        return rounded_corners(avatar_img, 75, (True, True, True, True))

    async def _draw_rating_block(self, cx: int, cy: int, rating: int):
        # Draw DX rating plate under the name
        ra_pic = self._findRaPic(rating)
        ra_plate_path = maidir / f'UI_CMN_DXRating_{ra_pic}.png'
        if ra_plate_path.exists():
            try:
                ra_plate = Image.open(ra_plate_path).convert('RGBA').resize((186, 35))
                self._im.alpha_composite(ra_plate, (cx - 93, cy))
            except Exception:
                pass

        # Draw DX rating digits
        rating_str = f'{rating:05d}'
        for n, digit in enumerate(rating_str):
            digit_path = maidir / f'UI_NUM_Drating_{digit}.png'
            if digit_path.exists():
                try:
                    digit_img = Image.open(digit_path).convert('RGBA').resize((17, 20))
                    self._im.alpha_composite(digit_img, (cx - 93 + 85 + 15 * n, cy + 7))
                except Exception:
                    pass
