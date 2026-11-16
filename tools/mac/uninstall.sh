#!/bin/bash
# Removes the Sideways Wire video helper from this Mac (yt-dlp and ffmpeg stay).
launchctl bootout "gui/$(id -u)/nl.sttpmedia.sidewayswire.video" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/nl.sttpmedia.sidewayswire.video.plist"
rm -rf "$HOME/Library/Application Support/SidewaysWire" "$HOME/Library/Caches/SidewaysWire"
echo "Verwijderd. De sleutel staat nog in de sleutelhanger; verwijderen met:"
echo "  security delete-generic-password -s sidewayswire-mac"
