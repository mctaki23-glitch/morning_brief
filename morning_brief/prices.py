"""시세 데이터 조회 — 소스 어댑터 + 아카이브 캐시 + 전일 폴백 (PRD D4 확정: 무료 비공식 조합).

미국: Nasdaq Data API(거래량 포함) → 네이버 해외주식(api.stock.naver.com, 거래량 없음) → investing.com(비공식) → Stooq CSV → Yahoo Finance
한국: 네이버 금융 siseJson → Yahoo Finance(.KS/.KQ)
(GitHub Actions 러너 실측 2026-09-09: Stooq 는 공용 IP 일일 한도, Yahoo 는 429 로 실패. Nasdaq·네이버는 정상.
 네이버 해외주식 price 응답 키: closePrice, openPrice, highPrice, lowPrice, localTradedAt, fluctuationsRatio, stockExchangeType — 거래량 없음.)

모든 어댑터는 urllib 만 사용한다(HTTPS_PROXY 환경변수 자동 인식). 성공 시 archive/<date>/prices/<ticker>.json 에
저장하고, 전부 실패하면 최근 아카이브 캐시(source="cache")를 쓴다. 합성 데이터는 개발·테스트 전용이며
운영 모드(allow_synthetic=False)에서는 None 을 돌려 차트 없이 텍스트만 노출한다.
"""

from __future__ import annotations

import csv
import io
import json
import re
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from .models import PricePoint, PriceSeries

_TIMEOUT = 15
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
_NET_ERRORS = (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError)


def _get(url: str, referer: Optional[str] = None) -> str:
    headers = {"User-Agent": _UA, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ── 어댑터: Stooq (미국) ──────────────────────────────────────
def from_stooq(ticker: str, days: int, suffix: str = ".us") -> Optional[PriceSeries]:
    body = _get(f"https://stooq.com/q/d/l/?s={ticker.lower()}{suffix}&i=d")
    return parse_stooq(body, ticker, days, currency="USD" if suffix == ".us" else "KRW")


def parse_stooq(body: str, ticker: str, days: int, currency: str = "USD") -> Optional[PriceSeries]:
    if not body or body.lstrip().startswith("<") or "Date" not in body[:64]:
        if body and "daily hits limit" in body.lower():
            print(f"[prices] stooq: 일일 조회 한도 초과 ({ticker})")
        return None
    points: list[PricePoint] = []
    for row in csv.DictReader(io.StringIO(body)):
        try:
            points.append(PricePoint(row["Date"], float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]),
                                     float(row.get("Volume") or 0) or 0.0))
        except (KeyError, ValueError):
            continue
    return _finish(points, ticker, currency, "stooq", days)


# ── 어댑터: Yahoo Finance (미국·한국) ─────────────────────────
def from_yahoo(symbol: str, ticker: str, days: int, currency_hint: str) -> Optional[PriceSeries]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=6mo&interval=1d"
    return parse_yahoo(json.loads(_get(url)), ticker, days, currency_hint)


def parse_yahoo(data: dict, ticker: str, days: int, currency_hint: str = "USD") -> Optional[PriceSeries]:
    result = (data.get("chart") or {}).get("result") or []
    if not result:
        return None
    r = result[0]
    meta = r.get("meta") or {}
    tz = ZoneInfo(meta.get("exchangeTimezoneName") or ("Asia/Seoul" if currency_hint == "KRW" else "America/New_York"))
    quote = (r.get("indicators") or {}).get("quote") or [{}]
    q = quote[0]
    points: list[PricePoint] = []
    for i, ts in enumerate(r.get("timestamp") or []):
        try:
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        except (KeyError, IndexError):
            continue
        if None in (o, h, l, c):
            continue
        v = (q.get("volume") or [None])[i] if i < len(q.get("volume") or []) else None
        d = datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d")
        points.append(PricePoint(d, float(o), float(h), float(l), float(c), float(v or 0)))
    return _finish(points, ticker, meta.get("currency") or currency_hint, "yahoo", days)


