"""일일 브리핑 파이프라인 오케스트레이션.

수집(ingest) → 요약/구조화(summarize) → 시세·차트(prices) → 렌더(render).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from . import ingest, prices, render, summarize
from .config import Config
from .models import Brief
from .stock_master import StockMaster


def now_kst(cfg: Config) -> datetime:
    return datetime.now(ZoneInfo(cfg.timezone))


def today_kst(cfg: Config) -> str:
    return now_kst(cfg).strftime("%Y-%m-%d")


def build_brief(cfg: Config, raw: str, date_str: str, *, msg_count: int = 1, fetch_method: str = "fixture",
                message_ids: Optional[list[int]] = None, posted_at: str = "", master: Optional[StockMaster] = None) -> Brief:
    """원문 텍스트 → 요약·시세가 채워진 Brief (렌더 직전 상태)."""
    master = master or StockMaster.load()
    print(f"[2/4] 요약: {'Claude (' + cfg.model + ')' if cfg.has_claude else '규칙 기반'}")
    summary = summarize.summarize(raw, cfg, master)

    print(f"[3/4] 시세·차트: {len(summary.stocks)}개 종목")
    sources: Counter[str] = Counter()
    for m in summary.stocks:
        if not m.ticker:
            continue
        m.prices = prices.get_prices(m.ticker, m.market, days=cfg.price_days, allow_synthetic=not cfg.production)
        if m.prices is None:
            continue
        sources[m.prices.source] += 1
        if m.change_pct is None and m.prices.change_pct is not None and m.direction == "FLAT":
            pct = m.prices.change_pct
            m.direction = "UP" if pct > 0 else "DOWN" if pct < 0 else "FLAT"

    real = [s for s in sources if s != "synthetic"]
    price_source = max(real, key=lambda s: sources[s]) if real else ("synthetic" if sources else "none")

    return Brief(
        date=date_str, source_channel=cfg.channel, status="published", posted_at=posted_at,
        generated_at=now_kst(cfg).isoformat(timespec="seconds"),
        market_overview=summary.overview, kr_outlook=summary.kr_outlook, indices=summary.indices, stocks=summary.stocks,
        raw_text=raw, message_count=msg_count, message_ids=message_ids or [], fetch_method=fetch_method,
        summarizer=summary.summarizer, model=summary.model, prompt_version=summary.prompt_version,
        price_source=price_source, unmapped=summary.unmapped, evidence_failures=summary.evidence_failures,
    )


def run(cfg: Config, date_str: Optional[str] = None, use_fixtures: bool = False) -> Path:
    date_str = date_str or today_kst(cfg)
    master = StockMaster.load()

    print(f"[1/4] 수집: {cfg.channel} · {date_str}")
    raw, msg_count = ingest.fetch_briefing(cfg, date_str, use_fixtures=use_fixtures)
    print(f"       메시지 {msg_count}건 종합")
    fetch_method = "fixture" if (use_fixtures or not cfg.has_telegram) else "session"

    brief = build_brief(cfg, raw, date_str, msg_count=msg_count, fetch_method=fetch_method, master=master)

    print(f"[4/4] 렌더: {cfg.output_dir}")
    return render.render_site(brief, cfg.output_dir, base_url=cfg.base_url, logo_svg=cfg.logo_svg())
