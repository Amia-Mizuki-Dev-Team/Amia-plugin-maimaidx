import re
import traceback
from typing import Any, Optional
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg, Depends
from nonebot.exception import FinishedException
from loguru import logger as log

try:
    from zhconv import convert as zh_convert
except ImportError:
    zh_convert = None

from ..libraries.maimaidx_best_50 import appendix_absent_notice, generate
from ..libraries.maimaidx_error import (
    MaimaiError,
    OAuthConsentRequiredError,
    UserNotBindLXNSError,
    UserNotBindFishError,
)
from ..libraries.maimaidx_merge import fish_consent_missing, sources_label
from ..libraries.maimaidx_music import mai
from ..dependencies import get_at_user_id, get_real_qq
from ..release010_import import (
    format_user_error,
    send_error_with_diagnostic,
)

try:
    from ..libraries.maimaidx_player_score import music_global_data, player_score_data, score_line_data
except ImportError:
    music_global_data = None
    player_score_data = None
    score_line_data = None

# ============================================================
# 「B50 锐评」入口（任务 b50-critique-merge · P1b：全删，只留 b50）
# ============================================================
# 昨天这里是**反向**守卫（``rule=_not_coach_critique``）：整条消息恰好是锐评指令时
# 返回 False，把 ``b50锐评`` 让给 coach 的 priority=5 matcher。用户拍板合并入口后
# 方向整个反过来 —— 这些形态现在**由 best50 认领**、行为等同 ``b50``：尾部的
# 「锐评/点评」只是标记，吃掉它、``username`` 必须为空，锐评本体作为附录条拼在
# B50 图下方（见 libraries/maimaidx_best_50.py 的 generate/_render_appendix_png）。
# 守卫因此**退役**：它要拦的形态正是现在要接的形态，留着等于把 b50 自己的指令判死。
#
# 事故根因依然有效，所以这条纪律必须钉死（tests/test_b50_critique_guard.py）：
#   .env 的 COMMAND_START=["/", ""] 含空前缀，而 nonebot/rule.py:418 明示「命令内容
#   与后续消息间无需空格」，所以 on_command('b50') 连 `b50锐评` 这种粘连写法都会
#   认领，CommandArg 于是拿到「锐评」—— **把它当 username 去查分就是昨天那张
#   「落雪（LXNS）没有找到对应的舞萌玩家数据」报错卡的根因**。认领它现在是对的，
#   但标记解析必须先于 username 赋值，且解析后 username 恒为空串。
#
# 为什么仍然不用 force_whitespace=True：它会连带废掉 `b50张三` 这类粘连昵称查询
# （现存合法用法，回归面比要修的 bug 大），而带空格的 `b50 锐评` 本来就有空白、
# 它根本不触发。标记解析在 CommandArg 上做，两种写法一起解决。
#
# 不以 b50 开头的裸 `锐评` / `点评`（含倒序 `锐评b50`）与 best50 无关：on_command
# 本来就接不到它们，由 coach 的 matcher 回一句引导语（coach 侧 P1a 已改）。best50
# 既不拦也不放弃它们，所以不存在「既不认领也没人接」的静默洞。
B50_CRITIQUE_MARKER_PATTERN = r"^(?:无?锐评|无?点评)$"
"""整串恰好是这个标记时 = 用户要（或明确不要）锐评附录，``username`` 必须为空。
写成单个字符串字面量：跨仓库 diff 一眼可比（coach 侧 CRITIQUE_PATTERN 同手法）。"""
_B50_MARKER_RE = re.compile(B50_CRITIQUE_MARKER_PATTERN)

#: 非锚定写法（``b50 锐评 谢谢`` / ``b50锐评一下`` / ``b50 锐评b50``）的**前导**标记。
#: 整串不是标记，但以标记开头 —— 以前整串当 username 去查分，回的是
#: 「没有找到玩家数据」报错卡（用户实测）。现在按标记处理：标记吃掉，尾巴不猜。
_B50_LEADING_MARKER_RE = re.compile(r"^(无?锐评|无?点评)")


