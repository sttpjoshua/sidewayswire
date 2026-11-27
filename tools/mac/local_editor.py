"""Local editor: does the work of the Claude 'redactie' on Joshua's Mac Studio, without credits.

It runs inside the Mac helper (video_helper.py), only when data/settings.json has "local_editor": true.
A small language model (Qwen 2.5 via mlx-lm, downloaded once from Hugging Face) does two jobs:

1. Moments: for every transcribed livestream, vlog (and podcast, when podcasts are on) without
   data/podcasts/moments/<id>.json, it reads the transcript in pieces of about 5 minutes and picks the
   moments worth a clip. Times are exact because the model answers with segment numbers from the
   transcript, never with times it makes up. Names are only kept when they are in data/sources.csv.
2. News: at most two new posts per round from data/inbox.json (stories not handled yet), written only
   from the text of the source. They become drafts; the normal build adds stills or portraits.
   Since v2 (Joshua, 19 nov, learned from DriftReady) the model also picks a kop-post format: breaking
   (departure, transfer, new team), winner, look (new car or livery) or question (an open question on the
   news: "Which team will X join?"). Those use templates/hook.html: one big headline, the driver in front.
3. Replies: for the best comments on our own posts (data/replies.json, collected by lc/engage.py) it writes
   a short, human reply. Joshua approves every reply on the dashboard; nothing is sent on its own.

Since v3 (Joshua, 26 nov) the work is split over four editors, each an agent on the dashboard (AGENTS)
with its own on/off switch and Joshua's own instruction (data/agents.json):
  battle    livestreams: battles, qualifying, crashes, calls
  podcast   podcasts and vlogs: quotes, rumors, facts
  nieuws    news from the inbox (in the order of the news scout) and Joshua's own tips (data/tips.json) first
  community reply suggestions
Each writes what it is doing, what it made and what went wrong to docs/agents/<id>.json.
v3 also fixes why v2 found nothing from 19 to 26 nov (0 moments from 144 videos): long answers from the
model were cut off, so the JSON did not parse and the whole piece was lost without a word. Now every
complete item is kept, and the reasons why items are dropped are counted and shown.

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

VERSION = "3"
MODEL_BIG = "mlx-community/Qwen2.5-14B-Instruct-4bit"     # about 8 GB, for Macs with 32 GB or more
MODEL_SMALL = "mlx-community/Qwen2.5-7B-Instruct-4bit"    # about 4.5 GB
WINDOW = 70                 # transcript segments per question to the model
MAX_MOMENTS = {"stream": 30, "vlog": 8, "podcast": 12}
KINDS = {"stream": ["battle", "qualify", "crash", "omt", "call", "final", "moment"],
         "vlog": ["moment", "quote", "crash", "fact", "rumor"],
         "podcast": ["quote", "rumor", "fact", "moment"]}
NEWS_EVERY_H = 3
HOOK_FORMATS = ("breaking", "winner", "look", "question", "rumor")
HOOK_LABELS = {"breaking": "BREAKING", "winner": "WINNER", "look": "NEW LOOK", "question": "YOUR CALL", "rumor": "RUMOR"}
SERIES_LABEL = {"Formula DRIFT": "FORMULA DRIFT", "FD": "FORMULA DRIFT", "Drift Masters": "DRIFT MASTERS",
                "DM": "DRIFT MASTERS", "D1GP": "D1 GRAND PRIX"}
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
        # 26 nov: this never ran in v2, because ask() imported mlx_lm before calling model(). That is why the
        # editor found 0 moments from 19 to 26 nov. Install for this Python only (--user), once.
        import importlib
        import site
        log("taalmodel: mlx-lm installeren (eenmalig, alleen voor deze Python)")
        last = ""
        for extra in (["--user"], []):
            r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", *extra,
                                "mlx-lm"], capture_output=True, text=True)
            if r.returncode == 0:
                break
            last = (r.stderr or r.stdout)[-300:]
        else:
            raise RuntimeError(f"mlx-lm installeren lukte niet ({sys.executable}): {last}")
        try:
            sys.path.append(site.getusersitepackages())
        except Exception:
            pass
        importlib.invalidate_caches()
    from mlx_lm import load
    name = MODEL_BIG if _ram_gb() >= 30 else MODEL_SMALL
    log(f"taalmodel laden: {name} (de eerste keer wordt het gedownload)")
    _model = (name, *load(name))
    return _model


def ask(log, system: str, user: str, max_tokens: int = 1800) -> str:
    name, m, tok = model(log)               # first: installs and loads the model when needed
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
    try:
        return generate(m, tok, prompt=prompt, max_tokens=max_tokens, sampler=make_sampler(temp=0.3), verbose=False)
    except TypeError:                       # older mlx-lm
        return generate(m, tok, prompt=prompt, max_tokens=max_tokens, temp=0.3, verbose=False)


def _json(text: str):
    """The JSON in a model answer. A list that was cut off (answer too long) still gives every item that
    was complete, instead of nothing (the v2 problem)."""
    text = re.sub(r"```(json)?", "", str(text or ""))
    a_l, a_o = text.find("["), text.find("{")
    if a_l != -1 and (a_o == -1 or a_l < a_o):
        b = text.rfind("]")
        if b > a_l:
            try:
                return json.loads(text[a_l:b + 1])
            except json.JSONDecodeError:
                pass
        dec, out, i = json.JSONDecoder(), [], a_l + 1
        while True:
            j = text.find("{", i)
            if j == -1:
                break
            try:
                obj, end = dec.raw_decode(text, j)
            except json.JSONDecodeError:
                break
            if isinstance(obj, dict):
                out.append(obj)
            i = end
        return out or None
    if a_o != -1:
        b = text.rfind("}")
        try:
            return json.loads(text[a_o:b + 1])
        except json.JSONDecodeError:
            try:
                return json.JSONDecoder().raw_decode(text, a_o)[0]
            except json.JSONDecodeError:
                return None
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


def moments_for(ep: dict, transcript: dict, known: dict, log, beat, agent=None, note: str = "") -> list:
    kind = ep.get("kind", "podcast")
    segs = [s for s in transcript.get("segments", []) if s.get("text", "").strip()]
    allowed = KINDS[kind]
    system = SYSTEM_MOMENTS.replace("KINDS", ", ".join(allowed)) + _steer(note)
    why = agent.drops if agent else {}
    found = []
    for a in range(0, len(segs), WINDOW - 8):              # small overlap so a moment on a border is not lost
        b = min(len(segs), a + WINDOW)
        beat(f"lokale redactie: {ep.get('title', ep['id'])[:50]}: {int(100 * a / max(1, len(segs)))}%")
        user = f"{FOCUS[kind]}\nSource: {ep.get('podcast', '')} · {ep.get('title', '')}\n\n{_seg_lines(segs, a, b)}"
        try:
            raw = ask(log, system, user, 2600)
        except Exception as ex:
            log("taalmodel:", ex)
            if agent:
                agent.error(f"taalmodel: {ex}")
            continue
        items = _json(raw)
        if items is None:
            why["antwoord onleesbaar"] = why.get("antwoord onleesbaar", 0) + 1
            if agent and not agent.sample:
                agent.sample = str(raw)[:600]
            continue
        items = items if isinstance(items, list) else [items]
        nums = [it.get("start") for it in items if isinstance(it, dict) and isinstance(it.get("start"), int)]
        rel = a > 0 and nums and all(0 <= x < WINDOW for x in nums) and not any(a <= x < b for x in nums)
        for it in items:
            try:
                s0, s1 = int(it["start"]), int(it["end"])
                hk = int(it.get("hook", s0))
            except (KeyError, TypeError, ValueError):
                why["zonder nummers"] = why.get("zonder nummers", 0) + 1
                continue
            if rel:                          # the model counted from 0 in this piece
                s0, s1, hk = s0 + a, s1 + a, hk + a
            if not (a <= s0 <= s1 < b):
                why["buiten het stuk"] = why.get("buiten het stuk", 0) + 1
                continue
            start, end = float(segs[s0]["start"]), float(segs[s1]["end"])
            if end - start < 12 and s1 + 1 < b:      # too short: grow to whole sentences up to ~20 s
                while s1 + 1 < b and float(segs[s1]["end"]) - start < 18:
                    s1 += 1
                end = float(segs[s1]["end"])
            if not 10 <= end - start <= 90:
                why["te kort of te lang"] = why.get("te kort of te lang", 0) + 1
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
{"worth_it": true or false, "format": "breaking" or "winner" or "look" or "question" or "news",
 "headline": ["MAX 16 CHARS", "MAX 16 CHARS", "MAX 16 CHARS"],
 "kicker": "SERIES OR EVENT, short, capitals", "body": "2 or 3 short sentences",
 "caption": "1 to 3 short sentences for Instagram, no hashtags, no @handles",
 "people": ["Full Name", ...], "backdrop": "ONE WORD like the series or brand", "rumor": true or false}
worth_it is false for ads, merchandise, ticket sales, results older than a week, or stories without real news.
format: "breaking" when a well-known driver leaves, joins, switches team or series, or retires;
"winner" when someone won an event (headline names the driver and the win);
"look" for a new car, build or livery reveal; "question" when the news leaves something open that fans
will want to guess (headline is then that question, e.g. ["WHICH TEAM WILL", "LUKE FINK JOIN?"]);
otherwise "news". Off-season (December to March) the stories about what the pros do between seasons
are worth_it true: guest entries in other series or countries (for example two Formula DRIFT champions in
D1GP in Japan), new projects, builds, YouTube series, shows and demos, team or car changes, plans for the
new season. If they won or placed somewhere, use "winner"; a new car or livery is "look".
Announcements are the most important posts in the off-season: a driver joining, leaving or returning to
a series, a pro license, a full season, a retirement or "won't be back", a new team or car for next year.
Those are always worth_it true and format "breaking", with a headline that says it plainly, for example
["JIMMY OAKES", "JOINS", "FORMULA DRIFT"] or ["ADAM LZ OUT", "FOR 2027"]. Only when the text really says so.
A rumor (someone hints at it, says it is a plan, or others say it, but it is not confirmed) is worth_it
true too, with rumor true and format "rumor": the headline is then a QUESTION, for example
["IS JIMMY OAKES", "GOING PRO", "IN 2027?"]; the caption says exactly what is known and who said it,
says it is not confirmed, and ends with a question to the fans ("What do you think?").
An Instagram caption by the driver counts as the source: use only what it says. The headline IS the post: short, strong, in capitals, max 3 lines.
caption: 1 or 2 short sentences. Use a human detail from the text when there is one (a comeback, a new
baby, a first win). A light opinion is fine ("he had style"), never mock or attack a person or series.
For "question" end the caption with the question to the reader. For "breaking" no question needed."""


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


