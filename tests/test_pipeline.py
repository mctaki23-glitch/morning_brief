"""핵심 파이프라인 테스트 (외부 네트워크/API 불필요, fixture 기반)."""

from __future__ import annotations

import re

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
    assert "preserveAspectRatio" not in mini  # 비율 유지 스케일(늘려 그리지 않음)

    # 값이 긴 종목(수만 달러)도 최근가 태그가 잘리지 않게 우측 여백이 라벨 폭에 맞춰 늘어난다
    big = [PricePoint(f"2026-08-{i + 1:02d}", 77000 + i * 40, 77400 + i * 40, 76800 + i * 40, 77200 + i * 40, 1000) for i in range(25)]
    svg = chart.candlestick(big, currency="USD", width=360, height=330)
    tag = re.search(r'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)" height="20" fill="#1A1A1A"/>', svg)
    assert tag is not None
    assert float(tag.group(2)) >= chart._label_w(chart.fmt_price(big[-1].close)) + 8  # 태그 폭 ≥ 라벨 폭
    assert float(tag.group(1)) + float(tag.group(2)) <= 360  # 차트 밖으로 나가지 않음
    # 태그와 같은 높이의 눈금 라벨은 생략되어 숫자가 겹치지 않는다
    tag_y = float(re.search(r'<rect x="[\d.]+" y="([\d.]+)" width="[\d.]+" height="20" fill="#1A1A1A"/>', svg).group(1)) + 10
    tick_ys = [float(m.group(1)) - 4 for m in re.finditer(r'<text x="[\d.]+" y="([\d.]+)" font-size="12" text-anchor="start" fill="#6C6C6C"', svg)]
    assert all(abs(y - tag_y) >= 14 for y in tick_ys)
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
    assert 'data-sheet="s-nvda" tabindex="0"' in html and "btn-more" not in html and "상세 보기<" not in html  # 종목 칸 어디를 눌러도 시트가 열린다
    assert "tr[data-sheet]" in html and "e.key==='Enter'" in html  # 행 클릭·Enter 처리 스크립트
    assert "history.pushState" in html and "html.js .detail.open{display:block}" in html  # 닫을 때 #top 으로 점프하지 않는 JS 시트
    assert 'class="tile"' in html and 'class="spark"' in html and '<div class="note">최근 20일</div>' in html  # 지수 타일 스파크라인
    assert 'class="mini-link" href="#s-nvda"' in html
    for needle in ("시황 요약", "주요 지수", "오늘의 종목", "한국 증시 관전 포인트", 'id="s-nvda"', "MA20", "등락순", 'class="chart-sm"',
                   '<meta name="robots" content="noindex, nofollow">',
                   f'<meta property="og:image" content="https://example.test/mb/brief/{FIXTURE_DATE}/og.png">'):
        assert needle in html, needle
    assert "onepage" not in html  # 단일 페이지로 통합

    root = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert f'<base href="brief/{FIXTURE_DATE}/">' in root and "시황 요약" in root  # 루트는 최신 브리핑 본문(리다이렉트 아님)

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
    assert by["HXSCL"].change_pct == 4.83 and by["HXSCL"].market == "US" and by["HXSCL"].name == "SK하이닉스 ADR"  # SK하이닉스 ADR → 미국 예탁증서(원주 000660 아님)
    assert "000660" not in by
    assert by["NVS"].change_pct == -13.93 and by["GLW"].change_pct == 7.56
    assert "005930" not in by  # 삼성전자: 재고 뉴스 문맥의 언급(등락률 표기 없음)은 종목 서머리로 만들지 않는다
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
    assert '<td class="val r">' in html and 'data-sheet="x-gold"' in html
    assert "bp" in html  # 금리는 bp 표기
    assert macro_prices.is_close_only(yields) and not macro_prices.is_close_only(gold)
    assert 'stroke="#043B72" stroke-width="2"' in html  # 라인 차트(종가만 있는 시계열)


