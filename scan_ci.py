"""Разовый скан для GitHub Actions.

Сканирует рынок один раз и отправляет НОВЫЕ сигналы на лонг в Telegram.
Работает на серверах GitHub по расписанию — компьютер пользователя не нужен.

Состояние cooldown хранится в state/cooldown.json и коммитится обратно в репозиторий
(workflow это делает), чтобы не слать одну и ту же монету слишком часто между запусками.

Секреты (переменные окружения, задаются в настройках GitHub-репозитория):
  TELEGRAM_TOKEN — токен бота от @BotFather
  CHAT_IDS       — id получателей через запятую (напр. 122245443)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import requests

import journal
from config import Config
from engine import Scanner
from formatting import DISCLAIMER, format_scan_status, format_signal

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("scan_ci")

STATE_FILE = Path(__file__).parent / "state" / "cooldown.json"
LAST_SCAN_FILE = Path(__file__).parent / "state" / "last_scan.json"
_TG_SEND = "https://api.telegram.org/bot{token}/sendMessage"
MIN_SCAN_INTERVAL_SEC = int(os.getenv("MIN_SCAN_INTERVAL_SEC", "1500"))  # 25 мин между сканами


def load_cooldown() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text("utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def save_cooldown(cd: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(cd), "utf-8")


def save_scan_meta(meta: dict) -> None:
    path = Path(__file__).parent / "state" / "last_scan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")


def get_chat_ids() -> list:
    raw = os.getenv("CHAT_IDS", "").strip()
    out = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                out.append(int(part))
            except ValueError:
                pass
    if out:
        return out
    # запасной вариант — subscribers.json (локальный запуск)
    f = Path(__file__).parent / "subscribers.json"
    if f.exists():
        try:
            return list(json.loads(f.read_text("utf-8")))
        except (ValueError, OSError):
            return []
    return []


def send(token: str, chat_id: int, text: str) -> None:
    try:
        r = requests.post(
            _TG_SEND.format(token=token),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if r.status_code != 200:
            log.warning("Telegram %s: %s", r.status_code, r.text[:200])
    except requests.RequestException as e:
        log.warning("Не смог отправить в %s: %s", chat_id, e)


def is_manual_run() -> bool:
    return os.getenv("GITHUB_EVENT_NAME", "").strip() == "workflow_dispatch"


def should_skip_scan() -> tuple[bool, float]:
    """Не чаще MIN_SCAN_INTERVAL_SEC (кроме ручного запуска и внешнего cron)."""
    if os.getenv("FORCE_SCAN", "").lower() in ("1", "true", "yes"):
        return False, 0.0
    if is_manual_run():
        return False, 0.0
    if os.getenv("GITHUB_EVENT_NAME", "").strip() == "repository_dispatch":
        return False, 0.0
    if not LAST_SCAN_FILE.exists():
        return False, 0.0
    try:
        meta = json.loads(LAST_SCAN_FILE.read_text("utf-8"))
        last = float(meta.get("time") or 0)
        age = time.time() - last
        if age < MIN_SCAN_INTERVAL_SEC:
            return True, age
    except (ValueError, OSError, TypeError):
        pass
    return False, 0.0


def notify_manual_status(token: str, chat_ids: list, meta: dict) -> None:
    if not is_manual_run():
        return
    text = format_scan_status(meta)
    for chat_id in chat_ids:
        send(token, chat_id, text)


def main() -> None:
    t0 = time.time()
    cfg = Config.load()
    meta = {
        "time": t0,
        "max_symbols": cfg.max_symbols,
        "threshold": cfg.signal_threshold,
        "cooldown_min": cfg.cooldown_minutes,
        "symbols_scanned": 0,
        "signals_found": 0,
        "signals_sent": 0,
        "duration_sec": 0,
        "error": None,
    }
    token = cfg.telegram_token or os.getenv("TELEGRAM_TOKEN", "").strip()
    if not token:
        meta["error"] = "TELEGRAM_TOKEN missing"
        save_scan_meta(meta)
        raise SystemExit("Не задан TELEGRAM_TOKEN (секрет GitHub).")
    chat_ids = get_chat_ids()
    if not chat_ids:
        meta["error"] = "CHAT_IDS missing"
        save_scan_meta(meta)
        raise SystemExit("Нет получателей: задай секрет CHAT_IDS (твой chat id).")

    skip, age = should_skip_scan()
    if skip:
        log.info(
            "Пропуск: последний скан %.0f с назад (мин. интервал %d с)",
            age, MIN_SCAN_INTERVAL_SEC,
        )
        return

    try:
        journal.check_open_trades()
    except Exception as e:
        log.warning("Журнал (проверка исходов): %s", e)

    try:
        scanner = Scanner(cfg)
        signals = scanner.scan()
        meta["symbols_scanned"] = int(getattr(scanner, "_last_universe_size", 0) or 0)
    except Exception as e:
        meta["error"] = str(e)[:300]
        meta["duration_sec"] = round(time.time() - t0, 1)
        save_scan_meta(meta)
        notify_manual_status(token, chat_ids, meta)
        raise

    meta["signals_found"] = len(signals)
    if meta["symbols_scanned"] == 0:
        meta["symbols_scanned"] = cfg.max_symbols

    cd = load_cooldown()
    now = time.time()
    cd_seconds = cfg.cooldown_minutes * 60
    fresh = []
    for d in signals:
        if now - cd.get(d.symbol, 0) >= cd_seconds:
            fresh.append(d)
            cd[d.symbol] = now

    cd = {k: v for k, v in cd.items() if now - v < cd_seconds * 4}
    save_cooldown(cd)

    if not fresh:
        log.info("Новых сигналов нет.")
    else:
        log.info("Новых сигналов: %d", len(fresh))
        meta["signals_sent"] = len(fresh)
        for d in fresh:
            try:
                journal.log_signal(d)
            except Exception as e:
                log.warning("Журнал (запись сигнала): %s", e)
            text = format_signal(d) + DISCLAIMER
            for chat_id in chat_ids:
                send(token, chat_id, text)

    meta["duration_sec"] = round(time.time() - t0, 1)
    save_scan_meta(meta)
    notify_manual_status(token, chat_ids, meta)
    log.info("Скан завершён за %.0f с (%d монет, %d сигналов)",
             meta["duration_sec"], meta["symbols_scanned"], meta["signals_found"])


if __name__ == "__main__":
    main()
