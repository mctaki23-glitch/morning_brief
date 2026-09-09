"""게시 감지 대기 루프(scheduler) 테스트 — 시계·수집·시세를 주입해 네트워크 없이 검증."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from morning_brief import archive, ingest, pipeline, prices, scheduler
from morning_brief.config import Config
from morning_brief.ingest import Fetched, Message
from morning_brief.models import Brief

KST = ZoneInfo("Asia/Seoul")
DAY = "2026-09-09"


def _cfg(tmp_path: Path) -> Config:
    return Config(output_dir=str(tmp_path / "site"), archive_dir=str(tmp_path / "archive"), production=True)


def _clock(*stamps: str):
    """'06:10', '06:15', ... 순서로 시각을 돌려주는 now_fn (마지막 값 반복)."""
    times = [datetime.combine(datetime.strptime(DAY, "%Y-%m-%d").date(), datetime.strptime(s, "%H:%M").time(), tzinfo=KST) for s in stamps]
    state = {"i": 0}

    def now():
        t = times[min(state["i"], len(times) - 1)]
        state["i"] += 1
        return t
    return now


def _messages(posted: str) -> Fetched:
    base = datetime.combine(datetime.strptime(DAY, "%Y-%m-%d").date(), datetime.strptime(posted, "%H:%M").time(), tzinfo=KST)
    parts = ingest.load_fixture().split("\n\n")
    return Fetched(messages=[Message(id=7000 + i, posted_at=base + timedelta(minutes=i), text=t) for i, t in enumerate(parts)], method="preview")


@pytest.fixture(autouse=True)
def _fast_prices(monkeypatch):
    monkeypatch.setattr(prices, "get_prices", lambda ticker, market="US", days=45, **kw: prices.synthetic(ticker, market, days))


def _status(cfg: Config) -> dict:
    return json.loads((Path(cfg.output_dir) / "status.json").read_text(encoding="utf-8"))


def test_waiting_page_after_target_when_not_posted(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(ingest, "fetch_day", lambda c, d, use_fixtures=False: Fetched(method="none", errors=["preview: 없음"]))
    out = scheduler.run_scheduled(cfg, DAY, now_fn=_clock("06:35"), sleep_fn=lambda s: None)
    assert out == Path(cfg.output_dir) / "index.html"
    assert "대기 중" in out.read_text(encoding="utf-8")
    assert _status(cfg)["result"] == "waiting"
    assert (Path(cfg.output_dir) / "robots.txt").exists()


def test_past_date_without_briefing_keeps_root_on_latest(tmp_path):
    """과거 일자 재생성에서 브리핑을 못 찾아도 루트는 최신 브리핑 리다이렉트를 유지한다(대기 페이지로 덮지 않음)."""
    cfg = _cfg(tmp_path)
    latest = Brief(date="2026-09-10", market_overview="시황.", generated_at="2026-09-10T08:03:02+09:00", status="published")
    archive.save(cfg.archive_dir, latest)
    out = pipeline.publish_status(cfg, "2026-09-09", "waiting", Fetched(method="none"), today="2026-09-10")
    html = out.read_text(encoding="utf-8")
    assert "brief/2026-09-10/" in html and "대기 중" not in html
    assert _status(cfg)["result"] == "waiting" and _status(cfg)["latest"] == "2026-09-10"
    # 오늘 일자면 그대로 대기 페이지
    out2 = pipeline.publish_status(cfg, "2026-09-10", "waiting", Fetched(method="none"), today="2026-09-10")
    assert "대기 중" in out2.read_text(encoding="utf-8")


def test_no_briefing_after_deadline(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(ingest, "fetch_day", lambda c, d, use_fixtures=False: Fetched(method="none"))
    out = scheduler.run_scheduled(cfg, DAY, now_fn=_clock("09:05"), sleep_fn=lambda s: None)
    assert "브리핑이 없습니다" in out.read_text(encoding="utf-8")
    assert _status(cfg)["result"] == "no_briefing"


def test_polls_then_builds_when_posted(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    calls = {"n": 0}
    slept: list[float] = []

    def fetch(c, d, use_fixtures=False):
        calls["n"] += 1
        return Fetched(method="none") if calls["n"] == 1 else _messages("06:05")

    monkeypatch.setattr(ingest, "fetch_day", fetch)
    out = scheduler.run_scheduled(cfg, DAY, now_fn=_clock("06:10", "06:10", "06:15", "06:15", "06:16"), sleep_fn=slept.append)
    assert out == Path(cfg.output_dir) / "brief" / DAY / "index.html"
    assert slept and slept[0] <= 300  # 첫 미게시 → 폴링 대기
    st = _status(cfg)
    assert st["result"] == "published" and st["fetch_method"] == "preview" and st["message_count"] >= 3
    # 실데이터는 아카이브(소스 오브 트루스)에 저장된다
    assert (Path(cfg.archive_dir) / DAY / "brief.json").exists() and (Path(cfg.archive_dir) / DAY / "raw.txt").exists()
    assert archive.list_dates(cfg.archive_dir) == [DAY]


def test_settle_waits_for_split_messages(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    slept: list[float] = []
    seq = iter([_messages("06:10"), _messages("06:10")])  # 7개 메시지: 06:10 ~ 06:16
    monkeypatch.setattr(ingest, "fetch_day", lambda c, d, use_fixtures=False: next(seq))
    # 감지 시각 06:17 → 마지막 메시지(06:16) 1분 뒤이므로 남은 4분을 기다린 뒤 재수집
    scheduler.run_scheduled(cfg, DAY, now_fn=_clock("06:15", "06:15", "06:17", "06:25"), sleep_fn=slept.append)
    assert slept == [240.0]


def test_skips_when_already_archived(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    archive.save(cfg.archive_dir, Brief(date=DAY, market_overview="상승 마감.", generated_at="2026-09-09T06:31:00+09:00"))
    monkeypatch.setattr(ingest, "fetch_day", lambda *a, **k: pytest.fail("이미 아카이브된 날짜는 수집하지 않아야 함"))
    out = scheduler.run_scheduled(cfg, DAY, now_fn=_clock("07:00"), sleep_fn=lambda s: None)
    assert _status(cfg)["result"] == "skipped"
    assert (Path(cfg.output_dir) / "brief" / DAY / "index.html").exists()  # 아카이브에서 재생성
    assert "http-equiv" in out.read_text(encoding="utf-8")  # 루트 → 최신 브리핑


def test_pending_before_target_when_max_wait_exceeded(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(ingest, "fetch_day", lambda c, d, use_fixtures=False: Fetched(method="none"))
    scheduler.run_scheduled(cfg, DAY, now_fn=_clock("05:00", "05:50"), max_wait_sec=2700, sleep_fn=lambda s: None)
    assert _status(cfg)["result"] == "pending"


def test_rebuild_site_from_archive(tmp_path):
    cfg = _cfg(tmp_path)
    for d in ("2026-09-08", "2026-09-09"):
        archive.save(cfg.archive_dir, Brief(date=d, market_overview=f"{d} 시황.", generated_at=f"{d}T06:31:00+09:00"))
    assert pipeline.rebuild_site(cfg) == 2
    assert (Path(cfg.output_dir) / "brief" / "2026-09-08" / "index.html").exists()
    arc = (Path(cfg.output_dir) / "archive" / "index.html").read_text(encoding="utf-8")
    assert "2026-09-08" in arc and "2026-09-09" in arc
