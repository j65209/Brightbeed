#!/bin/bash
# 맥미니에 USD 환율 자동 수집(평일 09:00) 설치 — 한 번만 실행.
#   bash ~/projects/Brightbeed/scripts/mac/install-fx-usd.sh
# 제거: launchctl bootout gui/$(id -u)/com.brightbeed.fx-usd && rm ~/Library/LaunchAgents/com.brightbeed.fx-usd.plist
set -euo pipefail
LABEL=com.brightbeed.fx-usd
SCRIPT="$(cd "$(dirname "$0")" && pwd)/fx-usd.sh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/brightbeed-fx-usd.log"
chmod +x "$SCRIPT"

export PATH="$HOME/.local/node/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
command -v node >/dev/null || { echo "node 가 없습니다 (brew install node)"; exit 1; }
NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]')
[ "$NODE_MAJOR" -ge 18 ] || { echo "node 18 이상 필요 (현재 $(node -v))"; exit 1; }

DAYS=""
for d in 1 2 3 4 5; do
  DAYS="$DAYS    <dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
"
done

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$SCRIPT</string></array>
  <key>StartCalendarInterval</key>
  <array>
$DAYS  </array>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "설치 완료: 평일 09:00 실행 ($PLIST)"
echo "지금 한 번 테스트: launchctl kickstart gui/$(id -u)/$LABEL && sleep 10 && tail -5 $LOG"
