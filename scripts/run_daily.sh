#!/usr/bin/env bash
# 자체 서버 cron 용 (GitHub Actions 를 쓰지 않을 때). .env 를 로드한 뒤 게시 감지 대기 루프로 오늘 브리핑을 생성한다.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi
exec python -m morning_brief run --production --scheduled --out "${MORNING_BRIEF_OUT:-site}"
