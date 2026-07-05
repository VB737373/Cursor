"""CoinGecko — FDV, market cap и риск разблокировки (бесплатно).

Публичный API: https://api.coingecko.com/api/v3
Demo-ключ (опционально): COINGECKO_API_KEY — выше лимиты, но не обязателен.

Логика: FDV >> Market Cap = большая доля токенов ещё заблокирована → давление
на продажу при разблокировках → медвежий фактор для лонга.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from .base import SCOPE_SYMBOL, Contribution, DataSource
from .http import get_json

log = logging.getLogger("coingecko")

_API = "https://api.coingecko.com/api/v3"
_ID_TTL = 7 * 24 * 3600.0
_DATA_TTL = 3600.0

# Топовые тикеры перпов — чтобы не дергать /search на каждый скан
_SYMBOL_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin", "SOL": "solana",
    "XRP": "ripple", "ADA": "cardano", "DOGE": "dogecoin", "AVAX": "avalanche-2",
    "DOT": "polkadot", "LINK": "chainlink", "MATIC": "matic-network",
    "POL": "polygon-ecosystem-token", "LTC": "litecoin", "BCH": "bitcoin-cash",
    "ATOM": "cosmos", "UNI": "uniswap", "NEAR": "near", "APT": "aptos",
    "ARB": "arbitrum", "OP": "optimism", "SUI": "sui", "SEI": "sei-network",
    "INJ": "injective-protocol", "TIA": "celestia", "FIL": "filecoin",
    "AAVE": "aave", "MKR": "maker", "CRV": "curve-dao-token", "RUNE": "thorchain",
    "FET": "fetch-ai", "RENDER": "render-token", "WLD": "worldcoin-wld",
    "PEPE": "pepe", "SHIB": "shiba-inu", "BONK": "bonk", "WIF": "dogwifcoin",
    "JUP": "jupiter-exchange-solana", "PYTH": "pyth-network", "ENA": "ethena",
    "ETHFI": "ether-fi", "ONDO": "ondo-finance", "PENDLE": "pendle",
    "STX": "blockstack", "IMX": "immutable-x", "GRT": "the-graph",
    "SAND": "the-sandbox", "MANA": "decentraland", "AXS": "axie-infinity",
    "TRX": "tron", "TON": "the-open-network", "HYPE": "hyperliquid",
    "TAO": "bittensor", "FLOKI": "floki", "NOT": "notcoin",
}

_id_cache: dict[str, tuple[float, str]] = {}
_data_cache: dict[str, tuple[float, dict]] = {}


def _headers(key: str) -> dict:
    if not key:
        return {}
    return {"x-cg-demo-api-key": key}


def _coin_id(symbol: str, key: str) -> Optional[str]:
    sym = symbol.upper()
    if sym in _SYMBOL_IDS:
        return _SYMBOL_IDS[sym]

    now = time.time()
    cached = _id_cache.get(sym)
    if cached and now - cached[0] < _ID_TTL:
        return cached[1]

    resp = get_json(f"{_API}/search", params={"query": sym}, headers=_headers(key))
    if not isinstance(resp, dict):
        return cached[1] if cached else None

    best = None
    best_rank = 10**9
    for coin in resp.get("coins") or []:
        if not isinstance(coin, dict):
            continue
        if (coin.get("symbol") or "").upper() != sym:
            continue
        rank = coin.get("market_cap_rank") or best_rank
        if rank < best_rank:
            best_rank = rank
            best = coin.get("id")
    if best:
        _id_cache[sym] = (now, best)
    return best


def _market(coin_id: str, key: str) -> Optional[dict]:
    now = time.time()
    cached = _data_cache.get(coin_id)
    if cached and now - cached[0] < _DATA_TTL:
        return cached[1]

    rows = get_json(
        f"{_API}/coins/markets",
        params={"vs_currency": "usd", "ids": coin_id, "sparkline": "false"},
        headers=_headers(key),
    )
    if not isinstance(rows, list) or not rows:
        return cached[1] if cached else None

    row = rows[0]
    _data_cache[coin_id] = (now, row)
    return row


def _fdv_ratio(row: dict) -> Optional[float]:
    mcap = row.get("market_cap")
    fdv = row.get("fully_diluted_valuation")
    try:
        mcap = float(mcap) if mcap is not None else 0.0
        fdv = float(fdv) if fdv is not None else 0.0
    except (TypeError, ValueError):
        mcap = fdv = 0.0

    if mcap > 0 and fdv > 0:
        return fdv / mcap

    circ = row.get("circulating_supply")
    total = row.get("total_supply") or row.get("max_supply")
    try:
        circ = float(circ) if circ is not None else 0.0
        total = float(total) if total is not None else 0.0
    except (TypeError, ValueError):
        return None
    if circ > 0 and total > 0:
        return total / circ
    return None


class CoinGeckoFDV(DataSource):
    name = "CoinGecko (FDV/MCap)"
    scope = SCOPE_SYMBOL
    requires_key = False

    def __init__(self, cfg, weight=1.0):
        super().__init__(cfg, weight)
        self.key = cfg.api_keys.get("coingecko", "")

    def enabled(self) -> bool:
        return True

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        coin_id = _coin_id(base_asset, self.key)
        if not coin_id:
            return None

        row = _market(coin_id, self.key)
        if not row:
            return None

        ratio = _fdv_ratio(row)
        if ratio is None:
            return None

        if ratio <= 1.5:
            score = 0.08
            reason = f"FDV/MCap {ratio:.1f}x — низкий риск разблокировки"
        elif ratio <= 3.0:
            score = 0.0
            reason = f"FDV/MCap {ratio:.1f}x — норма"
        elif ratio <= 5.0:
            score = -0.15
            reason = f"FDV/MCap {ratio:.1f}x — риск разблокировки"
        elif ratio <= 8.0:
            score = -0.25
            reason = f"FDV/MCap {ratio:.1f}x — высокий риск"
        else:
            score = -0.35
            reason = f"FDV/MCap {ratio:.1f}x — экстремальный риск"

        mcap = row.get("market_cap")
        if mcap:
            try:
                reason += f" (cap ${float(mcap)/1e9:.1f}B)"
            except (TypeError, ValueError):
                pass

        return Contribution(self.name, score, self.weight, reason).clamped()
