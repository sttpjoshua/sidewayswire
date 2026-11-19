"""Local editor: does the work of the Claude 'redactie' on Joshua's Mac Studio, without credits.

It runs inside the Mac helper (video_helper.py), only when data/settings.json has "local_editor": true.
A small language model (Qwen 2.5 via mlx-lm, downloaded once from Hugging Face) does two jobs:

1. Moments: for every transcribed livestream, vlog (and podcast, when podcasts are on) without
   data/podcasts/moments/<id>.json, it reads the transcript in pieces of about 5 minutes and picks the
   moments worth a clip. Times are exact because the model answers with segment numbers from the
   transcript, never with times it makes up. Names are only kept when they are in data/sources.csv.
2. News: at most two new posts per round from data/inbox.json (stories not handled yet), written only
   from the text of the source. They become drafts; the normal build adds stills or portraits.

Rules from Joshua (EDITOR.md) apply: English, short, no em-dash, no drift or judging explainers,
rumors only as rumor and always checked, no made-up handles.
"""
from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone

VERSION = "1"
MODEL_BIG = "mlx-community/Qwen2.5-14B-Instruct-4bit"     # about 8 GB, for Macs with 32 GB or more
MODEL_SMALL = "mlx-community/Qwen2.5-7B-Instruct-4bit"    # about 4.5 GB
WINDOW = 70                 # transcript segments per question to the model
MAX_MOMENTS = {"stream": 30, "vlog": 8, "podcast": 12}
KINDS = {"stream": ["battle", "qualify", "crash", "omt", "call", "final", "moment"],
         "vlog": ["moment", "quote", "crash", "fact", "rumor"],
         "podcast": ["quote", "rumor", "fact", "moment"]}
NEWS_EVERY_H = 3
NEWS_PER_ROUND = 2

_model = None


# ---------- the model ----------
def _ram_gb() -> float:
    try:
        return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout) / 2**30
    except Exception:
        return 16


def model(log):
    global _model
    if _model:
        return _model
    try:
        import mlx_lm  # noqa: F401
    except ImportError:
        log("taalmodel: mlx-lm installeren (eenmalig)")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "mlx-lm"],
                       check=True)
    from mlx_lm import load
    name = MODEL_BIG if _ram_gb() >= 30 else MODEL_SMALL
    log(f"taalmodel laden: {name} (de eerste keer wordt het gedownload)")
    _model = (name, *load(name))
    return _model


def ask(log, system: str, user: str, max_tokens: int = 1800) -> str:
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler
    name, m, tok = model(log)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
    return generate(m, tok, prompt=prompt, max_tokens=max_tokens, sampler=make_sampler(temp=0.3), verbose=False)


def _json(text: str):
    text = re.sub(r"```(json)?", "", text)
    for open_, close in (("[", "]"), ("{", "}")):
        a, b = text.find(open_), text.rfind(close)
        if a != -1 and b > a:
            try:
                return json.loads(text[a:b + 1])
            except json.JSONDecodeError:
                continue
    return None


def _clean(s: str) -> str:
    return re.sub(r"\s*[—–]\s*", ", ", str(s or "")).strip()      # Joshua: never an em-dash


# ---------- names ----------
def _key(n: str) -> str:
    n = n.lower().translate(str.maketrans({"ł": "l", "ø": "o", "ß": "ss"}))
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode())


def known_people(json_or, gh) -> dict:
    """key -> proper name, for every person in data/sources.csv plus Joshua's own handles."""
    out = {}
    try:
        text = gh("/contents/data/sources.csv?ref=main", raw=True).decode("utf-8")
        for r in csv.DictReader(io.StringIO(text)):
            if r.get("Naam"):
                out[_key(r["Naam"])] = r["Naam"]
    except Exception:
        pass
    for name in json_or("data/handles_manual.json", {}):
        out[_key(name)] = name
    surnames = {}
    for k, n in list(out.items()):
        last = _key(n.split()[-1])
        surnames.setdefault(last, set()).add(n)
    out["_surnames"] = {k: next(iter(v)) for k, v in surnames.items() if len(v) == 1 and len(k) >= 4}
    return out


