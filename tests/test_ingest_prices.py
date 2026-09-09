"""수집(공개 미리보기 파서) · 시세 어댑터 파서 · 캐시 폴백 · 아카이브 저장/복원 테스트 (네트워크 불필요)."""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from morning_brief import archive, ingest, prices
from morning_brief.config import Config
from morning_brief.models import Brief, PricePoint, PriceSeries, StockMention

PREVIEW_HTML = """
<html><body>
<div class="tgme_widget_message_wrap js-widget_message_wrap">
 <div class="tgme_widget_message text_not_supported_wrap js-widget_message" data-post="ehdwl/5011" data-view="x">
  <div class="tgme_widget_message_bubble">
   <div class="tgme_widget_message_text js-message_text" dir="auto">[서상영의 미국 증시 시황 ①] 9월 9일<br/>■ 시황 요약<br/>간밤 미국 증시는 <b>상승</b> 마감 <i class="emoji" style="x"><b>📈</b></i>했습니다.</div>
   <div class="tgme_widget_message_footer"><a class="tgme_widget_message_date" href="https://t.me/ehdwl/5011"><time datetime="2026-09-08T21:12:03+00:00" class="time">06:12</time></a></div>
  </div>
 </div>
</div>
<div class="tgme_widget_message_wrap js-widget_message_wrap">
 <div class="tgme_widget_message text_not_supported_wrap js-widget_message" data-post="ehdwl/5012">
  <div class="tgme_widget_message_bubble">
   <div class="tgme_widget_message_text js-message_text" dir="auto">[② 특징 종목] 엔비디아(NVDA)는 +5.2% 급등했습니다.</div>
   <div class="tgme_widget_message_footer"><a class="tgme_widget_message_date" href="https://t.me/ehdwl/5012"><time datetime="2026-09-08T21:15:40+00:00" class="time">06:15</time></a></div>
  </div>
 </div>
</div>
<div class="tgme_widget_message_wrap"><div class="tgme_widget_message js-widget_message" data-post="ehdwl/5013">
  <div class="tgme_widget_message_text js-message_text">어제 오후 코멘트</div>
  <time datetime="2026-09-08T05:00:00+00:00"></time></div></div>
<div class="tgme_widget_message_wrap"><div class="tgme_widget_message js-widget_message" data-post="ehdwl/5014">
  <div class="tgme_widget_message_text js-message_text">[장중 코멘트] 코스피 반도체 강세 지속.</div>
  <time datetime="2026-09-09T05:00:00+00:00"></time></div></div>
</body></html>
"""


def test_parse_preview_extracts_ids_times_and_text():
    msgs = ingest.parse_preview(PREVIEW_HTML)
    assert [m.id for m in msgs] == [5011, 5012, 5013, 5014]
    first = msgs[0]
    assert first.text.startswith("[서상영의 미국 증시 시황 ①] 9월 9일\n■ 시황 요약\n")
    assert "상승 마감" in first.text and "📈" in first.text  # 인라인 태그 안 텍스트 유지
    assert first.posted_at == datetime(2026, 9, 8, 21, 12, 3, tzinfo=ZoneInfo("UTC"))
    assert first.posted_at.astimezone(ZoneInfo("Asia/Seoul")).strftime("%H:%M") == "06:12"


def test_fetch_day_uses_preview_and_filters_window(monkeypatch):
    monkeypatch.setattr(ingest, "_http_get", lambda url: PREVIEW_HTML)
    cfg = Config(production=True)
    f = ingest.fetch_day(cfg, "2026-09-09")
    assert f.method == "preview" and f.ids == [5011, 5012, 5014]  # 5013 은 전날(KST 14:00) → 제외, 5014 는 당일 14:00 → 포함
    assert f.count == 3 and "엔비디아(NVDA)" in f.text and "장중 코멘트" in f.text
    assert f.posted_at_iso("Asia/Seoul") == "2026-09-09T06:12:03+09:00"


def test_fetch_day_production_never_falls_back_to_fixture(monkeypatch):
    def boom(url):
        raise urllib.error.URLError("blocked")
    monkeypatch.setattr(ingest, "_http_get", boom)
    prod = ingest.fetch_day(Config(production=True), "2026-09-09")
    assert not prod.ok and prod.method == "none" and prod.errors
    dev = ingest.fetch_day(Config(production=False), "2026-09-09")
    assert dev.ok and dev.method == "fixture"


