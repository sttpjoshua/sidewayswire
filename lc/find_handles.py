"""Fills data/sources.csv with the socials of every Formula DRIFT driver.

formulad.com lists each driver's Instagram and YouTube on the profile page.
Run on GitHub Actions (workflow 'handles'), not locally: python -m lc.find_handles
Drift Masters does not list socials; those handles are checked through the
Instagram API (Instagram.check_username) once the Meta app exists.
"""
from __future__ import annotations

import csv
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "sources.csv"
BASE = "https://www.formulad.com"
UA = {"User-Agent": "Mozilla/5.0 (sidewayswire source list)"}
SKIP = {"formulad", "formuladrift", "p", "reel", "explore"}


def socials(html: str) -> dict:
    ig = [h for h in re.findall(r"instagram\.com/([A-Za-z0-9_.]+)", html) if h.lower() not in SKIP]
    yt = [u for u in re.findall(r"(?:m\.|www\.)?(youtube\.com/[^\s\"'<>?]+)", html) if "formuladrift" not in u.lower()]
    return {"instagram": "@" + ig[0].rstrip(".") if ig else "", "youtube": yt[0] if yt else ""}


def run() -> dict:
    rows = list(csv.DictReader(CSV.open(encoding="utf-8")))
    fields = list(rows[0].keys())
    by_name = {r["Naam"].lower(): r for r in rows}
    index = requests.get(f"{BASE}/drivers", headers=UA, timeout=30).text
    slugs = sorted(set(re.findall(r'/drivers/([a-z0-9-]+)', index)))
    report = {"profiles": len(slugs), "updated": 0, "added": 0, "failed": []}
    for slug in slugs:
        try:
            html = requests.get(f"{BASE}/drivers/{slug}", headers=UA, timeout=30).text
            s = socials(html)
            m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
            name = re.sub(r"<[^>]+>|\s+", " ", m.group(1)).strip() if m else slug.replace("-", " ").title()
            row = by_name.get(name.lower())
            if row is None:
                row = {f: "" for f in fields} | {"Naam": name, "Type": "Coureur", "Serie": "FD",
                                                 "Prioriteit": "2", "Status": "Te controleren"}
                rows.append(row); by_name[name.lower()] = row; report["added"] += 1
            if s["instagram"] and row["Instagram"] != s["instagram"]:
                row["Instagram"], row["Status"] = s["instagram"], "Gecontroleerd"
                report["updated"] += 1
            if s["youtube"] and not row["YouTube / website"]:
                row["YouTube / website"] = s["youtube"]
            time.sleep(0.5)
        except Exception as e:
            report["failed"].append(f"{slug}: {str(e)[:80]}")
    with CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    return report


if __name__ == "__main__":
    print(run())
