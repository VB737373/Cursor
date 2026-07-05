"""Загрузка и хранение конфигурации бота из .env / переменных окружения."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _load_addresses(filename: str) -> list:
    """Читает список адресов Hyperliquid из файла (по одному в строке)."""
    path = Path(__file__).parent / filename
    out = []
    if path.exists():
        for line in path.read_text("utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line.split()[0])  # адрес до первого пробела/комментария
    return out


def _load_labeled(filename: str):
    """Читает адреса с метками: строка «0xADDR Имя». Возвращает (адреса, {addr:имя})."""
    path = Path(__file__).parent / filename
    addrs, labels = [], {}
    if path.exists():
        for line in path.read_text("utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            addr = parts[0]
            addrs.append(addr)
            if len(parts) > 1:
                name = parts[1].strip().lstrip("#").strip()
                if name:
                    labels[addr.lower()] = name
    return addrs, labels


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get(name) or default)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(_get(name) or default)
    except ValueError:
        return default


@dataclass
class Config:
    telegram_token: str = ""

    # Ключи внешних источников
    api_keys: dict = field(default_factory=dict)

    # Биржи для сканирования
    exchanges: list = field(default_factory=lambda: ["binance"])

    # Сканирование
    scan_mode: str = "top"
    max_symbols: int = 60
    min_volume_usdt: float = 5_000_000
    min_exchanges: int = 2
    require_futures: bool = True
    whale_addresses: list = field(default_factory=list)
    whales_auto: bool = True
    whales_top_n: int = 30
    whales_min_account: float = 2_000_000.0
    mm_addresses: list = field(default_factory=list)
    mm_labels: dict = field(default_factory=dict)
    mm_auto: bool = True
    mm_top_n: int = 20
    mm_min_volume: float = 50_000_000.0
    interval: str = "1h"
    check_interval_seconds: int = 300
    signal_threshold: float = 65.0
    cooldown_minutes: int = 120

    # Веса источников
    weights: dict = field(default_factory=dict)

    # Параметры стратегии
    ema_fast: int = 9
    ema_slow: int = 21
    ema_trend: int = 50
    rsi_period: int = 14
    rsi_long_min: float = 50
    rsi_long_max: float = 72
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_period: int = 14
    stop_atr_mult: float = 1.5
    take_atr_mult: float = 3.0

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        cfg.telegram_token = _get("TELEGRAM_TOKEN")

        cfg.api_keys = {
            "coinglass": _get("COINGLASS_API_KEY"),
            "coinmarketcap": _get("COINMARKETCAP_API_KEY"),
            "glassnode": _get("GLASSNODE_API_KEY"),
            "cryptoquant": _get("CRYPTOQUANT_API_KEY"),
            "nansen": _get("NANSEN_API_KEY"),
            "arkham": _get("ARKHAM_API_KEY"),
            "debank": _get("DEBANK_API_KEY"),
            "dropstab": _get("DROPSTAB_API_KEY"),
            "coingecko": _get("COINGECKO_API_KEY"),
            "lunarcrush": _get("LUNARCRUSH_API_KEY"),
        }

        exchanges_raw = _get("EXCHANGES") or "binance,bybit,bitget,gate,kucoin"
        cfg.exchanges = [x.strip().lower() for x in exchanges_raw.split(",") if x.strip()]

        cfg.scan_mode = (_get("SCAN_MODE") or "top").lower()
        cfg.max_symbols = _get_int("MAX_SYMBOLS", 60)
        cfg.min_volume_usdt = _get_float("MIN_VOLUME_USDT", 5_000_000)
        cfg.min_exchanges = _get_int("MIN_EXCHANGES", 2)
        cfg.require_futures = (_get("REQUIRE_FUTURES") or "true").lower() in ("1", "true", "yes")
        cfg.whale_addresses = _load_addresses("whales.txt")
        cfg.whales_auto = (_get("WHALES_AUTO") or "true").lower() in ("1", "true", "yes")
        cfg.whales_top_n = _get_int("WHALES_TOP_N", 30)
        cfg.whales_min_account = _get_float("WHALES_MIN_ACCOUNT", 2_000_000.0)
        cfg.mm_addresses, cfg.mm_labels = _load_labeled("market_makers.txt")
        cfg.mm_auto = (_get("MM_AUTO") or "true").lower() in ("1", "true", "yes")
        cfg.mm_top_n = _get_int("MM_TOP_N", 20)
        cfg.mm_min_volume = _get_float("MM_MIN_VOLUME", 50_000_000.0)
        cfg.interval = _get("INTERVAL") or "1h"
        cfg.check_interval_seconds = _get_int("CHECK_INTERVAL_SECONDS", 300)
        cfg.signal_threshold = _get_float("SIGNAL_THRESHOLD", 69.0)
        cfg.cooldown_minutes = _get_int("COOLDOWN_MINUTES", 120)

        cfg.weights = {
            "Technical Analysis": _get_float("WEIGHT_TA", 3.0),
            "Multi-Timeframe": _get_float("WEIGHT_MULTITF", 2.5),
            "Derivatives (Funding/OI)": _get_float("WEIGHT_DERIVATIVES", 2.5),
            "Order Flow (стакан/дельта)": _get_float("WEIGHT_ORDERFLOW", 2.0),
            "Volume Profile (POC)": _get_float("WEIGHT_VOLUME_PROFILE", 2.0),
            "Liquidations": _get_float("WEIGHT_LIQUIDATIONS", 1.5),
            "Liquidation Zones (оценка)": _get_float("WEIGHT_LIQ_ZONES", 1.5),
            "Hyperliquid Whales": _get_float("WEIGHT_WHALES", 2.0),
            "Hyperliquid Market Makers": _get_float("WEIGHT_MARKETMAKERS", 1.0),
            "Market Regime": _get_float("WEIGHT_REGIME", 1.0),
            "News": _get_float("WEIGHT_NEWS", 1.5),
            "Telegram Social": _get_float("WEIGHT_TELEGRAM", 1.5),
            "LunarCrush (соцсети)": _get_float("WEIGHT_LUNARCRUSH", 1.5),
            "Fear & Greed": _get_float("WEIGHT_FEAR_GREED", 1.0),
            "CoinGecko (FDV/MCap)": _get_float("WEIGHT_COINGECKO_FDV", 1.0),
            "DefiLlama": _get_float("WEIGHT_DEFILLAMA", 1.0),
            "CoinGlass": _get_float("WEIGHT_COINGLASS", 2.0),
            "CoinMarketCap": _get_float("WEIGHT_COINMARKETCAP", 1.0),
            "Glassnode": _get_float("WEIGHT_GLASSNODE", 1.5),
            "CryptoQuant": _get_float("WEIGHT_CRYPTOQUANT", 1.5),
            "Nansen": _get_float("WEIGHT_NANSEN", 2.0),
            "Arkham": _get_float("WEIGHT_ARKHAM", 1.5),
            "DeBank": _get_float("WEIGHT_DEBANK", 1.0),
            "DropsTab": _get_float("WEIGHT_DROPSTAB", 1.0),
        }

        cfg.ema_fast = _get_int("EMA_FAST", 9)
        cfg.ema_slow = _get_int("EMA_SLOW", 21)
        cfg.ema_trend = _get_int("EMA_TREND", 50)
        cfg.rsi_period = _get_int("RSI_PERIOD", 14)
        cfg.rsi_long_min = _get_float("RSI_LONG_MIN", 50)
        cfg.rsi_long_max = _get_float("RSI_LONG_MAX", 72)
        cfg.macd_fast = _get_int("MACD_FAST", 12)
        cfg.macd_slow = _get_int("MACD_SLOW", 26)
        cfg.macd_signal = _get_int("MACD_SIGNAL", 9)
        cfg.atr_period = _get_int("ATR_PERIOD", 14)
        cfg.stop_atr_mult = _get_float("STOP_ATR_MULT", 1.5)
        cfg.take_atr_mult = _get_float("TAKE_ATR_MULT", 3.0)
        return cfg
