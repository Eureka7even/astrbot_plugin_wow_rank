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


# Raider.io 月份英文缩写 → 数字（updatedAt 解析用）
_MONTH_NUMS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _format_updated_at(s: str) -> str:
    """将 Raider.io updatedAt（如 “Thu Oct 08 2026 00:04:33 GMT+0000 (Coordinated Universal Time)”）
    转为北京时间 “MM-DD HH:MM”；解析失败则截取前 16 字符兜底。"""
    parts = s.split()
    if len(parts) >= 5 and parts[1] in _MONTH_NUMS:
        try:
            dt = datetime.datetime(
                int(parts[3]), _MONTH_NUMS[parts[1]], int(parts[2]),
                *map(int, parts[4].split(":")[:2]),
                tzinfo=datetime.timezone.utc,
            ) + datetime.timedelta(hours=8)
            return dt.strftime("%m-%d %H:%M")
        except ValueError:
            pass
    return s[:16]


def build_cutoff_vars(regions: list[dict]) -> dict:
    """将多区域 cutoff API 数据转换为 cutoff.html 模板变量。

    regions: [{key, name, color, cutoffs}, ...]，列表顺序即表格列顺序（国服排最前）；
    数据列取各区域全阵营（all）分数，趋势图取首个区域（国服）。
    """
    first = regions[0]
    first_cutoffs = first.get("cutoffs", {}) or {}
    updated = _format_updated_at(first_cutoffs.get("updatedAt", ""))

    tiers = [
        ("前 0.1%", "赛季称号", "p999", "#f26b5a"),
        ("前 1%", "", "p990", "#e3598b"),
        ("前 10%", "", "p900", "#b33bdc"),
        ("前 25%", "", "p750", "#4f67e1"),
        ("前 40%", "", "p600", "#397ece"),
    ]

    cols_meta = [
        {"name": r.get("name", r.get("key", "")), "color": r.get("color", "#8892aa")}
        for r in regions
    ]
    rows = []
    for label, sublabel, key, _color in tiers:
        cols = []
        for r in regions:
            tier = (r.get("cutoffs") or {}).get(key, {})
            cols.append(f"{tier.get('all', {}).get('quantileMinValue', 0):,.1f}")
        rows.append({
            "label": label,
            "sublabel": sublabel,
            "cols": cols,
        })

    # ── 趋势图 SVG 数据（取首个区域，即国服）──
    graph_data = first_cutoffs.get("graphData", {})
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
        "season": "season-mn-2",
        "updated": updated,
        "rows": rows,
        "cols_meta": cols_meta,
        "trend_region": first.get("name", ""),
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


# ── 专精图标 CSS ──────────────────────────────
_icons_css_cache: dict[int, str] = {}
_ICON_GRID = 64  # 雪碧图格子尺寸（specs.scss 生成数据：每图标 64×64，共 7×6 格）

# 队伍成员展示顺序：坦克 → 治疗 → 输出（角色取自 spec_map.json 的 role 字段）
_ROLE_ORDER = {"tank": 0, "healer": 1, "dps": 2}


