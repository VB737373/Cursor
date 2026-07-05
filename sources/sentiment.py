"""Простой анализ настроения текста (EN + RU) + сопоставление монет.

Без внешних зависимостей: считаем «бычьи» и «медвежьи» слова в тексте
и нормируем в оценку [-1, 1]. Плюс карта тикер→названия, чтобы находить
упоминания монеты в новостях и сообщениях.
"""
from __future__ import annotations

import re
from typing import List, Optional

_POSITIVE = {
    # EN
    "bull", "bullish", "moon", "pump", "long", "buy", "buying", "breakout",
    "ath", "rally", "surge", "surges", "soar", "gain", "gains", "up", "uptrend",
    "accumulate", "accumulation", "support", "squeeze", "rebound", "bounce",
    "adoption", "partnership", "listing", "listed", "upgrade", "burn", "bullrun",
    # RU
    "рост", "растёт", "растет", "лонг", "покупка", "покупки", "бычий", "пробой",
    "ракета", "памп", "вверх", "закуп", "накопление", "отскок", "листинг",
    "партнёрство", "партнерство", "сжигание", "аптренд", "сквиз",
}

_NEGATIVE = {
    # EN
    "bear", "bearish", "dump", "dumping", "short", "sell", "selling", "crash",
    "rug", "rugpull", "scam", "down", "downtrend", "drop", "drops", "fall",
    "falls", "dead", "liquidated", "liquidation", "hack", "hacked", "exploit",
    "ban", "lawsuit", "fud", "correction", "plunge", "collapse",
    # RU
    "падение", "падает", "шорт", "продажа", "продажи", "медвежий", "дамп",
    "скам", "вниз", "слив", "крах", "обвал", "взлом", "ликвидация", "запрет",
    "иск", "коррекция", "паника",
}

# Тикер -> дополнительные названия для поиска в тексте
COIN_NAMES = {
    "BTC": ["bitcoin", "биткоин", "биток"],
    "ETH": ["ethereum", "эфириум", "эфир"],
    "SOL": ["solana", "солана"],
    "BNB": ["binance coin", "bnb"],
    "XRP": ["ripple", "рипл"],
    "ADA": ["cardano", "кардано"],
    "DOGE": ["dogecoin", "доги", "дож"],
    "AVAX": ["avalanche", "аваланч"],
    "DOT": ["polkadot", "полкадот"],
    "MATIC": ["polygon", "полигон"],
    "POL": ["polygon", "полигон"],
    "LINK": ["chainlink", "чейнлинк"],
    "TON": ["toncoin", "тон"],
    "TRX": ["tron", "трон"],
    "LTC": ["litecoin", "лайткоин", "лайт"],
    "SHIB": ["shiba", "шиба"],
    "PEPE": ["pepe", "пепе"],
    "SUI": ["sui"],
    "APT": ["aptos", "аптос"],
    "ARB": ["arbitrum", "арбитрум"],
    "OP": ["optimism"],
    "NEAR": ["near protocol"],
    "INJ": ["injective"],
    "RNDR": ["render"],
    "RENDER": ["render"],
    "WLD": ["worldcoin", "worldcoin"],
    "TIA": ["celestia", "селестия"],
    "SEI": ["sei network"],
    "FET": ["fetch.ai", "fetch ai"],
}

_word_re_cache: dict = {}


def score_text(text: str) -> Optional[float]:
    """Оценка настроения текста в [-1, 1] или None, если слов не найдено."""
    if not text:
        return None
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ]+", text.lower())
    if not words:
        return None
    pos = sum(1 for w in words if w in _POSITIVE)
    neg = sum(1 for w in words if w in _NEGATIVE)
    total = pos + neg
    if total == 0:
        return None
    return (pos - neg) / total


def mentions(text: str, base_asset: str) -> bool:
    """Упоминается ли монета в тексте (по тикеру или названию)."""
    if not text:
        return False
    low = text.lower()
    # $TICKER или тикер как отдельное слово
    ticker = base_asset.lower()
    pat = _word_re_cache.get(base_asset)
    if pat is None:
        pat = re.compile(r"(?:\$" + re.escape(ticker) + r"\b)|(?:\b" +
                         re.escape(ticker) + r"\b)")
        _word_re_cache[base_asset] = pat
    if pat.search(low):
        # для очень коротких тикеров (<=2) требуем ещё и название, чтобы не ловить шум
        if len(base_asset) > 2:
            return True
    for name in COIN_NAMES.get(base_asset, []):
        if name in low:
            return True
    if len(base_asset) > 2 and pat.search(low):
        return True
    return False


def aggregate(texts: List[str]) -> Optional[float]:
    """Средняя оценка настроения по списку текстов."""
    scores = [s for s in (score_text(t) for t in texts) if s is not None]
    if not scores:
        return None
    return sum(scores) / len(scores)
