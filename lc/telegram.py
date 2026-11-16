"""Telegram: Joshua's remote control.

Secrets: TG_TOKEN (from BotFather), TG_CHAT (Joshua's chat id).
Checks arrive as a photo with buttons. Answers are picked up on the next run
(every 15 minutes) through getUpdates; no server needed.
"""
from __future__ import annotations

import json
import os

import requests

API = "https://api.telegram.org/bot{}/{}"


class Telegram:
    def __init__(self, token: str | None = None, chat: str | None = None):
        self.token = token or os.environ.get("TG_TOKEN")
        self.chat = chat or os.environ.get("TG_CHAT")

    @property
    def on(self) -> bool:
        return bool(self.token and self.chat)

    def _call(self, method: str, files=None, **data):
        r = requests.post(API.format(self.token, method), data=data, files=files, timeout=60)
        r.raise_for_status()
        return r.json()["result"]

    def text(self, msg: str):
        return self._call("sendMessage", chat_id=self.chat, text=msg[:4000])

    def check(self, post: dict, image_path: str, reason: str):
        """Ask Joshua to approve a post."""
        kb = {"inline_keyboard": [
            [{"text": "✅ Plaatsen", "callback_data": f"ok:{post['id']}"},
             {"text": "❌ Overslaan", "callback_data": f"skip:{post['id']}"}],
            [{"text": "🚫 Bron niet meer delen", "callback_data": f"block:{post['id']}"}],
        ]}
        cap = f"CHECK ({post['kind']}): {reason}\n\n{post.get('caption', '')}"[:1000]
        method, field = ("sendVideo", "video") if image_path.endswith(".mp4") else ("sendPhoto", "photo")
        with open(image_path, "rb") as f:
            return self._call(method, files={field: f}, chat_id=self.chat,
                              caption=cap, reply_markup=json.dumps(kb))

    def answers(self, offset: int = 0) -> tuple[list[tuple[str, str]], int]:
        """Returns ([(action, post_id)], next_offset). Only Joshua's chat counts."""
        ups = self._call("getUpdates", offset=offset, timeout=0,
                         allowed_updates=json.dumps(["callback_query"]))
        out = []
        for u in ups:
            offset = max(offset, u["update_id"] + 1)
            cq = u.get("callback_query")
            if not cq or str(cq["message"]["chat"]["id"]) != str(self.chat):
                continue
            action, _, pid = cq["data"].partition(":")
            out.append((action, pid))
            self._call("answerCallbackQuery", callback_query_id=cq["id"], text="Genoteerd")
        return out, offset
