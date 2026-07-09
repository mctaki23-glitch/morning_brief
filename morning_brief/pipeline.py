"""일일 브리핑 파이프라인 오케스트레이션.

수집(ingest) → 요약/구조화(summarize) → 시세·차트(prices) → 렌더(render).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from . import ingest, prices, render, summarize
from .config import Config
from .models import Brief
from .stock_master import StockMaster


def today_kst(cfg: Config) -> str:
    return datetime.now(ZoneInfo(cfg.timezone)).strftime("%Y-%m-%d")


def run(
    cfg: Config,
    date_str: Optional[str] = None,
    use_fixtures: bool = False,
) -> Path:
    date_str = date_str or today_kst(cfg)
    master = StockMaster.load()

    print(f"[1/4] 수집: {cfg.channel} · {date_str}")
    raw, msg_count = ingest.fetch_briefing(cfg, date_str, use_fixtures=use_fixtures)
    print(f"       메시지 {msg_count}건 종합")

    print(f"[2/4] 요약: {'Claude' if cfg.has_claude else '규칙 기반'}")
    summary = summarize.summarize(raw, cfg, master)

    print(f"[3/4] 시세·차트: {len(summary.stocks)}개 종목")
    price_sources: set[str] = set()
    for m in summary.stocks:
        if not m.ticker:
            continue
        m.prices = prices.get_prices(m.ticker, m.market, days=cfg.chart_days)
        price_sources.add(m.prices.source)
        # 텍스트에 등락률이 없으면 시세 기준으로 방향 보정
        if m.change_pct is None and m.prices.change_pct is not None:
            if m.direction == "FLAT":
                pct = m.prices.change_pct
                m.direction = "UP" if pct > 0 else "DOWN" if pct < 0 else "FLAT"

    price_source = "stooq" if "stooq" in price_sources else "synthetic"

    brief = Brief(
        date=date_str,
        source_channel=cfg.channel,
        market_overview=summary.overview,
        indices=summary.indices,
        stocks=summary.stocks,
        raw_text=raw,
        generated_at=datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
        summarizer=summary.summarizer,
        price_source=price_source,
        message_count=msg_count,
    )

    print(f"[4/4] 렌더: {cfg.output_dir}")
    index_path = render.render_site(brief, cfg.output_dir)
    return index_path
