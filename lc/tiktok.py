"""TikTok: Login with TikTok and the Content Posting API (Joshua, 20 nov 2026).

The app "Sideways Wire Publisher" (developers.tiktok.com) has Login Kit and Content Posting API with the
scopes user.info.basic, video.upload and video.publish. Until TikTok has audited the app, posts can only
be private (SELF_ONLY): settings.tiktok_privacy decides, and stays SELF_ONLY until Joshua changes it.

How the connection is made (Joshua clicks, the system does the rest; no key passes through the chat):
1. Dashboard, INSTELLINGEN > Kanalen, KOPPEL TIKTOK: starts .github/workflows/tiktok.yml with action
   "login". This writes the TikTok sign-in link to data/tiktok/auth.json (the client key is public in
   that link anyway; the client secret never leaves GitHub's secrets).
2. Joshua signs in at TikTok and allows the app. TikTok sends him back to docs/tiktok-callback.html,
   which saves the one-time code in data/tiktok/code.json and starts the workflow with "exchange".
3. "exchange" trades the code for tokens. They are stored encrypted (key derived from the client secret)
   in data/tiktok/token.enc, and refreshed on every use (access 24 h, refresh 365 days).

Secrets: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET (GitHub > Settings > Secrets > Actions).

    python -m lc.tiktok login | exchange | info | test <video path or url>
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
DIR = ROOT / "data" / "tiktok"
AUTH, CODE, TOKEN, INFO = DIR / "auth.json", DIR / "code.json", DIR / "token.enc", DIR / "creator.json"
REDIRECT = "https://sttpjoshua.github.io/sidewayswire/tiktok-callback.html"
SCOPES = "user.info.basic,video.upload,video.publish"
API = "https://open.tiktokapis.com/v2"
CHUNK = 64 * 1024 * 1024          # TikTok: one piece up to 64 MB (our clips are far smaller)


def _keys() -> tuple[str, str]:
    k, s = os.environ.get("TIKTOK_CLIENT_KEY", "").strip(), os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()
    if not k or not s:
        raise RuntimeError("TIKTOK_CLIENT_KEY of TIKTOK_CLIENT_SECRET ontbreekt in de GitHub-secrets")
    return k, s


def _fernet():
    from cryptography.fernet import Fernet
    _, s = _keys()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("sidewayswire-tiktok:" + s).encode()).digest()))


def _save_token(t: dict) -> None:
    now = time.time()
    t["access_until"] = now + float(t.get("expires_in", 86400)) - 300
    t["refresh_until"] = now + float(t.get("refresh_expires_in", 31536000)) - 3600
    DIR.mkdir(parents=True, exist_ok=True)
    TOKEN.write_bytes(_fernet().encrypt(json.dumps(t).encode()))


def _load_token() -> dict:
    if not TOKEN.exists():
        raise RuntimeError("TikTok is nog niet gekoppeld")
    return json.loads(_fernet().decrypt(TOKEN.read_bytes()))


def _oauth(data: dict) -> dict:
    k, s = _keys()
    r = requests.post(f"{API}/oauth/token/", timeout=30, headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={"client_key": k, "client_secret": s, **data})
    j = r.json()
    if r.status_code >= 400 or j.get("error"):
        raise RuntimeError(f"TikTok: {j.get('error_description') or j.get('error') or r.text[:200]}")
    return j


def access_token() -> str:
    t = _load_token()
    if time.time() < t.get("access_until", 0):
        return t["access_token"]
    if time.time() > t.get("refresh_until", 0):
        raise RuntimeError("TikTok-koppeling verlopen: koppel opnieuw via het dashboard")
    nt = _oauth({"grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
    _save_token(nt)
    return nt["access_token"]


def connected() -> bool:
    try:
        return bool(access_token())
    except Exception:
        return False


def login() -> dict:
    """Step 1: the sign-in link, with a fresh state against forged answers."""
    k, _ = _keys()
    state = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urlencode(
        {"client_key": k, "scope": SCOPES, "response_type": "code", "redirect_uri": REDIRECT, "state": state})
    d = {"url": url, "state": state, "at": datetime.now(timezone.utc).isoformat()}
    DIR.mkdir(parents=True, exist_ok=True)
    AUTH.write_text(json.dumps(d, indent=1) + "\n")
    return {"ok": True, "url": url}


def exchange() -> dict:
    """Step 3: one-time code -> tokens (encrypted), then the creator info for the dashboard."""
    if not CODE.exists():
        raise RuntimeError("geen TikTok-code gevonden; begin opnieuw met KOPPEL TIKTOK")
    c = json.loads(CODE.read_text())
    a = json.loads(AUTH.read_text()) if AUTH.exists() else {}
    CODE.unlink()                                     # a code works once; never keep it
    if not a.get("state") or c.get("state") != a.get("state"):
        raise RuntimeError("TikTok-antwoord hoort niet bij deze koppelpoging (state); begin opnieuw")
    t = _oauth({"grant_type": "authorization_code", "code": c["code"], "redirect_uri": REDIRECT})
    _save_token(t)
    AUTH.unlink(missing_ok=True)
    return info() | {"connected": True}


def _post(path: str, body: dict | None = None) -> dict:
    r = requests.post(f"{API}/{path}", timeout=60, json=body or {},
                      headers={"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json; charset=UTF-8"})
    j = r.json()
    err = (j.get("error") or {})
    if r.status_code >= 400 or (err.get("code") not in (None, "ok")):
        raise RuntimeError(f"TikTok {path}: [{err.get('code')}] {err.get('message') or r.text[:200]}")
    return j.get("data") or {}


def info() -> dict:
    """Who we post as and what the account allows (TikTok wants this shown before every post)."""
    d = _post("post/publish/creator_info/query/")
    out = {k: d.get(k) for k in ("creator_nickname", "creator_username", "creator_avatar_url", "privacy_level_options",
                                 "comment_disabled", "duet_disabled", "stitch_disabled", "max_video_post_duration_sec")}
    out["checked"] = datetime.now(timezone.utc).isoformat()
    INFO.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    _mark(True, f"verbonden als @{out.get('creator_username') or out.get('creator_nickname')}")
    return out


def _mark(ok: bool, text: str) -> None:
    f = ROOT / "data" / "channels.json"
    d = json.loads(f.read_text())
    for c in d["channels"]:
        if c["id"] == "tiktok":
            c["connected"], c["check"] = ok, text
    f.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")


def _privacy(options: list[str]) -> str:
    want = json.loads((ROOT / "data" / "settings.json").read_text()).get("tiktok_privacy", "SELF_ONLY")
    if want in (options or []):
        return want
    if "SELF_ONLY" in (options or []):
        return "SELF_ONLY"
    raise RuntimeError(f"privacy {want} niet toegestaan door TikTok ({options})")


def post_video(src: str, caption: str, draft: bool = False, choice: dict | None = None) -> str:
    """Posts one video (file path or https url) straight to the profile. Returns the publish id.
    draft=True: "Upload to TikTok" instead: the video lands in the creator's TikTok inbox as a draft and
    Joshua posts it himself in the app (no caption or privacy via the API then)."""
    ci = {} if draft else info()
    path = Path(src) if not str(src).startswith("http") else None
    with __import__("tempfile").TemporaryDirectory() as tmp:
        if path is None:
            path = Path(tmp) / "v.mp4"
            with requests.get(src, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for b in r.iter_content(1 << 20):
                        f.write(b)
        size = path.stat().st_size
        # One piece when it fits (then chunk_size must equal the file size); else 64 MB pieces, the last
        # one takes the rest (total_chunk_count = size // chunk_size, as TikTok asks).
        chunk = size if size <= CHUNK else CHUNK
        n = 1 if size <= CHUNK else size // chunk
        src_info = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": n}
        d = _post("post/publish/inbox/video/init/", {"source_info": src_info}) if draft else _post("post/publish/video/init/", {
            "post_info": _post_info(caption, ci, choice),
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": n}})
        with open(path, "rb") as f:
            for i in range(n):
                start = i * chunk
                end = size - 1 if i == n - 1 else start + chunk - 1   # the last chunk takes the rest
                f.seek(start)
                body = f.read(end - start + 1)
                r = requests.put(d["upload_url"], data=body, timeout=300, headers={
                    "Content-Type": "video/mp4", "Content-Length": str(len(body)),
                    "Content-Range": f"bytes {start}-{end}/{size}"})
                if r.status_code >= 400:
                    raise RuntimeError(f"TikTok upload: {r.status_code} {r.text[:200]}")
    pid = d["publish_id"]
    for _ in range(40):                                  # TikTok processes the video; wait for the verdict
        s = _post("post/publish/status/fetch/", {"publish_id": pid})
        st = s.get("status")
        if st == "SEND_TO_USER_INBOX" and draft:
            return pid
        if st == "PUBLISH_COMPLETE":
            ids = s.get("publicaly_available_post_id") or s.get("publicly_available_post_id") or []
            return str(ids[0]) if ids else pid
        if st == "FAILED":
            raise RuntimeError(f"TikTok weigerde de video: {s.get('fail_reason')}")
        time.sleep(6)
    return pid


def fetch_for(post: dict, out_dir: Path) -> Path:
    """The file TikTok gets: the short version, else the full clip; from this checkout or the media store."""
    from . import mediastore
    for rel in [post.get("short"), post.get("video")] + list(post.get("media") or []):
        if not rel or not str(rel).endswith(".mp4"):
            continue
        local = ROOT / rel
        if local.exists() and local.stat().st_size > 0:
            return local
        out = out_dir / Path(rel).name
        if mediastore.download(rel, out):
            return out
    raise RuntimeError(f"geen video gevonden voor {post.get('id')}")


def post_for(post: dict, caption: str, draft: bool = False, choice: dict | None = None) -> str:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        return post_video(str(fetch_for(post, Path(tmp))), caption, draft, choice)


def _post_info(caption: str, ci: dict, choice: dict | None) -> dict:
    """What TikTok gets with a direct post. 'choice' comes from the posting page (docs/tiktok-post.html),
    where the person picks the privacy level and interactions himself, as TikTok's guidelines ask."""
    c = choice or {}
    opts = ci.get("privacy_level_options") or []
    priv = c.get("privacy") if c.get("privacy") in opts else _privacy(opts)
    return {"title": caption[:2200], "privacy_level": priv,
            "disable_comment": bool(ci.get("comment_disabled")) or not c.get("comment", True),
            "disable_duet": bool(ci.get("duet_disabled")) or not c.get("duet", True),
            "disable_stitch": bool(ci.get("stitch_disabled")) or not c.get("stitch", True),
            "brand_content_toggle": bool(c.get("brand_content")), "brand_organic_toggle": bool(c.get("brand_organic"))}


