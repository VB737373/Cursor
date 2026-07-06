"""Запуск облачного скана (GitHub Actions) по API."""
from __future__ import annotations

import os

import requests


def trigger_github_scan(repo: str | None = None, ref: str = "master") -> tuple[bool, str]:
    """Стартует облачный скан. Сначала repository_dispatch, затем workflow_dispatch."""
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = (repo or os.getenv("GITHUB_REPO") or "VB737373/Cursor").strip()
    if not token:
        return False, "Не задан GITHUB_TOKEN в .env (Personal Access Token с правом repo)."
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    actions_url = f"https://github.com/{repo}/actions/workflows/signals.yml"
    try:
        r = requests.post(
            f"https://api.github.com/repos/{repo}/dispatches",
            headers=headers,
            json={"event_type": "scan"},
            timeout=20,
        )
        if r.status_code == 204:
            return True, actions_url
        r2 = requests.post(
            f"https://api.github.com/repos/{repo}/actions/workflows/signals.yml/dispatches",
            headers=headers,
            json={"ref": ref},
            timeout=20,
        )
        if r2.status_code == 204:
            return True, actions_url
        return False, f"GitHub API {r.status_code}/{r2.status_code}: {r.text[:200]} | {r2.text[:200]}"
    except requests.RequestException as e:
        return False, str(e)
