"""WowRank 插件常量定义"""

import os

TMPL_PATH = os.path.join(os.path.dirname(__file__), "templates", "card.html")
CUTOFF_TMPL_PATH = os.path.join(os.path.dirname(__file__), "templates", "cutoff.html")
SPEC_POP_TMPL_PATH = os.path.join(os.path.dirname(__file__), "templates", "spec_popularity.html")
HALL_OF_FAME_TMPL_PATH = os.path.join(os.path.dirname(__file__), "templates", "hall_of_fame.html")
SPRITE_PATH = os.path.join(os.path.dirname(__file__), "specs_sprite.png")

# 副本名称映射文件（dungeons.json 与插件同目录）
DUNGEON_MAP_FILE = os.path.join(os.path.dirname(__file__), "dungeons.json")

# WoW 职业颜色
CLASS_COLORS = {
    "Warrior": "#C69B3A",
    "Paladin": "#F48CBA",
    "Hunter": "#AAD372",
    "Rogue": "#FFF468",
    "Priest": "#FFFFFF",
    "Death Knight": "#C41E3A",
    "Shaman": "#0070DD",
    "Mage": "#3FC7EB",
    "Warlock": "#8788EE",
    "Monk": "#00FF98",
    "Druid": "#FF7C0A",
    "Demon Hunter": "#A330C9",
    "Evoker": "#33937F",
}

# 团本键名 → 中文显示名
RAID_TIER_NAMES = {
    "the-venomous-abyss": "烈毒之渊",
    "tier-mn-1": "至暗之夜",
    "manaforge-omega": "奥术锻造站-Ω",
    "liberation-of-undermine": "暗矿解放",
    "nerubar-palace": "涅鲁巴宫殿",
    "amirdrassil-the-dreams-hope": "艾米德拉希尔",
    "aberrus-the-shadowed-crucible": "影渊坩埚",
    "vault-of-the-incarnates": "化身之穹",
}

# 当前赛季团本（/wow 卡片团本进度固定展示该团本，新赛季切换时改这里）
CURRENT_RAID_TIER = "the-venomous-abyss"

RAID_TOTAL_BOSSES_DEFAULT = {
    "the-venomous-abyss": 8,
    "tier-mn-1": 9,
    "manaforge-omega": 9,
    "liberation-of-undermine": 8,
    "nerubar-palace": 8,
}
