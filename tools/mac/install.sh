#!/bin/bash
# Installs the Sideways Wire video helper on this Mac. Run it again to update.
# What it does:
#   1. installs yt-dlp and ffmpeg with Homebrew (only if they are missing)
#   2. copies video_helper.py to ~/Library/Application Support/SidewaysWire/
#   3. adds a launchd job that runs the helper every 15 minutes, also after a restart
# Remove everything again with: bash uninstall.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Library/Application Support/SidewaysWire"
PLIST="$HOME/Library/LaunchAgents/nl.sttpmedia.sidewayswire.video.plist"
LOG="$HOME/Library/Logs/sidewayswire-video.log"

if ! command -v brew >/dev/null 2>&1; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
fi
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew ontbreekt. Installeer het eerst via https://brew.sh en start dit script opnieuw."; exit 1
fi
for p in yt-dlp ffmpeg python@3.12; do
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
cp "$HERE/video_helper.py" "$APP/video_helper.py"
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
launchctl bootout "gui/$(id -u)/nl.sttpmedia.sidewayswire.video" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Klaar. De helper draait nu elke 15 minuten. Log: $LOG"