# ── 어댑터: 네이버 해외주식 (미국) ─────────────────────────────
def _num(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).replace(",", "").replace("$", "").strip()
    if not t or t in ("-", "—"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def naver_world_symbols(ticker: str, exchange: Optional[str] = None) -> list[str]:
    """네이버 해외주식 심볼 후보: 나스닥 'TICKER.O', 뉴욕 'TICKER' (거래소를 알면 그것만)."""
    ex = (exchange or "").upper()
    if ex in ("NYSE", "NYS", "AMEX"):
        return [f"{ticker}.N", ticker, f"{ticker}.O"]  # 러너 실측: NYSE 종목은 접미사 없는 심볼이 409 를 돌려줌
    if ex in ("NASDAQ", "NAS"):
        return [f"{ticker}.O", ticker, f"{ticker}.N"]
    return [f"{ticker}.O", f"{ticker}.N", ticker]  # 힌트가 없거나 틀려도 나머지 후보로 폴백


def from_naver_world(ticker: str, days: int, exchange: Optional[str] = None) -> Optional[PriceSeries]:
    for symbol in naver_world_symbols(ticker, exchange):
        url = f"https://api.stock.naver.com/stock/{urllib.parse.quote(symbol)}/price?pageSize={min(max(days, 20), 60)}&page=1"
        try:
            body = _get(url, referer="https://m.stock.naver.com/")
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 600 and exc.code != 429:
                continue  # 심볼 불일치(400/404/409 등) → 다음 후보
            raise
        series = parse_naver_world(body, ticker, days)
        if series is not None:
            return series
    return None


def parse_naver_world(text: str, ticker: str, days: int) -> Optional[PriceSeries]:
    """api.stock.naver.com/stock/<symbol>/price 응답: [{localTradedAt, openPrice, highPrice, lowPrice, closePrice,
    accumulatedTradingVolume, ...}, ...] (최신순, 숫자는 문자열/콤마 포함 가능)"""
    text = (text or "").strip()
    if not text.startswith("["):
        return None
    rows = json.loads(text)
    points: list[PricePoint] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = str(r.get("localTradedAt") or r.get("localDate") or "")[:10]
        o, h, l, c = (_num(r.get(k)) for k in ("openPrice", "highPrice", "lowPrice", "closePrice"))
        if len(d) != 10 or None in (o, h, l, c):
            continue
        points.append(PricePoint(d.replace(".", "-"), o, h, l, c, _volume_of(r)))
    if rows and isinstance(rows[0], dict) and points and points[-1].volume == 0 and not _LOGGED_KEYS.get("naver_world"):
        _LOGGED_KEYS["naver_world"] = True
        print(f"[prices] naver_world 응답 키(거래량 필드 확인용): {sorted(rows[0].keys())}")
    return _finish(points, ticker, "USD", "naver", days)


_LOGGED_KEYS: dict[str, bool] = {}


def _volume_of(row: dict) -> float:
    """거래량 필드명이 소스·시장별로 달라 'volume' 이 들어간 키를 우선순위로 찾는다."""
    for key in ("accumulatedTradingVolume", "accTradeVolume", "tradingVolume", "volume"):
        v = _num(row.get(key))
        if v is not None:
            return v
    for key, val in row.items():
        if "volume" in key.lower() and "value" not in key.lower():
            v = _num(val)
            if v is not None:
                return v
    return 0.0


# ── 어댑터: Nasdaq Data API (미국) ────────────────────────────
def from_nasdaq(ticker: str, days: int, today: Optional[date] = None) -> Optional[PriceSeries]:
    end = today or datetime.now(ZoneInfo("America/New_York")).date()
    start = end - timedelta(days=days * 2 + 14)
    url = (f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(ticker)}/historical?assetclass=stocks"
           f"&fromdate={start:%Y-%m-%d}&todate={end:%Y-%m-%d}&limit=9999")
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/",
    })
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return parse_nasdaq(json.loads(body), ticker, days)


