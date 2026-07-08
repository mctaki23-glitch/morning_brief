"""브리핑 파이프라인의 데이터 모델 (표준 라이브러리만 사용)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PricePoint:
    date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class PriceSeries:
    ticker: str
    points: list[PricePoint] = field(default_factory=list)
    currency: str = "USD"
    source: str = "synthetic"  # stooq | synthetic

    @property
    def closes(self) -> list[float]:
        return [p.close for p in self.points]

    @property
    def dates(self) -> list[str]:
        return [p.date for p in self.points]

    @property
    def last_close(self) -> Optional[float]:
        return self.points[-1].close if self.points else None

    @property
    def prev_close(self) -> Optional[float]:
        return self.points[-2].close if len(self.points) >= 2 else None

    @property
    def change(self) -> Optional[float]:
        if self.last_close is None or self.prev_close is None:
            return None
        return self.last_close - self.prev_close

    @property
    def change_pct(self) -> Optional[float]:
        if self.change is None or not self.prev_close:
            return None
        return self.change / self.prev_close * 100.0


@dataclass
class IndexSnapshot:
    name: str
    value: Optional[float] = None
    change_pct: Optional[float] = None


@dataclass
class StockMention:
    name: str
    ticker: Optional[str] = None
    market: str = "US"  # US | KR
    direction: str = "FLAT"  # UP | DOWN | FLAT
    change_pct: Optional[float] = None  # 브리핑/시세에서 파악된 등락률
    reason_summary: str = ""  # 등락 이유 요약 (1~3줄)
    reason_context: str = ""  # 원문 근거 발췌
    prices: Optional[PriceSeries] = None
    slug: str = ""

    def price_change_pct(self) -> Optional[float]:
        """표시에 쓸 등락률: 텍스트에서 파악된 값이 우선, 없으면 시세 기준."""
        if self.change_pct is not None:
            return self.change_pct
        if self.prices is not None:
            return self.prices.change_pct
        return None


@dataclass
class Brief:
    date: str  # YYYY-MM-DD (KST 기준)
    source_channel: str = "ehdwl"
    market_overview: str = ""
    indices: list[IndexSnapshot] = field(default_factory=list)
    stocks: list[StockMention] = field(default_factory=list)
    raw_text: str = ""
    generated_at: str = ""  # ISO8601
    summarizer: str = "rule-based"  # rule-based | claude
    price_source: str = "synthetic"
