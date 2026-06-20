import httpx
import traceback
from typing import Optional
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, GroupMessageEvent, MessageSegment
from nonebot.params import CommandArg
from nonebot.exception import FinishedException
from loguru import logger as log

from ..libraries.maimaidx_challenge import challenge_manager
from ..libraries.maimaidx_api_data import maiconfig
from ..libraries.image import image_to_base64
from ..libraries.maimaidx_music import mai

# Command registration
mai_challenge_view = on_command('今日课题', aliases={'mai挑战', '今日挑战', '今日群课题'})
mai_challenge_submit = on_command('提交课题', aliases={'同步课题', '提交挑战', '同步挑战'})

@mai_challenge_view.handle()
async def _(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await mai_challenge_view.finish("❌ 今日课题排行榜仅支持在群聊中查看！")

    group_id = event.group_id
    try:
        # Load/update daily challenge
        info = challenge_manager.get_challenge_info()
        await mai_challenge_view.send(
            f"📅 今日课题随机挑战已就位！\n"
            f"· 歌曲: {info['song_title']}\n"
            f"· 难度: {info['difficulty']} (定数 {info['ds']:.1f})\n"
            f"· 挑战模式: 游玩并同步后，在群里发送「提交课题」即可打榜\n"
            f"正在生成群排行榜面板，请稍候..."
        )
        
        # Render and send scoreboard
        leaderboard_img = await challenge_manager.draw_leaderboard(group_id)
        await mai_challenge_view.finish(MessageSegment.image(image_to_base64(leaderboard_img)), reply_message=True)
    except FinishedException:
        raise
    except Exception as e:
        log.error(f"[今日课题] 查看排行榜失败: {e}\n{traceback.format_exc()}")
        await mai_challenge_view.finish("⚠️ 获取今日课题排行榜失败，请联系管理员。", reply_message=True)


@mai_challenge_submit.handle()
async def _(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await mai_challenge_submit.finish("❌ 课题成绩仅支持在群聊中提交！")

    qqid = event.user_id
    group_id = event.group_id
    info = challenge_manager.get_challenge_info()
    challenge_song_id = info["song_id"]
    if challenge_song_id == 0:
        await mai_challenge_submit.finish("❌ 当前今日课题尚未初始化完成，请稍后再次发送「今日课题」触发初始化！", reply_message=True)
        
    challenge_song_title = info["song_title"]
    challenge_level_index = info["level_index"]
    challenge_difficulty = info["difficulty"]

    if not maiconfig.lxnstoken:
        await mai_challenge_submit.finish("⚠️ Bot 未配置落雪开发者密钥，无法使用成绩同步功能。", reply_message=True)

    await mai_challenge_submit.send("🔍 正在拉取您在落雪的最近游玩记录，请稍候...")

    try:
        headers = {"Authorization": maiconfig.lxnstoken}
        async with httpx.AsyncClient(timeout=15) as client:
            # 1. Fetch friend_code and profile
            profile_res = await client.get(f"https://maimai.lxns.net/api/v0/maimai/player/qq/{qqid}", headers=headers)
            if profile_res.status_code != 200:
                await mai_challenge_submit.finish(
                    "❌ 未在落雪检测到您的绑定信息。\n"
                    "请先前往 https://maimai.lxns.net 绑定 QQ 并在官网个人设置中开启“成绩公开”。", 
                    reply_message=True
                )
            
            pdata = profile_res.json().get("data", {})
            friend_code = pdata.get("friend_code")
            nickname = pdata.get("name", str(qqid))
            if not friend_code:
                await mai_challenge_submit.finish("❌ 无法获取您的落雪好友码，请检查个人设置是否公开。", reply_message=True)
            
            # 2. Fetch recent records
            recents_res = await client.get(
                f"https://maimai.lxns.net/api/v0/maimai/player/{friend_code}/recents",
                headers=headers
            )
            if recents_res.status_code != 200:
                await mai_challenge_submit.finish("❌ 从落雪拉取您的最近游玩记录失败，请稍后再试。", reply_message=True)
            
            recents = recents_res.json().get("data", [])
            if not recents:
                await mai_challenge_submit.finish("📭 您的落雪最近游玩记录为空，请游玩后再试。", reply_message=True)

        # 3. Match daily challenge track and difficulty
        matching_record = None
        for r in recents:
            rid = int(r.get("id") or 0)
            # 健壮匹配：优先 ID 相同；其次取模 10000 相同且在曲库中歌名一致（兼容 DX/标准版前缀差异且防误判）
            is_matched = False
            if rid == challenge_song_id:
                is_matched = True
            elif rid % 10000 == challenge_song_id % 10000:
                song_r = mai.total_list.by_id(str(rid))
                song_c = mai.total_list.by_id(str(challenge_song_id))
                if song_r and song_c and song_r.title == song_c.title:
                    is_matched = True
            
            if is_matched and int(r.get("level_index")) == challenge_level_index:
                # Find the maximum achievement played today
                ach = float(r.get("achievements") or 0.0)
                if not matching_record or ach > matching_record["achievements"]:
                    matching_record = {
                        "achievements": ach,
                        "dx_score": int(r.get("dx_score") or 0),
                        "rate": r.get("rate", ""),
                        "fc": r.get("fc") or "",
                        "fs": r.get("fs") or ""
                    }

        if not matching_record:
            await mai_challenge_submit.finish(
                f"❌ 未在您的落雪最近 50 次成绩中找到课题『{challenge_song_title}』[ {challenge_difficulty} ] 难度的成绩！\n"
                f"请在街机上游玩并上传，或确认游玩的难度无误后，重新发送「提交课题」进行打榜。",
                reply_message=True
            )

        # 4. Submit to challenge database
        ach = matching_record["achievements"]
        rank, total = challenge_manager.submit_score(group_id, qqid, nickname, ach)
        
        await mai_challenge_submit.finish(
            f"✅ 课题成绩提交成功！\n"
            f"· 曲目: {challenge_song_title} [{challenge_difficulty}]\n"
            f"· 今日个人最佳: {ach:.4f}%\n"
            f"· 战况: 您当前在群课题挑战榜中排名第 {rank} / {total} 🏆\n"
            f"发送「今日课题」可以查看完整群排行榜大图！",
            reply_message=True
        )

    except FinishedException:
        raise
    except Exception as e:
        log.error(f"[提交课题] 异常: {e}\n{traceback.format_exc()}")
        await mai_challenge_submit.finish("⚠️ 提交课题成绩时遭遇故障，请联系管理员检修。", reply_message=True)
