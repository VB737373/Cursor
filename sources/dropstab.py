"""DropsTab Commercial API — tokenomics + market context.

Документация: https://api-docs.dropstab.com/
Базовый URL: https://public-api.dropstab.com/api/v1
Авторизация: заголовок x-dropstab-api-key (НЕ логин/пароль с сайта).

Важно: вход на dropstab.com (портфель, watchlist) — это B2C-аккаунт.
Для бота нужен отдельный API-ключ: https://dropstab.com/products/commercial-api
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from .base import SCOPE_SYMBOL, Contribution, DataSource
from .http import get_json

log = logging.getLogger("dropstab")

_API = "https://public-api.dropstab.com/api/v1"
_SLUG_TTL = 24 * 3600.0
_slug_cache: dict[str, tuple[float, str]] = {}


def _headers(key: str) -> dict:
    return {"x-dropstab-api-key": key}


def _unwrap(resp) -> Optional[dict]:
    if not isinstance(resp, dict) or resp.get("failure"):
        return None
    data = resp.get("data")
    return data if isinstance(data, dict) else None


def _slug_for_symbol(symbol: str, key: str) -> Optional[str]:
    sym = symbol.upper()
    now = time.time()
    cached = _slug_cache.get(sym)
    if cached and now - cached[0] < _SLUG_TTL:
        return cached[1]

    resp = get_json(
        f"{_API}/coins/symbol/{sym}",
        params={"pageSize": 5},
        headers=_headers(key),
    )
    page = _unwrap(resp)
    if not page:
        return cached[1] if cached else None

    content = page.get("content") or []
    slug = None
    for coin in content:
        if not isinstance(coin, dict):
            continue
        if coin.get("trading") != "CURRENTLY_TRADING":
            continue
        slug = coin.get("slug")
        if slug:
            break
    if not slug and content and isinstance(content[0], dict):
        slug = content[0].get("slug")

    if slug:
        _slug_cache[sym] = (now, slug)
    return slug


def _days_until(iso_date: str) -> Optional[float]:
    if not iso_date:
        return None
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt - datetime.now(timezone.utc)).total_seconds() / 86400
    except (TypeError, ValueError):
        return None


class DropsTab(DataSource):
    """DropsTab: анлоки токенов + FDV-риск (давление на продажу)."""
    name = "DropsTab"
    scope = SCOPE_SYMBOL
    requires_key = True

    def __init__(self, cfg, weight=1.0):
        super().__init__(cfg, weight)
        self.key = cfg.api_keys.get("dropstab", "")

    def enabled(self) -> bool:
        return bool(self.key)

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        slug = _slug_for_symbol(base_asset, self.key)
        if not slug:
            return None

        resp = get_json(
            f"{_API}/tokenUnlocks/{slug}",
            params={
                "unlocksTimelineFilter": "FUTURE",
                "unlocksDateSortOrder": "ASC",
            },
            headers=_headers(self.key),
        )
        data = _unwrap(resp)
        if not data:
            return None

        unlocks = data.get("tokenUnlocks") or []
        if not unlocks:
            locked_pct = float(data.get("totalTokensLockedPercent") or 0)
            if locked_pct > 60:
                return Contribution(
                    self.name, 0.05, self.weight,
                    f"заблокировано {locked_pct:.0f}%, ближайших анлоков нет",
                ).clamped()
            return Contribution(
                self.name, 0.08, self.weight, "нет данных об анлоках",
            ).clamped()

        nxt = unlocks[0]
        days = _days_until(nxt.get("date"))
        pct = float(nxt.get("allTokensSharePercent") or 0)
        usd = float(nxt.get("usdAmount") or 0)
        alloc = nxt.get("allocationName") or "unlock"

        if days is None:
            return None

        # Крупный анлок скоро — медвежий фактор для лонга
        if days <= 7 and pct >= 1.5:
            score = -0.35
            reason = f"анлок {pct:.1f}% ({alloc}) через {days:.0f}д (~${usd/1e6:.1f}M)"
        elif days <= 14 and pct >= 3.0:
            score = -0.25
            reason = f"крупный анлок {pct:.1f}% через {days:.0f}д"
        elif days <= 30 and pct >= 5.0:
            score = -0.15
            reason = f"анлок {pct:.1f}% через {days:.0f}д"
        else:
            score = 0.05
            reason = f"ближ. анлок {pct:.1f}% через {days:.0f}д — некритично"

        # FDV >> market cap = скрытый риск разблокировки
        fdv = float(data.get("fdv") or 0)
        mcap = float(data.get("marketCap") or 0)
        if mcap > 0 and fdv / mcap > 4 and days is not None and days <= 30:
            score = min(score, -0.1)
            reason += f"; FDV/MCap {fdv/mcap:.1f}x"

        return Contribution(self.name, score, self.weight, reason).clamped()
