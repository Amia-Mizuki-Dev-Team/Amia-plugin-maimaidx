import uuid
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger as log
from nonebot import get_driver, get_plugin_config
from pydantic import BaseModel, Field, AliasChoices

driver = get_driver()

class Config(BaseModel):
    # ==========================================
    # 【核心路由与双端凭证配置】
    # 使用 AliasChoices 强行兼容大写、小写、带下划线的 env 填写方式，彻底斩断 validation 报错
    # ==========================================
    # 全局缺省路由配置，可选 'lxns' 或 'diving-fish'
    prober_source: str = Field(default="lxns", validation_alias=AliasChoices("prober_source", "PROBER_SOURCE"))
    
    # 落雪数据源路径与 Token
    lxnspath: Optional[str] = Field(default=None, validation_alias=AliasChoices("lxnspath", "LXNSPATH", "lxns_path", "LXNS_PATH"))
    lxnstoken: str = Field(default="", validation_alias=AliasChoices("lxnstoken", "LXNSTOKEN", "lxns_token", "LXNS_TOKEN"))
    
    # 水鱼数据源 Token
    maimaidxtoken: Optional[str] = Field(default="", validation_alias=AliasChoices("maimaidxtoken", "MAIMAIDXTOKEN", "maimai_dx_token", "MAIMAIDX_TOKEN"))
    
    # lxns_b50 数据资源路径（代替 MAIMAIDXPATH）
    lxns_b50_path: Optional[str] = Field(default=None, validation_alias=AliasChoices(
        "lxns_b50_path", "LXNS_B50_PATH", "lxnsb50path", "LXNSB50PATH"
    ))

    # ==========================================
    # 【mai_sync_data 路径 — 默认相对 bot 运行目录下的 data/mai_sync_data】
    # ==========================================
    mai_sync_data_path: Optional[str] = Field(default=None, validation_alias=AliasChoices(
        "mai_sync_data_path", "MAI_SYNC_DATA_PATH", "mai_sync_data", "MAI_SYNC_DATA"
    ))

    # ==========================================
    # 【Markdown/按钮模式 — 适用于 QQ 官方机器人（公域/私域）】
    # use_markdown=True 时启用 Markdown 格式消息和交互按钮
    # official_bot_ids 列表中的机器人会自动启用按钮
    # ==========================================
    use_markdown: bool = Field(default=False, validation_alias=AliasChoices("use_markdown", "USE_MARKDOWN"))
    official_bot_ids: List[str] = Field(default=["3889004352", "3889047402"], validation_alias=AliasChoices("official_bot_ids", "OFFICIAL_BOT_IDS"))

    # ==========================================
    # 【老版本插件存量字段兼容兜底】
    # ==========================================
    maimaidxproberproxy: bool = False
    maimaidxaliasproxy: bool = False
    maimaidxaliaspush: bool = False
    saveinmem: bool = True
    botName: str = list(driver.config.nickname)[0] if driver.config.nickname else 'MizukiBot'

    class Config:
        # 允许外部传入未定义的多余字段而不崩溃
        extra = "allow"

try:
    maiconfig = get_plugin_config(Config)
except Exception as e:
    log.error(f"配置文件加载失败，正在尝试使用内部默认值硬核兜底: {e}")
    maiconfig = Config()

# ==========================================
# 【物理资产路径智能互补对齐总线】
# ==========================================
Root: Path = Path(__file__).parent.absolute()

# 路径优先级：LXNS_B50_PATH > LXNSPATH > 默认 data/lxns_b50
determined_path = "data/lxns_b50"

if maiconfig.lxns_b50_path:
    determined_path = maiconfig.lxns_b50_path
elif maiconfig.lxnspath:
    determined_path = maiconfig.lxnspath
else:
    log.warning("未在 .env 中设置 LXNS_B50_PATH，系统将默认挂载至 data/lxns_b50 目录。")

static: Path = Path(determined_path).resolve()

# 核心游戏资源骨架总线（资源直接位于 static 目录下）
maidir: Path = static / 'pic'
coverdir: Path = static / 'cover'
ratingdir: Path = static / 'rating'
platedir: Path = static / 'plate'

# 确保必要的本地缓存目录安全自愈存在
coverdir.mkdir(parents=True, exist_ok=True)
platedir.mkdir(parents=True, exist_ok=True)
ratingdir.mkdir(parents=True, exist_ok=True)

# ==========================================
# 【兼容别名与统一资源路径】
# maimaidir: maimaidx_player_score.py 中引用了此名称，作为 maidir 的别名
# icondir:   头像缓存目录
# ==========================================
maimaidir: Path = maidir
icondir: Path = static / 'icon'
icondir.mkdir(parents=True, exist_ok=True)

