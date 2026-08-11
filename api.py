"""
Raider.io API 查询模块
封装角色搜索、Profile 获取、结果格式化等网络请求逻辑。
"""

import asyncio

import aiohttp

from .utils import get_current_season_week, get_class_cn, get_spec_cn


# ── 复用的 ClientSession 与请求常量 ──
_HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
_TIMEOUT = aiohttp.ClientTimeout(total=30)
_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    """获取复用的 ClientSession（懒创建，连接池复用）。"""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=_TIMEOUT, headers=_HEADERS)
    return _session


async def close_session():
    """关闭复用的 ClientSession，供插件 terminate 时调用。"""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


def extract_char_ids(match: dict) -> tuple[str, str, str]:
    """从 search match 中提取 (region, realm_slug, name)。"""
    char_data = match.get("data", match)

    region_info = char_data.get("region", {})
    if isinstance(region_info, dict):
        region = region_info.get("slug", "cn")
    else:
        region = str(region_info or "cn")

    realm_info = char_data.get("realm", {})
    if isinstance(realm_info, dict):
        realm = realm_info.get("slug") or realm_info.get("name", "")
    else:
        realm = str(realm_info or "")

    name = char_data.get("name", "")
    return region, realm, name


class CharacterNotFoundError(Exception):
    """Raider.io Profile API 返回 404"""
    pass


async def search_characters(name: str, limit: int = 10) -> list:
    """
    调用 Raider.io /api/search 搜索角色（精确匹配，避免前缀包含干扰）。
    返回 matches 列表，每项包含 type/name/data 等字段。
    """
    url = "https://raider.io/api/search"
    params = {
        "type": "all",
        "term": name,
    }
    async with _get_session().get(url, params=params) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"搜索 API 错误 HTTP {resp.status}: {text[:200]}")
        data = await resp.json(content_type=None)
        matches = data.get("matches", [])
        return matches[:limit]


async def fetch_cutoffs(region: str = "cn", season: str = "season-mn-1") -> dict:
    """
    获取 M+ 赛季分数线（cutoffs）。
    返回包含 p999/p990/p900/p750/p600 各分段数据的字典。
    """
    url = "https://raider.io/api/v1/mythic-plus/season-cutoffs"
    params = {"region": region, "season": season}
    async with _get_session().get(url, params=params) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"Cutoff API 错误 HTTP {resp.status}: {text[:200]}")
        data = await resp.json(content_type=None)
        return data.get("cutoffs", {})


async def fetch_profile(match: dict) -> dict:
    """
    从 search match 中提取 region/realm/name，调用完整 profile API。
    """
    region, realm, name = extract_char_ids(match)
    if not realm or not name:
        raise ValueError("无法从搜索结果中获取完整的角色信息（realm/name 缺失）")

    return await fetch_character(region, realm, name)


async def fetch_character(region: str, realm: str, name: str) -> dict:
    """
    调用 Raider.io /api/v1/characters/profile 获取完整角色数据。
    """
    url = "https://raider.io/api/v1/characters/profile"
    fields = ",".join(
        [
            "mythic_plus_scores_by_season:current",
            "mythic_plus_best_runs",
            "mythic_plus_ranks",
            "raid_progression",
            "gear",
            "guild",
        ]
    )
    params = {
        "region": region,
        "realm": realm,
        "name": name,
        "fields": fields,
    }
    try:
        async with _get_session().get(url, params=params) as resp:
            if resp.status == 404:
                raise CharacterNotFoundError()
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Profile API 错误 HTTP {resp.status}: {text[:300]}")
            return await resp.json(content_type=None)
    except asyncio.TimeoutError:
        raise Exception(
            f"查询角色 {name}@{realm}({region}) 超时，请稍后重试或确认 Raider.io 服务状态。"
        )


async def fetch_spec_popularity(
    season: str = "season-mn-1",
    min_mythic_level: int = 2,
    week: int | None = None,
) -> dict:
    """
    获取专精热度统计。
    week 为 None 时查询全周期；传入具体周数时查询该周数据。
    min_mythic_level 最小为 2（API 要求）。
    """
    url = "https://raider.io/api/statistics/get-data"
    if min_mythic_level < 2:
        min_mythic_level = 2
    params = {
        "season": season,
        "type": "spec-popularity",
        "minMythicLevel": min_mythic_level,
        "maxMythicLevel": 99,
        "version": 3,
        "timedOnly": "false",
        "uniqueCharacters": "false",
        "groupBy": "popularity",
    }
    if week is not None:
        params["seasonWeekStart"] = week
        params["seasonWeekEnd"] = week
    else:
        # 全周期：从第1周到当前周
        current_week = get_current_season_week()
        params["seasonWeekStart"] = 1
        params["seasonWeekEnd"] = current_week

    async with _get_session().get(url, params=params) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"Statistics API 错误 HTTP {resp.status}: {text[:200]}")
        return await resp.json(content_type=None)