def _parse_b50_arg(text: Any) -> tuple[str, bool, bool]:
    """把 CommandArg 纯文本拆成 ``(username, want_appendix, asked_critique)``。

    - ``锐评`` / ``点评``（``b50锐评``、``b50 锐评``、``B50锐评``、``b50点评``、
      ``/b50锐评`` 的尾部）→ ``("", True, True)``：标记吃掉，本次接附录。
      ★ username 恒为空串，这是昨天事故的直接断言点。
    - ``无锐评`` / ``无点评`` → ``("", False, True)``：一次性修饰词，本次不接附录，
      **不做群内持久状态**（下一条裸 ``b50`` 照旧接）。
    - **前导标记 + 尾巴**（``锐评 谢谢`` / ``锐评一下`` / ``锐评b50``）→ 同标记语义
      （m3）：以前整串当 username 去查分，回的是「没有找到玩家数据」报错卡；
      现在标记吃掉、尾巴不猜意图，绝不拿标记当用户名。
    - 其余一律**原样**当 username —— 零回归：``b50张三``、``b50 谢谢锐评`` 这类
      不以标记开头的写法照旧走 b50 原有路径。
    - fail-open：``text`` 为 None / 非字符串 / 取文本抛异常时按空串处理（等同裸
      ``b50``），绝不因为解析打断出图。
    """
    try:
        arg = str(text or "").strip()
    except Exception as exc:  # noqa: BLE001
        log.debug(f"[b50] 参数取文本失败，按空参数处理（等同裸 b50）: {exc!r}")
        return "", True, False
    if not _B50_MARKER_RE.match(arg):
        leading = _B50_LEADING_MARKER_RE.match(arg)
        if leading:
            # m3：前导标记按标记处理（尾巴不猜），不再当 username 查分
            return "", (not leading.group(1).startswith("无")), True
        return arg, True, False
    # 「无」前缀 = 本次不要附录；其余标记 = 要附录
    return "", (not arg.startswith("无")), True


# Keep the score commands ahead of legacy maimaidx installations which may
# still be present in a bot's environment.  A command matcher with the same
# priority is run concurrently in NoneBot, so ``priority=0`` is intentional:
# it lets this plugin handle the command before the usual priority-1 legacy
# matcher and ``block=True`` then prevents that matcher from replying again.
# This is especially important during upgrades, where the old matcher can
# report "没有找到玩家" while the current implementation has already
# generated the requested image.
# 入口改向（P1b）后 best50 **不再挂 rule 守卫**：粘连的「b50锐评」由本 matcher 认领，
# 标记在 handler 里剥掉（见 _parse_b50_arg），coach 的 priority=5 matcher 因此只会
# 看到不以 b50 开头的裸「锐评/点评」并回引导语。
best50 = on_command(
    'b50',
    aliases={'B50', '生成我的B50', '生成B50'},
    priority=0,
    block=True,
)
ap50 = on_command('ap50', aliases={'AP50'}, priority=0, block=True)
minfo = on_command(
    'minfo',
    aliases={'minfo', 'Minfo', 'MINFO', 'info', 'Info', 'INFO'},
    priority=0,
    block=True,
)
ginfo = on_command('ginfo', aliases={'ginfo', 'Ginfo', 'GINFO'}, priority=0, block=True)
score = on_command('分数线', priority=0, block=True)

def get_at_qq(message: MessageEvent) -> Optional[int]:
    for item in message.message:
        if isinstance(item, MessageSegment):
            target = get_at_user_id(item)
            if target is not None:
                return target
    return None