def build_icons_css(size: int = 32) -> str:
    """读取 spec_icons.css，将雪碧图替换为 base64 data URI 后返回（带缓存）。

    size: 最终图标显示尺寸（px）。雪碧图每格为 64×64，窗口必须与格子一致，
    否则只显示图标局部（32px 窗口截 64px 格子只剩左上 1/4），
    故所有像素尺寸（width/height/size/position）按 size/64 统一换算。

    AstrBot html_render 渲染环境无法加载外部 file:// 资源，
    故将完整 CSS 内联进模板，雪碧图一并内嵌，保证图标绝对可显示。
    """
    global _icons_css_cache
    if size in _icons_css_cache:
        return _icons_css_cache[size]
    import base64
    import re

    css_path = os.path.join(os.path.dirname(__file__), "spec_icons.css")
    png_path = os.path.join(os.path.dirname(__file__), "specs_sprite.png")
    try:
        with open(css_path, encoding="utf-8") as f:
            css = f.read()
        if 'url("specs_sprite.png")' in css and os.path.exists(png_path):
            with open(png_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            # 雪碧图以 CSS 变量声明一次，所有图标类共享（避免 base64 重复 40 次膨胀体积）
            css = css.replace('url("specs_sprite.png")', "var(--spec-sprite)")
            css = f':root{{--spec-sprite:url("data:image/png;base64,{b64}")}}' + css
        k = size / _ICON_GRID
        if k != 1.0:
            css = _scale_icon_css(css, k)
        _icons_css_cache[size] = css
    except OSError as e:
        raise OSError(f"读取专精图标资源失败: {e}") from e
    return css


def _scale_icon_css(css: str, scale: float) -> str:
    """按比例缩放图标 CSS 中的所有像素尺寸（含 background-position 偏移）。"""
    import re  # noqa: PLC0415 与 build_icons_css 保持一致的局部导入风格

    def _px(v: str) -> str:
        return f"{float(v) * scale:g}px"

    css = re.sub(r"width:\s*([0-9.]+)px", lambda m: f"width: {_px(m.group(1))}", css)
    css = re.sub(r"height:\s*([0-9.]+)px", lambda m: f"height: {_px(m.group(1))}", css)
    css = re.sub(
        r"background-size:\s*([0-9.]+)px\s+([0-9.]+)px",
        lambda m: f"background-size: {_px(m.group(1))} {_px(m.group(2))}",
        css,
    )
    css = re.sub(
        r"background-position:\s*(-?[0-9.]+)px\s+(-?[0-9.]+)px",
        lambda m: f"background-position: {_px(m.group(1))} {_px(m.group(2))}",
        css,
    )
    return css


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

    # 内联图标 CSS（雪碧图已转 data URI，可直接嵌入模板）
    icons_css = build_icons_css()

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
        "icons_css": icons_css,
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

    # ── 预计算公会统计数据 ──
    boss_kills_list = data.get("bossKills") or []
    total_bosses = len(boss_kills_list)
    guild_stats: dict[int, dict] = {}  # guild_id -> {killed_count, current_boss, best_percent}

    for idx, bk in enumerate(boss_kills_list):
        boss_num = idx + 1  # 1-based
        for dg in (bk.get("defeatedBy") or {}).get("guilds") or []:
            gid = (dg.get("guild") or {}).get("id")
            if gid:
                s = guild_stats.setdefault(gid, {"killed_count": 0, "current_boss": 0, "best_percent": 0.0})
                s["killed_count"] += 1
                if boss_num > s["current_boss"]:
                    s["current_boss"] = boss_num
        for att in (bk.get("attemptedBy") or {}).get("attempts") or []:
            gid = (att.get("guild") or {}).get("id")
            if gid:
                pct = (att.get("attempt") or {}).get("overall_percent", 0) or 0
                s = guild_stats.setdefault(gid, {"killed_count": 0, "current_boss": 0, "best_percent": 0.0})
                if pct > s["best_percent"]:
                    s["best_percent"] = pct
                if boss_num > s["current_boss"]:
                    s["current_boss"] = boss_num

    # ── 首杀榜单 ──
    rank1_gid = None
    guilds = []
    for i, g in enumerate(data.get("winningGuilds") or []):
        guild = g.get("guild") or {}
        gid = guild.get("id")
        stats = guild_stats.get(gid, {})
        faction = (guild.get("faction") or "").lower()
        guild_realm = guild.get("realm") or {}
        guild_region = guild.get("region") or {}
        guilds.append({
            "rank": g.get("rank", i + 1),
            "name": guild.get("displayName") or guild.get("name") or "?",
            "faction": faction,
            "faction_cn": "部落" if faction == "horde" else "联盟",
            "faction_color": "#FF4444" if faction == "horde" else "#4488FF",
            "realm": guild_realm.get("altName") or guild_realm.get("name") or "",
            "region": guild_region.get("short_name") or "",
            "logo": guild.get("logo") or "",
            "current_boss": stats.get("current_boss", 0),
            "best_percent": stats.get("best_percent", 0.0),
        })
        if g.get("rank") == 1:
            rank1_gid = gid

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
            tz_cn = datetime.timezone(datetime.timedelta(hours=8))
            if isinstance(first_ts, str):
                # 新接口：ISO 8601 字符串（如 "2026-08-21T03:40:38.000Z"）
                try:
                    dt = datetime.datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                except ValueError:
                    dt = None
            else:
                dt = datetime.datetime.fromtimestamp(first_ts, tz=tz_cn)
            if dt:
                first_time = dt.astimezone(tz_cn).strftime("%m-%d %H:%M")

        killer = ""
        if kill_guilds:
            kg = kill_guilds[0].get("guild") or {}
            kg_realm = kg.get("realm") or {}
            killer = kg.get("displayName") or kg.get("name") or "?"
            kr = kg_realm.get("altName") or kg_realm.get("name") or ""
            if kr:
                killer += f"（{kr}）"

        # ── 第一名公会的尝试血量 ──
        best_percent = 0.0
        best_pulls = 0
        if rank1_gid:
            for att in (attempted.get("attempts") or []):
                if (att.get("guild") or {}).get("id") == rank1_gid:
                    attempt_data = att.get("attempt") or {}
                    best_percent = attempt_data.get("overall_percent", 0) or 0
                    best_pulls = attempt_data.get("pulls", 0) or 0
                    break

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
            "best_percent": best_percent,
            "pulls": best_pulls,
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


# ── 大秘境日报 ──────────────────────────────

def _build_daily_comps(
    items: list, by_id: dict, classes_meta: dict
) -> list:
    """将某层数热门队伍配置原始数据转换为模板变量（按 坦克→治疗→输出 排序）。"""
    max_qty = max((c.get("quantity", 0) for c in items), default=0)
    comps = []
    for i, c in enumerate(items, 1):
        members = []
        for m in c.get("group", []):
            meta = by_id.get(str(m.get("spec_id", "")), {})
            class_key = meta.get("class_key", "")
            spec_key = meta.get("spec_key", "")
            spec_name = meta.get("spec_name", "?")
            class_name = meta.get("class_name", "")
            members.append({
                "icon_class": f"spec-{class_key}-{spec_key}",
                "name": f"{spec_name} {class_name}".rstrip(),
                "color": classes_meta.get(str(meta.get("class_id", "")), {}).get(
                    "class_color", "#AAAAAA"
                ) if meta else "#AAAAAA",
                "role": meta.get("role", "dps"),
            })
        # 按 坦克 → 治疗 → 输出 排列（未知名角色排最后）
        members.sort(key=lambda m: _ROLE_ORDER.get(m["role"], 3))
        qty = c.get("quantity", 0)
        comps.append({
            "rank": i,
            "quantity": f"{qty:,}",
            "pct": f"{c.get('pct', 0):.2f}",
            "bar_width": (qty / max_qty * 100) if max_qty else 0,
            "members": members,
        })
    return comps


def build_daily_report_vars(cache: dict) -> dict:
    """将大秘境日报缓存数据转换为 daily_report.html 模板变量。"""
    spec_map = _load_spec_map()
    specs_meta = spec_map.get("specs", {})
    classes_meta = spec_map.get("classes", {})

    # 排行数据以 (class_key, spec_key) 标识
    by_key = {
        (m.get("class_key", ""), m.get("spec_key", "")): m
        for m in specs_meta.values()
    }
    # 队伍配置以 spec_id 标识
    by_id = {str(m.get("spec_id", "")): m for m in specs_meta.values()}

    def _meta_color(meta: dict) -> str:
        return classes_meta.get(str(meta.get("class_id", "")), {}).get(
            "class_color", "#AAAAAA"
        )

    # ── 专精前 100 平均分（按均分降序，失败项排最后）──
    averages = list(cache.get("spec_averages", []))
    averages.sort(key=lambda x: (x.get("avg") is None, -(x.get("avg") or 0)))
    rows = []
    for i, item in enumerate(averages, 1):
        class_key = item.get("class_key", "")
        spec_key = item.get("spec_key", "")
        meta = by_key.get((class_key, spec_key), {})
        avg = item.get("avg")
        top = item.get("max")
        rows.append({
            "rank": i,
            "icon_class": f"spec-{class_key}-{spec_key}",
            "name": f"{meta.get('spec_name', spec_key)} {meta.get('class_name', class_key)}",
            "color": _meta_color(meta) if meta else "#AAAAAA",
            "score": f"{avg:.1f}" if avg is not None else "--",
            "top": f"{top:.1f}" if top is not None else "--",
            "failed": avg is None,
        })

    # ── 当前 CD 热门队伍配置 Top5（15+ / 20+ 各一套）──
    comps_by_level = cache.get("group_comps", {}) or {}
    comps_15 = _build_daily_comps(comps_by_level.get("15", []), by_id, classes_meta)
    comps_20 = _build_daily_comps(comps_by_level.get("20", []), by_id, classes_meta)

    fetched = cache.get("fetched_at", "")
    updated = fetched[:16].replace("T", " ") if fetched else ""

    return {
        "season": cache.get("season", "season-mn-2"),
        "week": cache.get("week", ""),
        "updated": updated,
        "rows": rows,
        "comps_15": comps_15,
        "comps_20": comps_20,
        "icons_css": build_icons_css(24),  # 24px 图标（64px 格子按 3/8 换算，窗口对齐格子）
        "warned": bool(cache.get("skipped")) or bool(cache.get("comps_error")),
        "failed_count": sum(1 for r in rows if r["failed"]),
    }
