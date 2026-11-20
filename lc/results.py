"""Battle clips run on until the result (Joshua, 20 nov 2026).

The clips were cut on the commentary and stopped at the last sentence about the second run, so the run
did not quite finish and the judges' call ("slide him left for James, right for Matt Field... Matt Field
takes down James Deane") and the result on screen fell off. This step looks in the transcript after the
run for the call and lets the clip run on to just after it:

- single battle clips: "end" moves to the end of the call (+1.5 s); no call found: 6 s more.
- split battles: run 2's piece runs on to the call, and the reel ends with that part full screen
  under a tape "THE JUDGES' CALL" (lc/clips.make_split).

The changed times ask the Mac for new pieces; the clip is made again ("redo") and keeps its place in
the calendar. Runs before the clips are made:   python -m lc.results
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import queue as q

ROOT = Path(__file__).resolve().parent.parent
MOMENTS = ROOT / "data" / "podcasts" / "moments"
TRANSCRIPTS = ROOT / "data" / "podcasts" / "t"
KINDS = ("battle", "final", "omt")
WINDOW = 40.0          # the call comes within this many seconds after the run
MAX_EXTRA = 30.0
DEFAULT_EXTRA = 6.0
AFTER = 1.5            # a little air after the last word of the call
MAX_SINGLE = 90.0      # podclips refuses longer single clips

RESULT = re.compile(
    r"\b(takes? (him |her )?(down|the win|it|the battle)|gets? the (win|nod|battle)|gets? (one|two|three|all|both|the) votes?"
    r"|advanc\w*|moves? on|moving on|goes through|going through|through to the|winner|wins\b|win it"
    r"|one more time|\bomt\b|unanimous|judges? (say|have|give|go|went|are)|the nod|victory)", re.I)
SIGNAL = re.compile(r"\b(slide (him|her|them|it)|left for|right for|judges?)\b", re.I)
NEXT = re.compile(r"\b(here we go|next up|initiat\w*|lead run|chase run|three, two, one|3, 2, 1)\b", re.I)


def find_call(segments: list[dict], run_end: float) -> float:
    """The moment the judges' call is done, in stream seconds."""
    seen_signal, end = None, None
    for s in segments:
        st, en, text = float(s["start"]), float(s.get("end") or s["start"] + 2), s.get("text") or ""
        if st < run_end - 2:
            continue
        if st > run_end + WINDOW:
            break
        if end is not None:                    # the call goes on over several sentences
            if RESULT.search(text) and st <= end + 2:
                end = en
                continue
            break
        if RESULT.search(text):
            end = en
        elif SIGNAL.search(text):
            seen_signal = en
        elif seen_signal and NEXT.search(text):
            break                              # the next battle starts and nobody said who won
    if end is not None:
        out = end + AFTER
    elif seen_signal is not None:
        out = seen_signal + 4.0                # the result graphic shows while the call is made
    else:
        out = run_end + DEFAULT_EXTRA
    return round(min(max(out, run_end + 2.0), run_end + MAX_EXTRA), 1)


def apply(folder: Path = MOMENTS) -> dict:
    rep = {"single": 0, "split": 0}
    posted = {p["id"] for p in q.load("posted")}
    for mf in sorted(folder.glob("*.json")):
        try:
            moments = json.loads(mf.read_text())
        except Exception:
            continue
        if not isinstance(moments, list):
            continue
        tf = TRANSCRIPTS / f"{mf.stem}.json"
        segs = json.loads(tf.read_text()).get("segments", []) if tf.exists() else []
        changed = False
        for i, m in enumerate(moments):
            if m.get("kind") not in KINDS or m.get("result_done") or m.get("status") == "skipped":
                continue
            if f"pod-{mf.stem}-{i}" in posted or not segs:
                continue
            sp = m.get("split")
            if sp:
                r2 = sp["runs"][1]
                to = find_call(segs, float(r2["end"]))
                sp["result"] = {"from": float(r2["end"]), "to": to}
                m["end"] = max(float(m["end"]), to)
                rep["split"] += 1
            else:
                to = min(find_call(segs, float(m["end"])), float(m["start"]) + MAX_SINGLE)
                m["run_end"] = float(m["end"])
                m["end"] = max(float(m["end"]), to)
                rep["single"] += 1
            m.update(result_done=1, redo=m.get("status") not in (None, "new"))
            changed = True
        if changed:
            mf.write_text(json.dumps(moments, indent=1, ensure_ascii=False))
    return rep


if __name__ == "__main__":
    print(json.dumps(apply()))
