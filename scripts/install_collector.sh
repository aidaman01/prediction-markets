#!/bin/sh
# Install the order-book collector as a per-user launchd agent: starts at login, restarts if it dies.
# It runs under `caffeinate -s`, which keeps the Mac from sleeping while it is on AC power (on battery the Mac
# sleeps as usual and the collector pauses). The display may still turn off; closing the lid still sleeps.
# Uninstall: launchctl bootout gui/$(id -u)/com.prediction-markets.collector
#            rm ~/Library/LaunchAgents/com.prediction-markets.collector.plist
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
LABEL=com.prediction-markets.collector
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$ROOT/logs" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/caffeinate</string><string>-s</string><string>$ROOT/.venv/bin/python</string><string>-m</string><string>pm.collect</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$ROOT/logs/launchd.out</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/launchd.err</string>
</dict>
</plist>
PL
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
for i in 1 2 3 4 5 6 7 8 9 10; do                      # bootout finishes asynchronously
    launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || break
    sleep 1
done
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $PLIST"
