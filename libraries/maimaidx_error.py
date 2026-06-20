from textwrap import dedent

class UserNotFoundError(Exception):
    def __str__(self) -> str:
        return "未找到此玩家数据。"

class UserNotBindLXNSError(Exception):
    def __init__(self, is_official_bot: bool = True):
        self.is_official = is_official_bot
    def __str__(self) -> str:
        if self.is_official:
            return "❌ 您尚未绑定落雪查分器账户！\n\n💡 请前往落雪个人中心完成QQ授权及战绩同步：\n🔗 [点击前往落雪舞萌个人中心](https://maimai.lxns.net/user/profile?tab=profile)"
        return "❌ 未找到您的落雪玩家数据！\n请前往落雪官网绑定您的QQ号及数据：\nhttps://maimai.lxns.net/user/profile?tab=profile"

class UserNotBindFishError(Exception):
    def __init__(self, is_official_bot: bool = True):
        self.is_official = is_official_bot
    def __str__(self) -> str:
        if self.is_official:
            return "❌ 您尚未绑定水鱼查分器账户！\n\n💡 请前往水鱼官网完成导入与QQ绑定：\n🔗 [点击前往水鱼舞萌查分器](https://www.diving-fish.com/maimaidx/prober/)"
        return "❌ 未找到您的水鱼玩家数据！\n请前往水鱼官网完成数据同步与绑定：\nhttps://www.diving-fish.com/maimaidx/prober/"

class UserDisabledQueryError(Exception):
    def __str__(self) -> str:
        return '该用户禁止了其他人获取数据或未同意用户协议。'

class TokenNotFoundError(Exception):
    def __str__(self) -> str:
        return '未检测到查分器开放平台开发者密钥凭证。'

class UserNotExistsError(Exception):
    def __str__(self) -> str:
        return '该用户不存在。'

class MusicNotPlayError(Exception):
    def __str__(self) -> str:
        return '未游玩该谱面。'

class UnknownError(Exception):
    def __str__(self) -> str:
        return '中继层发生未知异常。'

# ==========================================
# 【关键修复】补回老版本 alias 别名文件依赖的异常类
# ==========================================
class ServerError(Exception):
    def __str__(self) -> str:
        return '服务器连接错误或数据源异常。'
