"""Журнал сделок: логирует каждый отправленный сигнал и отслеживает исход.

Записывает сигналы в trades.json со статусом open. На каждом скане проверяет
открытые сделки по свечам Binance: задет ли стоп (loss) или тейк (win),
и обновляет статус. Команда /stats в боте показывает живую статистику.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

from sources.http import get_json

log = logging.getLogger("journal")

TRADES_FILE = Path(__file__).parent / "trades.json"
_SBASE = "https://api.binance.com"
_FBASE = "https://fapi.binance.com"
_MAX_HOLD_HOURS = 72  # через сколько часов закрывать сделку «по времени»
_KLINE_INTERVAL = "1h"


def to_binance_symbol(symbol: str, base: str | None = None) -> str:
    """Символ для Binance spot API: LTC-USDT / LTC_USDT → LTCUSDT."""
    if symbol:
        s = symbol.strip().upper().replace("-", "").replace("_", "")
        if s.endswith("USDT"):
            return s
    b = (base or "").strip().upper()
    if b:
        return f"{b}USDT"
    return symbol.strip().upper().replace("-", "").replace("_", "") if symbol else ""


def _trade_binance_symbol(t: dict) -> str:
    return t.get("binance_symbol") or to_binance_symbol(t.get("symbol", ""), t.get("base"))


def load_trades() -> List[dict]:
    if TRADES_FILE.exists():
        try:
            return json.loads(TRADES_FILE.read_text("utf-8"))
        except (ValueError, OSError):
            return []
    return []


def save_trades(trades: List[dict]) -> None:
    try:
        TRADES_FILE.write_text(json.dumps(trades, ensure_ascii=False, indent=2), "utf-8")
    except OSError as e:
        log.warning("Не удалось сохранить журнал: %s", e)


def log_signal(d) -> None:
    """Добавляет новый сигнал в журнал (статус open)."""
    trades = load_trades()
    trades.append({
        "time": time.time(),
        "symbol": d.symbol,
        "binance_symbol": to_binance_symbol(d.symbol, d.base),
        "base": d.base,
        "confidence": d.confidence,
        "entry": d.entry,
        "stop": d.stop,
        "take": d.take,
        "reasons": list(d.reasons),
        "status": "open",
        "exit_price": None,
        "exit_time": None,
        "pnl_pct": None,
    })
    save_trades(trades)


def _norm_kline_rows(rows: List[list]) -> List[list]:
    """Единый формат: [open_ms, o, h, l, c, v, close_ms]."""
    out: List[list] = []
    for r in rows:
        try:
            if len(r) >= 7 and int(r[0]) > 1_000_000_000_000:
                out.append([int(r[0]), float(r[1]), float(r[2]), float(r[3]),
                            float(r[4]), float(r[5]), int(r[6])])
            elif len(r) >= 6:
                open_ms = int(r[0]) * 1000 if int(r[0]) < 1_000_000_000_000 else int(r[0])
                close_ms = open_ms + 3_599_999
                out.append([open_ms, float(r[1]), float(r[2]), float(r[3]),
                            float(r[4]), float(r[5]), close_ms])
        except (TypeError, ValueError, IndexError):
            continue
    return sorted(out, key=lambda x: x[0])


def _fetch_binance_klines(base_url: str, symbol: str, start_ms: int) -> Optional[List[list]]:
    path = "/fapi/v1/klines" if "fapi" in base_url else "/api/v3/klines"
    data = get_json(f"{base_url}{path}",
                    params={"symbol": symbol, "interval": _KLINE_INTERVAL,
                            "startTime": start_ms, "limit": 200})
    if isinstance(data, list) and data:
        return _norm_kline_rows(data)
    return None


def _symbol_variants(symbol: str, base: str | None = None) -> List[str]:
    """Варианты символа для разных бирж (исходный + нормализованный)."""
    b = (base or "").strip().upper()
    if not b and symbol:
        s = symbol.strip().upper()
        for sep in ("-", "_"):
            if sep in s:
                b = s.split(sep)[0]
                break
        if not b and s.endswith("USDT"):
            b = s[:-4]
    out: List[str] = []
    for cand in (symbol, to_binance_symbol(symbol, base)):
        c = (cand or "").strip()
        if c and c not in out:
            out.append(c)
    if b:
        for cand in (f"{b}USDT", f"{b}_USDT", f"{b}-USDT"):
            if cand not in out:
                out.append(cand)
    return out


def _fetch_exchange_klines(start_ms: int, symbol: str, base: str | None) -> Optional[List[list]]:
    """Свечи с других бирж, если монеты нет на Binance spot."""
    from sources.exchanges.bybit import Bybit
    from sources.exchanges.bitget import Bitget
    from sources.exchanges.gateio import GateIO
    from sources.exchanges.bingx import BingX
    from sources.exchanges.kucoin import KuCoin

    start_sec = start_ms // 1000
    variants = _symbol_variants(symbol, base)

    for sym in variants:
        compact = sym.replace("-", "").replace("_", "")
        gate_sym = sym.replace("-", "_") if "-" in sym else (
            f"{sym[:-4]}_USDT" if sym.endswith("USDT") and "_" not in sym else sym
        )
        bing_sym = sym.replace("_", "-") if "_" in sym else (
            f"{sym[:-4]}-USDT" if sym.endswith("USDT") and "-" not in sym else sym
        )
        kucoin_sym = sym.replace("_", "-") if "_" in sym else (
            f"{sym[:-4]}-USDT" if sym.endswith("USDT") and "-" not in sym else sym
        )

        data = get_json(
            "https://api.bybit.com/v5/market/kline",
            params={"category": "spot", "symbol": compact, "interval": "60",
                    "start": start_ms, "limit": 200},
        )
        try:
            rows = data["result"]["list"]
            if rows:
                norm = [[r[0], r[1], r[2], r[3], r[4], r[5], int(r[0]) + 3_599_999]
                        for r in rows]
                return _norm_kline_rows(norm)
        except (KeyError, TypeError):
            pass

        data = get_json(
            "https://api.bitget.com/api/v2/spot/market/candles",
            params={"symbol": compact, "granularity": _KLINE_INTERVAL,
                    "startTime": start_ms, "limit": 200},
        )
        rows = data.get("data") if isinstance(data, dict) else None
        if isinstance(rows, list) and rows:
            norm = [[r[0], r[1], r[2], r[3], r[4], r[5], int(r[0]) + 3_599_999]
                    for r in rows]
            return _norm_kline_rows(norm)

        data = get_json(
            "https://api.gateio.ws/api/v4/spot/candlesticks",
            params={"currency_pair": gate_sym, "interval": _KLINE_INTERVAL,
                    "from": start_sec, "limit": 200},
        )
        if isinstance(data, list) and data:
            norm = [[r[0], r[5], r[3], r[4], r[2], r[6] if len(r) > 6 else r[1],
                     int(r[0]) * 1000 + 3_599_999] for r in data]
            return _norm_kline_rows(norm)

        data = get_json(
            "https://open-api.bingx.com/openApi/spot/v2/market/kline",
            params={"symbol": bing_sym, "interval": _KLINE_INTERVAL,
                    "startTime": start_ms, "limit": 200},
        )
        if isinstance(data, dict) and data.get("code") == 0:
            rows = data.get("data")
            if isinstance(rows, list) and rows:
                norm = [[r[0], r[1], r[2], r[3], r[4], r[5],
                         int(r[6]) if len(r) > 6 else int(r[0]) + 3_599_999]
                        for r in rows]
                return _norm_kline_rows(norm)

        data = get_json(
            "https://api.kucoin.com/api/v1/market/candles",
            params={"symbol": kucoin_sym, "type": "1hour", "startAt": start_sec},
        )
        if isinstance(data, dict) and data.get("code") == "200000":
            rows = data.get("data")
            if isinstance(rows, list) and rows:
                norm = [[r[0], r[1], r[3], r[4], r[2], r[5],
                         int(r[0]) * 1000 + 3_599_999] for r in rows]
                return _norm_kline_rows(norm)

        for ex, ex_sym in (
            (Bybit(), compact),
            (Bitget(), compact),
            (GateIO(), gate_sym),
            (BingX(), bing_sym),
            (KuCoin(), kucoin_sym),
        ):
            kl = ex.get_klines(ex_sym, _KLINE_INTERVAL, limit=200)
            if not kl:
                continue
            n = len(kl["close"])
            if n == 0:
                continue
            step = 3_600_000
            end_ms = int(time.time() * 1000)
            start_est = end_ms - n * step
            norm = []
            for i in range(n):
                open_ms = start_est + i * step
                if open_ms + step <= start_ms:
                    continue
                norm.append([open_ms, kl["open"][i], kl["high"][i], kl["low"][i],
                             kl["close"][i], kl["volume"][i], open_ms + step - 1])
            if norm:
                return _norm_kline_rows(norm)

    return None


def _fetch_klines_since(symbol: str, start_ms: int, base: str | None = None) -> Optional[List[list]]:
    """Свечи 1h с start_ms: Binance spot → futures → другие биржи."""
    for url in (_SBASE, _FBASE):
        kl = _fetch_binance_klines(url, symbol, start_ms)
        if kl:
            return kl
    return _fetch_exchange_klines(start_ms, symbol, base)


def check_open_trades() -> int:
    """Проверяет открытые сделки, отмечает исход. Возвращает число закрытых."""
    trades = load_trades()
    closed = 0
    changed = False
    now = time.time()

    for t in trades:
        bn = _trade_binance_symbol(t)
        if t.get("binance_symbol") != bn:
            t["binance_symbol"] = bn
            changed = True

        if t.get("status") != "open":
            continue
        entry = t.get("entry")
        stop = t.get("stop")
        take = t.get("take")
        if entry is None or stop is None or take is None:
            continue

        start_ms = int(t["time"] * 1000)
        kl = _fetch_klines_since(bn or t.get("symbol", ""), start_ms, t.get("base")) if bn or t.get("symbol") else None
        if not kl:
            # монета не на Binance или нет данных — закроем по времени, если пора
            if now - t["time"] >= _MAX_HOLD_HOURS * 3600:
                t["status"] = "timeout"
                t["exit_time"] = now
                t["pnl_pct"] = 0.0
                closed += 1
                changed = True
            continue

        outcome = None
        exit_price = None
        exit_ms = None
        for c in kl:
            try:
                high = float(c[2])
                low = float(c[3])
                close_ms = int(c[6])
                if close_ms < start_ms:
                    continue
            except (TypeError, ValueError, IndexError):
                continue
            if low <= stop:          # консервативно: стоп раньше тейка
                outcome, exit_price, exit_ms = "loss", stop, close_ms
                break
            if high >= take:
                outcome, exit_price, exit_ms = "win", take, close_ms
                break

        if outcome:
            t["status"] = outcome
            t["exit_price"] = exit_price
            t["exit_time"] = exit_ms / 1000 if exit_ms else now
            t["pnl_pct"] = (exit_price - entry) / entry * 100
            closed += 1
            changed = True
        elif now - t["time"] >= _MAX_HOLD_HOURS * 3600:
            last_close = float(kl[-1][4])
            t["status"] = "timeout"
            t["exit_price"] = last_close
            t["exit_time"] = now
            t["pnl_pct"] = (last_close - entry) / entry * 100
            closed += 1
            changed = True

    if changed:
        save_trades(trades)
    return closed


def summary() -> str:
    """Текстовая сводка по журналу для команды /stats."""
    trades = load_trades()
    if not trades:
        return "📓 Журнал пуст — сигналов ещё не было."

    closed = [t for t in trades if t.get("status") in ("win", "loss", "timeout")
              and t.get("pnl_pct") is not None]
    open_n = sum(1 for t in trades if t.get("status") == "open")

    if not closed:
        return (f"📓 <b>Статистика сделок</b>\n"
                f"Всего сигналов: {len(trades)}\n"
                f"Открыто (в работе): {open_n}\n"
                f"Закрытых пока нет — статистика появится позже.")

    wins = [t for t in closed if t["pnl_pct"] > 0]
    losses = [t for t in closed if t["pnl_pct"] <= 0]
    win_rate = len(wins) / len(closed) * 100
    avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0.0
    gross_win = sum(t["pnl_pct"] for t in wins)
    gross_loss = abs(sum(t["pnl_pct"] for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    total = sum(t["pnl_pct"] for t in closed)
    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"

    return (f"📓 <b>Статистика живых сигналов</b>\n\n"
            f"Всего сигналов: {len(trades)} (открыто: {open_n})\n"
            f"Закрыто: {len(closed)}\n"
            f"Win rate: <b>{win_rate:.0f}%</b> ({len(wins)}/{len(losses)})\n"
            f"Средний профит: {avg_win:+.2f}%\n"
            f"Средний убыток: {avg_loss:+.2f}%\n"
            f"Profit factor: <b>{pf_str}</b>\n"
            f"Суммарный P&L: {total:+.1f}%")
