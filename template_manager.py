"""HTML 模板加载与缓存管理"""

from .constants import (
    TMPL_PATH,
    CUTOFF_TMPL_PATH,
    SPEC_POP_TMPL_PATH,
    HALL_OF_FAME_TMPL_PATH,
)


class TemplateManager:
    """管理 card.html / cutoff.html / spec_popularity.html / hall_of_fame.html 的读取与内存缓存。"""

    def __init__(self):
        self._card_cache: str | None = None
        self._cutoff_cache: str | None = None
        self._spec_pop_cache: str | None = None
        self._hof_cache: str | None = None

    @property
    def card(self) -> str:
        if self._card_cache is None:
            with open(TMPL_PATH, encoding="utf-8") as f:
                self._card_cache = f.read()
        return self._card_cache

    @property
    def cutoff(self) -> str:
        if self._cutoff_cache is None:
            with open(CUTOFF_TMPL_PATH, encoding="utf-8") as f:
                self._cutoff_cache = f.read()
        return self._cutoff_cache

    @property
    def spec_popularity(self) -> str:
        if self._spec_pop_cache is None:
            with open(SPEC_POP_TMPL_PATH, encoding="utf-8") as f:
                self._spec_pop_cache = f.read()
        return self._spec_pop_cache

    @property
    def hall_of_fame(self) -> str:
        if self._hof_cache is None:
            with open(HALL_OF_FAME_TMPL_PATH, encoding="utf-8") as f:
                self._hof_cache = f.read()
        return self._hof_cache
