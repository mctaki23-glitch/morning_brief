"""핵심 파이프라인 테스트 (외부 네트워크/API 불필요, fixture 기반)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from morning_brief import chart, ingest
from morning_brief.config import Config
from morning_brief.pipeline import run
from morning_brief.stock_master import StockMaster
from morning_brief.summarize import summarize


@pytest.fixture()
def master() -> StockMaster:
    return StockMaster.load()


def test_stock_master_scan_no_short_alias_false_positive(master: StockMaster):
    # "필라델피아" 안의 "델"이 Dell 로 오탐되면 안 된다.
    hits = {e.ticker for e in master.scan("필라델피아 반도체지수는 강세였습니다.")}
    assert "DELL" not in hits


def test_stock_master_resolves_aliases(master: StockMaster):
    assert master.resolve("삼전").ticker == "005930"
    assert master.resolve("엔비디아").ticker == "NVDA"
    assert master.resolve("NVDA").ticker == "NVDA"


def test_rule_based_summary_extracts_stocks_and_reasons(master: StockMaster):
    text = ingest.load_fixture()
    cfg = Config()  # Claude 미설정 → 규칙 기반
    result = summarize(text, cfg, master)

    assert result.summarizer == "rule-based"
    assert result.overview  # 시황 요약 존재
    tickers = {s.ticker for s in result.stocks}
    assert {"NVDA", "AAPL", "TSLA", "MU"} <= tickers

    nvda = next(s for s in result.stocks if s.ticker == "NVDA")
    assert nvda.direction == "UP"
    assert "GPU" in nvda.reason_summary or "수주" in nvda.reason_summary

    aapl = next(s for s in result.stocks if s.ticker == "AAPL")
    assert aapl.direction == "DOWN"
    assert aapl.change_pct == pytest.approx(-1.3)


def test_indices_dedup(master: StockMaster):
    text = ingest.load_fixture()
    result = summarize(text, Config(), master)
    names = [i.name for i in result.indices]
    assert "SOX" not in names  # 필라델피아 반도체와 중복 제거
    assert "필라델피아 반도체" in names


def test_chart_svg_renders_and_scales():
    svg = chart.line_chart([10, 12, 11, 15, 14], ["D-4", "D-3", "D-2", "D-1", "D-0"], up=True)
    assert svg.startswith("<svg")
    assert "polyline" in svg
    assert "15.00" in svg and "10.00" in svg  # 최고/최저 라벨
    # 빈 입력도 안전하게 처리
    assert "차트 데이터 없음" in chart.line_chart([])


def test_end_to_end_generates_site(tmp_path: Path, master: StockMaster):
    cfg = Config.from_env(output_dir=str(tmp_path))
    index = run(cfg, date_str="2026-07-08", use_fixtures=True)

    assert index.exists()
    assert (tmp_path / "index.html").exists()  # 아카이브
    data = json.loads((tmp_path / "brief" / "2026-07-08" / "data.json").read_text(encoding="utf-8"))
    assert data["date"] == "2026-07-08"
    assert len(data["stocks"]) >= 5

    # 종목 상세 페이지가 종목 수만큼 생성됐는지
    stock_pages = list((tmp_path / "brief" / "2026-07-08" / "stock").glob("*.html"))
    assert len(stock_pages) == len(data["stocks"])

    # 시황 페이지에 핵심 요소 포함
    market_html = index.read_text(encoding="utf-8")
    assert "시황 요약" in market_html
    assert "오늘 언급된 종목" in market_html