def _resolve_music(name: str) -> tuple[Optional[Any], list[Any]]:
    """Resolve ID/title/alias, retaining ambiguity instead of taking item 1."""
    name = name.strip()
    music = mai.total_list.by_id(name)
    if music:
        return music, [music]
    title_matches = [m for m in mai.total_list if str(m.title) == name]
    if title_matches:
        return (
            title_matches[0] if len(title_matches) == 1 else None,
            title_matches,
        )
    name_lower = name.casefold()
    exact = []
    for sid, aliases in mai.total_alias_list.items():
        alias_lower = [str(a).casefold() for a in aliases]
        if name_lower in alias_lower:
            music = mai.total_list.by_id(sid)
            if music: exact.append(music)
    if exact:
        unique = {str(m.id): m for m in exact}
        return (next(iter(unique.values())) if len(unique) == 1 else None), list(unique.values())
    fuzzy = []
    if len(name_lower) >= 2:
        for sid, aliases in mai.total_alias_list.items():
            if any(name_lower in str(a).casefold() for a in aliases):
                music = mai.total_list.by_id(sid)
                if music: fuzzy.append(music)
    if zh_convert:
        for src in (zh_convert(name_lower, 'zh-cn'), zh_convert(name_lower, 'zh-tw')):
            if src == name_lower:
                continue
            for sid, aliases in mai.total_alias_list.items():
                alias_lower = [str(a).casefold() for a in aliases]
                if src in alias_lower or (len(src) >= 2 and any(src in a for a in alias_lower)):
                    music = mai.total_list.by_id(sid)
                    if music: fuzzy.append(music)
    for m in mai.total_list:
        if m.title.casefold() == name_lower:
            fuzzy.append(m)
    unique = {str(m.id): m for m in fuzzy}
    return (next(iter(unique.values())) if len(unique) == 1 else None), list(unique.values())


def _search_music(name: str) -> Optional[Any]:
    """Compatibility helper for existing consumers; ambiguous results return None."""
    return _resolve_music(name)[0]


def _ambiguous_message(matches: list[Any]) -> str:
    ids = "、".join(str(m.id) for m in matches[:12])
    return f"找到多个可能的曲目，请改用歌曲 ID 查询：{ids}"

@best50.handle()
async def _(bot: Bot, event: MessageEvent, message: Message = CommandArg(), user_id: Optional[int] = Depends(get_at_qq)):
    arg_text = message.extract_plain_text()
    # ★ 标记必须先于 username 解析：「锐评/点评/无锐评」是修饰词，绝不是用户名
    username, want_appendix, asked_critique = _parse_b50_arg(arg_text)
    if asked_critique:
        log.info(
            f"[b50] 锐评入口并入 b50: arg={arg_text!r} → username='' "
            f"appendix={want_appendix}"
        )
    raw_qq = user_id if user_id is not None else event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    if real_qq_str and str(real_qq_str).isdigit():
        qqid = int(real_qq_str)
    elif user_id is not None and str(user_id).isdigit():
        # A native @ segment already carries a real QQ number; qbind is still
        # required for the sender's virtual adapter id, not for this target.
        qqid = int(user_id)
    else:
        qqid = None
    if qqid is None and not username:
        log.warning(f"[b50] 身份断点: 平台身份未完成 qbind 绑定，无法确定查询对象 sender={event.user_id} at={user_id}")
        await best50.finish(
            "我还没把你的平台身份绑定到真实 QQ，先完成 qbind 绑定后再生成 B50。",
            reply_message=True,
        )
    try:
        img_res, notice = await generate(qqid, username, appendix=want_appendix)
        # 只在用户主动打了锐评标记时才播报降级原因：裸 b50 的文字必须与改动前一致
        if asked_critique and want_appendix and not notice:
            # ★ m1：coach 缺席时 generate 保持静默（硬线），这句提示由调用方补
            notice = appendix_absent_notice()
        if asked_critique and notice:
            img_res = img_res + MessageSegment.text(f"\n{notice}")
        await best50.finish(img_res, reply_message=True)
    except FinishedException:
        raise
    except (UserNotBindLXNSError, UserNotBindFishError) as e:
        await send_error_with_diagnostic(best50, e, "MAI", context="b50")
    except MaimaiError as e:
        # Typed upstream/user states are expected outcomes.  Do not log them
        # as an unhandled traceback before the local error writer formats the
        # short chat response (and suppresses a second WebSocket failure).
        await send_error_with_diagnostic(best50, e, "MAI", context="b50")
    except Exception as e:
        log.error(f"[b50] 查询遭遇未捕获异常:\n{traceback.format_exc()}")
        await send_error_with_diagnostic(best50, e, "MAI", context="b50")

