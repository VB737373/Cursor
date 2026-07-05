"""Отслеживание китов Hyperliquid (бесплатно, публичный API).

Как HypurrScan: следим за позициями крупных прибыльных трейдеров.

Адреса китов подбираются автоматически с публичного лидерборда Hyperliquid
(топ по PnL за месяц среди крупных счётов = «умные деньги»). Дополнительно
можно вручную добавить адреса в whales.txt (они всегда в списке).

Для каждого адреса запрашиваем текущие позиции (clearinghouseState) и
агрегируем по монетам: сколько китов в лонге/шорте и на какой объём в $.

Логика для лонга: киты нетто в ЛОНГЕ по монете — подтверждение (умные деньги
набирают), голосуем за лонг. Нетто-шорт — против.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Optional

import requests

from .base import SCOPE_SYMBOL, Contribution, DataSource

log = logging.getLogger("whales")

_HL = "https://api.hyperliquid.xyz/info"
_LEADERBOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"

_POS_TTL = 120.0          # снимок позиций китов — раз в 2 минуты
_LB_TTL = 6 * 3600.0      # список китов с лидерборда — раз в 6 часов (файл ~33МБ)
_MIN_NOTIONAL = 50_000    # игнорируем монеты с суммарной позицией китов меньше этого

# Короткие таймауты, чтобы без VPN не тормозить скан
_LB_TIMEOUT = 25
_POS_TIMEOUT = 5

# «Предохранитель»: если Hyperliquid недоступен (напр. нет VPN) — отключаем
# источник на _BACKOFF секунд, чтобы не висеть в таймаутах на каждом скане.
_BACKOFF = 1800.0
_down_until = 0.0

_pos_cache: dict = {"ts": 0.0, "data": {}}
_lb_cache: dict = {"ts": 0.0, "addresses": []}


def _available() -> bool:
    return time.time() >= _down_until


def _trip() -> None:
    """Помечаем Hyperliquid как недоступный — источник молчит _BACKOFF секунд."""
    global _down_until
    _down_until = time.time() + _BACKOFF
    log.warning("Hyperliquid недоступен (нет VPN?) — киты отключены на %d мин, "
                "бот работает на остальных источниках", int(_BACKOFF / 60))


def _auto_addresses(top_n: int, min_account: float) -> list:
    """Топ-N прибыльных китов с лидерборда Hyperliquid (кэш 6ч)."""
    now = time.time()
    if _lb_cache["addresses"] and now - _lb_cache["ts"] < _LB_TTL:
        return _lb_cache["addresses"]
    if not _available():
        return _lb_cache["addresses"]
    try:
        rows = requests.get(_LEADERBOARD, timeout=_LB_TIMEOUT).json().get("leaderboardRows", [])
    except (requests.RequestException, ValueError, KeyError) as e:
        log.warning("Лидерборд Hyperliquid недоступен: %s", str(e)[:100])
        _trip()
        return _lb_cache["addresses"]

    picked = []
    for r in rows:
        try:
            av = float(r["accountValue"])
            perf = dict(r["windowPerformances"])
            month_pnl = float(perf["month"]["pnl"])
        except (KeyError, TypeError, ValueError):
            continue
        if av >= min_account and month_pnl > 0:
            picked.append((month_pnl, r["ethAddress"]))
    picked.sort(reverse=True)
    addresses = [a for _, a in picked[:top_n]]
    if addresses:
        _lb_cache["addresses"] = addresses
        _lb_cache["ts"] = now
        log.info("Киты Hyperliquid: отобрано %d прибыльных адресов с лидерборда",
                 len(addresses))
    return _lb_cache["addresses"]


def _resolve_addresses(cfg) -> list:
    manual = list(getattr(cfg, "whale_addresses", None) or [])
    if getattr(cfg, "whales_auto", True):
        auto = _auto_addresses(getattr(cfg, "whales_top_n", 30),
                               getattr(cfg, "whales_min_account", 2_000_000.0))
        # объединяем без дублей, ручные — первыми
        seen = {a.lower() for a in manual}
        manual += [a for a in auto if a.lower() not in seen]
    return manual


def _fetch_positions(address: str):
    """Список позиций адреса, либо None при сетевой ошибке (Hyperliquid недоступен)."""
    try:
        r = requests.post(_HL, json={"type": "clearinghouseState", "user": address},
                          timeout=_POS_TIMEOUT)
        if r.status_code == 200:
            return r.json().get("assetPositions", []) or []
        return []
    except (requests.RequestException, ValueError, KeyError):
        return None


def _snapshot(addresses: list) -> dict:
    """{coin: {'long':$, 'short':$, 'n_long':k, 'n_short':k}} по всем китам (кэш)."""
    now = time.time()
    if _pos_cache["data"] and now - _pos_cache["ts"] < _POS_TTL:
        return _pos_cache["data"]
    if not _available():
        return _pos_cache["data"]

    agg: dict = defaultdict(lambda: {"long": 0.0, "short": 0.0, "n_long": 0, "n_short": 0})
    for addr in addresses:
        positions = _fetch_positions(addr)
        if positions is None:            # обрыв связи — Hyperliquid недоступен
            _trip()
            return _pos_cache["data"]    # отдаём прошлый кэш, не тормозим скан
        for ap in positions:
            pos = ap.get("position", {})
            coin = pos.get("coin")
            if not coin:
                continue
            try:
                szi = float(pos.get("szi", 0))
                notional = abs(float(pos.get("positionValue", 0)))
            except (TypeError, ValueError):
                continue
            if szi > 0:
                agg[coin]["long"] += notional
                agg[coin]["n_long"] += 1
            elif szi < 0:
                agg[coin]["short"] += notional
                agg[coin]["n_short"] += 1

    _pos_cache["data"] = dict(agg)
    _pos_cache["ts"] = now
    return _pos_cache["data"]


class HyperliquidWhales(DataSource):
    name = "Hyperliquid Whales"
    scope = SCOPE_SYMBOL
    requires_key = False

    def enabled(self) -> bool:
        return bool(getattr(self.cfg, "whale_addresses", None)) or \
            bool(getattr(self.cfg, "whales_auto", True))

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        addresses = _resolve_addresses(self.cfg)
        if not addresses:
            return None
        snap = _snapshot(addresses)
        info = snap.get(base_asset)
        if not info:
            return None

        total = info["long"] + info["short"]
        if total < _MIN_NOTIONAL:
            return None

        net = (info["long"] - info["short"]) / total   # -1..1
        score = net * 0.6
        if net > 0.15:
            note = (f"киты в лонге: {info['n_long']} поз. "
                    f"${info['long']/1e6:.1f}M vs шорт ${info['short']/1e6:.1f}M")
        elif net < -0.15:
            note = (f"киты в шорте: {info['n_short']} поз. "
                    f"${info['short']/1e6:.1f}M vs лонг ${info['long']/1e6:.1f}M")
        else:
            note = "киты нейтральны"
        return Contribution(self.name, score, self.weight, note).clamped()
