"""매크로 자산 시세 어댑터 (표준 라이브러리만).

- nasdaq_commodity : api.nasdaq.com 원자재 선물 일봉 (금 GC:CMX, WTI CL:NMX, 브렌트 BZ:NMX, 구리 HG:CMX …) — OHLCV
- nasdaq_crypto    : api.nasdaq.com 암호화폐 일봉 (BTC)
- fred             : 세인트루이스 연준 FRED CSV (국채 금리 DGS10/DGS2, 달러/원 DEXKOUS, 달러 인덱스 DTWEXBGS, 유가) — 종가만
- coingecko        : CoinGecko 일별 가격 (비트코인) — 종가만
- naver_index      : 네이버 시장지표(환율 등) — 응답 형식이 확인되지 않아 방어적으로 파싱하고 키를 로그로 남긴다
- investing_pair   : investing.com 일봉 (고정 pair id: 금 8830, WTI 8849, 미 10년물 23705 …) — OHLC (사용자 허용 2026-09-09)
- treasury         : 미 재무부 일별 국채 수익률 곡선 CSV (10 Yr, 2 Yr …) — 종가만
- stooq            : Stooq 선물 일봉 (gc.f, cl.f …) — OHLCV, 러너 IP 는 일일 한도에 걸릴 수 있어 마지막 폴백
- naver_index      : api.stock.naver.com/index/<code>/price 세계 지수 일봉 (.DJI .IXIC .INX .SOX) — OHLC
- nasdaq_index     : api.nasdaq.com assetclass=index (COMP, SOX, NDX) — OHLC
- naver_sise       : finance.naver.com siseJson (KOSPI, KOSDAQ) — OHLCV
- nasdaq_proxy     : 지수 데이터가 없을 때 대표 ETF 일봉(예: 러셀2000 → IWM). source 가 'proxy:<ETF>' 로 표시된다
종가만 있는 시계열은 open=high=low=close 로 채우고 차트는 라인으로 그린다. 캐시·폴백 규칙은 prices 와 같다.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from . import prices as _p
from .macro import MacroInstrument
from .models import PricePoint, PriceSeries

_LOGGED: dict[str, bool] = {}


def is_close_only(series: PriceSeries) -> bool:
    return all(p.open == p.high == p.low == p.close for p in series.points)


# ── Nasdaq (원자재 · 암호화폐) ───────────────────────────────
def from_nasdaq_asset(symbol: str, key: str, days: int, assetclass: str, today: Optional[date] = None) -> Optional[PriceSeries]:
    end = today or datetime.now(ZoneInfo("America/New_York")).date()
    start = end - timedelta(days=days * 2 + 14)
    url = (f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(symbol, safe='')}/historical?assetclass={assetclass}"
           f"&fromdate={start:%Y-%m-%d}&todate={end:%Y-%m-%d}&limit=9999")
    req = urllib.request.Request(url, headers={
        "User-Agent": _p._UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/",
    })
    with urllib.request.urlopen(req, timeout=_p._TIMEOUT) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    data = json.loads(body)
    series = _p.parse_nasdaq(data, key, days)
    if series is not None:
        series.currency = "USD"
    elif not _LOGGED.get(f"nasdaq:{assetclass}"):
        _LOGGED[f"nasdaq:{assetclass}"] = True
        d = data.get("data") if isinstance(data, dict) else None
        print(f"[macro] nasdaq/{assetclass} {symbol} 파싱 실패 진단: status={json.dumps(data.get('status') if isinstance(data, dict) else None, ensure_ascii=False)[:160]} "
              f"data.keys={sorted(d.keys()) if isinstance(d, dict) else type(d).__name__}")
    return series


# ── FRED CSV ─────────────────────────────────────────────────
def from_fred(series_id: str, key: str, days: int) -> Optional[PriceSeries]:
    body = _p._get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={urllib.parse.quote(series_id)}")
    return parse_fred(body, key, days)


def parse_fred(body: str, key: str, days: int) -> Optional[PriceSeries]:
    """'observation_date,DGS10\\n2026-09-08,4.31\\n…' (결측은 '.')"""
    rows = list(csv.reader(io.StringIO(body.strip())))
    if len(rows) < 2:
        return None
    points: list[PricePoint] = []
    for row in rows[1:]:
        if len(row) < 2 or len(row[0]) != 10:
            continue
        v = _p._num(row[1])
        if v is None:
            continue
        points.append(PricePoint(row[0], v, v, v, v, 0.0))
    return _p._finish(points, key, "USD", "fred", days)


# ── CoinGecko ────────────────────────────────────────────────
def from_coingecko(coin: str, key: str, days: int) -> Optional[PriceSeries]:
    url = f"https://api.coingecko.com/api/v3/coins/{urllib.parse.quote(coin)}/market_chart?vs_currency=usd&days={days + 5}&interval=daily"
    return parse_coingecko(json.loads(_p._get(url)), key, days)


def parse_coingecko(data: dict, key: str, days: int) -> Optional[PriceSeries]:
    """{"prices": [[ts_ms, price], …]} — 하루 1점(UTC 00:00), 마지막은 현재가."""
    by_date: dict[str, float] = {}
    for item in (data or {}).get("prices") or []:
        try:
            ts, price = item[0], float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        by_date[d] = price  # 같은 날짜면 마지막 값
    points = [PricePoint(d, v, v, v, v, 0.0) for d, v in sorted(by_date.items())]
    return _p._finish(points, key, "USD", "coingecko", days)


# ── 네이버 시장지표 (형식 미확인 → 방어적 파싱) ───────────────
def from_naver_index(path: str, key: str, days: int) -> Optional[PriceSeries]:
    url = f"https://api.stock.naver.com/marketindex/{path}/prices?page=1&pageSize={min(max(days, 20), 60)}"
    body = _p._get(url, referer="https://m.stock.naver.com/")
    return parse_generic_rows(body, key, days, "naver", currency="KRW" if "KRW" in path else "USD")


def parse_generic_rows(text: str, key: str, days: int, source: str, currency: str = "USD") -> Optional[PriceSeries]:
    text = (text or "").strip()
    if not text.startswith("["):
        return None
    rows = json.loads(text)
    points: list[PricePoint] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = next((str(r[k])[:10] for k in ("localTradedAt", "localDate", "tradeDate", "date") if r.get(k)), "")
        c = next((_p._num(r[k]) for k in ("closePrice", "close", "price", "currentPrice", "value") if r.get(k) is not None), None)
        if len(d) != 10 or c is None:
            continue
        o = next((_p._num(r[k]) for k in ("openPrice", "open") if r.get(k) is not None), None)
        h = next((_p._num(r[k]) for k in ("highPrice", "high") if r.get(k) is not None), None)
        l = next((_p._num(r[k]) for k in ("lowPrice", "low") if r.get(k) is not None), None)
        if None in (o, h, l):
            o = h = l = c
        points.append(PricePoint(d.replace(".", "-"), o, h, l, c, _p._volume_of(r)))
    if not points and rows and isinstance(rows[0], dict) and not _LOGGED.get(source):
        _LOGGED[source] = True
        print(f"[macro] {source} 응답 키(파싱 실패 진단용): {sorted(rows[0].keys())}")
    return _p._finish(points, key, currency, source, days)


# ── investing.com (고정 pair id) ─────────────────────────────
def from_investing_pair(pair: int, key: str, days: int, today: Optional[date] = None) -> Optional[PriceSeries]:
    end = today or datetime.now(ZoneInfo("America/New_York")).date()
    start = end - timedelta(days=days * 2 + 14)
    url = (f"https://api.investing.com/api/financialdata/historical/{int(pair)}?start-date={start:%Y-%m-%d}&end-date={end:%Y-%m-%d}"
           f"&time-frame=Daily&add-missing-rows=false")
    return _p.parse_investing(_p._get_json(url, _p._INV_HEADERS), key, days)


# ── 미 재무부 일별 수익률 곡선 CSV ───────────────────────────
_TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                 "{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")


def from_treasury(column: str, key: str, days: int, today: Optional[date] = None) -> Optional[PriceSeries]:
    year = (today or datetime.now(ZoneInfo("America/New_York")).date()).year
    body = _p._get(_TREASURY_URL.format(year=year))
    if len(_treasury_rows(body)) < days + 5:  # 연초에는 전년도 파일도 합친다
        try:
            body = _p._get(_TREASURY_URL.format(year=year - 1)) + "\n" + body
        except _p._NET_ERRORS:
            pass
    return parse_treasury(body, column, key, days)


def _treasury_rows(body: str) -> list[dict]:
    rows: list[dict] = []
    for chunk in body.replace("\r", "").split("\nDate,"):
        text = chunk if chunk.startswith("Date,") else "Date," + chunk
        rows.extend(r for r in csv.DictReader(io.StringIO(text.strip())) if r.get("Date"))
    return rows


def parse_treasury(body: str, column: str, key: str, days: int) -> Optional[PriceSeries]:
    """'Date,"1 Mo",…,"2 Yr",…,"10 Yr",…\n09/08/2026,4.20,…' → column 열의 수익률(종가만)."""
    points: list[PricePoint] = []
    for r in _treasury_rows(body or ""):
        try:
            m, d_, y = str(r.get("Date", "")).split("/")
            d = f"{int(y):04d}-{int(m):02d}-{int(d_):02d}"
        except ValueError:
            continue
        v = _p._num(r.get(column))
        if v is None:
            continue
        points.append(PricePoint(d, v, v, v, v, 0.0))
    return _p._finish(points, key, "USD", "treasury", days)


# ── Stooq 선물 (gc.f, cl.f, dx.f …) ──────────────────────────
def from_stooq_symbol(symbol: str, key: str, days: int) -> Optional[PriceSeries]:
    body = _p._get(f"https://stooq.com/q/d/l/?s={symbol.lower()}&i=d")
    return _p.parse_stooq(body, key, days, currency="USD")


# ── 지수 (네이버 세계지수 · Nasdaq index · 네이버 국내지수) ────────
def from_naver_index(code: str, key: str, days: int) -> Optional[PriceSeries]:
    url = f"https://api.stock.naver.com/index/{urllib.parse.quote(code)}/price?pageSize={min(max(days, 20), 60)}&page=1"
    try:
        body = _p._get(url, referer="https://m.stock.naver.com/")
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 600 and exc.code != 429:
            return None  # 409 등: 네이버에 없는 지수 코드 → 다음 소스
        raise
    return _p.parse_naver_world(body, key, days)


def from_naver_sise(code: str, key: str, days: int) -> Optional[PriceSeries]:
    series = _p.from_naver(code, days)
    if series is not None:
        series.ticker = key
        series.currency = "KRW"
    return series


def from_nasdaq_proxy(symbol: str, key: str, days: int) -> Optional[PriceSeries]:
    series = _p.from_nasdaq(symbol, days)
    if series is not None:
        series.ticker = key
        series.source = f"proxy:{symbol}"
    return series


# ── 진입점 ───────────────────────────────────────────────────
def get_series(inst: MacroInstrument, days: int = 45, *, cache_dir: Optional[Path] = None, allow_synthetic: bool = True,
               key: Optional[str] = None) -> Optional[PriceSeries]:
    key = key or f"MACRO_{inst.id}"
    for kind, symbol in inst.sources:
        try:
            if kind == "nasdaq_commodity":
                series = from_nasdaq_asset(symbol, key, days, "commodities")
            elif kind == "nasdaq_crypto":
                series = from_nasdaq_asset(symbol, key, days, "cryptocurrency")
            elif kind == "fred":
                series = from_fred(symbol, key, days)
            elif kind == "coingecko":
                series = from_coingecko(symbol, key, days)
            elif kind == "naver_index":
                series = from_naver_index(symbol, key, days)
            elif kind == "investing_pair":
                series = from_investing_pair(int(symbol), key, days)
            elif kind == "treasury":
                series = from_treasury(symbol, key, days)
            elif kind == "stooq":
                series = from_stooq_symbol(symbol, key, days)
            elif kind == "naver_index":
                series = from_naver_index(symbol, key, days)
            elif kind == "nasdaq_index":
                series = from_nasdaq_asset(symbol, key, days, "index")
            elif kind == "naver_sise":
                series = from_naver_sise(symbol, key, days)
            elif kind == "nasdaq_proxy":
                series = from_nasdaq_proxy(symbol, key, days)
            else:
                continue
        except _p._NET_ERRORS as exc:
            print(f"[macro] {inst.id}/{kind}: {exc!r}")
            continue
        if series is None:
            print(f"[macro] {inst.id}/{kind}: 응답에 시세 없음 → 다음 소스")
            continue
        if series is not None:
            series.currency = "KRW" if inst.unit == "KRW" else series.currency
            print(f"[macro] {inst.id} ← {series.source} ({series.as_of}, {len(series.points)}점)")
            if cache_dir is not None:
                _p.save_cache(cache_dir, series)
            return series
    if cache_dir is not None:
        cached = _p.load_cache(cache_dir, key)
        if cached is not None:
            return cached
    if not allow_synthetic:
        return None
    s = _p.synthetic(key, "US", days)
    s.currency = "KRW" if inst.unit == "KRW" else "USD"
    return s
