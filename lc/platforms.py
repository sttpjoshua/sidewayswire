"""Everything that differs per platform: rhythm, which clips go where, captions, titles, collabs.

Why (Joshua, 19 nov: "zorg dat de content op alle manieren geoptimaliseerd wordt"):
- Instagram ranks on watch time, likes per reach and sends (DM shares), and spreads reach thin when an
  account posts a lot of weaker pieces. So Instagram gets few, strong posts: 1 reel and about 1 post a day,
  keywords in the first line, 3 to 5 hashtags, a "send this" hook on battles, and drivers as collaborators.
- TikTok tests every video on its own and rewards completion and search: short versions (max 30 s) that
  start with the action, names and event in the caption, 3 posts a day.
- YouTube Shorts are found through search: a clear title under 60 characters, 2 a day.
- Facebook follows Instagram plus one extra reel a day.
"""
from __future__ import annotations

import re

from . import handles

# Amsterdam times. kind: "reel" (video) or "post" (image/carousel).
RHYTHM = {
    "instagram": {"08:30": "post", "17:30": "reel"},
    "facebook": {"08:30": "post", "12:30": "reel", "17:30": "reel"},
    "tiktok": {"12:30": "reel", "17:30": "reel", "21:30": "reel"},
    "youtube": {"13:00": "reel", "20:00": "reel"},
}
VIDEO_ONLY = {"tiktok", "youtube"}
IG_MIN_SCORE = 55          # reels below this never go to Instagram (they still go to TikTok, YouTube, Facebook)
MAX_HASHTAGS = {"instagram": 5, "facebook": 3, "tiktok": 4, "youtube": 3}
SHARE_KINDS = {"battle", "final", "crash", "omt", "call", "rumor"}
SHARE_HOOKS = [
    "Send this to the friend who still thinks they had it 👀",
    "Who took this one? Send it to someone who'll argue 👇",
    "Send this to your drift group chat 🔥",
    "Tag the person you watch drift with 👇",
]
SERIES_TAGS = {"Formula DRIFT": ["#formuladrift", "#formulad"], "Drift Masters": ["#driftmasters"],
               "D1GP": ["#d1gp"]}


def _ascii(name: str) -> str:
    import unicodedata
    n = name.lower().translate(str.maketrans({"ł": "l", "ø": "o", "ß": "ss", "æ": "ae", "đ": "d"}))
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", n)


def _src(post: dict) -> dict:
    s = post.get("source")
    return s if isinstance(s, dict) else {}


def _parts(caption: str) -> dict:
    """Split our standard caption into body, source line, handles and hashtags."""
    blocks = [b.strip() for b in (caption or "").split("\n\n") if b.strip()]
    out = {"body": "", "source": "", "handles": [], "tags": []}
    rest = []
    for b in blocks:
        if re.match(r"^(🎥|🎙)", b):
            lines = b.splitlines()
            out["source"] = lines[0]
            out["handles"] = re.findall(r"@[\w.]+", " ".join(lines[1:]))
        elif all(w.startswith("#") for w in b.split()):
            out["tags"] = b.split()
        else:
            rest.append(b)
    out["body"] = "\n\n".join(rest)
    return out


PLACES = ["Long Beach", "Las Vegas", "Connecticut", "Seattle", "Indianapolis", "Atlanta", "Orlando",
          "Englishtown", "St. Louis", "Utah", "Irwindale", "Italy", "Spain", "Poland", "Ireland", "Latvia",
          "Finland", "Germany", "Greece", "Hungary", "Belgium", "Sweden", "Ebisu", "Tokyo", "Odaiba"]


def event_name(post: dict) -> str:
    """'Formula DRIFT Las Vegas 2026', 'Drift Masters 2026 Round 1 Italy', 'Formula DRIFT Long Beach 2026
    Qualifying'; the show name for podcasts. Built from the full episode title, not the cut-off source line."""
    src = _src(post)
    series = src.get("podcast", "")
    if post.get("kind") == "vlog_clip":
        return f"{series} vlog".strip()
    if post.get("kind") != "stream_clip":
        line = _parts(post.get("caption", ""))["source"]
        return re.sub(r"^🎙\s*Full episode:\s*", "", line).split(",")[0].strip() or series
    ep = f"{src.get('episode', '')} {_parts(post.get('caption', ''))['source']}"
    year = (re.search(r"20\d\d", ep) or re.search(r"20\d\d", post.get("created", "")))
    year = year.group(0) if year else ""
    place = "Long Beach" if re.search(r"shoreline showdown|long beach", ep, re.I) else \
        next((p for p in PLACES if re.search(rf"\b{re.escape(p)}\b", ep, re.I)), "")
    rnd = re.search(r"round \d+", ep, re.I)
    grand = re.search(r"grand final", ep, re.I)
    stage = "Qualifying" if re.search(r"qualif", ep, re.I) else ""
    if series == "Drift Masters":
        parts = ["Drift Masters", year, "Grand Final" if grand else (rnd.group(0).title() if rnd else ""), place]
    else:
        fin = "Finale" if re.search(r"\bfinale\b", ep, re.I) and not place else ""
        parts = [series or "Formula DRIFT", place, fin, year]
    return " ".join(x for x in parts + [stage] if x)


