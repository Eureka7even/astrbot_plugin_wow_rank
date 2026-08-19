"""WowRank 插件工具函数"""

import datetime
import json
import os

from astrbot.api import logger

from .constants import DUNGEON_MAP_FILE


# season-mn-2 第1周开始日期（周四）
SEASON_MN_2_START = datetime.date(2026, 8, 20)


def get_current_season_week(season_start: datetime.date = SEASON_MN_2_START) -> int:
    """计算当前是赛季第几周（从1开始），基于北京时间。"""
    tz = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(tz)
    today = now.date()
    days_passed = (today - season_start).days
    if days_passed < 0:
        return 1
    return (days_passed // 7) + 1


def load_dungeon_map(path: str = DUNGEON_MAP_FILE) -> dict[str, str]:
    """
    从 dungeons.json 加载副本 slug → 中文名映射。
    兼容两种格式：
      完整格式（与 map.json 相同）: {slug: {"name": "中文名", ...}}
      简单格式: {slug: "中文名"}
    """
    if not os.path.exists(path):
        logger.warning(f"[WowRank] 副本名称文件不存在: {path}")
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        result: dict[str, str] = {}
        for slug, info in data.items():
            if isinstance(info, dict):
                result[slug] = info.get("name") or slug
            elif isinstance(info, str):
                result[slug] = info
        logger.info(f"[WowRank] 已加载 {len(result)} 个副本中文名")
        return result
    except Exception as e:
        logger.error(f"[WowRank] 加载副本名称映射失败: {e}")
        return {}


def score_color(score: float) -> str:
    """根据评分返回对应颜色。"""
    if score >= 3000:
        return "#FF8000"
    if score >= 2500:
        return "#A335EE"
    if score >= 2000:
        return "#0070DD"
    if score >= 1500:
        return "#1EFF00"
    if score >= 500:
        return "#FFFFFF"
    return "#9D9D9D"


def level_color(level: int) -> str:
    """根据大秘境层数返回对应颜色。"""
    if level >= 20:
        return "#FF8000"
    if level >= 15:
        return "#A335EE"
    if level >= 10:
        return "#0070DD"
    if level >= 5:
        return "#1EFF00"
    return "#9D9D9D"


# ── 职业/专精中英文映射（基于 Spec.json）──
_prof_data_cache: dict | None = None


def _load_prof_data() -> dict:
    """懒加载 Spec.json（首次调用时读取，缓存至全局变量）。"""
    global _prof_data_cache
    if _prof_data_cache is None:
        path = os.path.join(os.path.dirname(__file__), "Spec.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _prof_data_cache = json.load(f)
        else:
            _prof_data_cache = {"classes": {}, "specs": {}, "races": {}}
    return _prof_data_cache


def _en_to_key(name: str) -> str:
    """英文名转 key：小写 + 空格变连字符。"""
    return name.lower().replace(" ", "-")


def get_class_cn(class_en: str) -> str:
    """职业英文名 → 中文名。查不到时 fallback 返回原文。"""
    if not class_en:
        return ""
    prof = _load_prof_data()
    key = _en_to_key(class_en)
    return prof.get("classes", {}).get(key, {}).get("name", class_en)


def get_spec_cn(class_en: str, spec_en: str) -> str:
    """专精英文名 → 中文名（需传入职业英文名用于查找）。查不到时 fallback 返回原文。"""
    if not class_en or not spec_en:
        return spec_en
    prof = _load_prof_data()
    class_key = _en_to_key(class_en)
    spec_key = _en_to_key(spec_en)
    specs = prof.get("specs", {}).get(class_key, {})
    return specs.get(spec_key, {}).get("name", spec_en)