def parse_nasdaq(data: dict, ticker: str, days: int) -> Optional[PriceSeries]:
    """{"data": {"tradesTable": {"rows": [{"date": "09/08/2026", "close": "$178.42", "volume": "51,000,000",
    "open": "$171.20", "high": "$179.90", "low": "$170.80"}, ...]}}}"""
    rows = (((data or {}).get("data") or {}).get("tradesTable") or {}).get("rows") or []
    points: list[PricePoint] = []
    for r in rows:
        try:
            m, d_, y = str(r.get("date", "")).split("/")
            d = f"{int(y):04d}-{int(m):02d}-{int(d_):02d}"
        except ValueError:
            continue
        o, h, l, c = (_num(r.get(k)) for k in ("open", "high", "low", "close"))
        if None in (o, h, l, c):
            continue
        points.append(PricePoint(d, o, h, l, c, _num(r.get("volume")) or 0.0))
    return _finish(points, ticker, "USD", "nasdaq", days)


# ── 어댑터: investing.com (미국, 비공식 — 사용자 허용 2026-09-09) ──────
_INV_HEADERS = {"User-Agent": _UA, "Accept": "application/json, text/plain, */*", "domain-id": "www",
                "Referer": "https://www.investing.com/", "Origin": "https://www.investing.com"}


def _get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def investing_pair_id(ticker: str) -> Optional[int]:
    """검색 API 로 종목의 pair id 를 찾는다(미국 주식 우선)."""
    data = _get_json(f"https://api.investing.com/api/search/v2/search?q={urllib.parse.quote(ticker)}", _INV_HEADERS)
    return pick_investing_quote(data, ticker)


def pick_investing_quote(data: dict, ticker: str) -> Optional[int]:
    quotes = (data or {}).get("quotes") or []
    best = None
    for q in quotes:
        if str(q.get("symbol", "")).upper() != ticker.upper():
            continue
        flag = str(q.get("flag", "")).upper()
        exch = str(q.get("exchange", "")).upper()
        score = 2 if flag in ("USA", "US") or exch in ("NASDAQ", "NYSE", "NYSE ARCA", "AMEX") else 1
        if best is None or score > best[0]:
            best = (score, q.get("id"))
    if best and best[1] is not None:
        try:
            return int(best[1])
        except (TypeError, ValueError):
            return None
    return None


def from_investing(ticker: str, days: int, today: Optional[date] = None) -> Optional[PriceSeries]:
    pair = investing_pair_id(ticker)
    if pair is None:
        return None
    end = today or datetime.now(ZoneInfo("America/New_York")).date()
    start = end - timedelta(days=days * 2 + 14)
    url = (f"https://api.investing.com/api/financialdata/historical/{pair}?start-date={start:%Y-%m-%d}&end-date={end:%Y-%m-%d}"
           f"&time-frame=Daily&add-missing-rows=false")
    return parse_investing(_get_json(url, _INV_HEADERS), ticker, days)


def parse_investing(data: dict, ticker: str, days: int) -> Optional[PriceSeries]:
    """{"data": [{"rowDateTimestamp": "2026-09-08T00:00:00Z", "last_closeRaw": 178.42, "last_openRaw": 171.2,
    "last_maxRaw": 179.9, "last_minRaw": 170.8, "volumeRaw": 51000000, ...}, ...]} (최신순)"""
    rows = (data or {}).get("data") or []
    points: list[PricePoint] = []
    for r in rows:
        ts = str(r.get("rowDateTimestamp") or "")[:10]
        if len(ts) != 10:
            continue
        o = _num(r.get("last_openRaw", r.get("last_open")))
        h = _num(r.get("last_maxRaw", r.get("last_max")))
        l = _num(r.get("last_minRaw", r.get("last_min")))
        c = _num(r.get("last_closeRaw", r.get("last_close")))
        if None in (o, h, l, c):
            continue
        points.append(PricePoint(ts, o, h, l, c, _num(r.get("volumeRaw", r.get("volume"))) or 0.0))
    return _finish(points, ticker, "USD", "investing", days)


