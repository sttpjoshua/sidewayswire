"""Proeftest kop-posts en community (19 nov 2026): python -m pytest -q tests/test_community.py"""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lc import engage, hooks, planner, stats  # noqa: E402
from lc import queue as q  # noqa: E402


def test_feed_keeps_stock_without_facts(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "USED", tmp_path / "used.json")
    added = hooks.feed(now=datetime(2026, 12, 2, tzinfo=timezone.utc), folder=tmp_path)
    assert len(added) == hooks.STOCK["off"]
    assert hooks.feed(now=datetime(2026, 12, 2, tzinfo=timezone.utc), folder=tmp_path) == []   # stock is full
    p = q.load(folder=tmp_path)[0]
    assert p["slides"][0]["template"] == "hook.html" and p["evergreen"] and not p.get("check")
    assert "—" not in json.dumps(json.loads(hooks.QUESTIONS.read_text()), ensure_ascii=False)
    summer = tmp_path / "s"
    summer.mkdir()
    assert len(hooks.feed(now=datetime(2027, 6, 2, tzinfo=timezone.utc), folder=summer)) == hooks.STOCK["on"]


def test_media_and_caption_credit():
    p = hooks.make("whatif", ["DEANE VS", "SHANAHAN"], "Who takes it? 👇", ["James Deane", "Conor Shanahan"],
                   tags=["#jamesdeane"], post_id="t-1")
    hooks.add_media([p])
    d = p["slides"][0]["data"]
    assert d["band"] in hooks.PALETTE and d["label"] == "WHAT IF?"
    assert d.get("photo") or d.get("backdrop")
    if d.get("photo"):
        assert "Photo: @formulad" in p["caption"] and p["caption"].endswith("#jamesdeane")


def test_planner_questions_fill_gaps_and_breaking_first():
    posts = []
    for i, x in enumerate(json.loads(hooks.QUESTIONS.read_text())["questions"][:4]):
        posts.append(hooks.make(x["type"], x["headline"], x["caption"], post_id=f"q-{i}", evergreen=x["id"])
                     | {"status": "ready", "media": ["a.png"], "created": f"2026-11-0{i + 1}"})
    posts.append({"id": "n1", "kind": "news", "status": "ready", "media": ["a.png"], "caption": "x",
                  "created": "2026-11-20", "platforms": ["instagram", "facebook"]})
    br = hooks.make("breaking", ["X LEAVES FD"], "Big news.", post_id="b1") | {
        "status": "ready", "media": ["a.png"], "post_at": "2026-12-01T09:10:00+00:00"}
    posts.append(br)
    planner.plan(posts, now=datetime(2026, 12, 1, tzinfo=timezone.utc))
    assert br["plan"]["facebook"] == "2026-12-01T09:10:00+00:00"          # breaking keeps its moment
    n1 = next(p for p in posts if p["id"] == "n1")
    first_q = min(p["plan"]["instagram"] for p in posts if p.get("evergreen"))
    assert n1["plan"]["instagram"] < first_q                                # real news before questions
    days = sorted(p["plan"]["facebook"][:10] for p in posts if p.get("evergreen"))
    assert len(set(days)) == len(days)                                      # max one question a day


def test_engage_likes_first_comment_and_sends_only_approved(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_DRY_RUN", "0")
    for name in ("FILE", "SUGGESTED", "DECISIONS"):
        monkeypatch.setattr(engage, name, tmp_path / f"{name}.json")
    import lc.meta
    monkeypatch.setattr(lc.meta, "accounts", lambda: {"page_id": "PAGE", "page_token": "t", "ig_token": "t",
                                                      "ig_username": "sidewayswire"})
    calls = []

    def fake(method, path, token, **kw):
        calls.append((method, path, kw))
        if path == "FB1/comments" and method == "GET":
            return {"data": [
                {"id": "c1", "message": "Forrest seemed 100% about style and FD does not care", "from": {"id": "u1", "name": "Eric"}, "like_count": 115},
                {"id": "c2", "message": "👏", "from": {"id": "u2", "name": "Ann"}, "like_count": 0},
                {"id": "c3", "message": "our own", "from": {"id": "PAGE"}, "like_count": 0}]}
        if path == "IG1/comments":
            return {"data": [{"id": "i1", "text": "Who is the best? I say Deane", "username": "fan", "like_count": 3}]}
        return {"id": "new"}
    monkeypatch.setattr(engage, "_call", fake)
    folder = tmp_path / "queue"
    q.save({"id": "p1", "title": "SHOULD FORREST RETURN?", "status": "posted", "posted_at": "2026-12-02T08:00:00+00:00",
            "results": {"facebook": "FB1", "instagram": "IG1"}}, folder)
    now = datetime(2026, 12, 3, tzinfo=timezone.utc)
    rep = engage.run(now=now, folder=folder)
    assert rep["first"] == 1 and rep["liked"] == 2 and rep["new"] == 2 and rep["sent"] == 0
    assert ("POST", "c3/likes", {}) not in calls                         # never likes our own comment
    rep = engage.run(now=now, folder=folder)
    assert rep["first"] == 0 and rep["liked"] == 0 and rep["new"] == 0  # nothing twice
    # Mac drafts, Joshua approves one (edited) and skips the other
    engage.SUGGESTED.write_text(json.dumps({"facebook-c1": {"reply": "Valid point"}, "instagram-i1": {"reply": "Bold call"}}))
    engage.DECISIONS.write_text(json.dumps({"facebook-c1": {"status": "approved", "reply": "Valid point. Would a style series pay off though?"},
                                            "instagram-i1": {"status": "skipped"}}))
    rep = engage.run(now=now, folder=folder)
    assert rep["sent"] == 1
    assert ("POST", "c1/comments", {"message": "Valid point. Would a style series pay off though?"}) in calls
    assert not any(c[1] == "i1/replies" for c in calls)


def test_engage_does_nothing_in_test_phase(monkeypatch):
    monkeypatch.setenv("LC_DRY_RUN", "1")
    monkeypatch.setattr(engage, "_call", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no calls")))
    assert "off" in engage.run()


def test_stats_by_format():
    rows = {f"p{i}": {"format": "question", "facebook": {"reactions": 100, "comments": 40, "shares": 2}} for i in range(5)}
    rows |= {f"n{i}": {"format": "news", "instagram": {"likes": 50, "comments": 2, "shares": 1}} for i in range(5)}
    bf = stats.by_format(rows)
    assert bf["question"]["comments"] == 40 and bf["question"]["enough"]
    assert bf["question"]["engagement"] > bf["news"]["engagement"]
    assert stats.format_of({"hook": {"type": "debate"}}) == "debate"
    assert stats.format_of({"kind": "stream_clip"}) == "reel"
