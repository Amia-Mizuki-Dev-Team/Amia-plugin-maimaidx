import asyncio
import json
import re
import traceback
from textwrap import dedent

from loguru import logger as log
from nonebot import on_command, on_regex
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.params import CommandArg, RegexMatched
from nonebot.permission import SUPERUSER

from ..config import *
from ..libraries.image import text_to_bytes_io
from ..libraries.maimaidx_api_data import maiApi
from ..libraries.maimaidx_error import ServerError
from ..libraries.maimaidx_model import Alias
from ..libraries.maimaidx_music import mai, update_local_alias

update_alias        = on_command('更新别名库', permission=SUPERUSER)
alias_local_apply   = on_command('添加本地别名', aliases={'添加本地别称'})
alias_song          = on_regex(r'^(id)?\s?(.+)\s?有什么别[名称]$', re.IGNORECASE)


@update_alias.handle()
async def _(event: PrivateMessageEvent):
    try:
        await mai.get_music()
        log.info('手动更新别名库成功')
        await update_alias.send('手动更新别名库成功')
    except Exception as e:
        log.error(f'手动更新别名库失败: {e}')
        await update_alias.send('手动更新别名库失败')


@alias_local_apply.handle()
async def _(event: MessageEvent, message: Message = CommandArg()):
    args = message.extract_plain_text().strip().split()
    if len(args) != 2:
        await alias_local_apply.finish('参数错误', reply_message=True)
    song_id, alias_name = args
    if not mai.total_list.by_id(song_id):
        await alias_local_apply.finish(f'未找到ID「{song_id}」的曲目', reply_message=True)

    local_exist = mai.total_alias_list.get(song_id)
    if local_exist and alias_name.lower() in local_exist:
        await alias_local_apply.finish(f'本地别名库已存在该别名', reply_message=True)
    
    issave = await update_local_alias(song_id, alias_name)
    if not issave:
        msg = '添加本地别名失败'
    else:
        msg = f'已成功为ID「{song_id}」添加别名「{alias_name}」到本地别名库'
    await alias_local_apply.send(msg, reply_message=True)


@alias_song.handle()
async def _(match = RegexMatched()):
    findid = bool(match.group(1))
    name = match.group(2)
    aliases = None
    if findid and name.isdigit():
        alias_aliases = mai.total_alias_list.get(name)
        if not alias_aliases:
            await alias_song.finish(
                '未找到此歌曲\n可以使用「添加本地别名」指令给该乐曲添加别名', 
                reply_message=True
            )
        else:
            aliases = [type('_Alias', (), {'SongID': int(name), 'Alias': alias_aliases})()]
    else:            
        matched = [(sid, als) for sid, als in mai.total_alias_list.items()
                   if name.lower() in [a.lower() for a in als]]
        if matched:
            aliases = [type('_Alias', (), {'SongID': int(sid), 'Alias': als})()
                       for sid, als in matched]
        if not aliases:
            if name.isdigit():
                alias_aliases = mai.total_alias_list.get(name)
                if not alias_aliases:
                    await alias_song.finish(
                        '未找到此歌曲\n可以使用「添加本地别名」指令给该乐曲添加别名', 
                        reply_message=True
                    )
                else:
                    aliases = alias_id
            else:
                await alias_song.finish(
                    '未找到此歌曲\n可以使用「添加本地别名」指令给该乐曲添加别名', 
                    reply_message=True
                )
    if len(aliases) != 1:
        msg = []
        for songs in aliases:
            alias_list = '\n'.join(songs.Alias)
            msg.append(f'ID：{songs.SongID}\n{alias_list}')
        await alias_song.finish(
            f'找到{len(aliases)}个相同别名的曲目：\n' + '\n======\n'.join(msg), 
            reply_message=True
        )

    if len(aliases[0].Alias) == 1:
        await alias_song.finish('该曲目没有别名', reply_message=True)

    msg = f'该曲目有以下别名：\nID：{aliases[0].SongID}\n'
    msg += '\n'.join(aliases[0].Alias)
    await alias_song.finish(msg, reply_message=True)
