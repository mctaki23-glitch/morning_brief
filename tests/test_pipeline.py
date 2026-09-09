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
    assert "브리핑 전문" not in html  # 원문 전문 섹션은 페이지에 넣지 않는다(2026-09-09 사용자 지시). 데이터에는 보존
    assert data["messages"] and data["messages"][0]["text"].startswith("[서상영의 미국 증시 시황 ①]")
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



REAL_EXCERPT = """09/08 미 증시, AI, 반도체 강세에도 제약주 부진과 국제유가 상승 여파로 부진

미 증시는 중동 불안 속 국제유가 상승에 하락 출발. 다우지수가 1% 넘게 하락. 이후 지수에 더욱 부담(다우 -1.18%, 나스닥 -0.32%, S&P500 -0.58%, 러셀2000 -0.52%, 필라델피아 반도체 지수 +1.30%)

*변화요인: 상품가격 변화와 증시

이런 가운데 AI 및 반도체 업종의 강세가 뚜렷. 씨티의 TMT 컨퍼런스, 골드만 삭스의 컨퍼런스 등을 통해 AI 관련 종목군의 강세가 진행. 그 외에도 디지털오션은 AI 매출의 85%가 추론 부문에서 발생한다고 설명.

*특징 종목: 테슬라, AMD, 인텔 강세 Vs. 엔비디아, 암젠, 세일즈포스 부진

메모리, 스토리지 반도체: 시게이트 큰 폭 상승 Vs. 마이크론 보합권 등락
시게이트(+6.49%)는 AI 스토리지 수요 증가에 상승. SK하이닉스 ADR(+4.83%)도 강세. 반면, 샌디스크(-0.12%)는 차익 실현 매물로 하락 전환. 마이크론(-1.61%)은 상승 출발했지만 차익 실현 매물 출회되며 하락 전환. 아시아 시장에서 삼성전자와 SK하이닉스의 메모리 재고가 급감하고 있다는 소식에 상승 출발했지만 개별 기업들 중심으로 매물 소화한 점이 특징.

광통신: 코닝의 계약 소식에 대부분 크게 상승
코닝(+7.56%)은 버라이존과 2032년까지 광섬유를 공급하는 계약을 발표하자 큰 폭 상승. 인텔(+9.05%)은 10월 PC CPU 가격을 약 10% 추가 인상할 수 있다는 소식에 상승.

제약: 임상 실패 등에 부진
노바티스(-13.93%)는 2개의 임상 실패 소식에 크게 하락.

*한국 증시 관련 수치: 견조한 AI 산업과 컨퍼런스 효과

MSCI 한국 증시 ETF는 0.55% 상승, MSCI 신흥지수 ETF도 0.19% 상승. KOSPI 야간 선물은 0.8% 상승.

*FICC: 유럽 천연가스 상승

국제유가는 상승."""


def test_rule_based_on_real_briefing_format(master: StockMaster):
    from morning_brief.summarize import summarize_rule_based

    r = summarize_rule_based(REAL_EXCERPT, master)
    assert r.overview.startswith("09/08 미 증시") and "*변화요인" not in r.overview
    assert {(i.name, i.change_pct) for i in r.indices} == {("다우", -1.18), ("나스닥", -0.32), ("S&P500", -0.58), ("러셀2000", -0.52), ("필라델피아 반도체", 1.3)}
    assert r.kr_outlook.startswith("견조한 AI 산업") and "MSCI 한국 증시 ETF" in r.kr_outlook

    by = {m.ticker or m.name: m for m in r.stocks}
    assert by["INTC"].change_pct == 9.05 and by["INTC"].direction == "UP" and "PC CPU 가격" in by["INTC"].reason_summary
    assert by["MU"].change_pct == -1.61 and by["MU"].reason_summary.startswith("마이크론(-1.61%)은")  # 앞 문장에 붙지 않음
    assert by["000660"].change_pct == 4.83 and by["000660"].market == "KR"  # SK하이닉스 ADR → 000660
    assert by["NVS"].change_pct == -13.93 and by["GLW"].change_pct == 7.56
    assert "005930" in by and by["005930"].change_pct is None  # 삼성전자: 등락률 표기 없는 언급
    for noise in ("GS", "C", "DOCN", "VZ"):  # 문맥 언급(씨티·골드만삭스·디지털오션·버라이존)은 제외
        assert noise not in by, noise
    tickers = [m.ticker for m in r.stocks]
    assert tickers.index("STX") < tickers.index("MU") < tickers.index("INTC") < tickers.index("NVS")  # 언급순


