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
            elif f in THEIRS:
                _git("checkout", "--ours", f)
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
    for _ in range(5):
        if _git("pull", "--rebase", "-q").returncode != 0 and not _resolve():
            _git("rebase", "--abort")
            continue
        if _git("push", "-q").returncode == 0:
            return True
    print("push failed after 5 tries")
    return False


if __name__ == "__main__":
    sys.exit(0 if save(sys.argv[1], sys.argv[2:]) else 1)