@ap50.handle()
async def _(bot: Bot, event: MessageEvent, message: Message = CommandArg(), user_id: Optional[int] = Depends(get_at_qq)):
    username = message.extract_plain_text().strip()
    raw_qq = user_id if user_id is not None else event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    if real_qq_str and str(real_qq_str).isdigit():
        qqid = int(real_qq_str)
    elif user_id is not None and str(user_id).isdigit():
        qqid = int(user_id)
    else:
        qqid = None
    if qqid is None and not username:
        log.warning(f"[ap50] 身份断点: 平台身份未完成 qbind 绑定，无法确定查询对象 sender={event.user_id} at={user_id}")
        await ap50.finish(
            "我还没把你的平台身份绑定到真实 QQ，先完成 qbind 绑定后再生成 AP50。",
            reply_message=True,
        )
    try:
        # merged 调用下水鱼侧自动不参与（无 AP50 数据），降级结果标注“仅落雪”
        # ★ ap50 显式不接锐评附录（appendix=False → 连 capability 表都不查）
        img_res, _notice = await generate(qqid, username, is_ap=True, appendix=False)
        await ap50.finish(img_res, reply_message=True)
    except FinishedException:
        raise
    except (UserNotBindLXNSError, UserNotBindFishError) as e:
        await send_error_with_diagnostic(ap50, e, "MAI", context="ap50")
    except MaimaiError as e:
        await send_error_with_diagnostic(ap50, e, "MAI", context="ap50")
    except Exception as e:
        log.error(f"[ap50] 查询遭遇未捕获异常:\n{traceback.format_exc()}")
        await send_error_with_diagnostic(ap50, e, "MAI", context="ap50")

@minfo.handle()
async def _(bot: Bot, event: MessageEvent, message: Message = CommandArg(), user_id: Optional[int] = Depends(get_at_qq)):
    if not player_score_data:
        await minfo.finish('本地缺少单曲成绩查询组件 (player_score_data)，无法调用此功能。', reply_message=True)
        
    raw_qq = user_id if user_id is not None else event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    # 受保护的水鱼 OAuth 请求必须使用 qbind 解析出的真实 QQ 身份派生 subject；
    # 绝不能把适配器的虚拟 ``event.user_id`` 哈希成 OAuth subject。
    # A native @ segment already contains a real QQ number.  qbind remains
    # mandatory for the sender's virtual adapter id, but must not require a
    # second binding entry for a directly targeted QQ.
    if user_id is not None and str(user_id).isdigit() and not real_qq_str:
        real_qq_str = str(user_id)
    if not real_qq_str or not str(real_qq_str).isdigit():
        log.warning(f"[minfo] 身份断点: 平台身份未完成 qbind 绑定，无法确定查询对象 sender={event.user_id} at={user_id}")
        await minfo.finish(
            '我还没把你的平台身份绑定到真实 QQ，先完成 qbind 绑定后再查询单曲成绩。',
            reply_message=True,
        )
    qqid = int(real_qq_str)
    name = message.extract_plain_text().strip()
    if not name:
        await minfo.finish('请输入曲名或ID', reply_message=True)
        
    music, matches = _resolve_music(name)
    if not music:
        if matches:
            await minfo.finish(_ambiguous_message(matches), reply_message=True)
        await minfo.finish('没有找到这首歌，请检查曲名或 ID 后重试。', reply_message=True)
    
    try:
        data, meta = await player_score_data(qqid, music)
        tip_text = f"\n当前数据源：{sources_label(meta)}。"
        if fish_consent_missing(meta):
            tip_text += "发送「绑定水鱼」可启用双源汇总。"
        await minfo.finish(data + MessageSegment.text(tip_text), reply_message=True)
    except FinishedException:
        raise
    except OAuthConsentRequiredError:
        log.warning(f"[minfo] 成绩获取失败断点: qq={qqid} 水鱼 OAuth 尚未授权 (OAuthConsentRequiredError)")
        if user_id is not None:
            await minfo.finish(
                "指定玩家还没有授权水鱼，请让对方本人发送「绑定水鱼」。",
                reply_message=True,
            )
        await minfo.finish(
            "水鱼完整成绩需要 OAuth 授权，请发送「绑定水鱼」。",
            reply_message=True,
        )
    except MaimaiError as e:
        await send_error_with_diagnostic(minfo, e, "MAI", context="minfo")
    except Exception as e:
        await send_error_with_diagnostic(minfo, e, "MAI", context="minfo")

