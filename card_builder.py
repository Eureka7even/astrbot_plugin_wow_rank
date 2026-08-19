"""战绩卡片与分数线模板变量构建器"""

import datetime
import json
import os

from .constants import (
    CLASS_COLORS,
    CURRENT_RAID_TIER,
    RAID_TIER_NAMES,
    RAID_TOTAL_BOSSES_DEFAULT,
)
from .utils import score_color, level_color

# ── 职业/专精/种族中文映射（懒加载）──
_prof_data_cache: dict | None = None


def _load_prof_data() -> dict:
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


def _get_class_cn(class_en: str) -> str:
    prof = _load_prof_data()
    key = _en_to_key(class_en)
    return prof.get("classes", {}).get(key, {}).get("name", class_en)


def _get_spec_cn(class_en: str, spec_en: str) -> str:
    prof = _load_prof_data()
    class_key = _en_to_key(class_en)
    spec_key = _en_to_key(spec_en)
    specs = prof.get("specs", {}).get(class_key, {})
    return specs.get(spec_key, {}).get("name", spec_en)


def _get_race_cn(race_en: str) -> str:
    prof = _load_prof_data()
    key = _en_to_key(race_en)
    return prof.get("races", {}).get(key, {}).get("name", race_en)


def _parse_ranks(data: dict, class_cn: str) -> list:
    """解析 mythic_plus_ranks，过滤零值，翻译 key。

    class_cn: 角色的中文职业名（如 "德鲁伊"），用于 class/class_X 类排名标签。
    """
    ranks_raw = data.get("mythic_plus_ranks")
    if not ranks_raw:
        return []

    spec_map = _load_spec_map()
    specs_meta = spec_map.get("specs", {})

    # key → 标签翻译（需要 class_cn 动态生成）
    key_label_map = {
        "overall": "全部",
        "class": class_cn,
        "dps": "输出",
        "tank": "坦克",
        "healer": "治疗",
        "class_dps": f"{class_cn} 输出",
        "class_tank": f"{class_cn} 坦克",
        "class_healer": f"{class_cn} 治疗",
    }

    results = []
    for key, val in ranks_raw.items():
        # val = {world: int, region: int, realm: int}
        if not isinstance(val, dict):
            continue
        world = val.get("world", 0)
        region = val.get("region", 0)
        realm = val.get("realm", 0)
        # 跳过全零条目
        if world == 0 and region == 0 and realm == 0:
            continue

        # 翻译 key
        if key.startswith("spec_"):
            spec_id = key.split("_", 1)[1]
            meta = specs_meta.get(spec_id, {})
            if meta:
                label = f"{meta.get('class_name', '')}{meta.get('spec_name', '')}"
            else:
                label = f"专精{spec_id}"
        else:
            label = key_label_map.get(key, key)

        results.append({
            "label": label,
            "world": world,
            "region": region,
            "realm": realm,
        })

    return results