def fix_names(names: list, known: dict) -> list:
    out = []
    for n in names or []:
        k = _key(str(n))
        name = known.get(k) or known["_surnames"].get(_key(str(n).split()[-1]) if str(n).split() else "")
        if name and name not in out:
            out.append(name)
    return out[:4]


# ---------- moments ----------
SYSTEM_MOMENTS = """You are the clip editor of Sideways Wire, an English drift news channel (Formula DRIFT, Drift Masters).
You get a numbered piece of a transcript. Pick the moments that make a great short video clip on their own.
Answer ONLY with a JSON list. Each item:
{"start": first segment number, "end": last segment number, "hook": segment number of the strongest line,
 "kind": one of KINDS, "people": ["Full Name", ...], "topic": "HEADLINE IN CAPITALS, max 6 words",
 "hook_text": "TEASING QUESTION IN CAPITALS, max 7 words, does not give away the ending",
 "caption": "1 or 2 short English sentences for Instagram", "why": "a few words why this is strong"}
Rules: a moment is 15 to 70 seconds; it starts at the beginning of a sentence and ends after a finished
sentence; moments do not overlap. Skip ads, sponsor reads, greetings, filler. Never explain how drifting
or judging works. Never use an em-dash. Use only names that are spoken in the transcript or that you are
sure about; when unsure, leave people empty. If nothing in this piece is strong, answer []."""

FOCUS = {
    "stream": "This is a livestream commentary of a drift competition. Look for: the best qualifying runs "
              "(from start of the run to the score, kind 'qualify'), close or wild battles ('battle'), "
              "crashes and contact ('crash'), one more times ('omt'), judges' calls ('call'), the final ('final').",
    "vlog": "This is a YouTube vlog by a professional drifter. Look for: strong or surprising opinions ('quote'), "
            "big action on track or a crash ('crash' or 'moment'), reveals of new cars or plans ('fact'), "
            "hints about the future ('rumor').",
    "podcast": "This is a drift podcast. Look for: strong opinions ('quote'), hints about transfers, new cars or "
               "teams ('rumor'), facts fans do not know ('fact'), funny or emotional stories ('moment').",
}


def _seg_lines(segs: list, a: int, b: int) -> str:
    return "\n".join(f"[{i}] {int(s['start'] // 60):02d}:{int(s['start'] % 60):02d} {s['text'].strip()}"
                     for i, s in enumerate(segs[a:b], start=a))


def moments_for(ep: dict, transcript: dict, known: dict, log, beat) -> list:
    kind = ep.get("kind", "podcast")
    segs = [s for s in transcript.get("segments", []) if s.get("text", "").strip()]
    allowed = KINDS[kind]
    system = SYSTEM_MOMENTS.replace("KINDS", ", ".join(allowed))
    found = []
    for a in range(0, len(segs), WINDOW - 8):              # small overlap so a moment on a border is not lost
        b = min(len(segs), a + WINDOW)
        beat(f"lokale redactie: {ep.get('title', ep['id'])[:50]}: {int(100 * a / max(1, len(segs)))}%")
        user = f"{FOCUS[kind]}\nSource: {ep.get('podcast', '')} · {ep.get('title', '')}\n\n{_seg_lines(segs, a, b)}"
        try:
            items = _json(ask(log, system, user)) or []
        except Exception as ex:
            log("taalmodel:", ex)
            continue
        for it in items if isinstance(items, list) else []:
            try:
                s0, s1 = int(it["start"]), int(it["end"])
                hk = int(it.get("hook", s0))
            except (KeyError, TypeError, ValueError):
                continue
            if not (a <= s0 <= s1 < b):
                continue
            start, end = float(segs[s0]["start"]), float(segs[s1]["end"])
            if not 12 <= end - start <= 80:
                continue
            k = it.get("kind") if it.get("kind") in allowed else allowed[-1]
            people = fix_names(it.get("people"), known)
            quote = " ".join(segs[i]["text"].strip() for i in range(s0, s1 + 1))
            m = {"start": round(start, 2), "end": round(end, 2), "kind": k, "people": people,
                 "guest": " & ".join(people) or ep.get("creator") or ep.get("podcast", ""),
                 "topic": _clean(it.get("topic", "")).upper()[:60], "quote": quote,
                 "why": _clean(it.get("why", ""))[:120], "caption": _clean(it.get("caption", ""))[:400],
                 "credit": ep.get("credit") or "", "status": "new", "by": "local",
                 "score_hint": len(people)}
            if s0 <= hk <= s1:
                hs, he = float(segs[hk]["start"]), float(segs[hk]["end"])
                if 1.0 <= he - hs <= 6.0:
                    m["hook"] = {"start": round(hs, 2), "end": round(he, 2),
                                 "text": _clean(it.get("hook_text", "")).upper()[:60], "why": "lokale redactie"}
            if k == "rumor":
                m["check"], m["check_reason"] = True, "gerucht: check jij eerst"
            found.append(m)
    # no overlaps: keep the earlier one
    found.sort(key=lambda m: (m["start"], -len(m["people"])))
    out = []
    for m in found:
        if out and m["start"] < out[-1]["end"]:
            continue
        out.append(m)
    return out[:MAX_MOMENTS[kind]]


