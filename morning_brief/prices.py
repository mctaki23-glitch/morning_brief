"""시세 데이터 조회.

기본 소스: Stooq CSV (무료, 키 불필요, urllib만 사용) — 미국 종목 위주.
실패 시(네트워크/미지원): 티커 기반 결정적(seed 고정) 합성 시계열로 폴백하여
차트가 항상 렌더링되도록 한다. urllib은 HTTPS_PROXY 환경변수를 자동 사용한다.
"""

from __future__ import annotations

import csv
import io
import random
import urllib.error
import urllib.request

from .models import PricePoint, PriceSeries

_TIMEOUT = 12


def get_prices(ticker: str, market: str = "US", days: int = 20) -> PriceSeries:
    if market == "US":
        series = _from_stooq(ticker, days)
        if series is not None:
            return series
    else:
        # KR 종목은 Stooq 무료 CSV 커버리지가 제한적이므로 우선 합성.
        series = _from_stooq(ticker, days, suffix=".kr")
        if series is not None:
            return series
    return _synthetic(ticker, market, days)


def _from_stooq(ticker: str, days: int, suffix: str = ".us") -> PriceSeries | None:
    symbol = ticker.lower() + suffix
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "morning-brief/0.1"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None

    if not body or body.startswith("<") or "Date" not in body[:64]:
        return None

    points: list[PricePoint] = []
    reader = csv.DictReader(io.StringIO(body))
    for row in reader:
        try:
            points.append(
                PricePoint(
                    date=row["Date"],
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row.get("Volume") or 0) or 0.0,
                )
            )
        except (KeyError, ValueError):
            continue

    if len(points) < 2:
        return None

    points = points[-days:]
    currency = "USD" if suffix == ".us" else "KRW"
    return PriceSeries(ticker=ticker, points=points, currency=currency, source="stooq")


def _synthetic(ticker: str, market: str, days: int) -> PriceSeries:
    """티커로 시드를 고정한 결정적 랜덤워크. 실제 시세가 아님(데모/폴백용)."""
    seed = sum(ord(c) for c in ticker)
    rng = random.Random(seed)
    base = 50 + (seed % 400)  # 종목별로 다른 시작 가격
    price = float(base)
    points: list[PricePoint] = []
    # 간단한 영업일 인덱스 (YYYY-MM-DD 대신 상대 라벨)
    for i in range(days):
        drift = rng.uniform(-0.025, 0.028)
        price = max(1.0, price * (1 + drift))
        high = price * (1 + abs(rng.uniform(0, 0.012)))
        low = price * (1 - abs(rng.uniform(0, 0.012)))
        open_ = low + (high - low) * rng.random()
        points.append(
            PricePoint(
                date=f"D-{days - i - 1}",
                open=round(open_, 2),
                high=round(high, 2),
                low=round(low, 2),
                close=round(price, 2),
                volume=round(rng.uniform(1e6, 5e7)),
            )
        )
    currency = "USD" if market == "US" else "KRW"
    return PriceSeries(ticker=ticker, points=points, currency=currency, source="synthetic")