def test_index_prices_round_trip_and_tiles(tmp_path: Path):
    from morning_brief import archive, prices, render
    from morning_brief.models import Brief, IndexSnapshot

    dow = prices.synthetic("INDEX_DJI", "US", 30)
    proxy = prices.synthetic("INDEX_RUT", "US", 30)
    proxy.source = "proxy:IWM"
    brief = Brief(date="2026-09-10", market_overview="시황.", generated_at="2026-09-10T08:03:02+09:00", status="published", indices=[
        IndexSnapshot(name="다우", value=45123.4, change_pct=-0.77, ticker="DJI", prices=dow),
        IndexSnapshot(name="러셀2000", change_pct=-1.32, ticker="RUT", prices=proxy),
        IndexSnapshot(name="코스피", change_pct=0.5),
    ])
    archive.save(tmp_path, brief)
    loaded = archive.load(tmp_path, "2026-09-10")
    assert loaded.indices[0].prices is not None and len(loaded.indices[0].prices.points) == 30 and loaded.indices[0].ticker == "DJI"
    assert loaded.indices[2].prices is None
    html = render.render_brief(loaded)
    assert html.count('class="spark"') == 2 and "IWM ETF 추이" in html and "45,123" in html
    assert "최근 20일" in html  # 합성 데이터(D-n 날짜)는 기간을 알 수 없어 기본 문구
    assert 'class="c down"' in html and 'class="c up"' in html


def test_every_chart_shows_its_period(tmp_path: Path):
    """목록 미니 차트 · 매크로 미니 차트 · 지수 타일 · 상세 시트 차트 하단에 연.월.일 기간을 표기한다."""
    from morning_brief import chart, render
    from morning_brief.models import Brief, IndexSnapshot, PricePoint, PriceSeries, StockMention

    def series(key, n=25, start=1):
        pts = [PricePoint(f"2026-08-{start + i:02d}" if start + i <= 31 else f"2026-09-{start + i - 31:02d}", 10 + i, 11 + i, 9 + i, 10.5 + i, 100) for i in range(n)]
        return PriceSeries(key, pts, "USD", "nasdaq", pts[-1].date)

    assert chart.fmt_ymd("2026-09-08") == "2026.09.08" and chart.fmt_ymd("D-3") == ""
    s = series("META")
    assert chart.fmt_range(s.points) == "2026.08.06 – 2026.08.25"  # 표시 구간(마지막 20봉)
    assert chart.fmt_range([]) == ""

    brief = Brief(date="2026-09-10", market_overview="시황.", generated_at="2026-09-10T08:03:02+09:00", status="published",
                  indices=[IndexSnapshot(name="다우", value=45000.0, change_pct=-0.5, ticker="DJI", prices=series("INDEX_DJI"))],
                  stocks=[StockMention(name="메타", ticker="META", market="US", direction="UP", change_pct=6.55, reason_summary="이유.",
                                       evidence="이유.", evidence_verified=True, prices=series("META"))],
                  macros=[StockMention(name="금", ticker="GOLD", market="MACRO", kind="macro", unit="USD/oz", direction="DOWN",
                                       reason_summary="금 코멘트.", evidence="금 코멘트.", prices=series("MACRO_GOLD"))])
    html = render.render_brief(brief)
    assert html.count('<div class="c-dates">2026.08.06 – 2026.08.25</div>') == 2  # 종목 · 매크로 미니 차트
    assert '<div class="note">2026.08.06 – 2026.08.25</div>' in html  # 지수 타일
    assert html.count('<p class="chart-note">2026.08.06 – 2026.08.25 · ') >= 2  # 상세 시트(종목 · 매크로)


def test_only_explicit_pct_mentions_become_stock_summaries(master: StockMaster):
    """2026-09-11 오탐: 경제 코멘트 속 기관명(골드만삭스)과 뉴스 문맥의 기업명은 시세 분석 대상이 아니다."""
    from morning_brief.summarize import _extract_stocks

    text = ("실제 골드만삭스나 모건스탠리 등 주요 투자회사들은 오늘 발표된 생산자물가지수 발표 후 근원 PCE물가는 전월 대비 "
            "0.20% 내외에서 0.24% 상승으로 폭을 상향 조정. 아시아 시장에서 삼성전자와 SK하이닉스의 메모리 재고가 급감하고 있다는 "
            "소식에 상승 출발. 암젠(-2.25%)은 HSBC가 투자의견을 보유로 하향 조정하자 부진.")
    mentions, unmapped = _extract_stocks(text, master)
    tickers = {m.ticker for m in mentions}
    assert tickers == {"AMGN"} and unmapped == []