def format_match_list(matches: list) -> str:
    """
    将搜索结果格式化为可读的文字列表。
    """
    lines = ["找到以下角色，请发送序号选择（发送「取消」退出，60 秒超时）：\n"]
    for i, m in enumerate(matches, 1):
        d = m.get("data", {})

        char_name = d.get("name", "")

        realm_info = d.get("realm", {})
        realm_name = ""
        if isinstance(realm_info, dict):
            realm_name = realm_info.get("altName") or realm_info.get("name", "")

        class_info = d.get("class", {})
        class_name_en = class_info.get("name", "") if isinstance(class_info, dict) else ""
        class_name = get_class_cn(class_name_en) if class_name_en else ""

        # 新接口 /api/search 返回的 data 中可能包含 spec 或 active_spec_name
        spec_info = d.get("spec", {})
        spec_name = ""
        if isinstance(spec_info, dict):
            spec_name_en = spec_info.get("name", "")
            spec_name = get_spec_cn(class_name_en, spec_name_en) if class_name_en and spec_name_en else ""
        else:
            spec_name = d.get("active_spec_name", "")

        guild_info = d.get("guild")
        guild_name = guild_info.get("name", "") if guild_info else ""

        ilvl = round(d.get("itemLevelEquipped", 0))

        # 取当前赛季综合 M+ 分
        mplus_score = 0
        mplus_data = d.get("mplus", {})
        for season_val in mplus_data.values():
            if isinstance(season_val, dict):
                all_val = season_val.get("all", {})
                mplus_score = max(mplus_score, all_val.get("score", 0) if isinstance(all_val, dict) else 0)

        line = f"{i}. 【{realm_name}】{char_name}"
        if spec_name or class_name:
            line += f"  {spec_name} {class_name}".rstrip()
        if ilvl:
            line += f"  装等{ilvl}"
        if mplus_score:
            line += f"  M+{int(mplus_score)}"
        if guild_name:
            line += f"  <{guild_name}>"
        lines.append(line)

    lines.append(f"\n共 {len(matches)} 条结果")
    return "\n".join(lines)


# ── M+ 进度统计 ──────────────────────────────

async def fetch_mplus_progress(region: str, realm: str, name: str, season: str = "season-mn-1") -> dict:
    """
    获取角色 M+ 赛季进度数据（含限时通关次数统计）。
    返回 characterMythicPlusProgress 字典。
    """
    url = f"https://raider.io/api/characters/{region}/{realm}/{name}/mythic-plus-progress"
    params = {"season": season}
    async with _get_session().get(url, params=params) as resp:
        if resp.status != 200:
            # 非关键数据，返回空字典不阻断主流程
            return {}
        data = await resp.json(content_type=None)
        return data.get("characterMythicPlusProgress", {})


# ── 角色数据刷新 ──────────────────────────────

async def search_realm(realm_slug: str) -> dict:
    """
    搜索 realm 获取 realmId。
    返回 realm 信息 dict（包含 id, name, slug 等）。
    """
    url = "https://raider.io/api/search"
    params = {"type": "realm", "term": realm_slug}
    async with _get_session().get(url, params=params) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"Realm 搜索 API 错误 HTTP {resp.status}: {text[:200]}")
        data = await resp.json(content_type=None)
        matches = data.get("matches", [])
        if not matches:
            raise Exception(f"未找到服务器: {realm_slug}")
        # 返回第一个匹配的 realm 数据
        return matches[0].get("data", {}).get("realm", {})


async def refresh_character(region: str, realm_slug: str, realm_id: int, name: str) -> str:
    """
    创建角色数据刷新任务。
    返回 batchId 用于后续轮询状态。
    """
    url = "https://raider.io/api/crawler/characters"
    payload = {
        "realmId": realm_id,
        "realm": realm_slug,
        "region": region,
        "character": name,
    }
    async with _get_session().post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
    ) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"刷新任务创建失败 HTTP {resp.status}: {text[:200]}")
        data = await resp.json(content_type=None)
        if not data.get("success"):
            raise Exception(f"刷新任务创建失败: {data}")
        return data.get("jobData", {}).get("batchId", "")


async def check_refresh_status(batch_id: str) -> str:
    """
    查询刷新任务状态。
    返回状态字符串: "waiting", "active", "complete" 等。
    """
    url = "https://raider.io/api/crawler/monitor"
    params = {"batchId": batch_id}
    async with _get_session().get(url, params=params) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"刷新状态查询失败 HTTP {resp.status}: {text[:200]}")
        data = await resp.json(content_type=None)
        return data.get("batchInfo", {}).get("status", "unknown")
