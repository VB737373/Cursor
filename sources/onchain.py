"""On-chain и специализированные источники, требующие API-ключа.

Glassnode, CryptoQuant, Nansen, Arkham, DeBank, DropsTab.

Все они платные/закрытые. Здесь заданы корректные базовые URL и схемы
авторизации. Каждый коннектор:
  * включается только при наличии ключа (enabled());
  * делает best-effort запрос к документированному эндпоинту;
  * при любом несоответствии тарифа/схемы возвращает None (не голосует),
    чтобы бот продолжал работать на остальных источниках.

Точные пути/поля могут отличаться в зависимости от твоего тарифа —
скорректируй их под свою подписку в соответствующем классе.
"""
from __future__ import annotations

from typing import Optional

from .base import SCOPE_SYMBOL, Contribution, DataSource
from .http import get_json


def _series_change(data, value_keys=("v", "value")) -> Optional[float]:
    """Из ряда [{t, v}, ...] считает %-изменение последнего к ~7-му с конца."""
    if not isinstance(data, list) or len(data) < 8:
        return None
    def val(row):
        for k in value_keys:
            if isinstance(row, dict) and k in row and row[k] is not None:
                try:
                    return float(row[k])
                except (TypeError, ValueError):
                    return None
        return None
    now, prev = val(data[-1]), val(data[-8])
    if now is None or prev is None or prev == 0:
        return None
    return (now - prev) / abs(prev) * 100


class Glassnode(DataSource):
    """On-chain метрики. Используем изменение баланса бирж:
    отток с бирж (баланс падает) = бычий фактор."""
    name = "Glassnode"
    scope = SCOPE_SYMBOL
    requires_key = True
    _SUPPORTED = {"BTC", "ETH", "LTC", "BCH"}

    def __init__(self, cfg, weight=1.5):
        super().__init__(cfg, weight)
        self.key = cfg.api_keys.get("glassnode", "")

    def enabled(self) -> bool:
        return bool(self.key)

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        if base_asset not in self._SUPPORTED:
            return None
        data = get_json(
            "https://api.glassnode.com/v1/metrics/distribution/balance_exchanges",
            params={"a": base_asset, "i": "24h", "api_key": self.key},
        )
        change = _series_change(data)
        if change is None:
            return None
        # Баланс бирж растёт -> приток на продажу (медвежье); падает -> бычье
        score = max(-0.4, min(0.4, -change / 5.0))
        reason = f"баланс бирж {change:+.1f}% за 7д"
        return Contribution(self.name, score, self.weight, reason).clamped()


class CryptoQuant(DataSource):
    """Потоки на биржи. Отрицательный netflow (отток) = бычий фактор."""
    name = "CryptoQuant"
    scope = SCOPE_SYMBOL
    requires_key = True
    _MAP = {"BTC": "btc", "ETH": "eth"}

    def __init__(self, cfg, weight=1.5):
        super().__init__(cfg, weight)
        self.key = cfg.api_keys.get("cryptoquant", "")

    def enabled(self) -> bool:
        return bool(self.key)

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        asset = self._MAP.get(base_asset)
        if not asset:
            return None
        data = get_json(
            f"https://api.cryptoquant.com/v1/{asset}/exchange-flows/netflow",
            params={"exchange": "all_exchange", "window": "day", "limit": 8},
            headers={"Authorization": f"Bearer {self.key}"},
        )
        rows = data.get("result", {}).get("data") if isinstance(data, dict) else None
        change = _series_change(rows, value_keys=("netflow_total", "value", "v"))
        if change is None:
            return None
        score = max(-0.4, min(0.4, -change / 100.0))
        reason = f"netflow бирж {change:+.1f}% за 7д"
        return Contribution(self.name, score, self.weight, reason).clamped()


class Nansen(DataSource):
    """Smart money: чистый приток «умных денег» в токен = бычий фактор."""
    name = "Nansen"
    scope = SCOPE_SYMBOL
    requires_key = True

    def __init__(self, cfg, weight=2.0):
        super().__init__(cfg, weight)
        self.key = cfg.api_keys.get("nansen", "")

    def enabled(self) -> bool:
        return bool(self.key)

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        data = get_json(
            "https://api.nansen.ai/v1/smart-money/netflow",
            params={"symbol": base_asset},
            headers={"apiKey": self.key},
        )
        if not isinstance(data, dict):
            return None
        try:
            netflow = float(data.get("data", {}).get("netflow_usd"))
        except (TypeError, ValueError):
            return None
        if netflow > 0:
            score, note = 0.4, "приток smart money"
        elif netflow < 0:
            score, note = -0.4, "отток smart money"
        else:
            score, note = 0.0, "smart money нейтр."
        return Contribution(self.name, score, self.weight, note).clamped()


class Arkham(DataSource):
    """Arkham Intel: крупные перемещения/накопление сущностями."""
    name = "Arkham"
    scope = SCOPE_SYMBOL
    requires_key = True

    def __init__(self, cfg, weight=1.5):
        super().__init__(cfg, weight)
        self.key = cfg.api_keys.get("arkham", "")

    def enabled(self) -> bool:
        return bool(self.key)

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        data = get_json(
            "https://api.arkm.com/token/flows",
            params={"symbol": base_asset, "window": "7d"},
            headers={"API-Key": self.key},
        )
        if not isinstance(data, dict):
            return None
        try:
            inflow = float(data.get("cexInflowUSD", 0))
            outflow = float(data.get("cexOutflowUSD", 0))
        except (TypeError, ValueError):
            return None
        net = outflow - inflow  # отток с бирж > приток = бычье
        total = inflow + outflow
        if total <= 0:
            return None
        score = max(-0.4, min(0.4, net / total * 0.4))
        reason = f"нетто-отток с бирж {net:+.0f}$"
        return Contribution(self.name, score, self.weight, reason).clamped()


class DeBank(DataSource):
    """DeBank Cloud API: активность/приток в токен в EVM-сетях."""
    name = "DeBank"
    scope = SCOPE_SYMBOL
    requires_key = True

    def __init__(self, cfg, weight=1.0):
        super().__init__(cfg, weight)
        self.key = cfg.api_keys.get("debank", "")

    def enabled(self) -> bool:
        return bool(self.key)

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        # DeBank работает по адресам токенов/протоколов, а не по тикерам.
        # Без сопоставления тикер->контракт корректно голосовать нельзя.
        # Оставлено как точка расширения под конкретные адреса.
        return None


class DropsTab(DataSource):
    """DropsTab: крупная разблокировка токенов скоро = давление на продажу."""
    name = "DropsTab"
    scope = SCOPE_SYMBOL
    requires_key = True

    def __init__(self, cfg, weight=1.0):
        super().__init__(cfg, weight)
        self.key = cfg.api_keys.get("dropstab", "")

    def enabled(self) -> bool:
        return bool(self.key)

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        data = get_json(
            "https://api.dropstab.com/v1/unlocks",
            params={"symbol": base_asset},
            headers={"Authorization": f"Bearer {self.key}"},
        )
        if not isinstance(data, dict):
            return None
        try:
            days = float(data.get("nextUnlockInDays"))
            pct = float(data.get("nextUnlockPctOfSupply"))
        except (TypeError, ValueError):
            return None
        # Крупный анлок (>1.5% предложения) в ближайшие 7 дней — медвежье
        if days <= 7 and pct >= 1.5:
            score = -0.35
            reason = f"анлок {pct:.1f}% через {days:.0f}д"
        else:
            score = 0.05
            reason = "нет крупных анлоков рядом"
        return Contribution(self.name, score, self.weight, reason).clamped()
