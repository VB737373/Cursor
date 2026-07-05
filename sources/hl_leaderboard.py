"""Общий доступ к публичным данным Hyperliquid: лидерборд + позиции адресов.

Используется источниками «киты» (whales) и «маркет-мейкеры» (marketmakers),
чтобы НЕ качать 33-МБ лидерборд и позиции по несколько раз за один скан:
- строки лидерборда кэшируются на 6 часов;
- позиции каждого адреса кэшируются на 2 минуты (общие адреса тянутся один раз).

Есть «предохранитель»: если Hyperliquid недоступен (например, нет VPN) — оба
источника молчат _BACKOFF секунд, чтобы не висеть в таймаутах на каждом скане.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

import requests

log = logging.getLogger("hyperliquid")

_HL = "https://api.hyperliquid.xyz/info"
_LEADERBOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"

_LB_TIMEOUT = 30
_POS_TIMEOUT = 5
_LB_TTL = 6 * 3600.0
_POS_TTL = 120.0
_BACKOFF = 1800.0

_down_until = 0.0
_lb_cache: dict = {"ts": 0.0, "rows": []}
_pos_cache: dict = {}   # {address_lower: (ts, positions)}


def available() -> bool:
    return time.time() >= _down_until


def _trip() -> None:
    global _down_until
    _down_until = time.time() + _BACKOFF
    log.warning("Hyperliquid недоступен (нет VPN?) — киты/маркет-мейкеры отключены "
                "на %d мин, бот работает на остальных источниках", int(_BACKOFF / 60))


def leaderboard_rows() -> list:
    """Сырые строки лидерборда Hyperliquid (кэш 6ч). Пусто, если недоступно."""
    now = time.time()
    if _lb_cache["rows"] and now - _lb_cache["ts"] < _LB_TTL:
        return _lb_cache["rows"]
    if not available():
        return _lb_cache["rows"]
    try:
        rows = requests.get(_LEADERBOARD, timeout=_LB_TIMEOUT).json().get(
            "leaderboardRows", [])
    except (requests.RequestException, ValueError, KeyError) as e:
        log.warning("Лидерборд Hyperliquid недоступен: %s", str(e)[:100])
        _trip()
        return _lb_cache["rows"]
    if rows:
        _lb_cache["rows"] = rows
        _lb_cache["ts"] = now
    return _lb_cache["rows"]


def _positions(address: str):
    """Позиции адреса (кэш на адрес 2 мин). None при сетевой ошибке."""
    now = time.time()
    key = address.lower()
    cached = _pos_cache.get(key)
    if cached and now - cached[0] < _POS_TTL:
        return cached[1]
    if not available():
        return cached[1] if cached else []
    try:
        r = requests.post(_HL, json={"type": "clearinghouseState", "user": address},
                          timeout=_POS_TIMEOUT)
        if r.status_code == 200:
            positions = r.json().get("assetPositions", []) or []
            _pos_cache[key] = (now, positions)
            return positions
        return []
    except (requests.RequestException, ValueError, KeyError):
        return None


def position_on(address: str, coin: str):
    """(szi, notional) позиции адреса по монете; None, если позиции нет."""
    for ap in _positions(address) or []:
        pos = ap.get("position", {})
        if pos.get("coin") == coin:
            try:
                return float(pos.get("szi", 0)), abs(float(pos.get("positionValue", 0)))
            except (TypeError, ValueError):
                return None
    return None


def aggregate(addresses: list) -> dict:
    """{coin: {'long':$, 'short':$, 'n_long':k, 'n_short':k}} по списку адресов."""
    agg: dict = defaultdict(lambda: {"long": 0.0, "short": 0.0,
                                     "n_long": 0, "n_short": 0})
    for addr in addresses:
        positions = _positions(addr)
        if positions is None:            # обрыв связи — Hyperliquid недоступен
            _trip()
            break
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
    return dict(agg)