# 核心渲染 UI 字体资源总线
SIYUAN: Path = static / 'common' / 'ResourceHanRoundedCN-Bold.ttf'
SHANGGUMONO: Path = static / 'common' / 'ShangguMonoSC-Regular.otf'
TBFONT: Path = static / 'common' / 'Torus SemiBold.otf'

# ==========================================
# 【mai_sync_data 路径解析 — 默认相对 bot 运行目录下的 data/mai_sync_data】
# 用户可在 .env 中通过 mai_sync_data_path 自定义
# ==========================================
if maiconfig.mai_sync_data_path:
    mai_sync_data_dir = Path(maiconfig.mai_sync_data_path)
else:
    mai_sync_data_dir = Path('data') / 'mai_sync_data'
mai_sync_data_dir.mkdir(parents=True, exist_ok=True)

# ==========================================
# musicDB.json 路径（存放在 mai_sync_data 目录下）
# 用于全量曲绘下载和 song_id 映射，每日同步自动更新
# ==========================================
music_db_path: Path = mai_sync_data_dir / 'musicDB.json'

# 核心数据本地快照缓冲区
music_file: Path = static / 'common' / 'music_data.json'
chart_file: Path = static / 'common' / 'music_chart.json'
guess_file: Path = static / 'lx' / 'group_guess_switch.json'
pie_html_file: Path = static / 'common' / 'temp_pie_sy.html'
SNAPSHOT_JS = Root / 'libraries' / 'snapshot.js'

