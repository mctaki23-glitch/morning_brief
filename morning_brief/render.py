"""구조화된 Brief → 정적 HTML 사이트 생성 (인라인 CSS/SVG, 외부 의존성 없음).

산출물 구조:
  <out>/index.html                          아카이브 + 최신 브리핑 링크
  <out>/brief/<date>/index.html             시황 정리 페이지
  <out>/brief/<date>/stock/<slug>.html      종목별 서머리 (등락 이유 + 차트)
  <out>/brief/<date>/data.json              구조화 데이터(프로그램 접근용)
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from . import chart
from .models import Brief, StockMention

_CSS = """
:root {
  --bg: #ffffff; --fg: #111418; --muted: #6b7280; --card: #f6f7f9;
  --border: #e5e7eb; --accent: #c2410c; --up: #16a34a; --down: #dc2626;
  --radius: 14px;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #0d1117; --fg: #e6edf3; --muted: #9aa4b2; --card: #161b22;
          --border: #262c36; --accent: #f97316; --up: #3fb950; --down: #f85149; }
}
:root[data-theme="light"] { --bg:#ffffff; --fg:#111418; --muted:#6b7280; --card:#f6f7f9;
  --border:#e5e7eb; --accent:#c2410c; --up:#16a34a; --down:#dc2626; }
:root[data-theme="dark"] { --bg:#0d1117; --fg:#e6edf3; --muted:#9aa4b2; --card:#161b22;
  --border:#262c36; --accent:#f97316; --up:#3fb950; --down:#f85149; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", Roboto, sans-serif;
  line-height: 1.55; -webkit-font-smoothing: antialiased; }
.wrap { max-width: 860px; margin: 0 auto; padding: 20px 16px 64px; }
a { color: inherit; }
header.top { display: flex; align-items: baseline; justify-content: space-between;
  gap: 12px; flex-wrap: wrap; border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 20px; }
header.top .brand { font-weight: 700; font-size: 18px; letter-spacing: -0.02em; }
header.top .date { color: var(--muted); font-size: 14px; }
.channel { color: var(--muted); font-size: 13px; }
.overview { background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px 18px; margin: 0 0 20px; }
.overview h2 { margin: 0 0 8px; font-size: 14px; color: var(--muted); font-weight: 600; }
.overview p { margin: 0; font-size: 15.5px; }
.indices { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 24px; }
.idx { border: 1px solid var(--border); border-radius: 999px; padding: 6px 12px;
  font-size: 13px; background: var(--card); white-space: nowrap; }
.idx .v { font-weight: 600; margin-left: 6px; }
.section-title { font-size: 14px; color: var(--muted); font-weight: 600; margin: 0 0 12px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; }
.card { display: flex; flex-direction: column; gap: 8px; text-decoration: none;
  border: 1px solid var(--border); border-radius: var(--radius); padding: 14px; background: var(--card);
  transition: border-color .15s ease, transform .1s ease; }
.card:hover { border-color: var(--accent); transform: translateY(-1px); }
.card .row { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.card .name { font-weight: 700; font-size: 15px; letter-spacing: -0.01em; }
.card .tkr { color: var(--muted); font-size: 12px; }
.card .reason { color: var(--muted); font-size: 13px; margin: 0;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.chg { font-weight: 700; font-size: 14px; white-space: nowrap; }
.up { color: var(--up); } .down { color: var(--down); } .flat { color: var(--muted); }
.spark { margin-top: 2px; }
.back { display: inline-block; color: var(--muted); text-decoration: none; font-size: 14px; margin-bottom: 16px; }
.back:hover { color: var(--accent); }
.stock-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 4px; }
.stock-head h1 { font-size: 24px; margin: 0; letter-spacing: -0.02em; }
.stock-head .tkr { color: var(--muted); font-size: 15px; }
.price-line { font-size: 20px; font-weight: 700; margin: 4px 0 20px; }
.block { border: 1px solid var(--border); border-radius: var(--radius); padding: 16px 18px; margin-bottom: 16px; background: var(--card); }
.block h2 { font-size: 14px; color: var(--muted); font-weight: 600; margin: 0 0 10px; }
.reason-list { margin: 0; padding-left: 18px; }
.reason-list li { margin: 4px 0; }
details.src { margin-top: 10px; }
details.src summary { cursor: pointer; color: var(--accent); font-size: 13px; }
details.src p { color: var(--muted); font-size: 13px; margin: 8px 0 0; }
.chart-note { color: var(--muted); font-size: 12px; margin: 8px 0 0; }
.disclaimer { color: var(--muted); font-size: 12px; border-top: 1px solid var(--border);
  margin-top: 32px; padding-top: 12px; }
.archive-list { list-style: none; padding: 0; margin: 0; }
.archive-list li { border-bottom: 1px solid var(--border); }
.archive-list a { display: flex; justify-content: space-between; padding: 12px 4px; text-decoration: none; }
.archive-list a:hover { color: var(--accent); }
.badge { display:inline-block; font-size:11px; color:var(--muted); border:1px solid var(--border);
  border-radius:6px; padding:1px 6px; margin-left:6px; }
"""


def _page(title: str, body: str, description: str = "") -> str:
    return (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(title)}</title>"
        f"<meta name=\"description\" content=\"{html.escape(description)}\">"
        f"<style>{_CSS}</style></head><body><div class=\"wrap\">{body}</div></body></html>"
    )


def slugify(mention: StockMention) -> str:
    base = mention.ticker or mention.name
    s = re.sub(r"[^0-9A-Za-z가-힣]+", "-", base).strip("-").lower()
    return s or "stock"


def _fmt_pct(pct: Optional[float]) -> tuple[str, str]:
    """(표시문자열, css클래스) 반환. 방향 기호(▲▼) + 색상으로 색맹 대응."""
    if pct is None:
        return ("—", "flat")
    if pct > 0:
        return (f"▲{pct:.1f}%", "up")
    if pct < 0:
        return (f"▼{abs(pct):.1f}%", "down")
    return ("0.0%", "flat")


def _dir_bool(mention: StockMention) -> Optional[bool]:
    pct = mention.price_change_pct()
    if pct is not None:
        if pct > 0:
            return True
        if pct < 0:
            return False
    if mention.direction == "UP":
        return True
    if mention.direction == "DOWN":
        return False
    return None


def render_site(brief: Brief, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    date_dir = out / "brief" / brief.date
    stock_dir = date_dir / "stock"
    stock_dir.mkdir(parents=True, exist_ok=True)

    # 종목별 상세 페이지
    for m in brief.stocks:
        m.slug = slugify(m)
    # slug 충돌 방지
    _dedupe_slugs(brief.stocks)

    for m in brief.stocks:
        (stock_dir / f"{m.slug}.html").write_text(_render_stock(brief, m), encoding="utf-8")

    # 시황 정리 페이지
    date_dir.joinpath("index.html").write_text(_render_market(brief), encoding="utf-8")

    # 구조화 데이터
    date_dir.joinpath("data.json").write_text(_dump_json(brief), encoding="utf-8")

    # 루트 아카이브
    out.joinpath("index.html").write_text(_render_archive(out), encoding="utf-8")
    return date_dir / "index.html"


def _dedupe_slugs(stocks: list[StockMention]) -> None:
    seen: dict[str, int] = {}
    for m in stocks:
        if m.slug in seen:
            seen[m.slug] += 1
            m.slug = f"{m.slug}-{seen[m.slug]}"
        else:
            seen[m.slug] = 1


def _render_market(brief: Brief) -> str:
    # 등락률 기준 정렬 (절댓값 큰 순 → 이슈 강도)
    def sort_key(m: StockMention):
        pct = m.price_change_pct()
        return -(abs(pct) if pct is not None else -1)

    stocks = sorted(brief.stocks, key=sort_key)

    idx_html = ""
    if brief.indices:
        chips = []
        for i in brief.indices:
            disp, cls = _fmt_pct(i.change_pct)
            chips.append(
                f'<span class="idx">{html.escape(i.name)}<span class="v {cls}">{disp}</span></span>'
            )
        idx_html = f'<div class="indices">{"".join(chips)}</div>'

    cards = []
    for m in stocks:
        disp, cls = _fmt_pct(m.price_change_pct())
        spark = ""
        if m.prices and m.prices.closes:
            spark = f'<div class="spark">{chart.sparkline(m.prices.closes, up=_dir_bool(m))}</div>'
        tkr = f'<span class="tkr">{html.escape(m.ticker)}</span>' if m.ticker else ""
        cards.append(
            f'<a class="card" href="stock/{m.slug}.html">'
            f'<div class="row"><span class="name">{html.escape(m.name)} {tkr}</span>'
            f'<span class="chg {cls}">{disp}</span></div>'
            f'<p class="reason">{html.escape(m.reason_summary)}</p>'
            f"{spark}</a>"
        )
    grid = f'<div class="grid">{"".join(cards)}</div>' if cards else "<p>언급된 종목이 없습니다.</p>"

    src_badge = "Claude 요약" if brief.summarizer == "claude" else "규칙 기반 요약"
    price_badge = "실시간 시세(Stooq)" if brief.price_source == "stooq" else "합성 시세(데모)"

    body = (
        '<header class="top">'
        '<div><div class="brand">📈 Morning Brief</div>'
        f'<div class="channel">텔레그램 · 사제콩이_서상영 (@{html.escape(brief.source_channel)})</div></div>'
        f'<div class="date">{html.escape(brief.date)}</div></header>'
        f'<div class="overview"><h2>시황 요약 <span class="badge">{src_badge}</span></h2>'
        f'<p>{html.escape(brief.market_overview) or "요약 없음"}</p></div>'
        f"{idx_html}"
        f'<div class="section-title">오늘 언급된 종목 ({len(stocks)}) · 등락순 '
        f'<span class="badge">{price_badge}</span></div>'
        f"{grid}"
        '<p class="disclaimer">본 페이지는 텔레그램 브리핑 원문을 자동 요약·재구성한 참고 자료이며, '
        "투자 자문이나 매매 권유가 아닙니다. 투자 판단의 책임은 이용자 본인에게 있습니다. "
        "원문 저작권은 작성자(서상영)에게 있습니다.</p>"
        '<p class="disclaimer"><a class="back" href="../../index.html">← 지난 브리핑 보기</a></p>'
    )
    return _page(
        f"Morning Brief · {brief.date}",
        body,
        description=f"{brief.date} 시황 정리 및 종목별 서머리",
    )


def _render_stock(brief: Brief, m: StockMention) -> str:
    disp, cls = _fmt_pct(m.price_change_pct())
    tkr = f'<span class="tkr">{html.escape(m.ticker)}</span>' if m.ticker else ""

    price_line = ""
    if m.prices and m.prices.last_close is not None:
        cur = f"{m.prices.last_close:,.2f} {m.prices.currency}"
        price_line = f'<div class="price-line">{cur} <span class="{cls}">{disp}</span></div>'
    else:
        price_line = f'<div class="price-line"><span class="{cls}">{disp}</span></div>'

    reason_items = m.reason_summary or "등락 이유 정보 없음"
    src = ""
    if m.reason_context:
        src = (
            '<details class="src"><summary>원문 근거 보기</summary>'
            f'<p>{html.escape(m.reason_context)}</p></details>'
        )

    chart_html = ""
    note = ""
    if m.prices and m.prices.closes:
        chart_html = chart.line_chart(m.prices.closes, m.prices.dates, up=_dir_bool(m))
        n = len(m.prices.closes)
        src_label = "Stooq 일봉" if m.prices.source == "stooq" else "합성 데이터(데모)"
        note = f'<p class="chart-note">최근 {n}영업일 종가 · {src_label}</p>'
    else:
        chart_html = chart.line_chart([])

    body = (
        f'<a class="back" href="../index.html">← 시황으로</a>'
        f'<div class="stock-head"><h1>{html.escape(m.name)}</h1>{tkr}</div>'
        f"{price_line}"
        f'<div class="block"><h2>등락 이유</h2>'
        f'<ul class="reason-list"><li>{html.escape(reason_items)}</li></ul>{src}</div>'
        f'<div class="block"><h2>차트</h2>{chart_html}{note}</div>'
        '<p class="disclaimer">투자 참고용 자료이며 매매 권유가 아닙니다. '
        "시세가 합성 데이터로 표시된 경우 실제 가격과 다릅니다.</p>"
    )
    return _page(
        f"{m.name} · Morning Brief {brief.date}",
        body,
        description=f"{m.name} 등락 이유 및 차트 ({brief.date})",
    )


def _render_archive(out: Path) -> str:
    briefs_dir = out / "brief"
    dates = []
    if briefs_dir.exists():
        dates = sorted(
            [p.name for p in briefs_dir.iterdir() if p.is_dir() and (p / "index.html").exists()],
            reverse=True,
        )
    items = []
    for d in dates:
        latest = " <span class=\"badge\">최신</span>" if d == dates[0] else ""
        items.append(
            f'<li><a href="brief/{d}/index.html"><span>{html.escape(d)}{latest}</span>'
            f'<span class="tkr">시황 정리 →</span></a></li>'
        )
    body = (
        '<header class="top"><div class="brand">📈 Morning Brief</div>'
        '<div class="channel">사제콩이_서상영 시황 브리핑 아카이브</div></header>'
        + (f'<ul class="archive-list">{"".join(items)}</ul>' if items else "<p>아직 브리핑이 없습니다.</p>")
        + '<p class="disclaimer">투자 참고용 자동 생성 리포트. 매매 권유가 아닙니다.</p>'
    )
    return _page("Morning Brief — 아카이브", body, description="시황 브리핑 아카이브")


def _dump_json(brief: Brief) -> str:
    def default(o):
        return asdict(o) if hasattr(o, "__dataclass_fields__") else str(o)

    return json.dumps(asdict(brief), ensure_ascii=False, indent=2, default=default)