def build_card_vars(data: dict, dungeon_cn_map: dict[str, str], progress_data: dict | None = None) -> dict:
    """将角色 profile API 数据转换为 card.html 模板变量。"""
    # ── 基本信息 ──
    class_name = data.get("class", "")
    spec_name = data.get("active_spec_name") or data.get("spec") or ""
    class_color = CLASS_COLORS.get(class_name, "#C0C0C0")

    class_name_cn = _get_class_cn(class_name)
    spec_name_cn = _get_spec_cn(class_name, spec_name)
    race_raw = data.get("race", "")
    race_cn = _get_race_cn(race_raw) if isinstance(race_raw, str) else ""

    guild_data = data.get("guild") or {}
    guild_name = guild_data.get("name", "")

    faction_raw = data.get("faction", guild_data.get("faction", "")) or ""
    if faction_raw == "horde" or str(faction_raw) == "1":
        faction_display, faction_color = "部落", "#FF4444"
    elif faction_raw == "alliance" or str(faction_raw) == "0":
        faction_display, faction_color = "联盟", "#4488FF"
    else:
        faction_display, faction_color = "", "#AAAAAA"

    char_level = data.get("level", 0)

    gear = data.get("gear") or {}
    ilvl = round(gear.get("item_level_equipped", 0), 1)

    thumbnail = data.get("thumbnail_url", "")
    if thumbnail.startswith("//"):
        thumbnail = "https:" + thumbnail

    realm_raw = data.get("realm", "")
    if isinstance(realm_raw, dict):
        realm_show = realm_raw.get("altName") or realm_raw.get("name") or ""
    else:
        realm_show = str(realm_raw)

    # ── M+ 评分 ──
    mplus_seasons = data.get("mythic_plus_scores_by_season") or []
    mplus_scores = mplus_seasons[0].get("scores", {}) if mplus_seasons else {}
    score_all = float(mplus_scores.get("all", 0))
    score_tank = float(mplus_scores.get("tank", 0))
    score_dps = float(mplus_scores.get("dps", 0))
    score_healer = float(mplus_scores.get("healer", 0))

    # ── 综合最高层数 ──
    best_runs: list = data.get("mythic_plus_best_runs") or []

    def _runs_to_dungeons(runs: list) -> list:
        result = []
        for r in runs:
            dungeon_en = r.get("dungeon", "")
            bg_url = r.get("background_image_url", "")
            if bg_url:
                slug = bg_url.rstrip("/").split("/")[-1].rsplit(".", 1)[0]
                cn_name = dungeon_cn_map.get(slug) or dungeon_en
            else:
                cn_name = dungeon_en
            ms = r.get("clear_time_ms", 0)
            minutes = ms // 60000
            seconds = (ms % 60000) // 1000
            result.append({
                "name": cn_name,
                "level": r.get("mythic_level", 0),
                "color": level_color(r.get("mythic_level", 0)),
                "score": r.get("score", 0.0),
                "time": f"{minutes}:{seconds:02d}",
                "icon_url": r.get("icon_url", ""),
            })
        return sorted(result, key=lambda x: x["level"], reverse=True)

    dungeons = _runs_to_dungeons(best_runs)

    # ── 团本进度 ──
    # 固定展示当前赛季团本（CURRENT_RAID_TIER），不再回退到旧团本
    raid_prog: dict = data.get("raid_progression") or {}
    current_tier = CURRENT_RAID_TIER

    raid_name = RAID_TIER_NAMES.get(current_tier, current_tier)
    normal_prog = heroic_prog = mythic_prog = 0
    total_bosses = RAID_TOTAL_BOSSES_DEFAULT.get(current_tier, 9)
    has_aotc = has_cutting_edge = False

    td = raid_prog.get(current_tier)
    if td:
        total_bosses = td.get("total_bosses", total_bosses)
        normal_prog = td.get("normal_bosses_killed", 0)
        heroic_prog = td.get("heroic_bosses_killed", 0)
        mythic_prog = td.get("mythic_bosses_killed", 0)
        has_aotc = total_bosses > 0 and heroic_prog >= total_bosses
        has_cutting_edge = total_bosses > 0 and mythic_prog >= total_bosses

    # ── M+ 排名 ──
    ranks = _parse_ranks(data, class_name_cn)

    # ── 限时通关次数统计 ──
    keystone_stats = []
    if progress_data:
        raw_stats = progress_data.get("keystoneAggregateStats", [])
        # 按 level 降序排序，只保留 count>0 的条目
        for item in sorted(raw_stats, key=lambda x: x.get("level", 0), reverse=True):
            lvl = item.get("level", 0)
            count = item.get("count", 0)
            if lvl > 0 and count > 0:
                keystone_stats.append({"level": lvl, "count": count})

    return {
        "name": data.get("name", ""),
        "level": char_level,
        "class_name": class_name,
        "spec_name": spec_name,
        "class_name_cn": class_name_cn,
        "spec_name_cn": spec_name_cn,
        "race_cn": race_cn,
        "class_color": class_color,
        "guild": guild_name,
        "realm": realm_show,
        "faction": faction_display,
        "faction_color": faction_color,
        "ilvl": ilvl,
        "achievement_points": data.get("achievement_points", 0),
        "thumbnail_url": thumbnail,
        "mplus_all": int(score_all),
        "mplus_tank": int(score_tank),
        "mplus_dps": int(score_dps),
        "mplus_healer": int(score_healer),
        "score_all_color": score_color(score_all),
        "score_tank_color": score_color(score_tank),
        "score_dps_color": score_color(score_dps),
        "score_healer_color": score_color(score_healer),
        "dungeons": dungeons[:8],
        "raid_name": raid_name,
        "normal_prog": normal_prog,
        "heroic_prog": heroic_prog,
        "mythic_prog": mythic_prog,
        "total_bosses": total_bosses,
        "has_aotc": has_aotc,
        "has_cutting_edge": has_cutting_edge,
        "ranks": ranks,
        "keystone_stats": keystone_stats,
    }