# ── 어댑터: 네이버 금융 (한국) ────────────────────────────────
def from_naver(code: str, days: int, today: Optional[date] = None) -> Optional[PriceSeries]:
    end = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
    start = end - timedelta(days=days * 2 + 14)
    url = (f"https://api.finance.naver.com/siseJson.naver?symbol={code}&requestType=1"
           f"&startTime={start:%Y%m%d}&endTime={end:%Y%m%d}&timeframe=day")
    return parse_naver(_get(url, referer="https://finance.naver.com/"), code, days)


def parse_naver(text: str, code: str, days: int) -> Optional[PriceSeries]:
    """네이버 siseJson 응답: [['날짜','시가','고가','저가','종가','거래량','외국인소진율'], ["20240102", 79400, ...], ...]"""
    cleaned = text.strip().replace("'", '"')
    if not cleaned.startswith("["):
        return None
    rows = json.loads(cleaned)
    points: list[PricePoint] = []
    for row in rows[1:]:
        if len(row) < 6 or any(v in (None, "") for v in row[:6]):
            continue
        d = str(row[0])
        if len(d) != 8:
            continue
        try:
            points.append(PricePoint(f"{d[:4]}-{d[4:6]}-{d[6:]}", float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])))
        except (TypeError, ValueError):
            continue
    return _finish(points, code, "KRW", "naver", days)


def _finish(points: list[PricePoint], ticker: str, currency: str, source: str, days: int) -> Optional[PriceSeries]:
    points = [p for p in points if p.high >= p.low > 0]
    points.sort(key=lambda p: p.date)
    if len(points) < 2:
        return None
    points = points[-days:]
    return PriceSeries(ticker=ticker, points=points, currency=currency, source=source, as_of=points[-1].date)


def clip_before(series: Optional[PriceSeries], date_str: str) -> Optional[PriceSeries]:
    """브리핑 일자(KST) 이전 세션만 남긴다 — 브리핑은 전일 미국장·전일 국내장을 다루므로, 과거 일자 재생성이나
    장중 재실행에서 섞여 들어오는 당일·이후 봉을 제외한다. 2봉 미만이 되면 원본을 그대로 둔다."""
    if series is None or not date_str:
        return series
    kept = [pt for pt in series.points if pt.date < date_str]
    if len(kept) >= 2 and len(kept) != len(series.points):
        series.points = kept
        series.as_of = kept[-1].date
    return series


# ── 캐시 (archive/<date>/prices/<ticker>.json) ───────────────
def series_to_dict(s: PriceSeries) -> dict:
    return {"ticker": s.ticker, "currency": s.currency, "source": s.source, "as_of": s.as_of, "points": [asdict(p) for p in s.points]}


def series_from_dict(d: dict) -> PriceSeries:
    return PriceSeries(ticker=d["ticker"], currency=d.get("currency", "USD"), source=d.get("source", "cache"), as_of=d.get("as_of", ""),
                       points=[PricePoint(**p) for p in d.get("points", [])])


def save_cache(cache_dir: Path, series: PriceSeries) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{series.ticker}.json").write_text(json.dumps(series_to_dict(series), ensure_ascii=False), encoding="utf-8")


def load_cache(cache_dir: Path, ticker: str) -> Optional[PriceSeries]:
    """현재 일자 캐시 → 없으면 아카이브의 가장 최근 다른 일자 캐시."""
    candidates = [cache_dir / f"{ticker}.json"]
    archive_root = cache_dir.parent.parent  # archive/<date>/prices → archive
    if archive_root.exists():
        for d in sorted((p for p in archive_root.iterdir() if p.is_dir()), reverse=True):
            candidates.append(d / "prices" / f"{ticker}.json")
    for path in candidates:
        if path.exists():
            try:
                s = series_from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            if len(s.points) >= 2:
                s.source = "cache"
                return s
    return None