def _tips_as_stories(json_or) -> list:
    """Joshua's own tips from the dashboard (TIP EEN NIEUWTJE): handled before anything else."""
    out = []
    for t in json_or("data/tips.json", {"tips": []}).get("tips", []):
        if t.get("status", "new") != "new":
            continue
        out.append({"id": "tip-" + t["id"], "tip": t, "title": t.get("note") or t.get("url") or "tip",
                    "series": t.get("series") or "", "buzz": 99,
                    "items": [{"source": "tip van Joshua", "title": t.get("note") or "", "url": t.get("url") or ""}]})
    return out


def news(gh, put, json_or, log, beat, known: dict, agent=None, note: str = "") -> int:
    inbox = json_or("data/inbox.json", {}).get("stories", [])
    handled = json_or("data/handled.json", {"handled": []})
    done = {h if isinstance(h, str) else h.get("id") for h in handled.get("handled", [])}
    tips = _tips_as_stories(json_or)
    tipfile = json_or("data/tips.json", {"tips": []})
    made, tips_changed = 0, False
    order = tips + sorted(inbox, key=lambda s: (-(s.get("scout") or {}).get("score", 0), -(s.get("buzz") or 0)))
    for s in order:
        is_tip = "tip" in s
        if s["id"] in done or (not is_tip and made >= NEWS_PER_ROUND):
            continue
        if not is_tip and (s.get("scout") or {}).get("skip"):
            continue
        beat(f"nieuwsredacteur: {s['title'][:60]}")
        if agent:
            agent.doing = f"leest: {s['title'][:80]}"
        src = "\n".join(f"- {i.get('source')}: {i.get('title')}" for i in s.get("items", [])[:6])
        body = _article_text(s["items"][0]["url"]) if s.get("items") and s["items"][0].get("url") else ""
        extra = ("\nJoshua, the owner, sent this tip himself because he finds it interesting for the channel. "
                 "Set worth_it true unless there is no news in it at all.") if is_tip else ""
        try:
            raw = ask(log, SYSTEM_NEWS + _steer(note), f"Story: {s['title']}\nSeries: {s.get('series')}\nHeadlines:\n{src}{extra}\n\nArticle text:\n{body or '(not available: use only the headlines)'}", 900)
        except Exception as ex:
            log("taalmodel nieuws:", ex)
            if agent:
                agent.error(f"taalmodel: {ex}")
            continue
        r = _json(raw)
        handled.setdefault("handled", []).append(s["id"])
        if is_tip:
            for t in tipfile.get("tips", []):
                if t["id"] == s["tip"]["id"]:
                    t["status"] = "done"
                    t["result"] = "geen nieuws gevonden in de tekst" if not (isinstance(r, dict) and r.get("worth_it")) else "post gemaakt"
                    tips_changed = True
        if not isinstance(r, dict):
            if agent:
                agent.drops["antwoord onleesbaar"] = agent.drops.get("antwoord onleesbaar", 0) + 1
                agent.sample = agent.sample or str(raw)[:600]
            continue
        if not r.get("worth_it"):
            if agent:
                agent.drops["geen nieuws volgens model"] = agent.drops.get("geen nieuws volgens model", 0) + 1
                agent.add(f"overgeslagen: {s['title'][:70]}")
            continue
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        slug = re.sub(r"[^a-z0-9]+", "-", s["title"].lower()).strip("-")[:48]
        head = [_clean(h).upper()[:18] for h in (r.get("headline") or [])][:3] or [s["title"].upper()[:18]]
        source = (s["items"][0].get("source") or "").split("·")[-1].strip() if s.get("items") else ""
        if is_tip or source.lower().startswith("tip"):
            # never "Source: tip van Joshua" in a caption: name the site of the link instead
            from urllib.parse import urlparse
            host = urlparse(s["items"][0].get("url") or "").netloc.replace("www.", "") if s.get("items") else ""
            source = host.split(".")[0].upper() if host else ""
        rumor = bool(r.get("rumor"))
        fmt = r.get("format") if r.get("format") in HOOK_FORMATS else "news"
        people = fix_names(r.get("people"), known)
        if fmt == "look" and not people:
            fmt = "news"
        caption = _clean(r.get("caption", "")) + (f"\n\nSource: {source}" if source else "")
        post = {"id": f"{day}-{slug}", "story": s["title"], "title": " ".join(head),
                "caption": caption, "people": people, "platforms": ["instagram", "facebook"],
                "check": rumor, "check_reason": "gerucht: check jij eerst" if rumor else "",
                "status": "draft", "by": "local", "created": datetime.now(timezone.utc).isoformat(),
                "scout_score": (s.get("scout") or {}).get("score"),
                "source": s["items"][0]["url"] if s.get("items") else ""}
        if fmt == "look":
            # A still from the livestream shows the OLD car: no still, and Joshua adds a photo we may use, or skips.
            post |= {"no_still": True, "check": True,
                     "check_reason": "nieuwe auto of livery: voeg een foto toe die we mogen gebruiken, of sla over"}
        if (s.get("scout") or {}).get("feature") or is_tip:
            post["fresh_hours"] = 120          # off-season features stay interesting longer than results
        if is_tip:
            post |= {"tip": s["tip"]["id"], "source": s["items"][0].get("url") or post["source"]}
        if rumor and people:
            fmt = "rumor"                       # 26 nov: rumors as a question post, Facebook first
            post |= {"platforms": ["facebook", "instagram"], "check": True,
                     "check_reason": "gerucht: klopt de basis? dan goedkeuren"}
        if fmt in HOOK_FORMATS and (not rumor or fmt == "rumor"):
            post |= {"kind": "breaking" if fmt == "breaking" else "hook", "hook": {"type": fmt},
                     "slides": [{"template": "hook.html", "data": {
                         "headline": head, "label": HOOK_LABELS[fmt],
                         "series": SERIES_LABEL.get(str(s.get("series") or ""), str(s.get("series") or "").upper())[:24]}}]}
        else:
            data = {"series_badge": [str(s.get("series") or "DRIFT")[:12]], "backdrop": _clean(r.get("backdrop") or s.get("series") or "DRIFT").upper()[:12],
                    "backdrop_size": 520, "kicker": _clean(r.get("kicker", "")).upper()[:40], "headline": head,
                    "body": _clean(r.get("body", ""))[:420], "source": source}
            post |= {"kind": "news", "slides": [{"template": "news_text.html", "data": data}]}
        put(f"queue/{post['id']}.json", json.dumps(post, indent=1, ensure_ascii=False).encode(),
            f"lokale redactie: nieuws {post['id']}")
        made += 1
        log("nieuwspost", post["id"])
        if agent:
            agent.add(f"nieuwspost: {' '.join(head)}" + (" (jouw tip)" if is_tip else ""), post["id"])
    if made or len(handled.get("handled", [])) != len(done):
        put("data/handled.json", json.dumps(handled, indent=1, ensure_ascii=False).encode(), "nieuwsredacteur: verwerkt")
    if tips_changed:
        put("data/tips.json", json.dumps(tipfile, indent=1, ensure_ascii=False).encode(), "nieuwsredacteur: tips verwerkt")
    return made


