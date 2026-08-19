"""
AstrBot WoW 战绩查询插件
用法：/wow 角色名
示例：/wow 超倔强双马尾
"""

import asyncio

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger
from astrbot.core.utils.session_waiter import session_waiter, SessionController

from .api import (
    check_refresh_status,
    close_session,
    extract_char_ids,
    fetch_cutoffs,
    fetch_hall_of_fame,
    fetch_mplus_progress,
    fetch_profile,
    fetch_spec_popularity,
    format_match_list,
    refresh_character,
    search_characters,
    search_realm,
)
from .card_builder import (
    build_card_vars,
    build_cutoff_vars,
    build_hall_of_fame_vars,
    build_spec_popularity_vars,
)
from .template_manager import TemplateManager
from .utils import get_current_season_week, load_dungeon_map


class WowRankPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._tmpl = TemplateManager()
        self._dungeon_cn_map = load_dungeon_map()

    # ── 主指令 ────────────────────────────────
    @filter.command("wow")
    async def query_wow(self, event: AstrMessageEvent):
        """查询 WoW 角色战绩卡片。
        用法：/wow 角色名
        示例：/wow 超倔强双马尾"""
        try:
            name = self._parse_args(event.message_str)
            yield event.plain_result(f"正在搜索角色「{name}」...")

            matches = await search_characters(name)

            if not matches:
                yield event.plain_result(
                    f"未找到名为「{name}」的角色，请确认角色名拼写是否正确。"
                )
                return

            if len(matches) == 1:
                # ── 唯一结果，直接出卡 ──
                char = matches[0]
                char_name = char.get("data", {}).get("name", name)
                yield event.plain_result(f"找到角色 {char_name}，正在获取战绩数据...")
                img_url = await self._render_char_card(char)
                yield event.image_result(img_url)

            else:
                # ── 多条结果，展示列表等待用户选择 ──
                show_count = min(len(matches), 10)
                list_text = format_match_list(matches[:show_count])
                yield event.plain_result(list_text)

                async def on_pick(
                    controller: SessionController, event: AstrMessageEvent, char: dict
                ):
                    char_name = char.get("data", {}).get("name", "")
                    await event.send(event.plain_result(f"正在获取 {char_name} 的战绩数据..."))
                    try:
                        img_url = await self._render_char_card(char)
                        await event.send(event.image_result(img_url))
                    except Exception as e:
                        logger.error(f"获取角色详情失败: {e}", exc_info=True)
                        await event.send(event.plain_result(f"获取角色数据失败：{e}"))

                await self._wait_choice(event, matches, "已取消查询。", on_pick)

        except ValueError as e:
            yield event.plain_result(str(e))
        except Exception as e:
            logger.error(f"WoW 战绩查询失败: {e}", exc_info=True)
            yield event.plain_result(f"查询失败：{e}")

    # ── 分数线查询 ───────────────────────────
    @filter.command("wow-cutoff", alias={"wow分数线"})
    async def query_cutoff(self, event: AstrMessageEvent):
        """查询当前国服 M+ 分数线。用法：/wow-cutoff"""
        try:
            cutoffs = await fetch_cutoffs(region="cn", season="season-mn-2")
            if not cutoffs:
                yield event.plain_result("未获取到分数线数据。")
                return

            vars_ = build_cutoff_vars(cutoffs)
            img_url = await self.html_render(
                self._tmpl.cutoff, vars_, options=self._render_options()
            )
            yield event.image_result(img_url)
        except Exception as e:
            logger.error(f"分数线查询失败: {e}", exc_info=True)
            yield event.plain_result(f"分数线查询失败：{e}")

    # ── 专精热度查询 ─────────────────────────
    @filter.command("wow专精热度")
    async def query_spec_popularity(self, event: AstrMessageEvent):
        """查询 M+ 专精热度统计。
        用法：/wow专精热度 [全体|本周] [层数]
        示例：/wow专精热度
              /wow专精热度 本周 15
              /wow专精热度 全体 10"""
        try:
            # 解析参数
            parts = event.message_str.strip().split(None, 1)
            args = parts[1].strip().split() if len(parts) > 1 and parts[1].strip() else []

            week = None
            min_level = 2

            # 第一个参数可能是范围关键词或层数
            if args:
                first = args[0].lower()
                if first in ("本周", "thisweek", "week"):
                    week = get_current_season_week()
                    args = args[1:]
                elif first in ("全体", "all", "total"):
                    args = args[1:]

            # 剩余参数中找层数
            for arg in args:
                if arg.isdigit():
                    min_level = max(int(arg), 2)
                    break

            scope_text = f"第{week}周" if week else "全周期"
            yield event.plain_result(f"正在获取 {scope_text} {min_level}层+ 专精热度数据...")

            data = await fetch_spec_popularity(
                season="season-mn-2",
                min_mythic_level=min_level,
                week=week,
            )
            if not data or not data.get("data"):
                yield event.plain_result("未获取到专精热度数据。")
                return

            vars_ = build_spec_popularity_vars(data, region="cn", min_level=min_level, week=week)
            img_url = await self.html_render(
                self._tmpl.spec_popularity, vars_, options=self._render_options()
            )
            yield event.image_result(img_url)
        except Exception as e:
            logger.error(f"专精热度查询失败: {e}", exc_info=True)
            yield event.plain_result(f"专精热度查询失败：{e}")

    # ── 团本首杀进度 ─────────────────────
    @filter.command("wow首杀")
    async def query_hall_of_fame(self, event: AstrMessageEvent):
        """查询团本首杀进度。
        用法：/wow首杀 [难度] [区域]
        示例：/wow首杀
              /wow首杀 英雄
              /wow首杀 史诗 世界"""
        try:
            parts = event.message_str.strip().split(None, 1)
            args = parts[1].strip().split() if len(parts) > 1 and parts[1].strip() else []

            difficulty = "mythic"
            region = "world"
            for arg in args:
                a = arg.lower()
                if a in ("史诗", "mythic", "m"):
                    difficulty = "mythic"
                elif a in ("英雄", "heroic", "h"):
                    difficulty = "heroic"
                elif a in ("普通", "normal", "n"):
                    difficulty = "normal"
                elif a in ("随机", "lfr"):
                    difficulty = "lfr"
                elif a in ("世界", "world"):
                    region = "world"
                elif a in ("国服", "cn"):
                    region = "cn"
                elif a in ("美服", "us"):
                    region = "us"
                elif a in ("欧服", "eu"):
                    region = "eu"
                elif a in ("韩服", "kr"):
                    region = "kr"
                elif a in ("台服", "tw"):
                    region = "tw"

            difficulty_cn = {"mythic": "史诗", "heroic": "英雄", "normal": "普通", "lfr": "随机"}[difficulty]
            region_cn = {"world": "世界", "cn": "国服", "us": "美服", "eu": "欧服", "kr": "韩服", "tw": "台服"}[region]
            yield event.plain_result(f"正在获取「烈毒之渊」{difficulty_cn}难度 {region_cn}首杀进度...")

            data = await fetch_hall_of_fame(difficulty=difficulty, region=region)
            if not data:
                yield event.plain_result("未获取到首杀进度数据。")
                return

            vars_ = build_hall_of_fame_vars(data)
            img_url = await self.html_render(
                self._tmpl.hall_of_fame, vars_, options=self._render_options()
            )
            yield event.image_result(img_url)
        except Exception as e:
            logger.error(f"首杀进度查询失败: {e}", exc_info=True)
            yield event.plain_result(f"首杀进度查询失败：{e}")

    # ── 角色数据刷新 ─────────────────────
    @filter.command("wow刷新")
    async def refresh_wow(self, event: AstrMessageEvent):
        """刷新角色在 Raider.io 上的数据。
        用法：/wow刷新 角色名
        示例：/wow刷新 超倔强双马尾"""
        try:
            parts = event.message_str.strip().split(None, 1)
            if len(parts) < 2 or not parts[1].strip():
                yield event.plain_result("请提供角色名。用法：/wow刷新 角色名")
                return
            name = parts[1].strip()

            yield event.plain_result(f"正在搜索角色「{name}」...")
            matches = await search_characters(name)

            if not matches:
                yield event.plain_result(
                    f"未找到名为「{name}」的角色，请确认角色名拼写是否正确。"
                )
                return

            if len(matches) == 1:
                char = matches[0]
                await self._do_refresh(event, char)
            else:
                show_count = min(len(matches), 10)
                list_text = format_match_list(matches[:show_count])
                yield event.plain_result(list_text)

                async def on_pick(
                    controller: SessionController, event: AstrMessageEvent, char: dict
                ):
                    await self._do_refresh(event, char)

                await self._wait_choice(event, matches, "已取消刷新。", on_pick)

        except Exception as e:
            logger.error(f"角色刷新失败: {e}", exc_info=True)
            yield event.plain_result(f"刷新失败：{e}")

    async def _do_refresh(self, event: AstrMessageEvent, match: dict):
        """执行角色数据刷新流程。"""
        region, realm_slug, char_name = extract_char_ids(match)

        if not realm_slug or not char_name:
            await event.send(event.plain_result("无法获取角色的服务器信息。"))
            return

        await event.send(event.plain_result(f"正在刷新 {char_name} 的数据..."))

        try:
            # 搜索 realmId
            realm_data = await search_realm(realm_slug)
            realm_id = realm_data.get("id")
            if not realm_id:
                await event.send(event.plain_result(f"未能获取服务器 {realm_slug} 的 ID。"))
                return

            # 创建刷新任务
            batch_id = await refresh_character(region, realm_slug, realm_id, char_name)
            if not batch_id:
                await event.send(event.plain_result("刷新任务创建失败，未返回任务 ID。"))
                return

            # 轮询状态（最多 30 秒）
            for _ in range(15):
                await asyncio.sleep(2)
                status = await check_refresh_status(batch_id)
                if status == "complete":
                    await event.send(event.plain_result(
                        f"✅ {char_name} 的数据已刷新完成！"
                    ))
                    return

            # 超时
            await event.send(event.plain_result(
                f"ℹ️ {char_name} 的刷新任务已提交，但尚未完成，请稍后查询。"
            ))

        except Exception as e:
            logger.error(f"刷新角色数据失败: {e}", exc_info=True)
            await event.send(event.plain_result(f"刷新失败：{e}"))

    # ── LLM 工具（自然语言自动调用）─────────────
    @filter.llm_tool(name="wow_character_card")
    async def llm_query_character_card(
        self,
        event: AstrMessageEvent,
        character_name: str = "",
        realm: str = "",
    ):
        '''查询魔兽世界国服角色的大秘境战绩卡片，返回一张包含 M+ 综合评分、最佳限时钥匙、团本进度、装备与公会信息的图片。

        Args:
            character_name(string): 角色名，必填
            realm(string): 服务器名，可选，角色同名时用于精确匹配
        '''
        if not character_name.strip():
            yield "缺少角色名，请提供要查询的角色名。"
            return
        try:
            status, content = await self._search_and_render_card(
                character_name.strip(), realm or None
            )
            if status == "image":
                yield f"已成功生成角色「{character_name}」的战绩卡片图片并发送给用户。"
                yield event.image_result(content)
            elif status == "list":
                yield (
                    f"找到多个同名角色「{character_name}」，以下是候选列表，"
                    f"请向用户询问服务器名（realm）以精确匹配：\n{content}"
                )
            else:
                yield content
        except Exception as e:
            logger.error(f"LLM 工具查询角色失败: {e}", exc_info=True)
            yield f"查询失败：{e}"

    @filter.llm_tool(name="wow_mplus_cutoff")
    async def llm_query_cutoff(self, event: AstrMessageEvent):
        '''查询魔兽世界国服（WOW）当前赛季大秘境（M+）各分段分数线（0.1%/1%/5%/10%/25% 分段），返回一张分数线图片。本工具无需任何参数。'''
        try:
            cutoffs = await fetch_cutoffs(region="cn", season="season-mn-2")
            if not cutoffs:
                yield "未获取到分数线数据。"
                return
            vars_ = build_cutoff_vars(cutoffs)
            img_url = await self.html_render(
                self._tmpl.cutoff, vars_, options=self._render_options()
            )
            yield "已成功生成M+分数线图片并发送给用户。"
            yield event.image_result(img_url)
        except Exception as e:
            logger.error(f"LLM 工具查询分数线失败: {e}", exc_info=True)
            yield f"分数线查询失败：{e}"

    @filter.llm_tool(name="wow_spec_popularity")
    async def llm_query_spec_popularity(
        self, event: AstrMessageEvent, week: str = "", min_level: str = ""
    ):
        '''查询魔兽世界国服大秘境专精热度统计，返回一张展示各职业专精出场占比与数量的图片。

        Args:
            week(string): 可选，传「本周」只统计本周，留空或传「全体」统计整个赛季
            min_level(string): 可选，最低大秘境层数，如 "15" 表示统计 15 层以上，留空默认 2 层
        '''
        try:
            week_val = (
                get_current_season_week()
                if week and week.strip().lower() in ("本周", "thisweek", "week")
                else None
            )
            try:
                min_level_val = max(int(min_level), 2) if str(min_level).strip() else 2
            except ValueError:
                min_level_val = 2

            data = await fetch_spec_popularity(
                season="season-mn-2",
                min_mythic_level=min_level_val,
                week=week_val,
            )
            if not data or not data.get("data"):
                yield "未获取到专精热度数据。"
                return

            vars_ = build_spec_popularity_vars(
                data, region="cn", min_level=min_level_val, week=week_val
            )
            img_url = await self.html_render(
                self._tmpl.spec_popularity, vars_, options=self._render_options()
            )
            yield "已成功生成专精热度统计图片并发送给用户。"
            yield event.image_result(img_url)
        except Exception as e:
            logger.error(f"LLM 工具查询专精热度失败: {e}", exc_info=True)
            yield f"专精热度查询失败：{e}"

    # ── 辅助方法 ─────────────────────────────
    @staticmethod
    def _render_options() -> dict:
        """统一的 HTML 渲染选项（800px 宽、2x 缩放、PNG、整页裁剪）。"""
        return {
            "viewport": {"width": 800, "deviceScaleFactor": 2},
            "scale": "device",
            "type": "png",
            "full_page": True,
            "clip": {"x": 0, "y": 0, "width": 800, "height": 10000},
        }

    async def _search_and_render_card(
        self, name: str, realm: str | None = None
    ) -> tuple[str, str]:
        """搜索角色并渲染战绩卡片。

        返回 (状态, 内容)：
        - "image": 内容为渲染出的图片 URL
        - "list": 内容为候选角色列表文本（同名多服务器）
        - "none": 未找到角色
        """
        matches = await search_characters(name)
        if not matches:
            return "none", f"未找到名为「{name}」的角色，请确认角色名拼写是否正确。"

        # 按服务器名精确过滤（同名角色多服务器时）
        if realm and len(matches) > 1:
            filtered = []
            for m in matches:
                d = m.get("data", {})
                r = d.get("realm", {})
                rname = (
                    r.get("altName") or r.get("name", "")
                    if isinstance(r, dict)
                    else str(r or "")
                )
                slug = r.get("slug", "") if isinstance(r, dict) else str(r or "")
                if realm.lower() in rname.lower() or realm.lower() in slug.lower():
                    filtered.append(m)
            if filtered:
                matches = filtered

        if len(matches) > 1:
            return "list", format_match_list(matches[:10])

        char = matches[0]
        img_url = await self._render_char_card(char)
        return "image", img_url

    async def _render_char_card(self, char: dict) -> str:
        """获取角色战绩数据并渲染战绩卡片，返回图片 URL。"""
        data = await fetch_profile(char)
        region, realm, cname = extract_char_ids(char)
        progress = await fetch_mplus_progress(region, realm, cname)
        card_vars = build_card_vars(data, self._dungeon_cn_map, progress)
        return await self.html_render(
            self._tmpl.card, card_vars, options=self._render_options()
        )

    async def _wait_choice(
        self,
        event: AstrMessageEvent,
        matches: list,
        cancel_text: str,
        on_pick,
    ) -> None:
        """展示候选列表后等待用户输入序号选择角色。

        on_pick: async (controller, event, char) -> None，选中角色后回调。
        """
        show_count = min(len(matches), 10)

        @session_waiter(timeout=60, record_history_chains=False)
        async def wait_selection(
            controller: SessionController, event: AstrMessageEvent
        ):
            choice = event.message_str.strip()

            # 取消
            if choice.lower() in ("取消", "cancel", "q", "exit"):
                await event.send(event.plain_result(cancel_text))
                controller.stop()
                return

            # 非数字
            if not choice.isdigit():
                await event.send(event.plain_result(
                    f"请输入 1~{show_count} 之间的数字，或发送「取消」退出。"
                ))
                controller.keep(timeout=60, reset_timeout=True)
                return

            idx = int(choice) - 1
            if not (0 <= idx < show_count):
                await event.send(event.plain_result(
                    f"序号超出范围，请输入 1~{show_count} 之间的数字。"
                ))
                controller.keep(timeout=60, reset_timeout=True)
                return

            char = matches[idx]
            await on_pick(controller, event, char)
            controller.stop()

        await wait_selection(event)

    def _parse_args(self, message_str: str) -> str:
        """
        解析消息，返回角色名。
        支持：
          /wow 角色名
        """
        parts = message_str.strip().split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            raise ValueError("请提供角色名。用法：/wow 角色名")

        return parts[1].strip()

    async def terminate(self):
        await close_session()
        logger.info("WoW 战绩查询插件已卸载")