# ---------- news ----------
SYSTEM_NEWS = """You write news posts for Sideways Wire, an English drift news channel for fans aged 16 to 35.
Use ONLY facts that are in the text you get. Never guess results, numbers or quotes. Never use an em-dash.
Never explain how drifting works. Answer ONLY with JSON:
{"worth_it": true or false, "headline": ["MAX 16 CHARS", "MAX 16 CHARS", "MAX 16 CHARS"],
 "kicker": "SERIES OR EVENT, short, capitals", "body": "2 or 3 short sentences",
 "caption": "1 to 3 short sentences for Instagram, no hashtags, no @handles",
 "people": ["Full Name", ...], "backdrop": "ONE WORD like the series or brand", "rumor": true or false}
worth_it is false for ads, merchandise, ticket sales, results older than a week, or stories without real news."""


def _article_text(url: str) -> str:
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=20).read(400_000).decode("utf-8", "ignore")
    except Exception:
        return ""
    paras = re.findall(r"<p[^>]*>(.*?)</p>", html, flags=re.S | re.I)
    text = " ".join(re.sub(r"<[^>]+>", "", p) for p in paras)
    return re.sub(r"\s+", " ", text)[:6000]


def news(gh, put, json_or, log, beat, known: dict) -> int:
    inbox = json_or("data/inbox.json", {}).get("stories", [])
    handled = json_or("data/handled.json", {"handled": []})
    done = {h if isinstance(h, str) else h.get("id") for h in handled.get("handled", [])}
    made = 0
    for s in sorted(inbox, key=lambda s: -(s.get("buzz") or 0)):
        if made >= NEWS_PER_ROUND or s["id"] in done:
            continue
        beat(f"lokale redactie: nieuws: {s['title'][:60]}")
        src = "\n".join(f"- {i.get('source')}: {i.get('title')}" for i in s.get("items", [])[:6])
        body = _article_text(s["items"][0]["url"]) if s.get("items") else ""
        try:
            r = _json(ask(log, SYSTEM_NEWS, f"Story: {s['title']}\nSeries: {s.get('series')}\nHeadlines:\n{src}\n\nArticle text:\n{body or '(not available: use only the headlines)'}", 700))
        except Exception as ex:
            log("taalmodel nieuws:", ex)
            continue
        handled.setdefault("handled", []).append(s["id"])
        if not isinstance(r, dict) or not r.get("worth_it"):
            continue
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        slug = re.sub(r"[^a-z0-9]+", "-", s["title"].lower()).strip("-")[:48]
        head = [_clean(h).upper()[:18] for h in (r.get("headline") or [])][:3] or [s["title"].upper()[:18]]
        source = (s["items"][0].get("source") or "").split("·")[-1].strip() if s.get("items") else ""
        data = {"series_badge": [str(s.get("series") or "DRIFT")[:12]], "backdrop": _clean(r.get("backdrop") or s.get("series") or "DRIFT").upper()[:12],
                "backdrop_size": 520, "kicker": _clean(r.get("kicker", "")).upper()[:40], "headline": head,
                "body": _clean(r.get("body", ""))[:420], "source": source}
        rumor = bool(r.get("rumor"))
        post = {"id": f"{day}-{slug}", "kind": "news", "story": s["title"], "title": " ".join(head),
                "slides": [{"template": "news_text.html", "data": data}],
                "caption": _clean(r.get("caption", "")) + (f"\n\nSource: {source}" if source else ""),
                "people": fix_names(r.get("people"), known), "platforms": ["instagram", "facebook"],
                "check": rumor, "check_reason": "gerucht: check jij eerst" if rumor else "",
                "status": "draft", "by": "local", "created": datetime.now(timezone.utc).isoformat(),
                "source": s["items"][0]["url"] if s.get("items") else ""}
        put(f"queue/{post['id']}.json", json.dumps(post, indent=1, ensure_ascii=False).encode(),
            f"lokale redactie: nieuws {post['id']}")
        made += 1
        log("nieuwspost", post["id"])
    if made or len(handled.get("handled", [])) != len(done):
        put("data/handled.json", json.dumps(handled, indent=1, ensure_ascii=False).encode(), "lokale redactie: verwerkt")
    return made


