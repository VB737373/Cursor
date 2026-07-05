"""Запуск облачного скана (GitHub Actions) по API."""
from __future__ import annotations

import os

import requests


def trigger_github_scan(repo: str | None = None, ref: str = "master") -> tuple[bool, str]:
    """Стартует workflow signals.yml. Возвращает (ok, url_или_текст_ошибки)."""
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = (repo or os.getenv("GITHUB_REPO") or "VB737373/Cursor").strip()
    if not token:
        return False, "Не задан GITHUB_TOKEN в .env (Personal Access Token с правом actions:write)."
    url = f"https://api.github.com/repos/{repo}/actions/workflows/signals.yml/dispatches"
    try:
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"ref": ref},
            timeout=20,
        )
    except requests.RequestException as e:
        return False, str(e)
    actions_url = f"https://github.com/{repo}/actions/workflows/signals.yml"
    if r.status_code == 204:
        return True, actions_url
    return False, f"GitHub API {r.status_code}: {r.text[:300]}"
