"""일일 브리핑 파이프라인 오케스트레이션.

수집(ingest) → 요약/구조화(summarize) → 시세·차트(prices) → 아카이브 저장 → 렌더(render) → 상태 기록.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from . import archive, ingest, macro, macro_prices, prices, render, summarize
from .config import Config
from .ingest import Fetched
from .models import Brief
from .stock_master import StockMaster


def now_kst(cfg: Config) -> datetime:
    return datetime.now(ZoneInfo(cfg.timezone))


def today_kst(cfg: Config) -> str:
    return now_kst(cfg).strftime("%Y-%m-%d")


def build_brief(cfg: Config, raw: str, date_str: str, *, msg_count: int = 1, fetch_method: str = "fixture",
                message_ids: Optional[list[int]] = None, posted_at: str = "", master: Optional[StockMaster] = None,
                cache_dir: Optional[Path] = None, messages: Optional[list[dict]] = None) -> Brief:
    """원문 텍스트 → 요약·시세가 채워진 Brief (렌더 직전 상태)."""
    master = master or StockMaster.load()
    print(f"[2/4] 요약: {'Claude (' + cfg.model + ')' if cfg.has_claude else '규칙 기반'}")
    summary = summarize.summarize(raw, cfg, master)

    print(f"[3/4] 시세·차트: {len(summary.stocks)}개 종목")
    sources: Counter[str] = Counter()
    for m in summary.stocks:
        if not m.ticker:
            continue
        entry = master.resolve(m.ticker)
        m.prices = prices.get_prices(m.ticker, m.market, days=cfg.price_days, allow_synthetic=not cfg.production,
                                     cache_dir=cache_dir, exchange=entry.exchange if entry else None)
        if m.prices is None:
            continue
        sources[m.prices.source] += 1
        if m.change_pct is None and m.prices.change_pct is not None and m.direction == "FLAT":
            pct = m.prices.change_pct
            m.direction = "UP" if pct > 0 else "DOWN" if pct < 0 else "FLAT"

    real = [s for s in sources if s != "synthetic"]
    price_source = max(real, key=lambda s: sources[s]) if real else ("synthetic" if sources else "none")

    instruments = macro.load_instruments()
    macros = macro.extract_macros(raw, instruments)
    print(f"       매크로 자산: {len(macros)}개 ({', '.join(m.name for m in macros)})")
    by_id = macro.by_id(instruments)
    for mm in macros:
        inst = by_id.get(mm.ticker or "")
        if inst is None:
            continue
        mm.prices = macro_prices.get_series(inst, days=cfg.price_days, cache_dir=cache_dir, allow_synthetic=not cfg.production)
        if mm.prices is not None and mm.prices.change_pct is not None and mm.direction == "FLAT":
            mm.direction = "UP" if mm.prices.change_pct > 0 else "DOWN" if mm.prices.change_pct < 0 else "FLAT"

    return Brief(
        date=date_str, source_channel=cfg.channel, status="published", posted_at=posted_at,
        generated_at=now_kst(cfg).isoformat(timespec="seconds"),
        market_overview=summary.overview, kr_outlook=summary.kr_outlook, indices=summary.indices, stocks=summary.stocks, macros=macros,
        raw_text=raw, message_count=msg_count, message_ids=message_ids or [], messages=messages or [], fetch_method=fetch_method,
        summarizer=summary.summarizer, model=summary.model, prompt_version=summary.prompt_version,
        price_source=price_source, unmapped=summary.unmapped, evidence_failures=summary.evidence_failures,
    )


def write_status(cfg: Config, **fields) -> Path:
    out = Path(cfg.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {"last_run_at": now_kst(cfg).isoformat(timespec="seconds"), **fields}
    path = out / "status.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def publish_status(cfg: Config, date_str: str, status: str, fetched: Optional[Fetched] = None, *, today: Optional[str] = None) -> Path:
    """브리핑이 없을 때: 아카이브 기반 사이트 재생성 + 루트에 상태 페이지 게시. today 는 기준 일자(KST, 기본 오늘)."""
    out = Path(cfg.output_dir)
    rebuild_site(cfg)
    dates = archive.list_dates(cfg.archive_dir)
    latest = dates[-1] if dates else (render.collect_archive(out)[0]["date"] if render.collect_archive(out) else None)
    if date_str < (today or today_kst(cfg)):
        # 과거 일자 재생성에서 브리핑을 못 찾은 경우: 루트는 최신 브리핑 리다이렉트를 유지한다(대기 페이지로 덮지 않음)
        print(f"       과거 일자({date_str}) 브리핑 없음 → 루트 페이지는 최신 브리핑({latest}) 유지")
        root_html = None
    else:
        root_html = render.render_status(date_str, status, latest=latest, checked_at=now_kst(cfg).isoformat(timespec="seconds"),
                                         logo_svg=cfg.logo_svg())
    render.write_shared_pages(out, logo_svg=cfg.logo_svg(), root_html=root_html)
    write_status(cfg, result=status, brief_date=date_str, message_count=0, latest=latest,
                 warnings=(fetched.errors if fetched else []))
    return out / "index.html"


def rebuild_site(cfg: Config) -> int:
    """아카이브의 모든 날짜를 사이트로 재생성한다(과거 브리핑 보존). 생성한 날짜 수를 돌려준다."""
    n = 0
    for date_str in archive.list_dates(cfg.archive_dir):
        brief = archive.load(cfg.archive_dir, date_str)
        if brief is None:
            continue
        render.render_site(brief, cfg.output_dir, base_url=cfg.base_url, logo_svg=cfg.logo_svg())
        n += 1
    return n


def run(cfg: Config, date_str: Optional[str] = None, use_fixtures: bool = False) -> Path:
    date_str = date_str or today_kst(cfg)
    print(f"[1/4] 수집: {cfg.channel} · {date_str} ({'샘플' if use_fixtures else '공개 미리보기 → 세션'})")
    fetched = ingest.fetch_day(cfg, date_str, use_fixtures=use_fixtures)
    if not fetched.ok:
        archived = archive.load(cfg.archive_dir, date_str)
        if archived is not None:
            # 이미 생성된 날짜의 재실행에서 수집이 실패하면 아카이브로 사이트만 다시 만든다(대기 페이지로 덮지 않음)
            print(f"       수집 실패({', '.join(fetched.errors) or '메시지 없음'}) → 아카이브({date_str})로 사이트 재생성")
            rebuild_site(cfg)
            write_status(cfg, result="published", brief_date=date_str, posted_at=archived.posted_at, message_count=archived.message_count,
                         stock_count=len(archived.stocks), source="archive", warnings=fetched.errors)
            return Path(cfg.output_dir) / "index.html"
        print("       브리핑이 없습니다 → 상태 페이지 게시")
        return publish_status(cfg, date_str, "waiting", fetched)
    print(f"       메시지 {fetched.count}건 종합 ({fetched.method})")
    return run_fetched(cfg, date_str, fetched)


def run_fetched(cfg: Config, date_str: str, fetched: Fetched) -> Path:
    """수집 결과 → 요약 · 시세 · 아카이브 · 렌더 · 상태 기록."""
    master = StockMaster.load()
    cache_dir = archive.date_dir(cfg.archive_dir, date_str) / "prices" if fetched.method != "fixture" else None
    tz = ZoneInfo(cfg.timezone)
    messages = [{"id": m.id, "posted_at": m.posted_at.astimezone(tz).isoformat(timespec="seconds"), "text": m.text} for m in fetched.messages]
    brief = build_brief(cfg, fetched.text, date_str, msg_count=fetched.count, fetch_method=fetched.method,
                        message_ids=fetched.ids, posted_at=fetched.posted_at_iso(cfg.timezone), master=master, cache_dir=cache_dir,
                        messages=messages)

    if fetched.method != "fixture":
        archive.save(cfg.archive_dir, brief)  # 소스 오브 트루스 (샘플 데이터는 저장하지 않음)
        rebuild_site(cfg)  # 과거 날짜 포함 재생성

    print(f"[4/4] 렌더: {cfg.output_dir}")
    index = render.render_site(brief, cfg.output_dir, base_url=cfg.base_url, logo_svg=cfg.logo_svg())
    write_status(cfg, result="published", brief_date=date_str, posted_at=brief.posted_at, message_count=brief.message_count,
                 stock_count=len(brief.stocks), summarizer=brief.summarizer, model=brief.model, price_source=brief.price_source,
                 fetch_method=brief.fetch_method, unmapped=brief.unmapped, evidence_failures=brief.evidence_failures,
                 warnings=fetched.errors)
    return index