# ---------- one round ----------
def run(gh, put, json_or, log, beat, state: dict, budget_s: int = 600) -> dict:
    settings = json_or("data/settings.json", {})
    if not settings.get("local_editor"):
        return {"off": True}
    t0, rep = time.time(), {"moments": 0, "episodes": 0, "news": 0}
    known = known_people(json_or, gh)
    eps = []
    reg = json_or("data/streams/streams.json", {"streams": [], "channels": []})
    for st in reg.get("streams", []) + json_or("data/streams/mac/_found.json", {"streams": []}).get("streams", []):
        mac = json_or(f"data/streams/mac/{st['id']}.json", {})
        if mac.get("status") == "transcribed":
            eps.append({"id": st["id"], "kind": st.get("kind", "stream"), "podcast": st.get("series"),
                        "title": st.get("title"), "credit": st.get("credit"), "creator": st.get("creator")})
    if settings.get("podcasts", True):
        ix = json_or("data/podcasts/episodes.json", {"episodes": {}})
        eps += [{"id": e["id"], "kind": "podcast", "podcast": e.get("podcast"), "title": e.get("title")}
                for e in ix.get("episodes", {}).values() if e.get("status") == "transcribed"]
    eps.sort(key=lambda e: {"stream": 0, "vlog": 1}.get(e["kind"], 2))
    for ep in eps:
        if time.time() - t0 > budget_s:
            break
        if json_or(f"data/podcasts/moments/{ep['id']}.json", None) is not None:
            continue
        t = json_or(f"data/podcasts/t/{ep['id']}.json", None)
        if not t:
            continue
        ms = moments_for(ep, t, known, log, beat)
        put(f"data/podcasts/moments/{ep['id']}.json", json.dumps(ms, indent=1, ensure_ascii=False).encode(),
            f"lokale redactie: {len(ms)} momenten uit {ep['id']}")
        rep["moments"] += len(ms)
        rep["episodes"] += 1
        log(f"lokale redactie: {len(ms)} momenten uit {ep.get('title')}")
    if time.time() - state.get("local_news", 0) > NEWS_EVERY_H * 3600 and time.time() - t0 < budget_s:
        rep["news"] = news(gh, put, json_or, log, beat, known)
        state["local_news"] = time.time()
    status = {"state": "local", "version": VERSION, "last_run": datetime.now(timezone.utc).isoformat(),
              "note": f"Lokale redactie op de Mac: {rep['moments']} momenten uit {rep['episodes']} video's, {rep['news']} nieuwsposts",
              "schedule": ["elke 15 minuten, als de Mac aanstaat"]}
    if rep["moments"] or rep["news"] or time.time() - state.get("local_status", 0) > 6 * 3600:
        put("docs/editor.json", json.dumps(status, indent=1, ensure_ascii=False).encode(), "lokale redactie: status")
        state["local_status"] = time.time()
    return rep