# ── 진입점 ────────────────────────────────────────────────────
def adapters_for(ticker: str, market: str, days: int, exchange: Optional[str] = None) -> list[Callable[[], Optional[PriceSeries]]]:
    if market == "KR":
        suffix = ".KQ" if (exchange or "").upper() == "KOSDAQ" else ".KS"
        return [lambda: from_naver(ticker, days), lambda: from_yahoo(f"{ticker}{suffix}", ticker, days, "KRW")]
    return [
        lambda: from_nasdaq(ticker, days),  # 거래량 포함
        lambda: from_naver_world(ticker, days, exchange),  # 안정적이나 거래량 없음
        lambda: from_investing(ticker, days),
        lambda: from_stooq(ticker, days),
        lambda: from_yahoo(ticker, ticker, days, "USD"),
    ]


def get_prices(ticker: str, market: str = "US", days: int = 45, *, allow_synthetic: bool = True,
               cache_dir: Optional[Path] = None, exchange: Optional[str] = None,
               freshen_through: Optional[str] = None) -> Optional[PriceSeries]:
    """freshen_through: 이 날짜(미국 세션 일자)까지의 봉이 있어야 한다. 1순위 소스(Nasdaq 은 새벽에 전일 봉이 아직 없음)가
    그보다 오래됐으면 네이버 세계주식에서 최신 봉을 받아 덧붙인다."""
    time.sleep(0.15)  # 소스별 rate limit 예방
    for fetch in adapters_for(ticker, market, days, exchange):
        try:
            series = fetch()
        except _NET_ERRORS as exc:
            print(f"[prices] {ticker}: {exc!r}")
            continue
        if series is not None:
            if freshen_through and market == "US" and series.source != "naver" and series.points[-1].date < freshen_through:
                series = freshen(series, ticker, days, exchange, freshen_through)
            print(f"[prices] {ticker} ← {series.source} ({series.as_of}, {len(series.points)}봉)")
            if cache_dir is not None:
                save_cache(cache_dir, series)
            return series
    if cache_dir is not None:
        cached = load_cache(cache_dir, ticker)
        if cached is not None:
            print(f"[prices] {ticker}: 소스 실패 → 캐시({cached.as_of}) 사용")
            return cached
    if not allow_synthetic:
        return None
    return synthetic(ticker, market, days)


def freshen(series: PriceSeries, ticker: str, days: int, exchange: Optional[str], through: str) -> PriceSeries:
    """series 마지막 봉 이후 ~ through 까지의 봉을 덧붙인다. 1차 네이버 세계주식 일봉(거래량 없음), 2차 Nasdaq 시세 API
    (/chart 구간 일봉 → /info·/summary 마감 종가 봉) — 네이버에 없는 NYSE 종목(OKLO·ORCL·DELL·ABBV·COHR·IONQ·CRCL 등)용."""
    last = series.points[-1].date
    extra: list[PricePoint] = []
    tag = ""
    try:
        fresh = from_naver_world(ticker, days, exchange)
    except _NET_ERRORS as exc:
        print(f"[prices] {ticker}: 네이버 보충 실패 {exc!r}")
        fresh = None
    if fresh is not None:
        extra = [p for p in fresh.points if last < p.date <= through]
        tag = "naver"
        if not extra:
            print(f"[prices] {ticker}: 네이버 마지막 봉 {fresh.points[-1].date} — 필요한 {through} 봉 없음")
    else:
        print(f"[prices] {ticker}: 네이버 세계주식 응답 없음(심볼 후보 {naver_world_symbols(ticker, exchange)})")
    if not extra:
        extra, tag = nasdaq_topup(ticker, last, through), "nasdaq-quote"
    if not extra:
        print(f"[prices] {ticker}: 최신 봉 보충 실패 — {last} 이후 ~{through} 봉을 어느 소스에서도 못 받음")
        return series
    series.points = (series.points + extra)[-days:]
    series.as_of = series.points[-1].date
    series.source = f"{series.source}+{tag}"
    print(f"[prices] {ticker}: {last} 이후 봉 {len(extra)}개를 {tag} 에서 보충 (~{series.as_of})")
    return series