def build_cutoff_vars(cutoffs: dict) -> dict:
    """将 cutoff API 数据转换为 cutoff.html 模板变量。"""
    region_name = cutoffs.get("region", {}).get("name", "CN")
    updated = cutoffs.get("updatedAt", "")[:16]

    tiers = [
        ("前 0.1%", "赛季称号", "p999", "#f26b5a"),
        ("前 1%", "", "p990", "#e3598b"),
        ("前 10%", "", "p900", "#b33bdc"),
        ("前 25%", "", "p750", "#4f67e1"),
        ("前 40%", "", "p600", "#397ece"),
    ]

    rows = []
    for label, sublabel, key, color in tiers:
        tier = cutoffs.get(key, {})
        rows.append({
            "label": label,
            "sublabel": sublabel,
            "all": f"{tier.get('all', {}).get('quantileMinValue', 0):,.1f}",
            "horde": f"{tier.get('horde', {}).get('quantileMinValue', 0):,.1f}",
            "alliance": f"{tier.get('alliance', {}).get('quantileMinValue', 0):,.1f}",
        })

    # ── 趋势图 SVG 数据 ──
    graph_data = cutoffs.get("graphData", {})
    chart_width, chart_height = 720, 280
    pad_left, pad_right, pad_top, pad_bottom = 60, 20, 20, 40
    inner_w = chart_width - pad_left - pad_right
    inner_h = chart_height - pad_top - pad_bottom

    all_y = []
    series_list = []
    for label, sublabel, key, color in tiers:
        gd = graph_data.get(key, {})
        pts = gd.get("data", [])
        if not pts:
            continue
        ys = [p["y"] for p in pts]
        all_y.extend(ys)
        series_list.append({"label": label, "color": color, "points": pts})

    svg_series = []
    x_labels = []
    if all_y and series_list:
        min_y = min(all_y)
        max_y = max(all_y)
        y_range = max_y - min_y if max_y > min_y else 1

        base_pts = list(reversed(max(series_list, key=lambda s: len(s["points"]))["points"]))
        n = len(base_pts)
        x_step = inner_w / (n - 1) if n > 1 else inner_w

        for s in series_list:
            pts = list(reversed(s["points"]))
            path_points = []
            for i, p in enumerate(pts):
                sx = pad_left + i * x_step
                sy = pad_top + inner_h - ((p["y"] - min_y) / y_range) * inner_h
                path_points.append(f"{sx:.1f},{sy:.1f}")
            svg_series.append({
                "label": s["label"],
                "color": s["color"],
                "path": " ".join(path_points),
            })

        idxs = [0, n // 3, 2 * n // 3, n - 1]
        for i in idxs:
            ts = base_pts[i]["x"] / 1000
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            x_labels.append({
                "x": pad_left + i * x_step,
                "text": dt.strftime("%m/%d"),
            })

    return {
        "region": region_name,
        "season": "season-mn-2",
        "updated": updated,
        "rows": rows,
        "chart_width": chart_width,
        "chart_height": chart_height,
        "svg_series": svg_series,
        "x_labels": x_labels,
        "y_min": f"{min(all_y):.0f}" if all_y else "",
        "y_max": f"{max(all_y):.0f}" if all_y else "",
    }


# ── 专精热度 ──────────────────────────────
_spec_map_cache: dict | None = None


def _load_spec_map() -> dict:
    global _spec_map_cache
    if _spec_map_cache is None:
        path = os.path.join(os.path.dirname(__file__), "spec_map.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _spec_map_cache = json.load(f)
        else:
            _spec_map_cache = {"specs": {}, "classes": {}}
    return _spec_map_cache


def build_spec_popularity_vars(
    data: dict,
    region: str = "cn",
    min_level: int = 1,
    week: int | None = None,
) -> dict:
    """将专精热度 API 数据转换为 spec_popularity.html 模板变量。"""
    spec_map = _load_spec_map()
    specs_meta = spec_map.get("specs", {})
    classes_meta = spec_map.get("classes", {})

    raw_items = data.get("data", [])
    raw_items.sort(key=lambda x: x.get("quantity", 0), reverse=True)
    total = sum(item.get("quantity", 0) for item in raw_items) if raw_items else 1

    # 取最大值用于条形宽度归一化
    max_qty = max((item.get("quantity", 0) for item in raw_items), default=1)

    # 读取 CSS sprite 定义
    css_path = os.path.join(os.path.dirname(__file__), "spec_icons.css")
    css_url = ""
    if os.path.exists(css_path):
        css_url = "file:///" + css_path.replace("\\", "/")

    specs = []
    for rank, item in enumerate(raw_items, 1):
        spec_id = str(item.get("spec_id", ""))
        meta = specs_meta.get(spec_id, {})
        class_id = str(meta.get("class_id", ""))
        cls = classes_meta.get(class_id, {})
        qty = item.get("quantity", 0)
        pct = (qty / total) * 100 if total else 0

        class_key = meta.get("class_key", "")
        spec_key = meta.get("spec_key", "")
        icon_class = f"spec-{class_key}-{spec_key}" if class_key and spec_key else ""

        specs.append({
            "rank": rank,
            "spec_name": meta.get("spec_name", "未知"),
            "class_name": meta.get("class_name", ""),
            "color": cls.get("class_color", "#AAAAAA"),
            "bar_color": (cls.get("class_color", "#AAAAAA") + "66"),
            "quantity": f"{qty:,}",
            "percent": f"{pct:.1f}",
            "bar_width": (qty / max_qty) * 100 if max_qty else 0,
            "icon_class": icon_class,
        })

    scope_desc = f"第{week}周" if week else "全周期"
    level_desc = f"{min_level}层+" if min_level > 1 else "全部层数"
    updated = data.get("aggregated_at", "")[:16]

    # 竖向网格线位置（均匀分布4条）
    grid_lines = [int(20 + 760 * i / 5) for i in range(1, 5)]

    return {
        "region": region.upper(),
        "scope_desc": scope_desc,
        "level_desc": level_desc,
        "updated": updated,
        "specs": specs,
        "css_url": css_url,
        "grid_lines": grid_lines,
    }


# ── 团本首杀进度 ──────────────────────────────

HOF_DIFFICULTY_CN = {"mythic": "史诗", "heroic": "英雄", "normal": "普通", "lfr": "随机"}
HOF_REGION_CN = {"world": "世界", "cn": "国服", "us": "美服", "eu": "欧服", "kr": "韩服", "tw": "台服"}

_dungeon_full_cache: dict | None = None


def _load_dungeon_full() -> dict:
    """懒加载完整 dungeons.json（含团本 bosses 映射），缓存至全局变量。"""
    global _dungeon_full_cache
    if _dungeon_full_cache is None:
        path = os.path.join(os.path.dirname(__file__), "dungeons.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _dungeon_full_cache = json.load(f)
        else:
            _dungeon_full_cache = {}
    return _dungeon_full_cache


def _get_boss_cn(raid_slug: str, boss_slug: str) -> str:
    """从 dungeons.json 获取 boss 中文名，找不到返回原文。"""
    raid = _load_dungeon_full().get(raid_slug, {})
    if isinstance(raid, dict):
        boss = raid.get("bosses", {}).get(boss_slug, {})
        if isinstance(boss, dict):
            return boss.get("name") or boss_slug
    return boss_slug


def build_hall_of_fame_vars(data: dict) -> dict:
    """将 Hall of Fame raceProgress 数据转换为模板变量。"""
    raid = data.get("raid") or {}
    region = data.get("region") or {}
    raid_slug = raid.get("slug") or "the-venomous-abyss"
    difficulty = (raid.get("difficulty") or "mythic").lower()

    # ── 首杀榜单 ──
    guilds = []
    for i, g in enumerate(data.get("winningGuilds") or []):
        guild = g.get("guild") or {}
        guild_realm = guild.get("realm") or {}
        guild_region = guild.get("region") or {}
        faction = (guild.get("faction") or "").lower()
        guilds.append({
            "rank": g.get("rank", i + 1),
            "name": guild.get("displayName") or guild.get("name") or "?",
            "faction": faction,
            "faction_cn": "部落" if faction == "horde" else "联盟",
            "faction_color": "#FF4444" if faction == "horde" else "#4488FF",
            "realm": guild_realm.get("altName") or guild_realm.get("name") or "",
            "region": guild_region.get("short_name") or "",
            "logo": guild.get("logo") or "",
        })

    # ── Boss 进度 ──
    bosses = []
    for bk in data.get("bossKills") or []:
        summary = bk.get("bossSummary") or {}
        defeated = bk.get("defeatedBy") or {}
        attempted = bk.get("attemptedBy") or {}
        kill_guilds = defeated.get("guilds") or []

        first_ts = bk.get("firstDefeatedAt")
        first_time = ""
        if first_ts:
            dt = datetime.datetime.fromtimestamp(
                first_ts, tz=datetime.timezone(datetime.timedelta(hours=8))
            )
            first_time = dt.strftime("%m-%d %H:%M")

        killer = ""
        if kill_guilds:
            kg = kill_guilds[0].get("guild") or {}
            kg_realm = kg.get("realm") or {}
            killer = kg.get("displayName") or kg.get("name") or "?"
            kr = kg_realm.get("altName") or kg_realm.get("name") or ""
            if kr:
                killer += f"（{kr}）"

        icon = ""
        boss_slug = bk.get("boss") or ""
        if boss_slug:
            # BOSS 头像必须使用 CDN portrait 格式（raider.io 相对路径图标会 404）
            icon = (
                f"https://cdn.raiderio.net/cdn-cgi/image/quality=75,width=205"
                f"/images/{raid_slug}/portraits/{boss_slug}.png"
            )

        bosses.append({
            "slug": bk.get("boss") or "",
            "name_cn": _get_boss_cn(raid_slug, bk.get("boss") or ""),
            "name_en": summary.get("name") or "",
            "icon": icon,
            "killed": bool(first_ts),
            "first_time": first_time,
            "killer": killer,
            "attempt_count": attempted.get("totalCount", 0),
        })

    # ── 头部信息 ──
    raid_icon = raid.get("icon_url") or ""
    if raid_icon.startswith("/"):
        # 团本图标同样走 CDN（raider.io 域名下 404）
        raid_icon = "https://cdn.raiderio.net" + raid_icon

    return {
        "raid_name_cn": RAID_TIER_NAMES.get(raid_slug) or raid.get("short_name") or raid.get("name") or raid_slug,
        "raid_name_en": raid.get("name") or "",
        "raid_short": raid.get("short_name") or "",
        "raid_icon": raid_icon,
        "difficulty": difficulty,
        "difficulty_cn": HOF_DIFFICULTY_CN.get(difficulty, "史诗"),
        "region": region.get("name") or "",
        "region_cn": HOF_REGION_CN.get(region.get("slug") or "world", "世界"),
        "guilds": guilds,
        "bosses": bosses,
        "total_bosses": len(bosses),
        "killed_count": sum(1 for b in bosses if b["killed"]),
    }
