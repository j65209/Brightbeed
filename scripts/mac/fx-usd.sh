#!/bin/bash
# 맥미니 launchd(com.brightbeed.fx-usd)가 평일 09:00 실행 — 오늘 USD 환율 기록 후 push.
# GitHub Actions(fx-usd.yml)는 10:30 백업: 이 스크립트가 못 돌았을 때만 채운다.
set -euo pipefail
export PATH="$HOME/.local/node/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"
echo "[$(date '+%F %T')] fx-usd 시작"

# 맥에서 다른 스크립트(meta-ads 등)가 만든 미커밋 변경은 건드리지 않도록 autostash
git pull --rebase --autostash -q origin main
FX_FORCE_TODAY=1 node scripts/fx-usd.mjs

git add data/fx-usd.json
if git diff --cached --quiet; then echo "변경 없음"; exit 0; fi
git commit -q -m "chore: USD 환율 갱신 $(date +%F) (mac)" -- data/fx-usd.json
for i in 1 2 3; do
  if git push -q origin main; then echo "push 완료"; exit 0; fi
  sleep 3
  git pull --rebase --autostash -q origin main
done
echo "push 실패"; exit 1
