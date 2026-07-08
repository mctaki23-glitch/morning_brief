#!/usr/bin/env bash
# 로컬/서버에 매일 아침 06:30 실행 cron 을 설치한다.
# (GitHub Actions 를 쓰지 않고 자체 호스팅할 때 사용)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CRON_LINE="30 6 * * * cd $REPO_DIR && ./scripts/run_daily.sh >> $REPO_DIR/morning_brief.log 2>&1"

# 기존 동일 항목 제거 후 추가 (중복 방지)
( crontab -l 2>/dev/null | grep -v "scripts/run_daily.sh" ; echo "$CRON_LINE" ) | crontab -

echo "설치 완료. 매일 06:30 에 실행됩니다:"
echo "  $CRON_LINE"
echo "확인: crontab -l"