def names(post: dict) -> list[str]:
    m = post.get("_moment") or {}
    return [n for n in handles.people(m) if n][:3] if m else []


def keyword_line(post: dict) -> str:
    who, ev = names(post), event_name(post)
    kind = (post.get("_moment") or {}).get("kind", "")
    if len(who) >= 2 and kind in ("battle", "final", "omt"):
        lead = f"{who[0]} vs {who[1]}"
    elif who:
        lead = who[0]
    else:
        lead = (post.get("title") or "").title()
    return " | ".join(x for x in (lead, ev) if x)


def _tags(post: dict, platform: str, have: list[str]) -> list[str]:
    series = _src(post).get("podcast", "")
    pref = SERIES_TAGS.get(series, []) + ["#drift"]
    people = ["#" + _ascii(n) for n in names(post)[:2]]
    tags = list(dict.fromkeys([*pref[:2], *people, *[t.lower() for t in have], "#sidewayswire"]))
    n = MAX_HASHTAGS[platform]
    return tags[:n - 1] + ["#sidewayswire"] if "#sidewayswire" not in tags[:n] else tags[:n]


def captions(post: dict) -> dict:
    """{'instagram','facebook','tiktok','youtube','youtube_title'} for one post. Joshua's own caption wins."""
    if post.get("caption_by") == "joshua":
        c = post.get("caption", "")
        return {p: c for p in RHYTHM} | {"youtube_title": (post.get("title") or keyword_line(post))[:60]}
    pt = _parts(post.get("caption", ""))
    kind = (post.get("_moment") or {}).get("kind", "")
    is_clip = post.get("kind") in ("stream_clip", "podcast_clip", "battle_reel", "vlog_clip")
    kw = keyword_line(post) if is_clip else ""
    share = SHARE_HOOKS[sum(map(ord, post.get("id", ""))) % len(SHARE_HOOKS)] if kind in SHARE_KINDS else ""
    hl = " ".join(pt["handles"])
    if post.get("kind") == "stream_clip" and pt["source"]:
        pt["source"] = f"🎥 Footage: {event_name(post)}"
    out = {}
    for p in ("instagram", "facebook"):
        blocks = [kw, pt["body"], share, "\n".join(x for x in (pt["source"], hl) if x), " ".join(_tags(post, p, pt["tags"]))]
        out[p] = "\n\n".join(b for b in blocks if b)
    # TikTok: short, searchable; names and event up front; handles as plain text credit.
    tt_body = pt["body"].split("\n")[0][:220]
    out["tiktok"] = "\n".join(x for x in (f"{kw}: {tt_body}" if kw else tt_body, share,
                                          f"{pt['source']} {hl}".strip(), " ".join(_tags(post, "tiktok", pt["tags"]))) if x)
    out["youtube_title"] = youtube_title(post, kw or post.get("title") or pt["body"].split("\n")[0])
    out["youtube"] = "\n\n".join(x for x in (pt["body"], "\n".join(y for y in (pt["source"], hl) if y),
                                            "Sideways Wire: drift news, battles and the best runs.",
                                            " ".join(_tags(post, "youtube", pt["tags"]))) if x)
    return out


def youtube_title(post: dict, full: str) -> str:
    """Under 60 characters, names and event first: full names, else surnames, else without the year."""
    if len(full) <= 60:
        return full
    who, ev = names(post), event_name(post)
    kind = (post.get("_moment") or {}).get("kind", "")
    sur = [n.split()[-1] for n in who]
    lead = (f"{sur[0]} vs {sur[1]}" if len(sur) >= 2 and kind in ("battle", "final", "omt") else (who[0] if who else ""))
    for t in (f"{lead} | {ev}", f"{lead} | {re.sub(r' 20\d\d', '', ev)}"):
        if lead and len(t) <= 60:
            return t
    return full[:57].rsplit(" ", 1)[0] + "..."


def collaborators(post: dict) -> list[str]:
    """Drivers with a checked handle, max 3, for Instagram collab invites (not the series or media)."""
    reg = handles.registry()
    out = []
    for n in names(post):
        r = reg.get(handles._key(n))
        if r and r.get("ok") and r.get("type") == "Coureur":
            out.append(r["handle"].lstrip("@"))
    return out[:3]