def test_parse_naver_and_yahoo():
    naver = """[['날짜', '시가', '고가', '저가', '종가', '거래량', '외국인소진율'], 
["20260901", 79400, 79800, 78200, 79600, 17142847, 53.50], 
["20260902", 79600, 80100, 79000, 80000, 15000000, 53.55]]"""
    s = prices.parse_naver(naver, "005930", 45)
    assert s is not None and s.source == "naver" and s.currency == "KRW" and s.as_of == "2026-09-02"
    assert s.points[0].date == "2026-09-01" and s.points[-1].close == 80000

    yahoo = {"chart": {"result": [{"meta": {"currency": "USD", "exchangeTimezoneName": "America/New_York"},
                                   "timestamp": [1756731600, 1756818000],  # 2025-09-01/02 13:30 UTC (09:30 ET)
                                   "indicators": {"quote": [{"open": [170.0, 171.0], "high": [175.0, 179.9], "low": [169.0, 170.5],
                                                             "close": [171.5, 178.4], "volume": [2e8, 3e8]}]}}]}}
    y = prices.parse_yahoo(yahoo, "NVDA", 45, "USD")
    assert y is not None and y.source == "yahoo" and len(y.points) == 2 and y.points[-1].close == 178.4
    assert y.points[0].date == "2025-09-01"
    assert prices.parse_yahoo({"chart": {"result": []}}, "X", 45) is None


def test_get_prices_cache_fallback_and_production(tmp_path: Path, monkeypatch):
    def fail(*a, **k):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(prices, "_get", fail)
    archive_root = tmp_path / "archive"
    older = archive_root / "2026-09-08" / "prices"
    prices.save_cache(older, PriceSeries("NVDA", [PricePoint("2026-09-05", 1, 2, 0.5, 1.5, 10), PricePoint("2026-09-08", 1.5, 2, 1, 1.8, 20)],
                                          "USD", "stooq", "2026-09-08"))
    today_cache = archive_root / "2026-09-09" / "prices"
    s = prices.get_prices("NVDA", "US", days=45, allow_synthetic=False, cache_dir=today_cache)
    assert s is not None and s.source == "cache" and s.as_of == "2026-09-08"  # 전일 캐시 폴백
    assert prices.get_prices("AAPL", "US", days=45, allow_synthetic=False, cache_dir=today_cache) is None  # 운영: 합성 금지
    dev = prices.get_prices("AAPL", "US", days=45, allow_synthetic=True)
    assert dev is not None and dev.source == "synthetic" and len(dev.points) == 45


def test_kr_symbol_suffix_by_exchange():
    kospi = prices.adapters_for("005930", "KR", 45, "KOSPI")
    kosdaq = prices.adapters_for("247540", "KR", 45, "KOSDAQ")
    assert len(kospi) == 2 and len(kosdaq) == 2
    from morning_brief.stock_master import StockMaster
    m = StockMaster.load()
    assert m.resolve("에코프로").exchange == "KOSDAQ" and m.resolve("삼성전자").exchange == "KOSPI"


def test_archive_save_load_roundtrip(tmp_path: Path):
    series = PriceSeries("NVDA", [PricePoint("2026-09-05", 1, 2, 0.5, 1.5, 10), PricePoint("2026-09-08", 1.5, 2, 1, 1.8, 20)], "USD", "stooq", "2026-09-08")
    brief = Brief(date="2026-09-09", posted_at="2026-09-09T06:12:03+09:00", generated_at="2026-09-09T06:31:00+09:00",
                  market_overview="상승 마감.", kr_outlook="반도체 우호.", raw_text="원문 전체",
                  stocks=[StockMention(name="엔비디아", ticker="NVDA", direction="UP", change_pct=5.2, reason_summary="수주 기대",
                                       evidence="엔비디아는 +5.2% 급등", order=0, prices=series)],
                  message_count=3, message_ids=[5011, 5012, 5013], fetch_method="preview", summarizer="claude", model="claude-opus-5")
    d = archive.save(tmp_path / "archive", brief)
    assert (d / "raw.txt").read_text(encoding="utf-8") == "원문 전체"
    assert "raw_text" not in json.loads((d / "brief.json").read_text(encoding="utf-8"))
    index = json.loads((tmp_path / "archive" / "index.json").read_text(encoding="utf-8"))
    assert index[0]["date"] == "2026-09-09" and index[0]["names"] == ["엔비디아"]

    loaded = archive.load(tmp_path / "archive", "2026-09-09")
    assert loaded is not None and loaded.raw_text == "원문 전체" and loaded.message_ids == [5011, 5012, 5013]
    assert loaded.stocks[0].prices.points[-1].close == 1.8 and loaded.stocks[0].evidence == "엔비디아는 +5.2% 급등"
    assert archive.list_dates(tmp_path / "archive") == ["2026-09-09"]