def test_connective_words_are_trimmed_from_captured_names(master: StockMaster):
    """'급락하며 프리포트맥모란(-6.59%)' 처럼 앞에 붙은 서술어·조사는 종목명에서 떼고, 두 단어 이름은 유지한다."""
    from morning_brief.summarize import _extract_stocks, _resolve_name

    text = ("구리 가격이 장중 고점에서 급락하며 프리포트맥모란(-6.59%), 서던코퍼(-7.23%) 등 하락. 광통신 기업들과 램리서치(-5.65%)도 부진. "
            "금 가격도 약세를 보이며 뉴몬트(-2.00%) 등 금광주도 부진. 물가 부담에 엑손모빌(+0.61%)은 보합. 윌리엄스 소노마(-1.66%) 등 가구 소매업체 하락.")
    names = {m.name: m.ticker for m in _extract_stocks(text, master)[0]}
    assert names == {"프리포트맥모란": "FCX", "서던코퍼": "SCCO", "램리서치": "LRCX", "뉴몬트": "NEM", "엑슨모빌": "XOM", "윌리엄스 소노마": "WSM"}  # 표시 이름은 마스터 대표명
    assert _resolve_name("급락하며 처음보는회사", master) == ("처음보는회사", None)  # 마스터에 없어도 서술어는 뗀다
    assert _resolve_name("마이크로 컴퓨터", master) == ("마이크로 컴퓨터", None)  # '마이크로' 는 조사가 아니다(2026-09-15 '컴퓨터' 오탐)
    assert _resolve_name("지수", master) == ("", None) and _resolve_name("전일 환율", master) == ("", None)  # 시장 용어는 종목이 아님
    assert _resolve_name("이틀", master)[1].ticker == "ETN"  # 채널 원문의 '이틀(+2.75%)' 은 이튼(Eaton) 표기 → 마스터 별칭으로 매핑
    assert _resolve_name("엘리번스 헬스", master)[0] == "엘리번스 헬스"


def test_cpi_components_in_econ_sentences_are_not_stocks(master: StockMaster):
    """2026-09-12: 소비자물가 품목(에너지·항공료·임대료 …)이 종목 형식 '이름(+x.xx%)' 으로 쓰여도 종목이 아니다."""
    from morning_brief.summarize import _extract_stocks

    text = ("미국 8월 소비자물가지수가 전월 대비 0.40% 상승하며 시장 예상에 부합했지만 근원 소비자 물가지수는 전월 대비 0.29% 상승해 시장 예상(+0.2%)을 상회. "
            "품목별로는 국제유가 영향에 에너지(+2.10%)가 상승하며 헤드라인 상승을 견인. 무선 전화 서비스(+5.90%), 항공료(+2.68%), 호텔 숙박(+2.36%)이 근원 물가 상승을 견인. "
            "다만, 자가주거비(+0.19%)와 임대료(+0.17%)는 둔화됐고 의료서비스(-0.25%) 등이 하락. "
            "델(+11.98%), HP엔터(+12.44%), 슈퍼마이크로 컴퓨터(+7.28%)등 AI 서버 관련 기업들, 아리스타네트웍(+5.61%), 시스코시스템(+4.37%)등이 상승. "
            "아날로그디바이스(+4.85%), 모놀리식 파워(+4.08%), 빅코어(+11.15%)등 전력 반도체 기업들도 상승.")
    mentions, unmapped = _extract_stocks(text, master)
    assert unmapped == []
    assert {m.ticker for m in mentions} == {"DELL", "HPE", "SMCI", "ANET", "CSCO", "ADI", "MPWR", "VICR"}


def test_three_word_names_resolve_whole(master: StockMaster):
    """2026-09-15: '슈퍼 마이크로 컴퓨터(-8.40%)' 가 '컴퓨터' 로 잘려 미매핑 행이 되었다. 세 단어 이름을 통째로 잡아 SMCI 로 매핑한다."""
    from morning_brief.summarize import _MENTION_RE, _extract_stocks

    text = "델(-5.85%), 슈퍼 마이크로 컴퓨터(-8.40%) 등 AI 서버 등도 부진. 부진한 흐름 속 애플(+1.00%)은 견조."
    assert [m.group(1) for m in _MENTION_RE.finditer(text)] == ["델", "슈퍼 마이크로 컴퓨터", "부진한 흐름 속 애플"[-len("흐름 속 애플"):]]
    mentions, unmapped = _extract_stocks(text, master)
    assert unmapped == [] and {m.ticker: m.name for m in mentions} == {"DELL": "델", "SMCI": "슈퍼마이크로", "AAPL": "애플"}  # 표시 이름은 마스터 대표명


