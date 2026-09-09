"""핵심 파이프라인 테스트 (외부 네트워크/API 불필요, fixture 기반)."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from morning_brief import chart, ingest, render
from morning_brief.config import Config
from morning_brief.models import PricePoint
from morning_brief.pipeline import run
from morning_brief.stock_master import StockMaster
from morning_brief.summarize import summarize, verify_evidence

FIXTURE_DATE = "2026-07-08"


@pytest.fixture()
def master() -> StockMaster:
    return StockMaster.load()


def _series(n: int = 45, seed: int = 7) -> list[PricePoint]:
    rng = random.Random(seed)
    price = 100.0
    pts = []
    for i in range(n):
        o = price
        c = price * (1 + rng.uniform(-0.02, 0.02))
        pts.append(PricePoint(f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", o, max(o, c) * 1.01, min(o, c) * 0.99, c, 1e6 * (1 + i % 5)))
        price = c
    return pts


def test_stock_master_scan_no_short_alias_false_positive(master: StockMaster):
    hits = {e.ticker for e in master.scan("필라델피아 반도체지수는 강세였습니다.")}
    assert "DELL" not in hits  # "델" 오탐 방지


def test_stock_master_resolves_aliases(master: StockMaster):
    assert master.resolve("삼전").ticker == "005930"
    assert master.resolve("엔비디아").ticker == "NVDA"
    assert master.resolve("NVDA").ticker == "NVDA"


def test_rule_based_summary_extracts_stocks_reasons_and_outlook(master: StockMaster):
    text = ingest.load_fixture()
    result = summarize(text, Config(), master)  # Claude 미설정 → 규칙 기반

    assert result.summarizer == "rule-based"
    assert result.overview
    assert "반도체" in result.kr_outlook  # 한국 증시 관전 포인트 섹션 추출
    tickers = [s.ticker for s in result.stocks]
    assert {"NVDA", "AAPL", "TSLA", "MU"} <= set(tickers)
    # 언급순 정렬: 엔비디아가 애플·테슬라보다 먼저
    assert tickers.index("NVDA") < tickers.index("AAPL") < tickers.index("TSLA")

    nvda = next(s for s in result.stocks if s.ticker == "NVDA")
    assert nvda.direction == "UP"
    assert "GPU" in nvda.reason_summary or "수주" in nvda.reason_summary
    assert nvda.evidence and nvda.evidence_verified
    assert verify_evidence(nvda.evidence, text)

    aapl = next(s for s in result.stocks if s.ticker == "AAPL")
    assert aapl.direction == "DOWN"
    assert aapl.change_pct == pytest.approx(-1.3)


def test_indices_dedup(master: StockMaster):
    result = summarize(ingest.load_fixture(), Config(), master)
    names = [i.name for i in result.indices]
    assert "SOX" not in names
    assert "필라델피아 반도체" in names


def test_verify_evidence_tolerates_formatting_but_rejects_fabrication():
    raw = "엔비디아(NVDA)는 차세대 GPU에 대한 대형 클라우드 업체들의 신규 수주 기대가 부각되며\n  +5.2% 급등했습니다."
    assert verify_evidence("엔비디아(NVDA)는 차세대 GPU에 대한 대형 클라우드 업체들의 신규 수주 기대가 부각되며 +5.2% 급등했습니다.", raw)
    assert verify_evidence("차세대 GPU에 대한 대형 클라우드 업체들의 신규 수주 기대", raw)  # 부분 인용
    assert not verify_evidence("엔비디아는 배당 확대 발표로 급등했습니다.", raw)  # 원문에 없는 내용
    assert not verify_evidence("", raw)


def test_candlestick_renders_volume_ma_and_tooltips():
    pts = _series(45)
    svg = chart.candlestick(pts, currency="USD", change_pct=1.2)
    assert svg.startswith("<svg")
    assert svg.count("<title>") == 20  # 표시 창 20봉, 봉별 툴팁
    assert svg.count("<polyline") == 2  # MA5 + MA20 (전체 45개로 계산)
    assert "#F58220" in svg and "#0086B8" in svg  # 차트 페어: 오렌지 → 블루
    assert "stroke-dasharray" in svg  # 점선 그리드
    assert "MA20" in svg and "거래량" in svg
    assert 'role="img"' in svg and "aria-label" in svg

    mini = chart.candlestick(pts, compact=True, width=120, height=36)
    assert "<rect" in mini and "<text" not in mini
    assert "차트 데이터 없음" in chart.candlestick([])
    assert "시세 준비 중" in chart.empty(message="시세 준비 중")


def test_candlestick_price_formats():
    assert chart.fmt_price(82300, "KRW") == "82,300"
    assert chart.fmt_price(178.4249, "USD") == "178.42"
    assert chart.fmt_volume(5.1e8) == "5.1억"


def test_message_aggregation():
    text, count = ingest.fetch_briefing(Config(), FIXTURE_DATE, use_fixtures=True)
    assert count >= 3
    assert "엔비디아" in text and "삼성전자" in text and "S&P500" in text


def test_status_page_waiting():
    html = render.render_status("2026-09-09", "waiting", latest="2026-09-08", checked_at="2026-09-09T06:31:00+09:00")
    assert "대기 중" in html and 'http-equiv="refresh"' in html and "2026-09-08" in html
    html2 = render.render_status("2026-09-09", "no_briefing")
    assert "브리핑이 없습니다" in html2 and 'http-equiv="refresh"' not in html2


def test_end_to_end_generates_site(tmp_path: Path):
    cfg = Config.from_env(output_dir=str(tmp_path), base_url="https://example.test/mb")
    index = run(cfg, date_str=FIXTURE_DATE, use_fixtures=True)

    assert index == tmp_path / "brief" / FIXTURE_DATE / "index.html"
    assert index.exists()
    assert (tmp_path / "archive" / "index.html").exists()
    assert (tmp_path / "robots.txt").read_text() .startswith("User-agent: *\nDisallow: /")
    assert (tmp_path / "brief" / FIXTURE_DATE / "og.png").stat().st_size > 1024  # Chrome 캡처 또는 기본 카드

    data = json.loads((tmp_path / "brief" / FIXTURE_DATE / "data.json").read_text(encoding="utf-8"))
    assert data["date"] == FIXTURE_DATE
    assert len(data["stocks"]) >= 5
    assert data["message_count"] >= 3
    assert "raw_text" not in data  # 원문 전문은 공개 데이터에서 제외
    assert data["stocks"][0]["evidence"]

    stock_pages = list((tmp_path / "brief" / FIXTURE_DATE / "stock").glob("*.html"))
    assert len(stock_pages) == len(data["stocks"])

    html = index.read_text(encoding="utf-8")
    for needle in ("시황 요약", "주요 지수", "오늘의 종목", "한국 증시 관전 포인트", 'id="s-nvda"', "MA20", "등락순", 'class="chart-sm"',
                   '<meta name="robots" content="noindex, nofollow">',
                   f'<meta property="og:image" content="https://example.test/mb/brief/{FIXTURE_DATE}/og.png">'):
        assert needle in html, needle
    assert "onepage" not in html  # 단일 페이지로 통합

    root = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "http-equiv" in root and f"brief/{FIXTURE_DATE}/" in root

    archive = (tmp_path / "archive" / "index.html").read_text(encoding="utf-8")
    assert FIXTURE_DATE in archive and "2026년 7월" in archive and "엔비디아" in archive


def test_og_card_default_and_chrome(tmp_path: Path, monkeypatch):
    from morning_brief import og

    out = tmp_path / "og.png"
    assert og.write_og_card(out, date_label="2026-09-09", headline="시황 요약") == "default"  # conftest: MORNING_BRIEF_OG=off
    assert out.stat().st_size > 1024
    if og.find_chrome() is None:
        pytest.skip("Chrome/Chromium 없음")
    monkeypatch.setenv("MORNING_BRIEF_OG", "on")
    out2 = tmp_path / "og2.png"
    assert og.write_og_card(out2, date_label="2026-09-09", weekday="수", headline="금리 인하 기대로 3대 지수 상승 마감",
                            foot_left="텔레그램 사제콩이_서상영 · 종목 12개") == "chrome"
    import struct
    w, h = struct.unpack(">II", out2.read_bytes()[16:24])
    assert (w, h) == (1200, 630)