def test_parse_naver_world_and_nasdaq():
    naver_world = """[{"localTradedAt":"2026-09-08","closePrice":"178.42","openPrice":"171.20","highPrice":"179.90","lowPrice":"170.80",
    "accumulatedTradingVolume":"51,000,000","fluctuationsRatio":"5.21"},
    {"localTradedAt":"2026-09-05","closePrice":"169.59","openPrice":"168.00","highPrice":"170.10","lowPrice":"166.90","accumulatedTradingVolume":"30,000,000"}]"""
    s = prices.parse_naver_world(naver_world, "NVDA", 45)
    assert s is not None and s.source == "naver" and s.currency == "USD"
    assert [p.date for p in s.points] == ["2026-09-05", "2026-09-08"] and s.points[-1].volume == 51_000_000
    assert prices.parse_naver_world('{"error":"x"}', "NVDA", 45) is None

    nasdaq = {"data": {"tradesTable": {"rows": [
        {"date": "09/08/2026", "close": "$178.42", "volume": "51,000,000", "open": "$171.20", "high": "$179.90", "low": "$170.80"},
        {"date": "09/05/2026", "close": "$169.59", "volume": "30,000,000", "open": "$168.00", "high": "$170.10", "low": "$166.90"}]}}}
    n = prices.parse_nasdaq(nasdaq, "NVDA", 45)
    assert n is not None and n.source == "nasdaq" and n.as_of == "2026-09-08" and n.points[0].close == 169.59
    assert prices.parse_nasdaq({"data": None}, "NVDA", 45) is None
    assert prices.naver_world_symbols("NVDA")[0] == "NVDA.O" and len(prices.naver_world_symbols("NVDA")) == 3
    assert prices.naver_world_symbols("JPM", "NYSE")[0] == "JPM.N"  # 거래소 힌트 우선, 나머지는 폴백



def test_parse_investing_and_pick_quote():
    search = {"quotes": [{"id": 999, "symbol": "NVDA", "exchange": "Frankfurt", "flag": "Germany"},
                         {"id": 6497, "symbol": "NVDA", "exchange": "NASDAQ", "flag": "USA"}]}
    assert prices.pick_investing_quote(search, "NVDA") == 6497
    assert prices.pick_investing_quote({"quotes": []}, "NVDA") is None
    hist = {"data": [{"rowDateTimestamp": "2026-09-08T00:00:00Z", "last_closeRaw": 178.42, "last_openRaw": 171.2, "last_maxRaw": 179.9,
                      "last_minRaw": 170.8, "volumeRaw": 51000000},
                     {"rowDateTimestamp": "2026-09-05T00:00:00Z", "last_close": "169.59", "last_open": "168.00", "last_max": "170.10",
                      "last_min": "166.90", "volume": "30.00M"}]}
    s = prices.parse_investing(hist, "NVDA", 45)
    assert s is not None and s.source == "investing" and s.as_of == "2026-09-08" and s.points[-1].close == 178.42
    assert s.points[0].close == 169.59


def test_naver_world_volume_key_detection():
    rows = '[{"localTradedAt":"2026-09-08","closePrice":"1","openPrice":"1","highPrice":"1","lowPrice":"1","accumulatedVolume":"1,234"}]'
    s = prices.parse_naver_world(rows, "X", 45)
    assert s is None  # 1개 봉 → None (2개 미만)
    rows2 = ('[{"localTradedAt":"2026-09-08","closePrice":"2","openPrice":"1","highPrice":"2","lowPrice":"1","tradeVolume":"1,234"},'
             '{"localTradedAt":"2026-09-05","closePrice":"1","openPrice":"1","highPrice":"1","lowPrice":"1","tradeVolume":"5"}]')
    s2 = prices.parse_naver_world(rows2, "X", 45)
    assert s2 is not None and s2.points[-1].volume == 1234.0
