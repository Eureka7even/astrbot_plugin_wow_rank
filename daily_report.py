"""大秘境日报：数据拉取、缓存与定时调度。

每日北京时间 0/6/12/18 点刷新缓存（40 专精世界排行前 100 去除极值平均分 + 当前 CD 热门队伍配置 Top5），
用户请求时返回缓存；无缓存则立即拉取一次后缓存。
"""

import asyncio
import datetime
import json
import os

from astrbot.api import logger

from .api import REQUEST_INTERVAL, fetch_group_comps, fetch_spec_ranking_scores
from .constants import DAILY_REFRESH_HOURS
from .utils import get_current_season_week

# 北京时间时区（与 utils.get_current_season_week 一致）
TZ_CN = datetime.timezone(datetime.timedelta(hours=8))

# 日报缓存文件名（存放于 AstrBot data 目录，插件重载不清除）
CACHE_FILE = "daily_cache.json"

# 与「大秘境排行榜.txt」一致的 40 个专精（class_key, spec_key），均已实测有效
DAILY_SPECS = [
    ("warrior", "arms"),
    ("warrior", "fury"),
    ("warrior", "protection"),
    ("paladin", "holy"),
    ("paladin", "protection"),
    ("paladin", "retribution"),
    ("hunter", "beast-mastery"),
    ("hunter", "marksmanship"),
    ("hunter", "survival"),
    ("rogue", "assassination"),
    ("rogue", "outlaw"),
    ("rogue", "subtlety"),
    ("priest", "discipline"),
    ("priest", "holy"),
    ("priest", "shadow"),
    ("death-knight", "blood"),
    ("death-knight", "frost"),
    ("death-knight", "unholy"),
    ("shaman", "elemental"),
    ("shaman", "enhancement"),
    ("shaman", "restoration"),
    ("mage", "arcane"),
    ("mage", "fire"),
    ("mage", "frost"),
    ("warlock", "affliction"),
    ("warlock", "demonology"),
    ("warlock", "destruction"),
    ("monk", "brewmaster"),
    ("monk", "mistweaver"),
    ("monk", "windwalker"),
    ("druid", "balance"),
    ("druid", "feral"),
    ("druid", "guardian"),
    ("druid", "restoration"),
    ("demon-hunter", "havoc"),
    ("demon-hunter", "vengeance"),
    ("demon-hunter", "devourer"),
    ("evoker", "devastation"),
    ("evoker", "preservation"),
    ("evoker", "augmentation"),
]