def test_ms_alias_is_microsoft_and_morgan_stanley_by_name(master: StockMaster):
    """채널 표기 'MS(+0.16%)' 는 마이크로소프트, '모건스탠리(+1.2%)' 는 모건스탠리(티커 MS). 별칭 정확 일치가 티커보다 우선한다."""
    from morning_brief.summarize import _extract_stocks

    assert master.resolve("MS").ticker == "MSFT" and master.resolve("모건스탠리").ticker == "MS" and master.resolve("BOA").ticker == "BAC"
    mentions, unmapped = _extract_stocks("MS(+0.16%)와 모건스탠리(+1.20%), BOA(-0.50%), 코스트코(+0.30%), P&G(-0.10%) 등락.", master)
    assert unmapped == [] and [m.ticker for m in mentions] == ["MSFT", "MS", "BAC", "COST", "PG"]


def test_stale_series_hides_data_delta_next_to_text_pct():
    """2026-09-15 오클로: 본문 -0.03%(09-14) 옆에 09-11 봉 기준 변동폭(-3.66)이 붙어 어긋났다. 세션 봉이 없으면 변동폭 대신 기준일을 표시."""
    from morning_brief import render
    from morning_brief.models import Brief, PricePoint, PriceSeries, StockMention

    assert render.expected_session("2026-09-15") == "2026-09-14" and render.expected_session("2026-09-12") == "2026-09-11"
    assert render.expected_session("2026-09-14") == "2026-09-11"  # 월요일 브리핑 → 금요일 세션
    pts = [PricePoint("2026-09-10", 40, 41, 39, 39.88, 1e6), PricePoint("2026-09-11", 39, 40, 35, 36.22, 1e6)]
    stale = StockMention(name="오클로", ticker="OKLO", market="US", direction="DOWN", change_pct=-0.03, reason_summary="제한적인 등락.",
                         evidence="오클로(-0.03%)", prices=PriceSeries("OKLO", pts, "USD", "nasdaq", "2026-09-11"))
    brief = Brief(date="2026-09-15", market_overview="시황.", generated_at="2026-09-15T09:29:00+09:00", stocks=[stale])
    html = render.render_brief(brief)
    assert "(−3.66)" not in html and "시세 2026-09-11 종가까지" in html and "▼0.03%" in html
    # 세션 봉이 있으면 변동폭 표시
    fresh_pts = pts + [PricePoint("2026-09-14", 36.3, 36.9, 35.9, 36.21, 1e6)]
    stale.prices = PriceSeries("OKLO", fresh_pts, "USD", "nasdaq+naver", "2026-09-14")
    html2 = render.render_brief(brief)
    assert "(−0.01)" in html2 and "종가까지" not in html2


def test_korean_adr_mentions_are_us_listings_not_the_kr_share(master: StockMaster):
    """'SK하이닉스 ADR(-7.60%)' · 'SK하이닉스ADR(+0.94%)' 은 미국 예탁증서 — 원주 000660(한국)이 아니라 HXSCL(미국)로.
    마스터에 DR 이 없는 한국 종목의 DR 은 티커 없는 미국 종목으로 두고, 원주 언급('SK하이닉스(+1.10%)')은 그대로 한국 종목."""
    from morning_brief.summarize import _extract_stocks
    text = ("SK하이닉스 ADR(-7.60%), 샌디스크(-4.98%) 등 메모리 낙폭 축소. 삼성전자 GDR(+1.20%)도 강세. TSMC ADR(+0.50%)은 보합권.\n"
            "한국 증시에서는 SK하이닉스(+1.10%)가 상승.")
    mentions, unmapped = _extract_stocks(text, master)
    by = {m.name: m for m in mentions}
    adr = by["SK하이닉스 ADR"]
    assert (adr.ticker, adr.market, adr.change_pct) == ("HXSCL", "US", -7.6)
    assert by["삼성전자 GDR"].ticker is None and by["삼성전자 GDR"].market == "US" and "삼성전자 GDR" in unmapped
    assert by["TSMC"].ticker == "TSM"  # 미국 기업의 ADR 은 미국 상장 그 자체
    assert (by["SK하이닉스"].ticker, by["SK하이닉스"].market, by["SK하이닉스"].change_pct) == ("000660", "KR", 1.1)
    m2, _ = _extract_stocks("마이크론(-0.22%), SK하이닉스ADR(+0.94%), 샌디스크(-3.50%) 하락.", master)
    assert [(m.name, m.ticker) for m in m2] == [("마이크론", "MU"), ("SK하이닉스 ADR", "HXSCL"), ("샌디스크", "SNDK")]
