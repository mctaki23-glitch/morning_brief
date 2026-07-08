#!/usr/bin/env bash
# 매일 실행용 스크립트 (로컬 cron / 서버 배포용).
# .env 가 있으면 로드한 뒤 오늘(KST) 브리핑 사이트를 생성한다.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

exec python -m morning_brief run --out "${MORNING_BRIEF_OUT:-site}"