# ---------- replies to comments (Joshua approves every one) ----------
SYSTEM_REPLY = """You run the Facebook and Instagram of Sideways Wire, an English drift news page, and you are a drift fan.
A fan commented under one of our posts. Write ONE short reply, max 15 words, casual and human, like
DriftReady does: sometimes a short agreement ("Valid point", "100%", "You're not wrong"), sometimes a
short question back that keeps the talk going ("Would that ever be profitable though?").
Never insult or mock anyone, never state facts that are not in the post title or the comment, never
promise anything, no hashtags, no @names, never an em-dash. If the comment is spam, hateful, or about
a crash, injury, death or politics, skip it. Answer ONLY with JSON: {"reply": "...", "skip": true or false}"""
REPLIES_PER_ROUND = 12


def replies(gh, put, json_or, log, beat, agent=None, note: str = "") -> int:
    """Drafts replies for new comments in data/replies.json into data/replies_suggested.json.
    lc/engage.py merges them; Joshua approves, edits or skips each one on the dashboard."""
    items = [x for x in json_or("data/replies.json", {}).get("items", []) if x.get("status") == "new"]
    done = json_or("data/replies_suggested.json", {})
    todo = [x for x in items if x["id"] not in done][:REPLIES_PER_ROUND]
    for x in todo:
        beat(f"lokale redactie: antwoord op {x.get('author', '')}")
        try:
            r = _json(ask(log, SYSTEM_REPLY + _steer(note), f"Our post: {x.get('post_title', '')}\nComment by {x.get('author', '')}: {x.get('text', '')}", 120))
        except Exception as ex:
            log("taalmodel antwoord:", ex)
            continue
        if not isinstance(r, dict):
            continue
        reply = _clean(r.get("reply", "")).replace("#", "").strip()
        done[x["id"]] = {"skip": True} if r.get("skip") or not reply else {"reply": reply[:220]}
        if agent and reply and not r.get("skip"):
            agent.add(f"voorstel voor {x.get('author', '')}: {reply[:80]}")
    if todo:
        put("data/replies_suggested.json", json.dumps(done, indent=1, ensure_ascii=False).encode(),
            f"lokale redactie: {len(todo)} antwoordvoorstellen")
    return len(todo)


