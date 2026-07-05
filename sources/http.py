"""Единый HTTP-клиент с таймаутами и безопасным разбором JSON."""
from __future__ import annotations

import logging
from typing import Optional

import requests

log = logging.getLogger("http")

_session = requests.Session()
_session.headers.update({"User-Agent": "crypto-long-signal-bot/1.0"})

DEFAULT_TIMEOUT = 15


def get_json(url: str, params: dict | None = None,
             headers: dict | None = None,
             timeout: int = DEFAULT_TIMEOUT) -> Optional[object]:
    """GET → распарсенный JSON или None при любой ошибке."""
    try:
        resp = _session.get(url, params=params, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            log.warning("GET %s -> HTTP %s", url, resp.status_code)
            return None
        return resp.json()
    except requests.RequestException as e:
        log.warning("GET %s failed: %s", url, e)
        return None
    except ValueError:
        log.warning("GET %s: невалидный JSON", url)
        return None


def get_text(url: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[str]:
    """GET → тело ответа как текст или None при ошибке (для RSS/XML)."""
    try:
        resp = _session.get(url, timeout=timeout)
        if resp.status_code != 200:
            log.warning("GET %s -> HTTP %s", url, resp.status_code)
            return None
        return resp.text
    except requests.RequestException as e:
        log.warning("GET %s failed: %s", url, e)
        return None
