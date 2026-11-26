"""Wanneer verlopen de sleutels? Schrijft data/keys.json, een keer per dag (vanuit run.yml).

Alleen vervaldatums en of een sleutel werkt; nooit de sleutels zelf.
- META_TOKEN (Instagram en Facebook): Meta's debug_token geeft expires_at (0 = verloopt nooit).
- MEDIA_TOKEN (GitHub-sleutel voor de media-opslag): GitHub zet de vervaldatum in een antwoordheader.
- TikTok: de refresh-sleutel in data/tiktok/token.enc (365 dagen, wordt bij gebruik vernieuwd).
- YouTube: zolang de Google-app op "Testing" staat, verloopt de koppeling na 7 dagen.
Het dashboard (kantoor) laat de serverkast roken als er een binnen 7 dagen verloopt of al stuk is.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "keys.json"
WARN_DAYS = 7


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None


def meta() -> dict:
    tok = os.environ.get("META_TOKEN", "").strip()
    if not tok:
        return {"name": "Meta (Instagram en Facebook)", "state": "ontbreekt"}
    try:
        r = requests.get("https://graph.facebook.com/v21.0/debug_token", params={"input_token": tok, "access_token": tok}, timeout=30).json()
        d = r.get("data") or {}
        if not d.get("is_valid", False):
            return {"name": "Meta (Instagram en Facebook)", "state": "werkt niet", "error": (r.get("error") or {}).get("message", "ongeldig")[:120]}
        exp = d.get("expires_at") or 0
        return {"name": "Meta (Instagram en Facebook)", "state": "ok", "expires": _iso(exp) if exp else None,
                "data_access_expires": _iso(d.get("data_access_expires_at")) if d.get("data_access_expires_at") else None}
    except Exception as e:
        return {"name": "Meta (Instagram en Facebook)", "state": "onbekend", "error": str(e)[:120]}


def media() -> dict:
    tok = os.environ.get("MEDIA_TOKEN", "").strip()
    if not tok:
        return {"name": "GitHub-sleutel media-opslag", "state": "ontbreekt"}
    try:
        r = requests.get("https://api.github.com/user", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        if r.status_code == 401:
            return {"name": "GitHub-sleutel media-opslag", "state": "werkt niet", "error": "GitHub weigert de sleutel"}
        h = r.headers.get("github-authentication-token-expiration")
        exp = datetime.strptime(h.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).isoformat() if h else None
        return {"name": "GitHub-sleutel media-opslag", "state": "ok", "expires": exp}
    except Exception as e:
        return {"name": "GitHub-sleutel media-opslag", "state": "onbekend", "error": str(e)[:120]}


def tiktok() -> dict:
    try:
        from . import tiktok as tt
        t = tt._load_token()
        return {"name": "TikTok", "state": "ok", "expires": _iso(t.get("refresh_until"))}
    except Exception as e:
        return {"name": "TikTok", "state": "niet gekoppeld" if "nog niet" in str(e) else "onbekend", "error": str(e)[:120]}


def youtube() -> dict:
    try:
        from . import youtube as yt
        t = yt._load_token()
        testing = json.loads((ROOT / "data" / "settings.json").read_text()).get("youtube_app_testing", True)
        since = t.get("refresh_since")
        return {"name": "YouTube", "state": "ok", "expires": _iso(since + 7 * 86400) if testing and since else None,
                "note": "Google-app staat op Testing: koppeling verloopt na 7 dagen" if testing else None}
    except Exception as e:
        return {"name": "YouTube", "state": "niet gekoppeld" if "nog niet" in str(e) else "onbekend", "error": str(e)[:120]}


def run(force: bool = False) -> dict:
    if not force and OUT.exists():
        try:
            last = json.loads(OUT.read_text()).get("checked")
            if last and time.time() - datetime.fromisoformat(last).timestamp() < 20 * 3600:
                return json.loads(OUT.read_text())         # een keer per dag is genoeg
        except Exception:
            pass
    keys = {"meta": meta(), "media": media(), "tiktok": tiktok(), "youtube": youtube()}
    now = time.time()
    for k in keys.values():
        exp = k.get("expires")
        if exp:
            days = (datetime.fromisoformat(exp).timestamp() - now) / 86400
            k["days_left"] = round(days, 1)
            if days < 0:
                k["state"] = "verlopen"
            elif days < WARN_DAYS and k["state"] == "ok":
                k["state"] = "verloopt bijna"
    out = {"checked": datetime.now(timezone.utc).isoformat(), "keys": keys}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    import sys
    print(json.dumps(run(force="--nu" in sys.argv), indent=1, ensure_ascii=False))