# ---------- one round ----------
def busy_hours(settings: dict, now: datetime | None = None) -> bool:
    """Joshua works on this Mac on weekdays 08:30-18:00 (20 nov): the model stays off then, so the Mac is
    all his. Evenings, nights and weekends it works. settings.local_editor_quiet = {"days": [0-4], "from", "to"}."""
    from zoneinfo import ZoneInfo
    qh = settings.get("local_editor_quiet") or {"days": [0, 1, 2, 3, 4], "from": "08:30", "to": "18:00"}
    t = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Europe/Amsterdam"))
    return t.weekday() in qh.get("days", []) and qh.get("from", "08:30") <= t.strftime("%H:%M") < qh.get("to", "18:00")


# ---------- agents on the dashboard ----------
AGENTS = {"battle": "Battle-redacteur", "podcast": "Podcast-redacteur", "nieuws": "Nieuwsredacteur",
          "community": "Community-redacteur"}


def _steer(note: str) -> str:
    note = (note or "").strip()
    return f"\n\nInstruction from Joshua, the owner (follow it, it wins over the rules above where they clash): {note[:600]}" if note else ""


class Agent:
    """What one editor is doing, for the dashboard: docs/agents/<id>.json."""

    def __init__(self, aid: str, put, json_or, state: dict):
        self.id, self.put, self.state = aid, put, state
        old = json_or(f"docs/agents/{aid}.json", {})
        self.history = old.get("history", [])[:25]
        self.doing, self.errors, self.drops, self.sample, self.made = None, [], {}, "", 0
        self.counts = old.get("counts", {})

    def add(self, text: str, ref: str | None = None):
        self.history.insert(0, {"at": datetime.now(timezone.utc).isoformat(), "text": text[:160], "ref": ref})
        self.history = self.history[:25]
        self.made += 1

    def error(self, text: str):
        self.errors.append(text[:200])

    def flush(self, state_word: str, note: str, force: bool = False):
        now = datetime.now(timezone.utc).isoformat()
        day = now[:10]
        if self.counts.get("day") != day:
            self.counts = {"day": day, "made": 0}
        self.counts["made"] = self.counts.get("made", 0) + self.made
        body = {"id": self.id, "name": AGENTS[self.id], "where": "Mac Studio (lokaal taalmodel)",
                "state": "fout" if self.errors else state_word, "doing": self.doing, "updated": now,
                "note": note, "history": self.history, "errors": self.errors[-5:], "drops": self.drops,
                "sample": self.sample, "counts": self.counts, "version": VERSION}
        key = f"agent_{self.id}"
        sig = json.dumps([body["state"], self.made, self.errors[-1:], self.drops], sort_keys=True)
        if force or self.made or self.errors or sig != self.state.get(key + "_sig") or time.time() - self.state.get(key, 0) > 3 * 3600:
            self.put(f"docs/agents/{self.id}.json", json.dumps(body, indent=1, ensure_ascii=False).encode(),
                     f"{AGENTS[self.id].lower()}: {body['state']}")
            self.state[key], self.state[key + "_sig"] = time.time(), sig
        self.made = 0