FICC_EXCERPT = REAL_EXCERPT.split("*FICC")[0] + """*FICC: 유럽 천연가스 상승, 브라질 헤알 강세 Vs. 제한적인 국제유가와 금리

국제유가는 지난 주말부터 이어진 미국과 이란의 군사적 충돌 등에 상승. 장 마감 앞두고는 재차 상승을 확대하며 1%대 상승. 미국 천연가스는 기온 안정에 따른 냉방 수요 감소 기대와 공급 증가 소식에 2% 하락. 반면, 유럽 천연가스는 호르무즈 해협 불안에 4%대 상승

달러화는 소비자 기대 조사 결과 기대 물가가 안정을 보이자 여타 환율에 대해 약세.

국채 금리는 높은 국제유가, 전일 유럽 국채 금리 상승 등을 반영하며 한 때 10년물 국채 금리가 4.8%를 기록하기도 했음.

금은 달러 약세 불구 높은 국제유가 등에 따른 물가 불안에 0.8% 하락. 은은 제한적인 상승. 구리 및 비철금속은 주석을 제외하고 대부분 상승.

농작물은 밀이 흑해 지역 선박 공격이 지속되자 상승. 대두는 작황 부진 이슈가 영향을 주며 상승. 반면, 옥수수는 차익 매물에 하락."""


def test_macro_extraction_from_ficc():
    from morning_brief.macro import extract_macros

    by = {m.ticker: m for m in extract_macros(FICC_EXCERPT)}
    assert by["WTI"].direction == "UP" and by["WTI"].change_pct == 1.0 and by["WTI"].reason_summary.startswith("국제유가는")
    assert by["NATGAS"].change_pct == -2.0 and by["NATGAS"].reason_summary.startswith("미국 천연가스는")  # 유럽 천연가스 문장이 아님
    assert by["GOLD"].change_pct == -0.8 and by["GOLD"].direction == "DOWN" and "금리" not in by["GOLD"].reason_summary[:3]
    assert by["SILVER"].direction == "UP" and by["SILVER"].reason_summary.startswith("은은")
    assert by["US10Y"].change_pct is None and "10년물" in by["US10Y"].reason_summary  # 금리 수준(4.8%)은 등락률로 쓰지 않음
    assert by["DXY"].direction == "DOWN" and by["WHEAT"].direction == "UP" and by["CORN"].direction == "DOWN"
    assert all(m.kind == "macro" and m.market == "MACRO" for m in by.values())
    assert "US2Y" not in by and "BTC" not in by  # 언급 없는 자산은 제외
    order = [m.ticker for m in extract_macros(FICC_EXCERPT)]
    assert order.index("WTI") < order.index("GOLD") < order.index("WHEAT")


def test_macro_section_renders_with_line_and_candle_charts(tmp_path: Path, monkeypatch):
    from morning_brief import macro_prices, prices, render
    from morning_brief.models import Brief, PricePoint, PriceSeries, StockMention

    closes = [4.2 + i * 0.01 for i in range(30)]
    yields = PriceSeries("MACRO_US10Y", [PricePoint(f"2026-08-{1 + i % 28:02d}", c, c, c, c, 0) for i, c in enumerate(closes)], "USD", "fred", "2026-08-28")
    gold = prices.synthetic("MACRO_GOLD", "US", 45)
    brief = Brief(date="2026-09-09", market_overview="시황.", generated_at="2026-09-09T06:31:00+09:00", macros=[
        StockMention(name="미국 10년물 국채 금리", ticker="US10Y", market="MACRO", kind="macro", unit="%", direction="UP",
                     reason_summary="국채 금리는 상승.", evidence="국채 금리는 상승.", prices=yields),
        StockMention(name="금", ticker="GOLD", market="MACRO", kind="macro", unit="USD/oz", direction="DOWN", change_pct=-0.8,
                     reason_summary="금은 0.8% 하락.", evidence="금은 0.8% 하락.", prices=gold),
    ])
    html = render.render_brief(brief)
    assert "금리 · 유가 · 금 · 환율" in html and 'id="x-us10y"' in html and 'id="x-gold"' in html
    assert "bp" in html  # 금리는 bp 표기
    assert macro_prices.is_close_only(yields) and not macro_prices.is_close_only(gold)
    assert 'stroke="#043B72" stroke-width="2"' in html  # 라인 차트(종가만 있는 시계열)
