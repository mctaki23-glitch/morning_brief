"""아카이브 = 소스 오브 트루스. archive/<date>/{raw.txt, meta.json, brief.json, prices/*.json} + archive/index.json

GitHub Pages 배포는 덮어쓰기이므로 과거 브리핑은 리포지토리에 커밋된 아카이브에서 매 실행마다 재생성한다.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from .models import Brief, IndexSnapshot, PricePoint, PriceSeries, StockMention


def date_dir(archive_dir: str | Path, date_str: str) -> Path:
    return Path(archive_dir) / date_str


def save(archive_dir: str | Path, brief: Brief, *, fetched_at: Optional[str] = None) -> Path:
    d = date_dir(archive_dir, brief.date)
    d.mkdir(parents=True, exist_ok=True)
    (d / "raw.txt").write_text(brief.raw_text or "", encoding="utf-8")
    meta = {
        "channel": brief.source_channel, "date": brief.date, "message_ids": brief.message_ids, "message_count": brief.message_count,
        "posted_at": brief.posted_at, "fetch_method": brief.fetch_method,
        "fetched_at": fetched_at or datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
    }
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    data = asdict(brief)
    data.pop("raw_text", None)  # 원문은 raw.txt 에
    (d / "brief.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    update_index(archive_dir)
    return d


def list_dates(archive_dir: str | Path) -> list[str]:
    root = Path(archive_dir)
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "brief.json").exists())


def load(archive_dir: str | Path, date_str: str) -> Optional[Brief]:
    d = date_dir(archive_dir, date_str)
    path = d / "brief.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    brief = brief_from_dict(data)
    raw = d / "raw.txt"
    if raw.exists():
        brief.raw_text = raw.read_text(encoding="utf-8")
    return brief


def _mentions_from(items: list[dict]) -> list[StockMention]:
    out = []
    for s in items:
        s = dict(s)
        prices = s.pop("prices", None)
        series = None
        if prices:
            series = PriceSeries(ticker=prices.get("ticker", s.get("ticker") or ""), currency=prices.get("currency", "USD"),
                                 source=prices.get("source", "cache"), as_of=prices.get("as_of", ""),
                                 points=[PricePoint(**p) for p in prices.get("points", [])])
        out.append(StockMention(**{k: v for k, v in s.items() if k in StockMention.__dataclass_fields__}, prices=series))
    return out


def brief_from_dict(data: dict) -> Brief:
    stocks = _mentions_from(data.get("stocks", []))
    macros = _mentions_from(data.get("macros", []))
    indices = [IndexSnapshot(**{k: v for k, v in i.items() if k in IndexSnapshot.__dataclass_fields__}) for i in data.get("indices", [])]
    fields = {k: v for k, v in data.items() if k in Brief.__dataclass_fields__ and k not in ("stocks", "macros", "indices")}
    return Brief(**fields, stocks=stocks, macros=macros, indices=indices)


def update_index(archive_dir: str | Path) -> list[dict]:
    """archive/index.json — 날짜별 요약 목록(최신순). 아카이브 페이지·검색용."""
    entries = []
    for date_str in reversed(list_dates(archive_dir)):
        try:
            data = json.loads((date_dir(archive_dir, date_str) / "brief.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        stocks = sorted(data.get("stocks", []), key=lambda s: s.get("order", 0))
        entries.append({
            "date": data.get("date", date_str), "status": data.get("status", "published"),
            "overview": (data.get("market_overview") or "")[:120], "stock_count": len(stocks),
            "names": [s.get("name", "") for s in stocks[:4]], "posted_at": data.get("posted_at", ""), "generated_at": data.get("generated_at", ""),
        })
    Path(archive_dir).mkdir(parents=True, exist_ok=True)
    (Path(archive_dir) / "index.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return entries
