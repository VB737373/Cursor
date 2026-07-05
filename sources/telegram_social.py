"""Анализ настроения из Telegram-групп/каналов.

Бот сохраняет текст сообщений из чатов, КУДА ЕГО ДОБАВИЛИ (группы или
каналы). Источник считает упоминания монеты за последние часы и оценивает
тональность (хайп/страх), а также всплеск упоминаний.

Важно: чтобы бот видел все сообщения в группе, у него должен быть отключён
режим приватности (@BotFather → /setprivacy → Disable) либо он должен быть
админом канала. Историю до добавления бот не видит — копит с момента входа.
"""
from __future__ import annotations

import time
from typing import Optional

from . import sentiment
from .base import SCOPE_SYMBOL, Contribution, DataSource

_KEEP_SECONDS = 24 * 3600


class MessageStore:
    def __init__(self):
        self._msgs: list[tuple] = []  # (ts, text)
        self._adds = 0

    def add(self, ts: float, text: str) -> None:
        if not text:
            return
        self._msgs.append((ts, text))
        self._adds += 1
        if self._adds % 100 == 0:
            self._prune()

    def _prune(self) -> None:
        cutoff = time.time() - _KEEP_SECONDS
        self._msgs = [m for m in self._msgs if m[0] >= cutoff]

    def recent_texts(self, window_sec: int) -> list[str]:
        cutoff = time.time() - window_sec
        return [t for ts, t in self._msgs if ts >= cutoff]

    def has_data(self) -> bool:
        return bool(self._msgs)


# Синглтон: bot.py пишет сюда сообщения, источник читает
STORE = MessageStore()


class TelegramSocial(DataSource):
    name = "Telegram Social"
    scope = SCOPE_SYMBOL
    requires_key = False

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        if not STORE.has_data():
            return None  # бот не добавлен в чаты / нет сообщений
        texts = STORE.recent_texts(window_sec=6 * 3600)
        hits = [t for t in texts if sentiment.mentions(t, base_asset)]
        if not hits:
            return None

        sent = sentiment.aggregate(hits)
        count = len(hits)

        score = 0.0
        if sent is not None:
            score += sent * 0.30
        # Всплеск упоминаний = хайп (умеренный плюс)
        if count >= 5:
            score += 0.10

        reason = (f"упоминаний в TG: {count}, "
                  f"тон {('+' if (sent or 0) >= 0 else '')}{(sent or 0):.2f}")
        return Contribution(self.name, score, self.weight, reason).clamped()
