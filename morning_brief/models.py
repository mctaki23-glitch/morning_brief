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
    source: str = "synthetic"  # stooq | yahoo | naver | cache | synthetic
    as_of: str = ""  # 마지막 봉 일자 (YYYY-MM-DD)

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

    @property
    def is_real(self) -> bool:
        """실제 시세 여부 (합성 데이터는 데모·테스트 전용)."""
        return self.source != "synthetic"


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
    change_pct: Optional[float] = None  # 브리핑 본문에 명시된 등락률 (시세 계산값보다 우선)
    reason_summary: str = ""  # 등락 이유 요약 (1~3줄)
    evidence: str = ""  # 원문 근거 발췌
    evidence_verified: bool = True  # 근거 발췌가 원문에 실제로 존재하는지 검증 결과
    message_id: Optional[int] = None  # 근거가 포함된 텔레그램 메시지 ID (원문 링크용)
    order: int = 0  # 본문 등장 순서 (언급순 정렬용)
    kind: str = "stock"  # stock | macro (금리 · 유가 · 금 · 환율 등)
    unit: str = ""  # macro 표시 단위 (%, KRW, USD/bbl, USD/oz …)
    prices: Optional[PriceSeries] = None
    slug: str = ""

    def price_change_pct(self) -> Optional[float]:
        """표시에 쓸 등락률: 본문 명시 값이 우선, 없으면 시세 기준."""
        if self.change_pct is not None:
            return self.change_pct
        if self.prices is not None:
            return self.prices.change_pct
        return None


@dataclass
class Brief:
    date: str  # YYYY-MM-DD (KST 기준)
    source_channel: str = "ehdwl"
    status: str = "published"  # published | waiting | no_briefing
    posted_at: str = ""  # 첫 메시지 게시 시각 (ISO8601, KST). 알 수 없으면 빈 문자열
    generated_at: str = ""  # ISO8601
    market_overview: str = ""
    kr_outlook: str = ""  # 한국 증시 관전 포인트
    indices: list[IndexSnapshot] = field(default_factory=list)
    stocks: list[StockMention] = field(default_factory=list)
    macros: list[StockMention] = field(default_factory=list)  # 매크로 자산 서머리 (kind="macro")
    raw_text: str = ""
    message_count: int = 1  # 그날 종합한 텔레그램 메시지 수
    message_ids: list[int] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)  # [{id, posted_at(KST ISO), text}] 당일 채널 전문
    fetch_method: str = "fixture"  # fixture | preview | session
    summarizer: str = "rule-based"  # rule-based | claude
    model: str = ""  # 요약에 사용한 모델 ID
    prompt_version: str = ""
    price_source: str = "synthetic"  # 대표 시세 소스 (stooq | yahoo | naver | cache | synthetic | none)
    unmapped: list[str] = field(default_factory=list)  # 티커 미매핑 종목명
    evidence_failures: list[str] = field(default_factory=list)  # 근거 검증 실패 종목명

    @property
    def message_url(self) -> str:
        """원문(첫 메시지) 텔레그램 링크. 메시지 ID를 모르면 채널 링크."""
        if self.message_ids:
            return f"https://t.me/{self.source_channel}/{self.message_ids[0]}"
        return f"https://t.me/{self.source_channel}"
