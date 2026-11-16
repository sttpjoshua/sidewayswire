# Sideways Wire (@sidewayswire)

Automatisch drift-nieuwskanaal. Werkt zoals Bibleverse: cron-job.org start elke 15 minuten
GitHub Actions, een Claude-taak doet elk uur de redactie, jij checkt af en toe via Telegram.

## Wat er al staat

| Map / bestand | Wat het doet |
|---|---|
| `templates/` | Alle post-sjablonen in de Street-stijl (Jinja + HTML). `base.html` en `_parts.html` zijn de bouwstenen. |
| `lc/render.py` | Maakt van een sjabloon plus gegevens een PNG (1080x1350 of 1080x1920). Te lange tekst wordt verkleind; past het nog niet, dan `ok=False` en gaat de post naar Telegram ter controle. |
| `lc/video.py` | Battle-reel: run 1 boven, run 2 onder, automatisch gelijkgezet op de initiatie (via het geluid), overlay erover, H.264. |
| `lc/timezones.py` | Starttijden naar 12 steden, inclusief zomer- en wintertijd per datum. |
| `lc/collect.py` | De verzamelaar: leest bronnen, groepeert hetzelfde nieuws van verschillende bronnen tot een verhaal, schrijft `data/inbox.json`. |
| `lc/store.py` | Database (SQLite): items, verhalen, buzz-score, takedown-lijst. |
| `lc/feeds.py` | Websites (RSS) en YouTube-kanalen. |
| `lc/instagram.py` | Instagram lezen (Business Discovery) en posten (foto, carrousel, reel). |
| `lc/queue.py` | De wachtrij: elke post is een bestand in `queue/`, met vaste posttijden. |
| `lc/build.py` | Maakt van concepten afbeeldingen, plant ze in of stuurt ze naar Telegram ter controle. |
| `lc/publish.py` | Plaatst wat aan de beurt is. Staat standaard op proefdraaien (`LC_DRY_RUN=1`). |
| `lc/telegram.py` | Checks met knoppen: plaatsen, overslaan, bron niet meer delen. |
| `lc/status.py` + `docs/` | Dashboard, privacyverklaring en het TikTok-postscherm (GitHub Pages). |
| `lc/find_handles.py` | Haalt de socials van alle FD-coureurs op. |
| `EDITOR.md` | De instructie voor de Claude-taak die elk uur de redactie doet. |
| `lc/sources.py` | Leest de bronnenlijst (export van de Bronnen-sheet). |
| `data/archive/2026/` | Seizoen 2026: kalenders, winnaars en standen van FD en DM (D1GP nog onvolledig). |
| `.github/workflows/run.yml` | De hele ronde: verzamelen, bouwen, posten, dashboard. |

## Sjablonen

| Sjabloon | Gebruikt voor |
|---|---|
| `news.html` | Algemeen nieuws, jong talent, afscheid |
| `cover.html` | Gerucht (roze RUMOR), repost, carrousel-covers, throwback, countdown, build watch |
| `results.html` | Kwalificatie, podium, kampioen, livestream-schema, kalender, who to watch |
| `standings.html` | Kampioenschapsstand |
| `bracket_half.html` | Top 32 als boom, `mirror: true` voor de onderste helft |
| `zones.html` | Livestream "your time" |
| `quote.html` | Debat-post (agree or disagree) |
| `reel_split_overlay.html` | Overlay voor de battle-reel |

## Testen

```
pip install -r requirements.txt
python -m playwright install chromium
python -m tests.run_all
```

Uitkomst moet `ALL OK` zijn. De testbestanden komen in `out/`.

## Nog nodig van Joshua

Accounts (Instagram, Facebook, TikTok, YouTube), Meta-app, GitHub-repo, Telegram-bot,
cron-job.org en de platformkeuringen. Zie het plan-document.

## Geheimen in GitHub (Settings > Secrets and variables > Actions)

Secrets: `IG_USER_ID`, `IG_TOKEN`, `FB_PAGE_ID`, `FB_PAGE_TOKEN`, `TG_TOKEN`, `TG_CHAT`.
Variables: `PAGES_URL` (adres van GitHub Pages), `LC_DRY_RUN` (`1` = proefdraaien, `0` = echt posten).
