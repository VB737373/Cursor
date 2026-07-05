"""Деривативы: funding rate + open interest + long/short ratio.

Данные берутся с ПУБЛИЧНОГО API фьючерсов Binance (без ключей).
Это ключевые метрики для оценки качества входа в лонг:

  * Funding rate — кто «платит» на рынке. Отрицательный/нейтральный funding
    = есть запас хода вверх; экстремально высокий = толпа в лонгах, риск
    каскадных ликвидаций.
  * Open Interest (OI) — сколько открытых позиций. Рост OI вместе с ростом
    цены = приток свежих денег (сильный тренд). Рост OI при падении цены —
    плохо. Падение OI при росте цены = закрытие шортов (движение слабее).
  * Long/Short ratio — если розница массово в лонгах, это контрсигнал.
"""
from __future__ import annotations

from typing import Optional

import time
from typing import List, Tuple

import requests

from .base import SCOPE_SYMBOL, Contribution, DataSource
from .http import get_json

_FBASE = "https://fapi.binance.com"
_BYBIT = "https://api.bybit.com"
_BITGET = "https://api.bitget.com"
_HL = "https://api.hyperliquid.xyz/info"
# Периоды, поддерживаемые статистикой OI/LS у Binance
_STAT_PERIODS = {"5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"}

# Кэш снимка Hyperliquid (один запрос отдаёт все монеты) — обновляем раз в минуту
_hl_cache: dict = {"ts": 0.0, "data": {}}
_HL_TTL = 60.0


def _hl_snapshot() -> dict:
    """{coin: funding_%_в_8ч-эквиваленте} по всем монетам Hyperliquid (кэш)."""
    now = time.time()
    if _hl_cache["data"] and now - _hl_cache["ts"] < _HL_TTL:
        return _hl_cache["data"]
    out: dict = {}
    try:
        r = requests.post(_HL, json={"type": "metaAndAssetCtxs"}, timeout=10)
        if r.status_code == 200:
            d = r.json()
            universe, ctxs = d[0]["universe"], d[1]
            for u, c in zip(universe, ctxs):
                try:
                    # funding на Hyperliquid почасовой -> приводим к 8ч как у Binance
                    out[u["name"]] = float(c["funding"]) * 100 * 8
                except (KeyError, TypeError, ValueError):
                    continue
    except (requests.RequestException, ValueError, KeyError, IndexError):
        pass
    if out:
        _hl_cache["data"] = out
        _hl_cache["ts"] = now
    return _hl_cache["data"]


def _hyperliquid_funding(perp: str):
    base = perp[:-4] if perp.endswith("USDT") else perp
    return _hl_snapshot().get(base)


def _binance_funding(perp: str):
    prem = get_json(f"{_FBASE}/fapi/v1/premiumIndex", params={"symbol": perp})
    if isinstance(prem, dict) and "lastFundingRate" in prem:
        try:
            return float(prem["lastFundingRate"]) * 100
        except (TypeError, ValueError):
            return None
    return None


def _bybit_funding(perp: str):
    data = get_json(f"{_BYBIT}/v5/market/tickers",
                    params={"category": "linear", "symbol": perp})
    try:
        lst = data["result"]["list"]
        if lst and lst[0].get("fundingRate"):
            return float(lst[0]["fundingRate"]) * 100
    except (KeyError, TypeError, ValueError, IndexError):
        pass
    return None


def _bitget_funding(perp: str):
    data = get_json(f"{_BITGET}/api/v2/mix/market/current-fund-rate",
                    params={"symbol": perp, "productType": "USDT-FUTURES"})
    try:
        lst = data["data"]
        if lst and lst[0].get("fundingRate"):
            return float(lst[0]["fundingRate"]) * 100
    except (KeyError, TypeError, ValueError, IndexError):
        pass
    return None


def _aggregate_funding(perp: str) -> Tuple[List[Tuple[str, float]], float]:
    """Собирает funding с трёх бирж. Возвращает ([(биржа, %)...], среднее)."""
    parts: List[Tuple[str, float]] = []
    for label, fn in (("Bin", _binance_funding), ("Byb", _bybit_funding),
                      ("Bit", _bitget_funding), ("HL", _hyperliquid_funding)):
        val = fn(perp)
        if val is not None:
            parts.append((label, val))
    avg = sum(v for _, v in parts) / len(parts) if parts else 0.0
    return parts, avg


