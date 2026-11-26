"""Commit and push from a workflow, even when other runs pushed in the meantime.

Several workflows (collect, podcasts, clips) push to main. Generated files that every run
writes (docs/status.json, progress files) would make a normal `git pull --rebase` stop with a
conflict. Here such a conflict is solved by rebuilding the file (status) or taking the newest
version (progress). A conflict in any other file stops the rebase and leaves it for the next run.

    python -m lc.gitsave "message" path [path ...]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
G = ["git", "-c", "user.name=sidewayswire-bot", "-c", "user.email=bot@users.noreply.github.com"]
REBUILD = {"docs/status.json"}
THEIRS = {"docs/podcasts-now.json", "docs/clips-now.json"}
# 26 nov: the clips runs of that day lost an hour of work each because docs/agents/qc.json and queue files
# conflicted with the dashboard and the 15-minute run. Status files of agents: newest remote wins (the next
# run writes them again). Other JSON (posts, moments, settings): a three-way merge where both sides keep their
# own changes and, where both changed the same field, the remote side (Joshua on the dashboard) wins.
REMOTE_WINS_PREFIX = ("docs/agents/", "docs/stats.json", "docs/editor.json")
BINARY_REMOTE = {"data/lc.db"}


def _show(stage: int, f: str):
    import json
    r = _git("show", f":{stage}:{f}")
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def _merge(base, remote, local):
    """remote = what is on GitHub now, local = what this run made. Keys only one side changed are kept;
    when both changed a key, the remote value wins."""
    if isinstance(remote, dict) and isinstance(local, dict):
        base = base if isinstance(base, dict) else {}
        out = dict(local)
        for k in set(remote) | set(local) | set(base):
            if k in remote and remote.get(k) != base.get(k):
                out[k] = _merge(base.get(k), remote[k], local.get(k)) if k in local else remote[k]
            elif k not in remote and k in base and local.get(k) == base.get(k):
                out.pop(k, None)              # removed on GitHub, untouched here
        return out
    if isinstance(remote, list) and isinstance(local, list) and len(remote) == len(local):
        base = base if isinstance(base, list) and len(base) == len(local) else [None] * len(local)
        return [_merge(b, r, l) for b, r, l in zip(base, remote, local)]
    return remote if remote != base else local


def _json_merge(f: str) -> bool:
    import json
    base, remote, local = _show(1, f), _show(2, f), _show(3, f)
    if remote is None or local is None:
        return False
    merged = _merge(base, remote, local)
    (ROOT / f).write_text(json.dumps(merged, indent=1, ensure_ascii=False) + "\n")
    return True


def _git(*a, check=False) -> subprocess.CompletedProcess:
    return subprocess.run([*G, *a], cwd=ROOT, capture_output=True, text=True, check=check)


def _resolve() -> bool:
    """Solve the conflicts we know how to solve; True when the rebase could continue."""
    for _ in range(20):
        files = _git("diff", "--name-only", "--diff-filter=U").stdout.split()
        if not files:
            return True
        for f in files:
            if f in REBUILD:
                try:
                    from . import status
                    status.run()
                except Exception as e:
                    print("status rebuild:", e)
                    _git("checkout", "--ours", f)        # during a rebase 'ours' is the remote side
            elif f in THEIRS or f in BINARY_REMOTE or f.startswith(REMOTE_WINS_PREFIX):
                _git("checkout", "--ours", f)
            elif f.endswith(".json") and _json_merge(f):
                print("merged", f)
            else:
                print("conflict in", f, "- leaving it for the next run")
                return False
            _git("add", f)
        r = subprocess.run([*G, "-c", "core.editor=true", "rebase", "--continue"], cwd=ROOT, capture_output=True, text=True)
        if r.returncode == 0 and "rebase" not in _git("status").stdout.lower().split("\n")[0]:
            return True
    return False


def save(message: str, paths: list[str]) -> bool:
    _git("add", *paths)
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return True
    _git("commit", "-qm", message)
    import random
    import time
    for attempt in range(15):          # busy evenings: dashboard clicks, the Mac and runs all push
        if _git("pull", "--rebase", "-q").returncode != 0 and not _resolve():
            _git("rebase", "--abort")
            time.sleep(3 + random.random() * 5)
            continue
        if _git("push", "-q").returncode == 0:
            return True
        time.sleep(2 + attempt + random.random() * 4)
    print("push failed after 15 tries")
    return False


if __name__ == "__main__":
    sys.exit(0 if save(sys.argv[1], sys.argv[2:]) else 1)
