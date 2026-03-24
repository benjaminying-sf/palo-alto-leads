#!/bin/bash
# ============================================================
# macOS Launch Agent setup for Palo Alto Lead System
# Runs main.py every Sunday at 6:00 PM automatically,
# even if the terminal is closed (unlike a cron job).
# ============================================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="$(which python3)"
PLIST_NAME="com.paloaltoleads.weekly"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

echo "=== Palo Alto Lead System — macOS Scheduler Setup ==="
echo ""
echo "Project directory : $PROJECT_DIR"
echo "Python binary     : $PYTHON_BIN"
echo "Launch Agent      : $PLIST_PATH"
echo ""

# ── Write the plist ────────────────────────────────────────────────────────────
cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>

    <!-- Run every Sunday at 18:00 (6:00 PM) -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>0</integer>   <!-- 0 = Sunday -->
        <key>Hour</key>
        <integer>18</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$PROJECT_DIR/main.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>

    <!-- Logs -->
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/data/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/data/launchd_error.log</string>

    <!-- Keep running -->
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
PLIST

# ── Load the Launch Agent ─────────────────────────────────────────────────────
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "✓ Launch Agent installed and loaded."
echo ""
echo "The script will now run automatically every Sunday at 6:00 PM."
echo "Your Mac must be awake at that time (or it will run on next wake)."
echo ""
echo "Useful commands:"
echo "  Check status : launchctl list | grep paloaltoleads"
echo "  Run manually : python3 $PROJECT_DIR/main.py"
echo "  Run test     : python3 $PROJECT_DIR/main.py --test"
echo "  Uninstall    : launchctl unload $PLIST_PATH && rm $PLIST_PATH"
echo ""