@ginfo.handle()
async def _(message: Message = CommandArg()):
    if not music_global_data:
        await ginfo.finish('本地缺少全服统计组件 (music_global_data)。', reply_message=True)
        
    args = message.extract_plain_text().strip()
    match = re.match(r'^([绿黄红紫白]?)\s*(.+)$', args, re.IGNORECASE)
    if not match:
        await ginfo.finish('命令格式错误。例: ginfo紫799', reply_message=True)
        
    diff_char = match.group(1)
    name = match.group(2)
    level_index = '绿黄红紫白'.index(diff_char) if diff_char else 3
        
    music, matches = _resolve_music(name)
    if not music:
        await ginfo.finish(_ambiguous_message(matches) if matches else '没有找到这首歌，请检查曲名或 ID 后重试。', reply_message=True)
        
    try:
        pic = await music_global_data(music, level_index)
        await ginfo.finish(pic, reply_message=True)
    except FinishedException:
        raise
    except ValueError:
        await ginfo.finish('该难度暂无全服统计数据，换一个难度或曲目试试。', reply_message=True)
    except MaimaiError as e:
        await send_error_with_diagnostic(ginfo, e, "MAI", context="ginfo")
    except Exception as e:
        log.error(f"[ginfo] 全服统计资产渲染失败:\n{traceback.format_exc()}")
        await send_error_with_diagnostic(ginfo, e, "MAI", context="ginfo")

@score.handle()
async def _(message: Message = CommandArg()):
    if not score_line_data:
        await score.finish('本地缺少分数线查询组件 (score_line_data)。', reply_message=True)
        
    args = message.extract_plain_text().strip().split()
    if args and args[0] == "帮助":
        await score.finish(
            "分数线用法：分数线 紫799 100\n"
            "返回目标达成率下允许的 TAP GREAT 容错，以及 BREAK 50 落的等价值。\n"
            "难度支持：绿、黄、红、紫、白。\n"
            "容错参考：TAP 1/2.5/5，HOLD 2/5/10，SLIDE 3/7.5/15，"
            "TOUCH 1/2.5/5，BREAK 5/12.5/25（另计 200 落）。",
            reply_message=True,
        )
    if len(args) < 2:
        await score.finish('命令格式错误。例: 分数线 紫799 100', reply_message=True)
        
    target_score = args[-1]
    name = " ".join(args[:-1])
    
    match = re.match(r'^([绿黄红紫白]?)\s*(.+)$', name, re.IGNORECASE)
    if not match:
        await score.finish('无法解析难度，例: 分数线 紫799 100', reply_message=True)
        
    diff_char = match.group(1)
    song_name = match.group(2)
    level_index = '绿黄红紫白'.index(diff_char) if diff_char else 3
        
    music, matches = _resolve_music(song_name)
    if not music:
        await score.finish(_ambiguous_message(matches) if matches else '没有找到这首歌，请检查曲名或 ID 后重试。', reply_message=True)
        
    try:
        result_text = score_line_data(music, level_index, float(target_score))
        await score.finish(result_text, reply_message=True)
    except FinishedException:
        raise
    except ValueError:
        await score.finish('格式错误，请输入「分数线 帮助」查看用法。', reply_message=True)
