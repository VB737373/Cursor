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
from formatting import DISCLAIMER, format_signal

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("scan_ci")

STATE_FILE = Path(__file__).parent / "state" / "cooldown.json"
_TG_SEND = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_SIGNALS = 5


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


def main() -> None:
    cfg = Config.load()
    token = cfg.telegram_token or os.getenv("TELEGRAM_TOKEN", "").strip()
    if not token:
        raise SystemExit("Не задан TELEGRAM_TOKEN (секрет GitHub).")
    chat_ids = get_chat_ids()
    if not chat_ids:
        raise SystemExit("Нет получателей: задай секрет CHAT_IDS (твой chat id).")

    # Обновляем исходы ранее отправленных сигналов (журнал → trades.json)
    try:
        journal.check_open_trades()
    except Exception as e:
        log.warning("Журнал (проверка исходов): %s", e)

    scanner = Scanner(cfg)
    signals = scanner.scan()

    cd = load_cooldown()
    now = time.time()
    cd_seconds = cfg.cooldown_minutes * 60
    fresh = []
    for d in signals:
        if now - cd.get(d.symbol, 0) >= cd_seconds:
            fresh.append(d)
            cd[d.symbol] = now

    # чистим старые записи, чтобы файл не разрастался
    cd = {k: v for k, v in cd.items() if now - v < cd_seconds * 4}
    save_cooldown(cd)

    if not fresh:
        log.info("Новых сигналов нет.")
        return

    log.info("Новых сигналов: %d", len(fresh))
    for d in fresh[:_MAX_SIGNALS]:
        try:
            journal.log_signal(d)
        except Exception as e:
            log.warning("Журнал (запись сигнала): %s", e)
        text = format_signal(d) + DISCLAIMER
        for chat_id in chat_ids:
            send(token, chat_id, text)


if __name__ == "__main__":
    main()