def status_for_dashboard() -> dict:
    out = {"connected": TOKEN.exists(), "auth_waiting": AUTH.exists()}
    if INFO.exists():
        out["creator"] = json.loads(INFO.read_text())
    return out


if __name__ == "__main__":
    act = (sys.argv[1:] or ["info"])[0]
    try:
        if act == "publish":                      # from the posting page: the person's own choices
            from . import queue as q
            req = json.loads((DIR / "request.json").read_text())
            (DIR / "request.json").unlink()
            tp = json.loads((q.QUEUE / f"{req['post']}.json").read_text())
            res = {"ok": True, "post": tp["id"], "publish_id": post_for(tp, req.get("caption", "")[:2200], choice=req)}
        elif act in ("test", "draft"):               # a post id: its short version, exactly as TikTok will get it
            from . import queue as q
            tp = json.loads((q.QUEUE / f"{sys.argv[2]}.json").read_text())
            res = {"ok": True, "post": tp["id"], "draft": act == "draft",
                   "publish_id": post_for(tp, ((tp.get("captions") or {}).get("tiktok") or tp.get("caption") or "")[:2000],
                                          draft=act == "draft")}
        else:
            res = {"login": login, "exchange": exchange, "info": info}[act]()
    except Exception as e:
        res = {"ok": False, "error": str(e)}
        if act in ("exchange", "info"):
            _mark(False, str(e)[:160])
    res.pop("url", None) if act == "login" else None
    print(json.dumps(res, indent=1, ensure_ascii=False))
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "last.json").write_text(json.dumps({"action": act, "at": datetime.now(timezone.utc).isoformat(), **res},
                                              indent=1, ensure_ascii=False) + "\n")
