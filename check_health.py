"""Проверка здоровья GitHub Actions + последнего скана.

Запускается отдельным workflow каждые 2 часа. Если скан упал, завис
или давно не запускался — шлёт предупреждение в Telegram.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("health")

REPO = os.getenv("GITHUB_REPOSITORY", "VB737373/Cursor")
WORKFLOW = os.getenv("HEALTH_WORKFLOW", "signals.yml")
LAST_SCAN = Path(__file__).parent / "state" / "last_scan.json"
STALE_MINUTES = int(os.getenv("HEALTH_STALE_MINUTES", "90"))
SLOW_SCAN_SEC = int(os.getenv("HEALTH_SLOW_SCAN_SEC", "2400"))  # 40 мин
_TG = "https://api.telegram.org/bot{token}/sendMessage"


def _chat_ids() -> list[int]:
    out = []
    for part in os.getenv("CHAT_IDS", "").replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                out.append(int(part))
            except ValueError:
                pass
    return out


def _send(token: str, chat_id: int, text: str) -> None:
    try:
        requests.post(
            _TG.format(token=token),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=20,
        )
    except requests.RequestException as e:
        log.warning("Telegram %s: %s", chat_id, e)


def _runs() -> list[dict]:
    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/runs"
    r = requests.get(url, params={"per_page": 8}, timeout=20)
    r.raise_for_status()
    return r.json().get("workflow_runs") or []


def _parse_ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _fmt_age(minutes: float) -> str:
    if minutes < 60:
        return f"{minutes:.0f} мин"
    return f"{minutes / 60:.1f} ч"


def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat_ids = _chat_ids()
    issues: list[str] = []
    info: list[str] = []

    try:
        runs = _runs()
    except requests.RequestException as e:
        issues.append(f"Не удалось прочитать GitHub Actions API: {e}")
        runs = []

    now = time.time()
    if runs:
        latest = runs[0]
        status = latest.get("status")
        conclusion = latest.get("conclusion")
        event = latest.get("event", "?")
        updated = latest.get("updated_at") or latest.get("created_at")
        age_min = (now - _parse_ts(updated)) / 60 if updated else 999
        url = latest.get("html_url", "")

        info.append(
            f"Последний запуск: <b>{status}</b>"
            + (f" ({conclusion})" if conclusion else "")
            + f", {event}, {_fmt_age(age_min)} назад"
        )

        if status == "completed" and conclusion not in ("success", "skipped"):
            issues.append(f"Последний скан завершился с ошибкой: <b>{conclusion}</b>")
        elif status in ("queued", "in_progress"):
            started = latest.get("run_started_at") or updated
            run_min = (now - _parse_ts(started)) / 60 if started else age_min
            if run_min > 40:
                issues.append(
                    f"Скан выполняется уже <b>{_fmt_age(run_min)}</b> — риск таймаута (лимит 45 мин)"
                )

        # Был ли успешный запуск за последние STALE_MINUTES?
        recent_ok = False
        for run in runs:
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                continue
            ts = run.get("updated_at") or run.get("created_at")
            if ts and (now - _parse_ts(ts)) / 60 <= STALE_MINUTES:
                recent_ok = True
                break
        if not recent_ok:
            issues.append(
                f"Нет успешного скана за последние <b>{STALE_MINUTES} мин</b> "
                f"(ожидание ~каждые 30–60 мин на бесплатном GitHub)."
            )
        if url:
            info.append(f"<a href=\"{url}\">Открыть последний run</a>")
    else:
        issues.append("Workflow crypto-signals ещё ни разу не запускался.")

    if LAST_SCAN.exists():
        try:
            meta = json.loads(LAST_SCAN.read_text("utf-8"))
            dur = float(meta.get("duration_sec") or 0)
            symbols = meta.get("symbols_scanned")
            signals = meta.get("signals_found")
            sent = meta.get("signals_sent")
            info.append(
                f"Последний скан в логе: {symbols} монет за {dur:.0f}с, "
                f"сигналов {signals}, отправлено {sent}"
            )
            if dur >= SLOW_SCAN_SEC:
                issues.append(
                    f"Скан занял <b>{dur / 60:.0f} мин</b> — близко к лимиту 45 мин "
                    f"(сейчас MAX_SYMBOLS={meta.get('max_symbols', '?')})"
                )
            if meta.get("error"):
                issues.append(f"Ошибка в scan_ci: {meta['error']}")
        except (ValueError, OSError, TypeError) as e:
            issues.append(f"Битый state/last_scan.json: {e}")

    if issues:
        text = "⚠️ <b>Мониторинг бота — проблема</b>\n\n"
        text += "\n".join(f"• {x}" for x in issues)
        if info:
            text += "\n\n" + "\n".join(info)
        log.warning("Проблемы: %s", issues)
        if token and chat_ids:
            for cid in chat_ids:
                _send(token, cid, text)
        raise SystemExit(1)

    log.info("OK: %s", " | ".join(info))
    print("HEALTH_OK")


if __name__ == "__main__":
    main()