def run(gh, put, json_or, log, beat, state: dict, budget_s: int = 600) -> dict:
    settings = json_or("data/settings.json", {})
    if not settings.get("local_editor"):
        return {"off": True}
    cfg = json_or("data/agents.json", {}).get("agents", {})
    on = {a: cfg.get(a, {}).get("on", True) for a in AGENTS}
    note = {a: cfg.get(a, {}).get("note", "") for a in AGENTS}
    ag = {a: Agent(a, put, json_or, state) for a in AGENTS}
    if busy_hours(settings):
        for a in AGENTS:
            ag[a].doing = "pauze: werktijd, de Mac is van jou (weekdagen 08:30-18:00)"
            ag[a].flush("pauze" if on[a] else "uit", note[a])
        return {"off": True, "why": "werktijd: de Mac is van Joshua"}
    t0, rep = time.time(), {"moments": 0, "episodes": 0, "news": 0, "replies": 0}
    # Turbo (Joshua, 26 nov): to catch up the week that was lost, one long round instead of many short ones,
    # so the model is loaded once and keeps working. launchd never starts a second helper while one runs.
    global WINDOW
    turbo = False
    try:
        until = settings.get("local_editor_turbo_until")
        turbo = bool(until) and datetime.now(timezone.utc) < datetime.fromisoformat(until)
    except Exception:
        pass
    if turbo:
        budget_s, WINDOW = 50 * 60, 110
    try:
        model(log)                          # no model, no work: stop here instead of writing empty results
    except Exception as ex:
        for a in AGENTS:
            ag[a].doing = "wacht: het taalmodel start niet op deze Mac"
            ag[a].error(f"taalmodel: {ex}")
            ag[a].flush("fout", note[a])
        log("taalmodel start niet:", ex)
        return {"off": True, "why": f"taalmodel: {ex}"}
    known = known_people(json_or, gh)
    if on["community"]:
        ag["community"].doing = "leest nieuwe reacties"
        try:
            rep["replies"] = replies(gh, put, json_or, log, beat, ag["community"], note["community"])
        except Exception as ex:
            log("community-redacteur:", ex)
            ag["community"].error(str(ex))
        ag["community"].doing = None
    ag["community"].flush("wacht" if on["community"] else "uit", note["community"])
    # Joshua's tips first: they are what he wants now
    if on["nieuws"] and _tips_as_stories(json_or):
        rep["news"] += news(gh, put, json_or, log, beat, known, ag["nieuws"], note["nieuws"])
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
    # The hoofdredacteur (Claude, every morning) can put videos first: data/agents.json "priorities.first",
    # words or ids; a video whose id, title or channel contains one of them is read before the rest.
    first = [str(x).lower() for x in (json_or("data/agents.json", {}).get("priorities", {}).get("first") or [])]
    if first:
        hit = lambda e: any(w and (w in e["id"].lower() or w in str(e.get("title") or "").lower()
                                   or w in str(e.get("podcast") or "").lower()) for w in first)
        eps.sort(key=lambda e: not hit(e))
    # v2 wrote [] for 144 videos without finding anything: those are read again by v3 (once)
    redo = set(state.get("v3b_redo") or [])
    if not state.get("v3b_redo_set"):
        for e in eps:
            if json_or(f"data/podcasts/moments/{e['id']}.json", None) == []:
                redo.add(e["id"])
        state["v3b_redo"], state["v3b_redo_set"] = sorted(redo), True
    todo = {"battle": 0, "podcast": 0}
    for ep in eps:
        aid = "battle" if ep["kind"] == "stream" else "podcast"
        cur = json_or(f"data/podcasts/moments/{ep['id']}.json", None)
        if cur is not None and not (cur == [] and ep["id"] in redo):
            continue
        todo[aid] += 1
        if not on[aid] or time.time() - t0 > budget_s or busy_hours(settings):
            continue
        t = json_or(f"data/podcasts/t/{ep['id']}.json", None)
        if not t:
            continue
        a = ag[aid]
        a.doing = (f"{'turbo · ' if turbo else ''}leest: {ep.get('podcast') or ''} · {ep.get('title') or ep['id']}")[:120]
        a.flush("bezig", note[aid])
        n_err = len(a.errors)
        ms = moments_for(ep, t, known, log, beat, a, note[aid])
        if not ms and len(a.errors) > n_err:
            break                           # the model failed: keep this video for the next round
        put(f"data/podcasts/moments/{ep['id']}.json", json.dumps(ms, indent=1, ensure_ascii=False).encode(),
            f"{AGENTS[aid].lower()}: {len(ms)} momenten uit {ep['id']}")
        redo.discard(ep["id"])
        state["v3b_redo"] = sorted(redo)
        todo[aid] -= 1
        rep["moments"] += len(ms)
        rep["episodes"] += 1
        a.add(f"{len(ms)} momenten uit {ep.get('title') or ep['id']}", ep["id"])
        log(f"{AGENTS[aid]}: {len(ms)} momenten uit {ep.get('title')}")
    for aid in ("battle", "podcast"):
        ag[aid].doing = f"nog {todo[aid]} video's te lezen" if todo[aid] and on[aid] else None
        ag[aid].flush(("bezig" if todo[aid] else "wacht") if on[aid] else "uit", note[aid])
    if on["nieuws"] and time.time() - state.get("local_news", 0) > NEWS_EVERY_H * 3600 and time.time() - t0 < budget_s:
        rep["news"] += news(gh, put, json_or, log, beat, known, ag["nieuws"], note["nieuws"])
        state["local_news"] = time.time()
    ag["nieuws"].doing = None
    ag["nieuws"].flush("wacht" if on["nieuws"] else "uit", note["nieuws"])
    status = {"state": "local", "version": VERSION, "last_run": datetime.now(timezone.utc).isoformat(),
              "note": f"Lokale redactie op de Mac: {rep['moments']} momenten uit {rep['episodes']} video's, {rep['news']} nieuwsposts, {rep['replies']} antwoordvoorstellen",
              "schedule": ["elke 15 minuten, als de Mac aanstaat"]}
    if rep["moments"] or rep["news"] or rep["replies"] or time.time() - state.get("local_status", 0) > 6 * 3600:
        put("docs/editor.json", json.dumps(status, indent=1, ensure_ascii=False).encode(), "lokale redactie: status")
        state["local_status"] = time.time()
    return rep
