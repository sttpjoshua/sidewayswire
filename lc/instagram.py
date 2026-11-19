"""Instagram via Meta's Graph API.

Reading other accounts uses Business Discovery: it works for public business
and creator accounts, which most drivers and teams are. Needs the Sideways Wire
Instagram business account id and a token (GitHub secrets IG_USER_ID, IG_TOKEN).
Posting (images, carousels, reels) uses the content publishing endpoints, the
same way as Bibleverse.
"""
from __future__ import annotations

import os
import time
from datetime import datetime

import requests

GRAPH = "https://graph.facebook.com/v21.0"
MEDIA_FIELDS = ("id,caption,media_type,media_url,permalink,timestamp,thumbnail_url,"
                "children{media_type,media_url}")


class Instagram:
    def __init__(self, user_id: str | None = None, token: str | None = None):
        self.user_id = user_id or os.environ.get("IG_USER_ID")
        self.token = token or os.environ.get("IG_TOKEN")
        if not (self.user_id and self.token) and os.environ.get("META_TOKEN"):
            from .meta import accounts
            a = accounts()
            self.user_id, self.token = a.get("ig_user_id"), a.get("ig_token")

    def _get(self, path: str, **params):
        params["access_token"] = self.token
        r = requests.get(f"{GRAPH}/{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, **data):
        data["access_token"] = self.token
        r = requests.post(f"{GRAPH}/{path}", data=data, timeout=60)
        r.raise_for_status()
        return r.json()

    # ---------- reading other accounts ----------
    def check_username(self, username: str) -> dict:
        """Does this account exist and can we read it? Used to verify the sources sheet."""
        try:
            d = self._get(self.user_id, fields=f"business_discovery.username({username}){{username,followers_count,media_count}}")
            return {"ok": True, **d["business_discovery"]}
        except requests.HTTPError as e:
            return {"ok": False, "error": str(e)}

    def recent_media(self, username: str, limit: int = 10) -> list[dict]:
        d = self._get(self.user_id,
                      fields=f"business_discovery.username({username}){{media.limit({limit}){{{MEDIA_FIELDS}}}}}")
        out = []
        for m in d["business_discovery"]["media"]["data"]:
            out.append({
                "source": f"@{username}", "kind": "instagram",
                "title": (m.get("caption") or "").split("\n")[0][:200],
                "url": m.get("permalink"), "media_url": m.get("media_url"),
                "media_type": m.get("media_type"),
                "published": datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00")),
                "raw": m,
            })
        return out

    # ---------- posting ----------
    def _wait(self, container_id: str, timeout: int = 300):
        start = time.time()
        while time.time() - start < timeout:
            s = self._get(container_id, fields="status_code")["status_code"]
            if s == "FINISHED":
                return
            if s == "ERROR":
                raise RuntimeError(f"Instagram could not process media {container_id}")
            time.sleep(5)
        raise TimeoutError(container_id)

    def post_image(self, image_url: str, caption: str) -> str:
        c = self._post(f"{self.user_id}/media", image_url=image_url, caption=caption)["id"]
        return self._post(f"{self.user_id}/media_publish", creation_id=c)["id"]

    def post_carousel(self, image_urls: list[str], caption: str) -> str:
        children = [self._post(f"{self.user_id}/media", image_url=u, is_carousel_item="true")["id"]
                    for u in image_urls]
        c = self._post(f"{self.user_id}/media", media_type="CAROUSEL",
                       children=",".join(children), caption=caption)["id"]
        return self._post(f"{self.user_id}/media_publish", creation_id=c)["id"]

    def post_reel(self, video_url: str, caption: str, cover_url: str | None = None) -> str:
        data = {"media_type": "REELS", "video_url": video_url, "caption": caption}
        if cover_url:
            data["cover_url"] = cover_url
        c = self._post(f"{self.user_id}/media", **data)["id"]
        self._wait(c)
        return self._post(f"{self.user_id}/media_publish", creation_id=c)["id"]

    def delete_check(self, media_id: str) -> bool:
        """True if one of our posts is gone (removed after a report)."""
        try:
            self._get(media_id, fields="id")
            return False
        except requests.HTTPError:
            return True
