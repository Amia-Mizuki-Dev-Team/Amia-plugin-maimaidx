import json
import datetime
import random
from io import BytesIO
from typing import Optional, List, Dict, Any, Tuple
from PIL import Image, ImageDraw
from loguru import logger as log

from ..config import *
from .image import DrawText, image_to_base64, rounded_corners, get_cover_image, get_asset_image
from .maimaidx_music import mai
from .maimaidx_best_50 import ScoreBaseImage

CHALLENGE_FILE = mai_sync_data_dir / 'group_challenge.json'

class ChallengeManager(ScoreBaseImage):
    def __init__(self) -> None:
        # We start with a placeholder canvas, will dynamically size on drawing
        super().__init__(Image.new('RGBA', (1000, 400), (20, 22, 32, 255)))
        self.data = None

    def _load_data(self) -> Dict[str, Any]:
        if CHALLENGE_FILE.exists():
            try:
                with open(CHALLENGE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # Check if date is today
                today_str = datetime.date.today().strftime("%Y-%m-%d")
                if data.get("date") == today_str:
                    return data
            except Exception as e:
                log.warning(f"加载课题数据失败: {e}")
        
        # If not exists or date outdated, generate a new challenge
        return self._generate_new_challenge()

    def _generate_new_challenge(self) -> Dict[str, Any]:
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        
        # Robust fallback: if total_list is empty, try loading from local cache file
        if not mai.total_list and music_file.exists():
            try:
                with open(music_file, 'r', encoding='utf-8') as f:
                    local_music = json.load(f)
                from .maimaidx_music import Music, MusicList
                mai.total_list = MusicList([Music(m) for m in local_music])
                log.info(f"ChallengeManager: 从本地缓存加载了 {len(mai.total_list)} 首歌曲。")
            except Exception as e:
                log.warning(f"ChallengeManager: 从本地缓存加载曲库失败: {e}")

        # Filter valid songs (exclude Utage ID >= 100000)
        valid_songs = []
        for m in mai.total_list:
            try:
                mid = int(m.id)
            except ValueError:
                continue
            if mid >= 100000:
                continue
            
            # Filter Expert (2), Master (3), or Re:Master (4)
            available_lvs = []
            try:
                levels = m.get('level')
                ds = m.get('ds')
                if isinstance(levels, list) and isinstance(ds, list):
                    for idx in range(2, len(levels)):
                        if idx < len(ds) and ds[idx] > 0.0:
                            available_lvs.append(idx)
            except Exception:
                continue
            if available_lvs:
                valid_songs.append((m, available_lvs))
        
        if not valid_songs:
            if not mai.total_list:
                log.warning("曲库尚未初始化完毕，返回临时课题数据。")
                return {
                    "date": today_str,
                    "song_id": 0,
                    "song_title": "曲库同步中，请稍后再试",
                    "level_index": 3,
                    "difficulty": "Master",
                    "ds": 0.0,
                    "submissions": {}
                }
            # Fallback in case list is empty but total_list is not
            log.warning("未找到符合课题筛选条件的歌曲，使用第一首备用。")
            song = mai.total_list[0]
            lvs = [3] if len(song.level) > 3 else [len(song.level) - 1]
        else:
            song, lvs = random.choice(valid_songs)

        level_idx = random.choice(lvs)
        diff_label = diffs[level_idx]
        
        new_data = {
            "date": today_str,
            "song_id": int(song.id),
            "song_title": song.title,
            "level_index": level_idx,
            "difficulty": diff_label,
            "ds": song.ds[level_idx],
            "submissions": {}
        }
        
        self._save_data(new_data)
        return new_data

    def _save_data(self, data: Dict[str, Any]):
        try:
            CHALLENGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CHALLENGE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f"保存课题数据失败: {e}")

    def get_challenge_info(self) -> Dict[str, Any]:
        if self.data is None:
            self.data = self._load_data()
        # If it was a placeholder (song_id == 0) and we now have loaded songs, auto-generate a real one!
        if self.data.get("song_id") == 0 and len(mai.total_list) > 0:
            self.data = self._generate_new_challenge()
        # Double check in case date changed mid-run
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        if self.data.get("date") != today_str:
            self.data = self._generate_new_challenge()
        return self.data

    def submit_score(self, group_id: int, qqid: int, nickname: str, achievements: float) -> Tuple[int, int]:
        """
        Submit score for a group challenge.
        Returns (rank, total_submissions)
        """
        if self.data is None:
            self.data = self._load_data()
            
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        if self.data.get("date") != today_str:
            self.data = self._generate_new_challenge()

        gid_str = str(group_id)
        if gid_str not in self.data["submissions"]:
            self.data["submissions"][gid_str] = []
        
        submissions_list = self.data["submissions"][gid_str]
        
        # Check if user already submitted
        user_submission = None
        for sub in submissions_list:
            if sub["qqid"] == qqid:
                user_submission = sub
                break
        
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if user_submission:
            # Keep highest score
            if achievements > user_submission["achievements"]:
                user_submission["achievements"] = achievements
                user_submission["nickname"] = nickname
                user_submission["time"] = now_str
        else:
            submissions_list.append({
                "qqid": qqid,
                "nickname": nickname,
                "achievements": achievements,
                "time": now_str
            })
        
        # Sort group submissions
        submissions_list.sort(key=lambda x: x["achievements"], reverse=True)
        self._save_data(self.data)
        
        # Find user rank
        rank = 1
        for idx, sub in enumerate(submissions_list):
            if sub["qqid"] == qqid:
                rank = idx + 1
                break
                
        return rank, len(submissions_list)

    async def draw_leaderboard(self, group_id: int) -> Image.Image:
        info = self.get_challenge_info()
        gid_str = str(group_id)
        submissions = info["submissions"].get(gid_str, [])
        
        # Cap leaderboard to top 15
        top_subs = submissions[:15]
        
        row_height = 55
        header_height = 180
        footer_height = 80
        height = header_height + max(1, len(top_subs)) * row_height + footer_height
        
        # Create canvas with Mizuki Akiyama custom pink-purple tricolor gradient
        from .image import tricolor_gradient
        self._im = tricolor_gradient(1000, height, (236, 130, 156), (195, 146, 232), (45, 30, 50))
        dr = ImageDraw.Draw(self._im)
        self._sy = DrawText(dr, SIYUAN)
        self._tb = DrawText(dr, TBFONT)
            
        # Draw Honeycomb pattern
        pattern_path = maidir / 'pattern.png'
        if pattern_path.exists():
            try:
                pat = Image.open(pattern_path).convert('RGBA')
                for h in range((height // pat.height) + 1):
                    for w in range((1000 // pat.width) + 1):
                        self._im.alpha_composite(pat, (w * pat.width, h * pat.height))
            except Exception:
                pass

        # 1. Header Details
        self._sy.draw(500, 40, 32, "🏆 今日群课题挑战榜 🏆", (255, 200, 100, 255), 'mm')
        
        song_title = info["song_title"]
        diff_label = info["difficulty"]
        ds = info["ds"]
        song_id = info["song_id"]
        
        # Title length limit
        from .maimaidx_best_50 import coloumWidth, changeColumnWidth
        if coloumWidth(song_title) > 34:
            song_title_disp = changeColumnWidth(song_title, 33) + "..."
        else:
            song_title_disp = song_title
            
        self._sy.draw(220, 95, 20, f"挑战曲目: {song_title_disp}", (255, 255, 255, 255), 'lm')
        
        # Draw difficulty tag color
        diff_colors = [
            (111, 212, 61, 255),
            (248, 183, 9, 255),
            (255, 129, 141, 255),
            (159, 81, 220, 255),
            (219, 170, 255, 255)
        ]
        level_idx = info["level_index"]
        tag_color = diff_colors[level_idx]
        dr.rounded_rectangle((220, 122, 430, 152), radius=5, fill=tag_color)
        self._sy.draw(325, 137, 16, f"{diff_label} 定数 {ds:.1f}", (255, 255, 255, 255), 'mm')

        # Cover image on the top left
        try:
            cover = get_cover_image(song_id, (120, 120))
            cover = rounded_corners(cover, 10, (True, True, True, True))
            self._im.alpha_composite(cover, (70, 50))
        except Exception:
            pass

        # 2. Table Headers
        dr.rounded_rectangle((60, 170, 940, 210), radius=5, fill=(80, 50, 90, 220))
        self._sy.draw(120, 190, 16, "排名", (255, 218, 226, 255), 'mm')
        self._sy.draw(380, 190, 16, "玩家昵称 (QQ)", (255, 218, 226, 255), 'mm')
        self._sy.draw(700, 190, 16, "达成率", (255, 218, 226, 255), 'mm')
        self._sy.draw(850, 190, 16, "提交时间", (255, 218, 226, 255), 'mm')

        # 3. Submissions drawing
        if not top_subs:
            # Empty board state
            y_pos = 220
            dr.rounded_rectangle((60, y_pos, 940, y_pos + row_height), radius=5, fill=(75, 45, 80, 110))
            self._sy.draw(500, y_pos + row_height // 2, 18, "📭 暂无群友提交今日课题成绩，快发送「提交课题」抢沙发！", (236, 180, 200, 255), 'mm')
        else:
            for idx, sub in enumerate(top_subs):
                y_pos = 220 + idx * row_height
                rank = idx + 1
                bg_color = (85, 55, 95, 130) if rank % 2 == 1 else (65, 40, 75, 130)
                dr.rounded_rectangle((60, y_pos, 940, y_pos + row_height - 5), radius=5, fill=bg_color)
                
                # Rank representation
                if rank == 1:
                    rank_text = "🥇 1"
                    rank_color = (255, 215, 0, 255)
                    # Draw a nice left gold strip for Rank 1
                    dr.rectangle((60, y_pos, 65, y_pos + row_height - 5), fill=(255, 215, 0, 255))
                elif rank == 2:
                    rank_text = "🥈 2"
                    rank_color = (210, 225, 255, 255)
                elif rank == 3:
                    rank_text = "🥉 3"
                    rank_color = (244, 164, 96, 255)
                else:
                    rank_text = str(rank)
                    rank_color = (200, 220, 255, 255)
                    
                self._sy.draw(120, y_pos + row_height // 2, 18, rank_text, rank_color, 'mm')
                
                # Nickname & QQ
                nick = sub["nickname"]
                if coloumWidth(nick) > 20:
                    nick = changeColumnWidth(nick, 19) + "..."
                self._sy.draw(220, y_pos + row_height // 2, 16, f"{nick} ({sub['qqid']})", (255, 255, 255, 255), 'lm')
                
                # Achievements
                ach = sub["achievements"]
                self._tb.draw(700, y_pos + row_height // 2, 18, f"{ach:.4f}%", (255, 160, 185, 255), 'mm')
                
                # Submission time
                sub_time = sub["time"]
                # Format time string to MM-DD HH:MM
                try:
                    dt = datetime.datetime.strptime(sub_time, "%Y-%m-%d %H:%M:%S")
                    time_disp = dt.strftime("%m-%d %H:%M")
                except Exception:
                    time_disp = sub_time
                self._tb.draw(850, y_pos + row_height // 2, 14, time_disp, (140, 160, 180, 255), 'mm')

        # Footer
        self._sy.draw(500, height - 35, 14, "同步方式：打完该曲目并同步至查分器后，发送「提交课题」即可自动上传", (130, 140, 160, 255), 'mm')
        
        return self._im

challenge_manager = ChallengeManager()