class Derivatives(DataSource):
    name = "Derivatives (Funding/OI)"
    scope = SCOPE_SYMBOL
    requires_key = False

    def _stat_period(self) -> str:
        iv = self.cfg.interval
        return iv if iv in _STAT_PERIODS else "1h"

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        perp = f"{base_asset}USDT"

        # 1) Агрегированный funding rate по Binance + Bybit + Bitget
        funding_parts, funding = _aggregate_funding(perp)
        if not funding_parts:
            return None  # нет перпетуала ни на одной бирже

        period = self._stat_period()

        # 2) Изменение Open Interest
        oi_change = None
        oi = get_json(
            f"{_FBASE}/futures/data/openInterestHist",
            params={"symbol": perp, "period": period, "limit": 24},
        )
        if isinstance(oi, list) and len(oi) >= 2:
            try:
                now = float(oi[-1]["sumOpenInterest"])
                prev = float(oi[0]["sumOpenInterest"])
                if prev > 0:
                    oi_change = (now - prev) / prev * 100
            except (KeyError, TypeError, ValueError):
                pass

        # 3) Long/Short account ratio
        ls_ratio = None
        ls = get_json(
            f"{_FBASE}/futures/data/globalLongShortAccountRatio",
            params={"symbol": perp, "period": period, "limit": 1},
        )
        if isinstance(ls, list) and ls:
            try:
                ls_ratio = float(ls[0]["longShortRatio"])
            except (KeyError, TypeError, ValueError):
                pass

        # 4) Тренд цены за окно (из уже загруженных свечей)
        price_change = None
        k = context.get("klines")
        if k and len(k["close"]) >= 25 and k["close"][-25] > 0:
            price_change = (k["close"][-1] - k["close"][-25]) / k["close"][-25] * 100

        score = 0.0
        reasons = []

        # --- Funding (агрегированный по биржам) ---
        fsrc = "/".join(f"{lbl}{v:+.3f}" for lbl, v in funding_parts)
        if funding < -0.05:
            score += 0.30
            reasons.append(f"funding avg {funding:+.3f}% [{fsrc}] (шорты платят лонгам)")
        elif funding <= 0.03:
            score += 0.15
            reasons.append(f"funding avg {funding:+.3f}% [{fsrc}] (норма)")
        elif funding <= 0.08:
            score -= 0.10
            reasons.append(f"funding avg {funding:+.3f}% [{fsrc}] (повышен)")
        else:
            score -= 0.35
            reasons.append(f"funding avg {funding:+.3f}% [{fsrc}] (перегрев лонгов)")

        # Расхождение фандинга между биржами — признак дисбаланса/арбитража
        if len(funding_parts) >= 2:
            spread = max(v for _, v in funding_parts) - min(v for _, v in funding_parts)
            if spread > 0.05:
                reasons.append(f"funding расходится между биржами ({spread:.3f}%)")

        # --- OI + цена ---
        if oi_change is not None and price_change is not None:
            if oi_change > 1 and price_change > 0:
                score += 0.30
                reasons.append(f"OI {oi_change:+.1f}% + цена вверх (приток денег)")
            elif oi_change > 1 and price_change < 0:
                score -= 0.20
                reasons.append(f"OI {oi_change:+.1f}% при падении цены")
            elif oi_change < -1 and price_change > 0:
                score += 0.05
                reasons.append("рост на закрытии шортов")
            elif oi_change < -1 and price_change < 0:
                score -= 0.05
                reasons.append("делеверидж (OI падает)")
        elif oi_change is not None and oi_change > 1:
            score += 0.10
            reasons.append(f"OI {oi_change:+.1f}%")

        # --- Long/Short ratio ---
        if ls_ratio is not None:
            if ls_ratio > 3:
                score -= 0.15
                reasons.append(f"L/S {ls_ratio:.1f} (толпа в лонгах)")
            elif ls_ratio < 0.8:
                score += 0.15
                reasons.append(f"L/S {ls_ratio:.1f} (перевес шортов)")

        reason = ", ".join(reasons) if reasons else "деривативы нейтральны"
        return Contribution(self.name, score, self.weight, reason).clamped()
