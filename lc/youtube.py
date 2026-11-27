"""YouTube Shorts: Google sign-in (OAuth) and the YouTube Data API (Joshua, 20 nov 2026).

Channel: Sideways Wire (@SidewaysWire), account sidewayswire@outlook.com. The Google Cloud project has the
YouTube Data API v3 and an OAuth client of type "Web application" with the redirect below.

How the connection is made (same as TikTok; no key passes through the chat):
1. Dashboard, INSTELLINGEN > Kanalen, KOPPEL YOUTUBE: starts .github/workflows/youtube.yml with "login".
   That writes the Google sign-in link to data/youtube/auth.json.
2. Joshua signs in with the Sideways Wire account and allows the app. Google sends him back to
   docs/youtube-callback.html, which saves the one-time code in data/youtube/code.json and starts "exchange".
3. "exchange" trades the code for tokens, stored encrypted (key derived from the client secret) in
   data/youtube/token.enc. The access token lives 1 hour and is refreshed from the refresh token.

Until Google has audited the API project, every upload is locked to private (Google's rule for projects
made after July 2020). So posting only starts when settings.youtube_live is true (after the audit);
before that the channel shows as linked, and the planner leaves YouTube out.

Secrets: YT_CLIENT_ID, YT_CLIENT_SECRET (GitHub > Settings > Secrets > Actions).

    python -m lc.youtube login | exchange | info | test <post id>
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "youtube"
AUTH, CODE, TOKEN, INFO = DIR / "auth.json", DIR / "code.json", DIR / "token.enc", DIR / "channel.json"
REDIRECT = "https://sttpjoshua.github.io/sidewayswire/youtube-callback.html"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
CATEGORY = "2"            # Autos & Vehicles


def _settings() -> dict:
    return json.loads((ROOT / "data" / "settings.json").read_text())


def _keys() -> tuple[str, str]:
    k, s = os.environ.get("YT_CLIENT_ID", "").strip(), os.environ.get("YT_CLIENT_SECRET", "").strip()
    if not k or not s:
        raise RuntimeError("YT_CLIENT_ID of YT_CLIENT_SECRET ontbreekt in de GitHub-secrets")
    return k, s


def _fernet():
    from cryptography.fernet import Fernet
    _, s = _keys()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("sidewayswire-youtube:" + s).encode()).digest()))


def _save_token(t: dict) -> None:
    old = _load_token() if TOKEN.exists() else {}
    if t.get("refresh_token") and t["refresh_token"] != old.get("refresh_token"):
        t["refresh_since"] = time.time()                            # new sign-in: the 7-day clock (app in Testing) starts again
    else:
        t["refresh_since"] = old.get("refresh_since")
    t.setdefault("refresh_token", old.get("refresh_token"))       # Google sends it only at the first sign-in
    t["access_until"] = time.time() + float(t.get("expires_in", 3600)) - 300
    DIR.mkdir(parents=True, exist_ok=True)
    TOKEN.write_bytes(_fernet().encrypt(json.dumps(t).encode()))


def _load_token() -> dict:
    if not TOKEN.exists():
        raise RuntimeError("YouTube is nog niet gekoppeld")
    return json.loads(_fernet().decrypt(TOKEN.read_bytes()))


def _oauth(data: dict) -> dict:
    k, s = _keys()
    r = requests.post(TOKEN_URL, timeout=30, data={"client_id": k, "client_secret": s, **data})
    j = r.json()
    if r.status_code >= 400 or j.get("error"):
        if j.get("error") == "invalid_grant":
            raise RuntimeError("YouTube-koppeling verlopen of ingetrokken: koppel opnieuw via het dashboard")
        raise RuntimeError(f"Google: {j.get('error_description') or j.get('error') or r.text[:200]}")
    return j


def access_token() -> str:
    t = _load_token()
    if time.time() < t.get("access_until", 0):
        return t["access_token"]
    if not t.get("refresh_token"):
        raise RuntimeError("geen refresh token; koppel YouTube opnieuw")
    nt = _oauth({"grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
    _save_token(nt)
    return nt["access_token"]


def connected() -> bool:
    try:
        return bool(access_token())
    except Exception:
        return False


def live() -> bool:
    """Posting is on: linked, and Google has audited the project (Joshua sets youtube_live)."""
    return bool(_settings().get("youtube_live")) and connected()


def login() -> dict:
    k, _ = _keys()
    state = secrets.token_urlsafe(16)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {"client_id": k, "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPES, "state": state,
         "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"})
    d = {"url": url, "state": state, "at": datetime.now(timezone.utc).isoformat()}
    DIR.mkdir(parents=True, exist_ok=True)
    AUTH.write_text(json.dumps(d, indent=1) + "\n")
    return {"ok": True, "url": url}


def exchange() -> dict:
    if not CODE.exists():
        raise RuntimeError("geen Google-code gevonden; begin opnieuw met KOPPEL YOUTUBE")
    c = json.loads(CODE.read_text())
    a = json.loads(AUTH.read_text()) if AUTH.exists() else {}
    CODE.unlink()
    if not a.get("state") or c.get("state") != a.get("state"):
        raise RuntimeError("Google-antwoord hoort niet bij deze koppelpoging (state); begin opnieuw")
    t = _oauth({"grant_type": "authorization_code", "code": c["code"], "redirect_uri": REDIRECT})
    if not t.get("refresh_token"):
        raise RuntimeError("Google gaf geen refresh token; verwijder de app bij myaccount.google.com/permissions en koppel opnieuw")
    TOKEN.unlink(missing_ok=True)
    _save_token(t)
    AUTH.unlink(missing_ok=True)
    try:
        ch = info()
    except Exception:
        TOKEN.unlink(missing_ok=True)
        raise
    want = _settings().get("youtube_handle", "@sidewayswire").lower()
    if (ch.get("handle") or "").lower() != want:
        # 21 nov: the first try linked Joshua's own channel. Only the Sideways Wire channel may be linked.
        TOKEN.unlink(missing_ok=True)
        INFO.unlink(missing_ok=True)
        _mark(False, f"verkeerd kanaal gekozen ({ch.get('title')} {ch.get('handle') or ''}); koppel opnieuw met Sideways Wire", False)
        raise RuntimeError(f"verkeerd kanaal: {ch.get('title')} {ch.get('handle') or ''}. Kies bij Google het Sideways Wire-kanaal")
    return ch | {"connected": True}


def _get(path: str, **params) -> dict:
    r = requests.get(f"{API}/{path}", params=params, timeout=30, headers={"Authorization": f"Bearer {access_token()}"})
    j = r.json()
    if r.status_code >= 400:
        e = j.get("error") or {}
        raise RuntimeError(f"YouTube {path}: [{r.status_code}] {e.get('message') or r.text[:200]}")
    return j


def info() -> dict:
    items = _get("channels", part="snippet,statistics", mine="true").get("items") or []
    if not items:
        raise RuntimeError("dit Google-account heeft geen YouTube-kanaal")
    ch = items[0]
    sn = ch.get("snippet") or {}
    out = {"id": ch["id"], "title": sn.get("title"), "handle": sn.get("customUrl"),
           "thumb": ((sn.get("thumbnails") or {}).get("default") or {}).get("url"),
           "subscribers": (ch.get("statistics") or {}).get("subscriberCount"),
           "checked": datetime.now(timezone.utc).isoformat()}
    DIR.mkdir(parents=True, exist_ok=True)
    INFO.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    s = _settings()
    who = f"{out['title']} ({out.get('handle') or out['id']})"
    _mark(bool(s.get("youtube_live")), who if s.get("youtube_live") else f"gekoppeld als {who}; posten start na de YouTube-audit", True)
    return out


def _mark(ok: bool, text: str, linked: bool | None = None) -> None:
    f = ROOT / "data" / "channels.json"
    d = json.loads(f.read_text())
    for c in d["channels"]:
        if c["id"] == "youtube":
            c["connected"], c["check"] = ok, text
            if linked is not None:
                c["linked"] = linked
    f.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")


def upload(path: Path, title: str, description: str, tags: list[str] | None = None, privacy: str | None = None,
           shorts: bool = True) -> str:
    """Resumable upload in one go (our Shorts are a few MB). Returns the video id."""
    privacy = privacy or _settings().get("youtube_privacy", "private")
    title = title.strip()[:100] or "Sideways Wire"
    if shorts and "#shorts" not in (title + description).lower():
        description = (description + "\n\n#Shorts").strip()
    meta = {"snippet": {"title": title, "description": description[:5000], "tags": (tags or [])[:15],
                        "categoryId": CATEGORY, "defaultLanguage": "en"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False,
                       "embeddable": True}}
    size = path.stat().st_size
    r = requests.post(f"{UPLOAD}?uploadType=resumable&part=snippet,status", json=meta, timeout=60, headers={
        "Authorization": f"Bearer {access_token()}", "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(size), "Content-Type": "application/json; charset=UTF-8"})
    if r.status_code >= 400:
        raise RuntimeError(f"YouTube upload start: [{r.status_code}] {r.text[:300]}")
    loc = r.headers["Location"]
    with open(path, "rb") as f:
        r = requests.put(loc, data=f, timeout=600, headers={"Content-Type": "video/mp4", "Content-Length": str(size)})
    if r.status_code >= 400:
        raise RuntimeError(f"YouTube upload: [{r.status_code}] {r.text[:300]}")
    return r.json()["id"]


def post_for(post: dict, title: str, description: str, privacy: str | None = None) -> str:
    import tempfile
    from .tiktok import fetch_for          # same file choice: the short version, else the full clip
    tags = [t.lstrip("#") for t in (post.get("tags") or []) if t][:10]
    with tempfile.TemporaryDirectory() as tmp:
        if post.get("long"):              # own formats: the landscape version goes up as a normal video
            from . import mediastore
            local, out = ROOT / post["long"], Path(tmp) / Path(post["long"]).name
            src = local if local.exists() and local.stat().st_size else (out if mediastore.download(post["long"], out) else None)
            if not src:
                raise RuntimeError(f"geen liggende video gevonden voor {post.get('id')}")
            return upload(src, title, description, tags, privacy, shorts=False)
        return upload(fetch_for(post, Path(tmp)), title, description, tags, privacy)


def texts(post: dict) -> tuple[str, str]:
    caps = post.get("captions") or {}
    return (caps.get("youtube_title") or post.get("title") or "Sideways Wire"), (caps.get("youtube") or post.get("caption") or "")


def status_for_dashboard() -> dict:
    out = {"connected": TOKEN.exists(), "auth_waiting": AUTH.exists(), "live": bool(_settings().get("youtube_live"))}
    if INFO.exists():
        out["channel"] = json.loads(INFO.read_text())
    return out


if __name__ == "__main__":
    act = (sys.argv[1:] or ["info"])[0]
    try:
        if act == "test":                       # a post id: uploaded privately, exactly as YouTube will get it
            from . import queue as q
            tp = json.loads((q.QUEUE / f"{sys.argv[2]}.json").read_text())
            t, d = texts(tp)
            vid = post_for(tp, t, d, privacy="private")
            res = {"ok": True, "post": tp["id"], "video_id": vid, "url": f"https://youtube.com/shorts/{vid}"}
        else:
            res = {"login": login, "exchange": exchange, "info": info}[act]()
    except Exception as e:
        res = {"ok": False, "error": str(e)}
        if act in ("exchange", "info"):
            _mark(False, str(e)[:160])
    if act == "login":
        res.pop("url", None)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "last.json").write_text(json.dumps({"action": act, "at": datetime.now(timezone.utc).isoformat(), **res},
                                              indent=1, ensure_ascii=False) + "\n")
