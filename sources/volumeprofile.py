"""Объёмный профиль: POC + Value Area (кластеры, как в ATAS/Quantower).

По свечам строим распределение объёма по ценовым уровням:
  * POC (Point of Control) — уровень с максимальным наторгованным объёмом,
    работает как сильная поддержка/сопротивление;
  * Value Area (VAH/VAL) — диапазон, где прошло ~70% объёма (зона стоимости).

Логика для лонга:
  * цена выше POC = покупатели контролируют, POC — поддержка снизу → плюс;
  * цена ниже нижней границы Value Area (VAL) = слабость → минус.

Уровни POC/VAL кладём в context, чтобы сканер мог поставить стоп под поддержку.
"""
from __future__ import annotations

from typing import Optional

from .base import SCOPE_SYMBOL, Contribution, DataSource

_BINS = 50
_VALUE_AREA = 0.70


def compute_profile(highs, lows, volumes, bins=_BINS):
    """Возвращает (poc, val, vah) или None."""
    lo = min(lows)
    hi = max(highs)
    if hi <= lo:
        return None
    width = (hi - lo) / bins
    profile = [0.0] * bins

    for h, l, v in zip(highs, lows, volumes):
        b_lo = int((l - lo) / width)
        b_hi = int((h - lo) / width)
        b_lo = max(0, min(bins - 1, b_lo))
        b_hi = max(0, min(bins - 1, b_hi))
        n = b_hi - b_lo + 1
        share = v / n
        for b in range(b_lo, b_hi + 1):
            profile[b] += share

    total = sum(profile)
    if total <= 0:
        return None

    poc_bin = max(range(bins), key=lambda i: profile[i])
    poc = lo + (poc_bin + 0.5) * width

    # Value Area: расширяемся от POC, пока не наберём 70% объёма
    target = total * _VALUE_AREA
    acc = profile[poc_bin]
    lo_i = hi_i = poc_bin
    while acc < target and (lo_i > 0 or hi_i < bins - 1):
        left = profile[lo_i - 1] if lo_i > 0 else -1.0
        right = profile[hi_i + 1] if hi_i < bins - 1 else -1.0
        if right >= left and hi_i < bins - 1:
            hi_i += 1
            acc += profile[hi_i]
        elif lo_i > 0:
            lo_i -= 1
            acc += profile[lo_i]
        else:
            break

    val = lo + lo_i * width
    vah = lo + (hi_i + 1) * width
    return poc, val, vah


class VolumeProfile(DataSource):
    name = "Volume Profile (POC)"
    scope = SCOPE_SYMBOL
    requires_key = False

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        k = context.get("klines")
        if not k or len(k["close"]) < 30:
            return None

        res = compute_profile(k["high"], k["low"], k["volume"])
        if res is None:
            return None
        poc, val, vah = res
        price = k["close"][-1]

        # Сохраняем уровни для расчёта стопа/тейка в сканере
        context["poc"] = poc
        context["val"] = val
        context["vah"] = vah

        if price >= vah:
            score = 0.20
            note = "цена выше Value Area (сильная зона)"
        elif price >= poc:
            score = 0.25
            note = "цена выше POC (поддержка снизу)"
        elif price >= val:
            score = -0.05
            note = "цена в Value Area под POC"
        else:
            score = -0.20
            note = "цена ниже Value Area (слабость)"

        # Отбой от POC снизу вверх — зона накопления
        if val <= price <= poc and (poc - price) / price < 0.01:
            score = 0.15
            note = "отбой от POC (накопление)"

        reason = f"{note}; POC≈{poc:.6g}"
        return Contribution(self.name, score, self.weight, reason).clamped()
