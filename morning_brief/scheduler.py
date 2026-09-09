"""06:30 정시성 확보 — 게시 감지 대기 루프 (PRD D2 확정: 조기 예약 + 대기 루프, 8.4).

GitHub Actions 예약 실행은 1.5~2시간 지연될 수 있으므로 05:00~08:30 KST 에 30분 간격으로 예약을 걸고,
각 잡은 이 루프를 실행한다.
  ① 오늘 아카이브(brief.json)가 이미 있으면 사이트만 재생성하고 즉시 종료 (idempotent)
  ② 게시 감지(5분 간격) → 분할 게시 완료 대기(마지막 메시지 후 5분) → 생성 · 아카이브 · 렌더
  ③ 목표 시각(06:30) 이후에도 미게시면 "대기 중" 페이지를 게시하고 종료 (다음 예약 잡이 이어서 감지)
  ④ 마감(09:00) 이후 미게시면 "브리핑 없음" 으로 종료
  ⑤ 목표 시각 전에 최대 대기 시간이 지나면 아카이브 기반 사이트만 재생성하고 종료
"""

from __future__ import annotations

import time as _time
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from . import archive, ingest, pipeline, render
from .config import Config
from .ingest import Fetched

SPLIT_SETTLE_SEC = 300  # 분할 게시 완료 대기


def _at(cfg: Config, date_str: str, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    day = datetime.strptime(date_str, "%Y-%m-%d").date()
    return datetime.combine(day, time(h, m), tzinfo=ZoneInfo(cfg.timezone))


def run_scheduled(
    cfg: Config,
    date_str: Optional[str] = None,
    *,
    target: str = "06:30",
    deadline: str = "09:00",
    poll_sec: int = 300,
    max_wait_sec: int = 2700,
    now_fn: Callable[[], datetime] = None,
    sleep_fn: Callable[[float], None] = _time.sleep,
) -> Path:
    now_fn = now_fn or (lambda: pipeline.now_kst(cfg))
    started = now_fn()
    date_str = date_str or started.strftime("%Y-%m-%d")
    target_at, deadline_at = _at(cfg, date_str, target), _at(cfg, date_str, deadline)

    # ① 이미 처리된 날짜 → 사이트 재생성만
    if archive.load(cfg.archive_dir, date_str) is not None:
        print(f"[scheduler] {date_str} 브리핑은 이미 아카이브에 있습니다 → 사이트 재생성 후 종료")
        n = pipeline.rebuild_site(cfg)
        render.write_shared_pages(Path(cfg.output_dir), logo_svg=cfg.logo_svg())
        pipeline.write_status(cfg, result="skipped", brief_date=date_str, rebuilt=n)
        return Path(cfg.output_dir) / "index.html"

    while True:
        fetched = ingest.fetch_day(cfg, date_str)
        now = now_fn()
        if fetched.ok:
            fetched = _settle(cfg, date_str, fetched, now_fn, sleep_fn)
            print(f"[scheduler] 게시 감지 ({fetched.count}건, {fetched.method}) → 생성")
            return pipeline.run_fetched(cfg, date_str, fetched)
        if now >= deadline_at:
            print("[scheduler] 마감 시각 경과, 브리핑 없음")
            return pipeline.publish_status(cfg, date_str, "no_briefing", fetched)
        if now >= target_at:
            print("[scheduler] 목표 시각 경과, 미게시 → 대기 중 페이지 게시 (다음 예약 잡이 계속 감지)")
            return pipeline.publish_status(cfg, date_str, "waiting", fetched)
        if (now - started).total_seconds() >= max_wait_sec:
            print("[scheduler] 최대 대기 시간 경과 (목표 시각 전) → 아카이브 기반 사이트만 재생성")
            pipeline.rebuild_site(cfg)
            render.write_shared_pages(Path(cfg.output_dir), logo_svg=cfg.logo_svg())
            pipeline.write_status(cfg, result="pending", brief_date=date_str, warnings=fetched.errors)
            return Path(cfg.output_dir) / "index.html"
        wait = min(poll_sec, max(1.0, (target_at - now).total_seconds()))
        print(f"[scheduler] 미게시 — {int(wait)}초 후 재확인 (현재 {now:%H:%M})")
        sleep_fn(wait)


def _settle(cfg: Config, date_str: str, fetched: Fetched, now_fn, sleep_fn, rounds: int = 2) -> Fetched:
    """마지막 메시지 직후라면 분할 게시가 이어질 수 있으므로 잠시 기다려 다시 수집한다."""
    for _ in range(rounds):
        last = max(m.posted_at for m in fetched.messages)
        age = max(0.0, (now_fn() - last).total_seconds())  # 시계 오차로 음수가 되어도 최대 5분만 기다린다
        if age >= SPLIT_SETTLE_SEC:
            return fetched
        sleep_fn(SPLIT_SETTLE_SEC - age)
        again = ingest.fetch_day(cfg, date_str)
        if again.ok and again.count >= fetched.count:
            fetched = again
    return fetched