_NASDAQ_QUOTE_HEADERS = {"User-Agent": _UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
                         "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
_MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
_NY = ZoneInfo("America/New_York")


def _nasdaq_json(path: str) -> dict:
    return _get_json(f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(path, safe='/?=&')}", _NASDAQ_QUOTE_HEADERS)


def _parse_closed_at(ts: str) -> Optional[str]:
    """'Closed at Sep 14, 2026 4:00 PM ET' 또는 'Sep 14, 2026 7:56 PM ET' → '2026-09-14'."""
    m = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", ts or "")
    if not m or m.group(1) not in _MONTHS:
        return None
    return f"{int(m.group(3)):04d}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"


def _parse_mdy(s: str) -> Optional[str]:
    """/chart 일봉의 dateTime '9/14/2026'(M/D/YYYY) → '2026-09-14'. 분 단위 시세의 '4:00 AM ET' 꼴은 None."""
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*", s or "")
    if not m:
        return None
    return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"


def _session_complete(bar_date: str, now: Optional[datetime] = None) -> bool:
    """그 날짜의 미국 정규장이 끝났는가(뉴욕 16:05 이후). 장중에 호출되면 진행 중인 날의 봉은 받지 않는다."""
    now = now or datetime.now(_NY)
    today = now.date().isoformat()
    return bar_date < today or (bar_date == today and (now.hour, now.minute) >= (16, 5))


def nasdaq_chart_bars(ticker: str, from_date: str, to_date: str, assetclass: str = "stocks") -> list[PricePoint]:
    """/chart?fromdate=&todate= 는 구간 일봉 배열을 준다(러너 실측 2026-09-15): z={open, high, low, close, volume, dateTime 'M/D/YYYY'}.
    historical 보다 먼저(마감 직후) 갱신되고 종가가 공식 종가와 같다(OKLO 09-14: chart 36.21 ↔ 본문 -0.03%; /info 는 36.225).
    기간 없이 부르면 분 단위 시세(dateTime '4:00 AM ET')라 그런 행은 건너뛴다."""
    data = _nasdaq_json(f"{ticker}/chart?assetclass={assetclass}&fromdate={from_date}&todate={to_date}")
    rows = ((data or {}).get("data") or {}).get("chart") or []
    out: list[PricePoint] = []
    for row in rows:
        z = row.get("z") if isinstance(row, dict) else None
        if not isinstance(z, dict):
            continue
        d = _parse_mdy(str(z.get("dateTime", "")))
        close = _num(z.get("close")) if z.get("close") not in (None, "") else _num(z.get("value"))
        if not d or close is None:
            continue
        open_, high, low = _num(z.get("open")), _num(z.get("high")), _num(z.get("low"))
        if open_ is None:
            open_ = close
        if high is None or low is None:
            high, low = max(open_, close), min(open_, close)
        out.append(PricePoint(d, round(open_, 4), round(max(high, open_, close), 4), round(min(low, open_, close), 4), round(close, 4),
                              _num(z.get("volume")) or 0.0))
    out.sort(key=lambda p: p.date)
    return out


def nasdaq_topup(ticker: str, last: str, through: str, assetclass: str = "stocks") -> list[PricePoint]:
    """last 이후 ~ through 까지의 봉을 Nasdaq 시세 API 에서 받는다. 1차 /chart 구간 일봉(정식 OHLCV), 2차 /info 'Closed at' 종가 +
    /summary 고저·거래량으로 만든 봉. 네트워크·파싱 실패는 빈 목록(호출자가 다른 소스로 넘어감)."""
    try:
        start = (date.fromisoformat(through) - timedelta(days=10)).isoformat()
    except ValueError:
        return []
    bars: list[PricePoint] = []
    try:
        bars = [p for p in nasdaq_chart_bars(ticker, start, through, assetclass) if last < p.date <= through and _session_complete(p.date)]
    except _NET_ERRORS as exc:
        print(f"[prices] {ticker}: Nasdaq /chart 보충 실패 {exc!r}")
    if bars:
        return bars
    try:
        bar = nasdaq_latest_bar(ticker, through, assetclass)
    except _NET_ERRORS as exc:
        print(f"[prices] {ticker}: Nasdaq 시세 요약 보충 실패 {exc!r}")
        return []
    if bar is None or not (last < bar.date <= through):
        return []
    print(f"[prices] {ticker}: /chart 에 {through} 일봉 없음 → /info·/summary 마감 종가로 봉 구성")
    return [bar]


def nasdaq_latest_bar(ticker: str, through: str, assetclass: str = "stocks") -> Optional[PricePoint]:
    """Nasdaq /info 의 secondaryData('Closed at …', 정규장 종가)로 가장 최근 종가 봉을 만든다. 고가·저가·시가·거래량은
    /summary(TodayHighLow · OpenPrice · ShareVolume)에서, 없으면 종가로 채운다. /chart 일봉이 없을 때의 2차 수단."""
    info = _nasdaq_json(f"{ticker}/info?assetclass={assetclass}")
    d = (info or {}).get("data") or {}
    close_block = None
    for block in (d.get("secondaryData"), d.get("primaryData")):
        if isinstance(block, dict) and str(block.get("lastTradeTimestamp", "")).startswith("Closed at"):
            close_block = block
            break
    if close_block is None and str(d.get("marketStatus", "")).lower() in ("closed", "market closed") and isinstance(d.get("primaryData"), dict):
        close_block = d["primaryData"]  # 장 마감·애프터마켓 종료 후에는 primaryData 가 종가
    if not isinstance(close_block, dict):
        return None
    date_ = _parse_closed_at(str(close_block.get("lastTradeTimestamp", "")))
    close = _num(close_block.get("lastSalePrice"))
    if not date_ or close is None or date_ > through:
        return None
    high = low = open_ = None
    volume = 0.0
    try:
        summary = (_nasdaq_json(f"{ticker}/summary?assetclass={assetclass}") or {}).get("data") or {}
        sd = summary.get("summaryData") or {}
        val = lambda k: (sd.get(k) or {}).get("value") if isinstance(sd.get(k), dict) else None
        hl = str(val("TodayHighLow") or "")
        if "/" in hl:
            high, low = _num(hl.split("/")[0]), _num(hl.split("/")[1])
        open_ = _num(val("OpenPrice"))
        volume = _num(val("ShareVolume")) or 0.0
    except _NET_ERRORS as exc:
        print(f"[prices] {ticker}: Nasdaq summary 없음 {exc!r} — 종가만으로 봉 구성")
    if high is None or low is None:
        high = max(close, open_ or close)
        low = min(close, open_ or close)
    if open_ is None:
        open_ = close
    return PricePoint(date_, round(open_, 4), round(max(high, open_, close), 4), round(min(low, open_, close), 4), round(close, 4), volume)


def synthetic(ticker: str, market: str, days: int) -> PriceSeries:
    """티커로 시드를 고정한 결정적 랜덤워크. 실제 시세가 아님(데모·테스트 전용)."""
    seed = sum(ord(c) for c in ticker)
    rng = random.Random(seed)
    price = float(50 + (seed % 400))
    points: list[PricePoint] = []
    for i in range(days):
        price = max(1.0, price * (1 + rng.uniform(-0.025, 0.028)))
        high = price * (1 + abs(rng.uniform(0, 0.012)))
        low = price * (1 - abs(rng.uniform(0, 0.012)))
        open_ = low + (high - low) * rng.random()
        points.append(PricePoint(f"D-{days - i - 1}", round(open_, 2), round(high, 2), round(low, 2), round(price, 2), round(rng.uniform(1e6, 5e7))))
    return PriceSeries(ticker=ticker, points=points, currency="USD" if market == "US" else "KRW", source="synthetic", as_of="")
