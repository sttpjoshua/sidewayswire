"""One Meta key for Instagram and Facebook.

Joshua makes a system-user token in Meta Business Settings (it does not expire) and stores it
as the GitHub secret META_TOKEN. From that token this module finds the Facebook page, the page
token and the linked Instagram business account, so no other ids are needed. The older
secrets (IG_USER_ID, IG_TOKEN, FB_PAGE_ID, FB_PAGE_TOKEN) still win when they are set.

    python -m lc.meta      # tests the connection and marks the channels in data/channels.json
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import requests

GRAPH = "https://graph.facebook.com/v21.0"
ROOT = Path(__file__).resolve().parent.parent
PAGE_NAME = os.environ.get("FB_PAGE_NAME", "sideways wire")


def _get(path: str, token: str, **params) -> dict:
    params["access_token"] = token
    r = requests.get(f"{GRAPH}/{path}", params=params, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(r.json().get("error", {}).get("message", r.text)[:300])
    return r.json()


@lru_cache(maxsize=1)
def accounts() -> dict:
    """{page_id, page_token, page_name, ig_user_id, ig_username, ig_token} or {} without a key."""
    out = {
        "page_id": os.environ.get("FB_PAGE_ID") or "",
        "page_token": os.environ.get("FB_PAGE_TOKEN") or "",
        "ig_user_id": os.environ.get("IG_USER_ID") or "",
        "ig_token": os.environ.get("IG_TOKEN") or "",
    }
    token = os.environ.get("META_TOKEN") or ""
    if token and not (out["page_id"] and out["page_token"] and out["ig_user_id"]):
        pages = _get("me/accounts", token, fields="id,name,access_token,"
                     "instagram_business_account{id,username}", limit=50).get("data", [])
        if not pages:
            raise RuntimeError("de sleutel ziet geen Facebook-pagina: wijs de pagina toe aan de systeemgebruiker")
        page = next((p for p in pages if PAGE_NAME in p["name"].lower()), pages[0])
        ig = page.get("instagram_business_account") or {}
        out["page_id"] = out["page_id"] or page["id"]
        out["page_token"] = out["page_token"] or page.get("access_token") or token
        out["page_name"] = page["name"]
        out["ig_user_id"] = out["ig_user_id"] or ig.get("id", "")
        out["ig_username"] = ig.get("username", "")
        out["ig_token"] = out["ig_token"] or token
    return out if any(out.values()) else {}


def check() -> dict:
    """Read-only test of both channels. Never posts anything."""
    res = {"facebook": {"ok": False}, "instagram": {"ok": False}}
    try:
        a = accounts()
    except Exception as e:
        res["error"] = str(e)
        return res
    if not a:
        res["error"] = "geen sleutel: zet META_TOKEN als GitHub-secret"
        return res
    try:
        p = _get(a["page_id"], a["page_token"], fields="name,link")
        res["facebook"] = {"ok": True, "name": p.get("name"), "url": p.get("link", "")}
    except Exception as e:
        res["facebook"]["error"] = str(e)
    if a.get("ig_user_id"):
        try:
            u = _get(a["ig_user_id"], a["ig_token"], fields="username")
            lim = _get(f"{a['ig_user_id']}/content_publishing_limit", a["ig_token"], fields="quota_usage")
            res["instagram"] = {"ok": True, "username": u.get("username"),
                                "posts_today": (lim.get("data") or [{}])[0].get("quota_usage", 0)}
        except Exception as e:
            res["instagram"]["error"] = str(e)
    else:
        res["instagram"]["error"] = "geen Instagram-account aan de Facebook-pagina gekoppeld"
    return res


def mark(res: dict) -> None:
    f = ROOT / "data" / "channels.json"
    d = json.loads(f.read_text())
    for c in d["channels"]:
        r = res.get(c["id"])
        if r is None:
            continue
        c["connected"] = bool(r.get("ok"))
        c["check"] = "verbonden" if r.get("ok") else r.get("error", "niet verbonden")
        if c["id"] == "facebook" and r.get("url"):
            c["url"] = r["url"]
    meta_ok = res.get("facebook", {}).get("ok") and res.get("instagram", {}).get("ok")
    for s in d["setup"]:
        if s["step"].startswith("Meta-app") or s["step"].startswith("Instagram-account") \
                or s["step"].startswith("Facebook-pagina"):
            s["done"] = bool(meta_ok) or s["done"]
    f.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    r = check()
    print(json.dumps(r, indent=1, ensure_ascii=False))
    mark(r)
