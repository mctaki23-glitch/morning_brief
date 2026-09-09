"""시세 데이터 조회 — 소스 어댑터 + 아카이브 캐시 + 전일 폴백 (PRD D4 확정: 무료 비공식 조합).

미국: Stooq CSV → Yahoo Finance chart API
한국: 네이버 금융 siseJson → Yahoo Finance(.KS/.KQ)

모든 어댑터는 urllib 만 사용한다(HTTPS_PROXY 환경변수 자동 인식). 성공 시 archive/<date>/prices/<ticker>.json 에
저장하고, 전부 실패하면 최근 아카이브 캐시(source="cache")를 쓴다. 합성 데이터는 개발·테스트 전용이며
운영 모드(allow_synthetic=False)에서는 None 을 돌려 차트 없이 텍스트만 노출한다.
"""

from __future__ import annotations

import csv
import io
import json
import random
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
    return [lambda: from_stooq(ticker, days), lambda: from_yahoo(ticker, ticker, days, "USD")]


def get_prices(ticker: str, market: str = "US", days: int = 45, *, allow_synthetic: bool = True,
               cache_dir: Optional[Path] = None, exchange: Optional[str] = None) -> Optional[PriceSeries]:
    for fetch in adapters_for(ticker, market, days, exchange):
        try:
            series = fetch()
        except _NET_ERRORS as exc:
            print(f"[prices] {ticker}: {exc!r}")
            continue
        if series is not None:
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
