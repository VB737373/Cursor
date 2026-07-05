"""DefiLlama — бесплатный открытый API (без ключа).

Для монет, которые являются L1/L2 сетями, растущий TVL = приток капитала
в экосистему = бычий фактор. Для остальных монет источник не голосует.
"""
from __future__ import annotations

import time
from typing import Optional

from .base import SCOPE_SYMBOL, Contribution, DataSource
from .http import get_json

# Базовый актив -> chain slug в DefiLlama
CHAIN_MAP = {
    "ETH": "Ethereum",
    "SOL": "Solana",
    "BNB": "BSC",
    "AVAX": "Avalanche",
    "MATIC": "Polygon",
    "POL": "Polygon",
    "ARB": "Arbitrum",
    "OP": "Optimism",
    "FTM": "Fantom",
    "ATOM": "Cosmos",
    "NEAR": "Near",
    "APT": "Aptos",
    "SUI": "Sui",
    "TRX": "Tron",
    "TON": "Ton",
    "SEI": "Sei",
    "KAVA": "Kava",
    "INJ": "Injective",
    "CRO": "Cronos",
    "CORE": "CORE",
    "BASE": "Base",
    "MNT": "Mantle",
    "ADA": "Cardano",
}

_cache: dict = {}
_CACHE_TTL = 3600  # секунды


def _historical_tvl(chain: str):
    now = time.time()
    hit = _cache.get(chain)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    data = get_json(f"https://api.llama.fi/v2/historicalChainTvl/{chain}")
    _cache[chain] = (now, data)
    return data


class DefiLlama(DataSource):
    name = "DefiLlama"
    scope = SCOPE_SYMBOL
    requires_key = False

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        chain = CHAIN_MAP.get(base_asset)
        if not chain:
            return None
        data = _historical_tvl(chain)
        if not isinstance(data, list) or len(data) < 8:
            return None
        try:
            tvl_now = float(data[-1]["tvl"])
            tvl_prev = float(data[-8]["tvl"])  # ~7 дней назад
        except (KeyError, ValueError, TypeError):
            return None
        if tvl_prev <= 0:
            return None

        change = (tvl_now - tvl_prev) / tvl_prev * 100
        if change > 5:
            score = 0.4
        elif change > 1:
            score = 0.2
        elif change < -5:
            score = -0.4
        elif change < -1:
            score = -0.2
        else:
            score = 0.0
        reason = f"TVL {chain} {change:+.1f}% за 7д"
        return Contribution(self.name, score, self.weight, reason).clamped()