def _next_refresh_seconds(now: datetime.datetime) -> float:
    """返回距离下一个刷新时刻（0/6/12/18 点整）的秒数，最小 0。"""
    for hour in DAILY_REFRESH_HOURS:
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target >= now:
            return (target - now).total_seconds()
    tomorrow = (now + datetime.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (tomorrow - now).total_seconds()


def _last_refresh_boundary(now: datetime.datetime) -> datetime.datetime:
    """当前时刻之前最近一次应刷新的时间点（0/6/12/18 点中 ≤ now 的最大者）。"""
    for hour in reversed(DAILY_REFRESH_HOURS):
        boundary = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if boundary <= now:
            return boundary
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _trimmed_mean(scores: list[float]) -> float | None:
    """去掉最高、最低各 1 名后求平均（保留 1 位小数）。

    样本不足 3 个时退化为全量平均；无样本返回 None。
    """
    if not scores:
        return None
    vals = sorted(scores)
    trimmed = vals[1:-1] if len(vals) > 2 else vals
    return round(sum(trimmed) / len(trimmed), 1)


class DailyReportService:
    """大秘境日报缓存服务：定时拉取 → 内存缓存 + 持久化文件。"""

    def __init__(self, data_dir: str, season: str = "season-mn-2"):
        self._data_dir = data_dir
        self._season = season
        self._cache: dict | None = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._cache_path = os.path.join(data_dir, CACHE_FILE)
        try:
            os.makedirs(data_dir, exist_ok=True)
        except OSError as e:
            logger.warning(f"[WowDaily] 创建数据目录失败: {e}")
        self._load_cache()

    # ── 对外接口 ──────────────────────────────

    def has_cache(self) -> bool:
        """是否已有可用缓存（供命令层决定是否提示等待）。"""
        return self._cache is not None

    async def get_report(self) -> dict:
        """获取日报数据：有缓存直接返回；无缓存则立即拉取一次（并发安全）。"""
        if self._cache is None:
            await self._refresh()
        return self._cache or {}

    async def start(self):
        """启动后台定时调度任务（不阻塞）。"""
        self._task = asyncio.get_event_loop().create_task(self._scheduler_loop())

    async def stop(self):
        """停止调度任务，供插件 terminate 调用。"""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    # ── 调度循环 ──────────────────────────────

    async def _scheduler_loop(self):
        try:
            now = datetime.datetime.now(TZ_CN)
            if self._cache is None:
                # 无任何缓存 → 立即补刷一次
                await self._refresh()
            else:
                fetched = _parse_fetched_at(self._cache.get("fetched_at", ""))
                if fetched is None or fetched < _last_refresh_boundary(now):
                    # 缓存早于最近一次刷新点 → 补刷
                    await self._refresh()
        except Exception as e:
            logger.error(f"[WowDaily] 启动补刷失败: {e}", exc_info=True)

        while True:
            await asyncio.sleep(_next_refresh_seconds(datetime.datetime.now(TZ_CN)))
            try:
                await self._refresh()
            except Exception as e:
                logger.error(f"[WowDaily] 定时刷新失败: {e}", exc_info=True)

    # ── 数据拉取与计算 ────────────────────────

    async def _refresh(self):
        """全量拉取 40 专精排行 + 队伍配置并写入缓存（持锁，防并发重复拉取）。"""
        async with self._lock:
            await self._do_refresh()

    async def _do_refresh(self):
        week = get_current_season_week()
        spec_averages = []
        skipped = []

        for class_key, spec_key in DAILY_SPECS:
            scores = None
            for attempt in range(2):
                try:
                    scores = await fetch_spec_ranking_scores(
                        "world", self._season, class_key, spec_key
                    )
                    break
                except Exception as e:
                    if attempt == 0:
                        logger.warning(
                            f"[WowDaily] 拉取 {class_key}/{spec_key} 失败，重试: {e}"
                        )
                        await asyncio.sleep(3)
            if scores is None:
                skipped.append(f"{class_key}/{spec_key}")
                logger.error(f"[WowDaily] 拉取 {class_key}/{spec_key} 失败，已跳过")
            spec_averages.append(
                {
                    "class_key": class_key,
                    "spec_key": spec_key,
                    "avg": _trimmed_mean(scores),
                    "max": max(scores) if scores else None,
                }
            )
            await asyncio.sleep(REQUEST_INTERVAL)

        # 当前 CD 热门队伍配置
        comps = {"items": [], "total_quantity": 0}
        comps_error = False
        for attempt in range(2):
            try:
                comps = await fetch_group_comps(self._season, week)
                break
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"[WowDaily] 拉取队伍配置失败，重试: {e}")
                    await asyncio.sleep(3)
        else:
            comps_error = True
            logger.error(f"[WowDaily] 拉取队伍配置失败，已跳过")

        total_qty = comps.get("total_quantity", 0) or 1
        group_comps = [
            {
                "quantity": item.get("quantity", 0),
                "successRate": item.get("successRate", 0),
                "pct": round(item.get("quantity", 0) / total_qty * 100, 2),
                "group": item.get("group", []),
            }
            for item in sorted(
                comps.get("items", []), key=lambda x: x.get("quantity", 0), reverse=True
            )[:5]
        ]

        self._cache = {
            "fetched_at": datetime.datetime.now(TZ_CN).isoformat(timespec="seconds"),
            "season": self._season,
            "week": week,
            "spec_averages": spec_averages,
            "group_comps": group_comps,
            "total_quantity": total_qty,
            "comps_error": comps_error,
            "skipped": skipped,
        }
        self._save_cache()
        ok_count = sum(1 for s in spec_averages if s["avg"] is not None)
        logger.info(
            f"[WowDaily] 日报缓存已更新：{ok_count}/{len(spec_averages)} 专精"
            f"，队伍配置 {len(group_comps)} 条"
            + (f"，跳过: {', '.join(skipped)}" if skipped else "")
        )

    # ── 持久化 ────────────────────────────────

    def _load_cache(self):
        if not os.path.exists(self._cache_path):
            return
        try:
            with open(self._cache_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("fetched_at") and data.get("spec_averages"):
                if not all("max" in s for s in data["spec_averages"]):
                    logger.info("[WowDaily] 本地缓存结构过旧，忽略并等待重新拉取")
                    return
                self._cache = data
                logger.info(f"[WowDaily] 已载入本地日报缓存（{data.get('fetched_at')}）")
        except Exception as e:
            logger.warning(f"[WowDaily] 载入本地缓存失败: {e}")

    def _save_cache(self):
        try:
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[WowDaily] 写入本地缓存失败: {e}")


def _parse_fetched_at(s: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None