# ==========================================
# 【舞萌 DX 全量硬编码游戏常量字典总线】
# ==========================================
UUID = uuid.uuid1()
SONGS_PER_PAGE: int = 25
scoreRank: List[str] = ['d', 'c', 'b', 'bb', 'bbb', 'a', 'aa', 'aaa', 's', 's+', 'ss', 'ss+', 'sss', 'sss+']
score_Rank: List[str] = ['d', 'c', 'b', 'bb', 'bbb', 'a', 'aa', 'aaa', 's', 'sp', 'ss', 'ssp', 'sss', 'sssp']
score_Rank_l: Dict[str, str] = {
    'd': 'D', 'c': 'C', 'b': 'B', 'bb': 'BB', 'bbb': 'BBB', 
    'a': 'A', 'aa': 'AA', 'aaa': 'AAA', 's': 'S', 'sp': 'Sp', 
    'ss': 'SS', 'ssp': 'SSp', 'sss': 'SSS', 'sssp': 'SSSp'
}
comboRank: List[str] = ['fc', 'fc+', 'ap', 'ap+']
combo_rank: List[str] = ['fc', 'fcp', 'ap', 'app']
syncRank: List[str] = ['fs', 'fs+', 'fdx', 'fdx+']
sync_rank: List[str] = ['fs', 'fsp', 'fsd', 'fsdp']
sync_rank_p: List[str] = ['fs', 'fsp', 'fdx', 'fdxp']
diffs: List[str] = ['Basic', 'Advanced', 'Expert', 'Master', 'Re:Master']
levelList: List[str] = ['1', '2', '3', '4', '5', '6', '7', '7+', '8', '8+', '9', '9+', '10', '10+', '11', '11+', '12', '12+', '13', '13+', '14', '14+', '15']
achievementList: List[float] = [50.0, 60.0, 70.0, 75.0, 80.0, 90.0, 94.0, 97.0, 98.0, 99.0, 99.5, 100.0, 100.5]
BaseRaSpp: List[float] = [7.0, 8.0, 9.6, 11.2, 12.0, 13.6, 15.2, 16.8, 20.0, 20.3, 20.8, 21.1, 21.6, 22.4]
fcl: Dict[str, str] = {'fc': 'FC', 'fcp': 'FCp', 'ap': 'AP', 'app': 'APp'}
fsl: Dict[str, str] = {'fs': 'FS', 'fsp': 'FSp', 'fsd': 'FSD', 'fdx': 'FSD', 'fsdp': 'FSDp', 'fdxp': 'FSDp', 'sync': 'Sync'}
plate_to_sd_version: Dict[str, str] = {
    '初': 'maimai', '真': 'maimai PLUS', '超': 'maimai GreeN', '檄': 'maimai GreeN PLUS',
    '橙': 'maimai ORANGE', '暁': 'maimai ORANGE PLUS', '晓': 'maimai ORANGE PLUS', '桃': 'maimai PiNK',
    '櫻': 'maimai PiNK PLUS', '樱': 'maimai PiNK PLUS', '紫': 'maimai MURASAKi', '菫': 'maimai MURASAKi PLUS',
    '堇': 'maimai MURASAKi PLUS', '白': 'maimai MiLK', '雪': 'MiLK PLUS', '輝': 'maimai FiNALE', '辉': 'maimai FiNALE'
}
plate_to_dx_version: Dict[str, str] = {
    **plate_to_sd_version,
    '熊': 'maimai でらっくす', '華': 'maimai でらっくす PLUS', '华': 'maimai でらっくす PLUS',
    '爽': 'maimai でらっくす Splash', '煌': 'maimai でらっくす Splash PLUS', '宙': 'maimai でらっくす UNiVERSE',
    '星': 'maimai でらっくす UNiVERSE PLUS', '祭': 'maimai でらっくす FESTiVAL', '祝': 'maimai でらっくす FESTiVAL PLUS',
    '双': 'maimai でらっくす BUDDiES', '宴': 'maimai でらっくす BUDDiES PLUS', '镜': 'maimai でらっくす PRiSM', '彩': 'maimai でらっくす PRiSM PLUS'
}
version_map = {
    '真': ([plate_to_dx_version['真'], plate_to_dx_version['初']], '真'),
    '超': ([plate_to_sd_version['超']], '超'), '檄': ([plate_to_sd_version['檄']], '檄'),
    '橙': ([plate_to_sd_version['橙']], '橙'), '暁': ([plate_to_sd_version['暁']], '暁'),
    '桃': ([plate_to_sd_version['桃']], '桃'), '櫻': ([plate_to_sd_version['櫻']], '櫻'),
    '紫': ([plate_to_sd_version['紫']], '紫'), '菫': ([plate_to_sd_version['菫']], '菫'),
    '白': ([plate_to_sd_version['白']], '白'), '雪': ([plate_to_sd_version['雪']], '雪'),
    '輝': ([plate_to_sd_version['輝']], '輝'),
    '霸': (list(set(plate_to_sd_version.values())), '舞'), '舞': (list(set(plate_to_sd_version.values())), '舞'),
    '熊': ([plate_to_dx_version['熊']], '熊&华'), '华': ([plate_to_dx_version['熊']], '熊&华'), '華': ([plate_to_dx_version['熊']], '熊&华'),
    '爽': ([plate_to_dx_version['爽']], '爽&煌'), '煌': ([plate_to_dx_version['爽']], '爽&煌'),
    '宙': ([plate_to_dx_version['宙']], '宙&星'), '星': ([plate_to_dx_version['宙']], '宙&星'),
    '祭': ([plate_to_dx_version['祭']], '祭&祝'), '祝': ([plate_to_dx_version['祭']], '祭&祝'),
    '双': ([plate_to_dx_version['双']], '双&宴'), '宴': ([plate_to_dx_version['双']], '双&宴'),
    '镜': ([plate_to_dx_version['镜']], '镜&彩'), '彩': ([plate_to_dx_version['镜']], '镜&彩')
}
platecn = {'晓': '暁', '樱': '櫻', '堇': '菫', '辉': '輝', '华': '華'}
category: Dict[str, str] = {
    '流行&动漫': 'anime', '舞萌': 'maimai', 'niconico & VOCALOID': 'niconico', '东方Project': 'touhou',
    '其他游戏': 'game', '音击&中二节奏': 'ongeki', 'POPSアニメ': 'anime', 'maimai': 'maimai',
    'niconicoボーカロイド': 'niconico', '東方Project': 'touhou', 'ゲームバラ电体': 'game',
    'オンゲキCHUNITHM': 'ongeki', '宴会場': '宴会场'
}

# ==========================================
# 【关键修复】放行 Python 内置和 Typing 基础类，满足老文件的依赖需求
# ==========================================
__all__ = [
    "Config", "maiconfig", "Root", "static",
    "maidir", "maimaidir", "coverdir", "ratingdir", "platedir", "icondir",
    "mai_sync_data_dir", "music_db_path",
    "SIYUAN", "SHANGGUMONO", "TBFONT", "music_file", "chart_file", "guess_file", "pie_html_file",
    "SNAPSHOT_JS", "UUID", "SONGS_PER_PAGE", "scoreRank", "score_Rank", "score_Rank_l",
    "comboRank", "combo_rank", "syncRank", "sync_rank", "sync_rank_p", "diffs", "levelList",
    "achievementList", "BaseRaSpp", "fcl", "fsl", "plate_to_sd_version", "plate_to_dx_version",
    "version_map", "platecn", "category",
    "Path", "Dict", "List", "Optional"
]