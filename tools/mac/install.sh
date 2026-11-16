#!/bin/bash
# Installs the Sideways Wire video helper on this Mac. Run it again to update.
# What it does:
#   1. installs yt-dlp and ffmpeg with Homebrew (only if they are missing)
#   2. copies video_helper.py to ~/Library/Application Support/SidewaysWire/
#   3. adds a launchd job that runs the helper every 15 minutes, also after a restart
# Remove everything again with: bash uninstall.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"
APP="$HOME/Library/Application Support/SidewaysWire"
PLIST="$HOME/Library/LaunchAgents/nl.sttpmedia.sidewayswire.video.plist"
LOG="$HOME/Library/Logs/sidewayswire-video.log"

if ! command -v brew >/dev/null 2>&1; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
fi
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew ontbreekt. Installeer het eerst via https://brew.sh en start dit script opnieuw."; exit 1
fi
for p in yt-dlp ffmpeg deno python@3.12; do
  brew list --formula "$p" >/dev/null 2>&1 || brew install -q "$p"
done
PY="$(brew --prefix)/bin/python3"
[ -x "$PY" ] || PY="$(brew --prefix python@3.12)/bin/python3.12"

if ! security find-generic-password -s sidewayswire-mac -w >/dev/null 2>&1; then
  echo "Nog geen GitHub-sleutel in de sleutelhanger. Zet hem erin met:"
  echo "  security add-generic-password -a sidewayswire -s sidewayswire-mac -U -w"
  echo "(hij vraagt dan om de sleutel; plakken en Enter). Start daarna dit script opnieuw."
  exit 1
fi

mkdir -p "$APP" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
# own little Python environment with numpy (for matching the sound), separate from the rest of the Mac
[ -x "$APP/venv/bin/python3" ] || "$PY" -m venv "$APP/venv"
"$APP/venv/bin/python3" -m pip install -q --disable-pip-version-check --upgrade numpy
PY="$APP/venv/bin/python3"
if [ -f "$HERE/video_helper.py" ]; then
  cp "$HERE/video_helper.py" "$APP/video_helper.py"
else   # started with curl | bash: fetch the newest helper from GitHub
  curl -fsSL -H "Accept: application/vnd.github.raw" \
    "https://api.github.com/repos/sttpjoshua/sidewayswire/contents/tools/mac/video_helper.py?ref=main" -o "$APP/video_helper.py"
fi
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>nl.sttpmedia.sidewayswire.video</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$APP/video_helper.py</string></array>
  <key>StartInterval</key><integer>900</integer>
  <key>RunAtLoad</key><true/>
  <key>LowPriorityIO</key><true/>
  <key>Nice</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
PL
rm -f "$APP/state.json"    # forget earlier failures, try everything again
launchctl bootout "gui/$(id -u)/nl.sttpmedia.sidewayswire.video" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 20
echo ""
echo "Klaar. De helper draait nu elke 15 minuten, ook na een herstart."
echo "Eerste run:"; tail -n 5 "$LOG" 2>/dev/null || true
echo "Log: $LOG"
