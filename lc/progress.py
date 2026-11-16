"""Live progress of the podcast run, for the podcast page on the dashboard.

While a run is busy we write docs/podcasts-now.json straight to GitHub through the API
(not through git), at most every two minutes, so the page can show what is happening.
Outside GitHub Actions this does nothing.
"""
from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone

import requests

PATH = "docs/podcasts-now.json"
EVERY = 120          # seconds between updates
_state: dict = {}
_last = 0.0


def _put(data: dict):
    token, repo = os.environ.get("GH_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return
    url = f"https://api.github.com/repos/{repo}/contents/{PATH}"
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        r = requests.get(url, headers=h, params={"ref": "main"}, timeout=20)
        sha = r.json().get("sha") if r.ok else None
        if r.ok and data.get("phase") == "done":
            old = json.loads(base64.b64decode(r.json().get("content", "")) or b"{}")
            if old.get("phase") == "done":
                return                           # nothing was running, no need for a commit
        body = {"message": f"progress: {data.get('phase')}", "branch": "main",
                "content": base64.b64encode(json.dumps(data, ensure_ascii=False, indent=1).encode()).decode()}
        if sha:
            body["sha"] = sha
        requests.put(url, headers=h, json=body, timeout=20)
    except Exception as ex:                      # progress is nice to have, never break the run
        print("progress:", ex)


def update(force: bool = False, **kw):
    """Merge kw into the state and push it if forced or if EVERY seconds have passed."""
    global _last
    _state.update(kw)
    _state["updated"] = datetime.now(timezone.utc).isoformat()
    _state.setdefault("started", _state["updated"])
    _state.setdefault("run", os.environ.get("GITHUB_RUN_ID"))
    if force or time.time() - _last >= EVERY:
        _last = time.time()
        _put(dict(_state))


def done():
    update(force=True, phase="done", episode=None, pct=None)
