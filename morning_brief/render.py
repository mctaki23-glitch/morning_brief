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
  --border: #e5e7eb; --accent: #c2410c; --up: #dc2626; --down: #2563eb;
  --radius: 14px;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #0d1117; --fg: #e6edf3; --muted: #9aa4b2; --card: #161b22;
          --border: #262c36; --accent: #f97316; --up: #f85149; --down: #4f8cff; }
}
:root[data-theme="light"] { --bg:#ffffff; --fg:#111418; --muted:#6b7280; --card:#f6f7f9;
  --border:#e5e7eb; --accent:#c2410c; --up:#dc2626; --down:#2563eb; }
:root[data-theme="dark"] { --bg:#0d1117; --fg:#e6edf3; --muted:#9aa4b2; --card:#161b22;
  --border:#262c36; --accent:#f97316; --up:#f85149; --down:#4f8cff; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", Roboto, sans-serif;
  line-height: 1.55; -webkit-font-smoothing: antialiased; overflow-x: hidden; }
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

    # 단일 파일 공유 버전 (모든 종목 상세 포함, 완전 자기완결)
    date_dir.joinpath("onepage.html").write_text(
        render_single_page(brief, standalone=True), encoding="utf-8"
    )

    # 구조화 데이터
    date_dir.joinpath("data.json").write_text(_dump_json(brief), encoding="utf-8")

    # 아카이브(지난 브리핑 목록) + 루트는 최신 종합 화면(onepage)으로 바로 이동
    out.joinpath("archive.html").write_text(_render_archive(out), encoding="utf-8")
    latest = _latest_date(out)
    out.joinpath("index.html").write_text(_render_root(latest), encoding="utf-8")
    return date_dir / "index.html"


def _latest_date(out: Path) -> Optional[str]:
    briefs_dir = out / "brief"
    if not briefs_dir.exists():
        return None
    dates = sorted(
        [p.name for p in briefs_dir.iterdir() if p.is_dir() and (p / "onepage.html").exists()],
        reverse=True,
    )
    return dates[0] if dates else None


def _render_root(latest: Optional[str]) -> str:
    """루트(/)는 최신 '아침 종합' 모바일 화면으로 바로 이동."""
    if not latest:
        return _page("Morning Brief", '<div class="wrap"><p>아직 브리핑이 없습니다.</p></div>')
    target = f"brief/{latest}/onepage.html"
    return (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f'<meta http-equiv="refresh" content="0; url={target}">'
        f'<link rel="canonical" href="{target}">'
        "<title>Morning Brief</title>"
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans KR',sans-serif;"
        "background:#0b0d11;color:#e8ebf1;display:grid;place-items:center;height:100vh;margin:0}"
        "a{color:#e0a94a}</style></head>"
        f'<body><p>최신 브리핑으로 이동 중… <a href="{target}">열리지 않으면 여기를 누르세요</a></p></body></html>'
    )


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
        f'<div class="overview"><h2>시황 요약 <span class="badge">{src_badge}</span>'
        f'<span class="badge">아침 {brief.message_count}건 종합</span></h2>'
        f'<p>{html.escape(brief.market_overview) or "요약 없음"}</p></div>'
        f"{idx_html}"
        f'<div class="section-title">오늘 언급된 종목 ({len(stocks)}) · 등락순 '
        f'<span class="badge">{price_badge}</span></div>'
        f"{grid}"
        '<p class="disclaimer">본 페이지는 텔레그램 브리핑 원문을 자동 요약·재구성한 참고 자료이며, '
        "투자 자문이나 매매 권유가 아닙니다. 투자 판단의 책임은 이용자 본인에게 있습니다. "
        "원문 저작권은 작성자(서상영)에게 있습니다.</p>"
        '<p class="disclaimer"><a class="back" href="../../archive.html">← 지난 브리핑 보기</a></p>'
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
    if m.prices and m.prices.points:
        chart_html = chart.candlestick(m.prices.points, up=_dir_bool(m))
        n = len(m.prices.points)
        src_label = "Stooq 일봉" if m.prices.source == "stooq" else "합성 데이터(데모)"
        note = f'<p class="chart-note">최근 {n}영업일 봉차트(OHLC) · {src_label}</p>'
    else:
        chart_html = chart.candlestick([])

    body = (
        f'<a class="back" href="../index.html">← 시황으로</a>'
        f'<div class="stock-head"><h1>{html.escape(m.name)}</h1>{tkr}</div>'
        f"{price_line}"
        f'<div class="block"><h2>등락 이유</h2>'
        f'<ul class="reason-list"><li>{html.escape(reason_items)}</li></ul>{src}</div>'
        f'<div class="block"><h2>차트 (봉차트)</h2>{chart_html}{note}</div>'
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


# ── 단일 페이지 렌더 (공유 링크/Artifact용, 완전 자기완결) ──────────
_SINGLE_CSS = """
:root{
  --bg:#f6f6f4; --surface:#ffffff; --surface-2:#fbfbfa; --ink:#15181e;
  --muted:#5c6572; --line:#e5e7ec; --up:#e23744; --down:#2f76e6; --flat:#8a919c;
  --accent:#b07d2b; --shadow:0 1px 2px rgba(20,24,30,.06),0 8px 24px rgba(20,24,30,.06);
  --radius:12px;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",Roboto,Helvetica,Arial,sans-serif;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0b0d11; --surface:#14171d; --surface-2:#11141a; --ink:#e8ebf1;
  --muted:#8b93a1; --line:#222834; --up:#ff5a67; --down:#5b97ff; --flat:#7c8494;
  --accent:#e0a94a; --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.35);
}}
:root[data-theme="light"]{--bg:#f6f6f4;--surface:#ffffff;--surface-2:#fbfbfa;--ink:#15181e;
  --muted:#5c6572;--line:#e5e7ec;--up:#e23744;--down:#2f76e6;--flat:#8a919c;--accent:#b07d2b;
  --shadow:0 1px 2px rgba(20,24,30,.06),0 8px 24px rgba(20,24,30,.06);}
:root[data-theme="dark"]{--bg:#0b0d11;--surface:#14171d;--surface-2:#11141a;--ink:#e8ebf1;
  --muted:#8b93a1;--line:#222834;--up:#ff5a67;--down:#5b97ff;--flat:#7c8494;--accent:#e0a94a;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.35);}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  line-height:1.55;-webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums;
  overflow-x:hidden;}
.page{max-width:900px;margin:0 auto;padding:28px 20px 72px;}
a{color:inherit;text-decoration:none}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums;letter-spacing:-0.01em}
.up{color:var(--up)} .down{color:var(--down)} .flat{color:var(--flat)}

.masthead{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;
  flex-wrap:wrap;padding-bottom:16px;border-bottom:1px solid var(--line);margin-bottom:22px}
.brand{display:flex;align-items:center;gap:9px;font-weight:750;font-size:19px;letter-spacing:-0.02em}
.brand .dot{width:10px;height:10px;border-radius:50%;background:var(--accent);
  box-shadow:0 0 0 4px color-mix(in srgb,var(--accent) 22%,transparent)}
.brand .sub{color:var(--muted);font-weight:500;font-size:12.5px;margin-left:2px;letter-spacing:0}
.masthead .when{text-align:right}
.masthead .when .d{font-family:var(--mono);font-size:14px}
.masthead .when .src{color:var(--muted);font-size:11.5px;letter-spacing:.02em;text-transform:uppercase}

.pulse{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  padding:18px 20px;box-shadow:var(--shadow);margin-bottom:14px}
.eyebrow{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:650;margin:0 0 9px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.pill{display:inline-block;font-size:10.5px;letter-spacing:.02em;text-transform:none;font-weight:650;
  color:var(--accent);background:color-mix(in srgb,var(--accent) 14%,transparent);
  border:1px solid color-mix(in srgb,var(--accent) 35%,transparent);border-radius:999px;padding:2px 9px}
.pulse p{margin:0;font-size:16px;text-wrap:pretty;max-width:64ch}
.indices{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 26px}
.chip{display:inline-flex;align-items:baseline;gap:7px;border:1px solid var(--line);
  background:var(--surface);border-radius:999px;padding:6px 13px;font-size:13px}
.chip .nm{color:var(--muted)}
.chip .v{font-family:var(--mono);font-weight:600;font-size:13px}

.movers-head{display:flex;align-items:baseline;justify-content:space-between;margin:0 0 10px}
.movers-head .eyebrow{margin:0}
.movers-head .hint{font-size:11.5px;color:var(--muted)}
.list{display:flex;flex-direction:column;border:1px solid var(--line);border-radius:var(--radius);
  overflow:hidden;background:var(--surface);box-shadow:var(--shadow)}
.row{display:grid;grid-template-columns:1fr auto 128px;align-items:center;gap:14px;
  padding:13px 16px;border-bottom:1px solid var(--line);border-left:3px solid transparent;
  transition:background .12s ease,border-color .12s ease}
.row:last-child{border-bottom:none}
.row:hover,.row:focus-visible{background:var(--surface-2);border-left-color:var(--accent);outline:none}
.row .id{min-width:0}
.row .nm{font-weight:680;font-size:15px;letter-spacing:-0.01em;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.row .tkr{font-family:var(--mono);font-size:11.5px;color:var(--muted);
  border:1px solid var(--line);border-radius:5px;padding:1px 5px}
.row .why{color:var(--muted);font-size:13px;margin:3px 0 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .chg{font-family:var(--mono);font-weight:700;font-size:15px;white-space:nowrap;text-align:right}
.row .spark{justify-self:end}
.chev{display:none}

.foot{color:var(--muted);font-size:12px;line-height:1.6;margin-top:26px;
  border-top:1px solid var(--line);padding-top:14px}
.foot a.gh{color:var(--accent);font-weight:600}

/* 종목 상세 — :target 오버레이 (JS 불필요) */
.detail{position:fixed;inset:0;z-index:50;display:none}
.detail:target{display:block}
.detail .scrim{position:absolute;inset:0;background:color-mix(in srgb,#0b0d11 55%,transparent);
  backdrop-filter:blur(2px)}
.sheet{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
  width:min(680px,calc(100vw - 32px));max-height:calc(100vh - 48px);overflow:auto;
  background:var(--surface);border:1px solid var(--line);border-radius:16px;
  box-shadow:0 24px 60px rgba(0,0,0,.35);padding:22px 24px 26px}
.sheet .close{position:sticky;top:0;float:right;width:32px;height:32px;display:grid;place-items:center;
  border-radius:8px;color:var(--muted);font-size:20px;line-height:1;background:var(--surface)}
.sheet .close:hover{background:var(--surface-2);color:var(--ink)}
.sheet h2{margin:2px 0 0;font-size:23px;letter-spacing:-0.02em;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;text-wrap:balance}
.sheet h2 .tkr{font-family:var(--mono);font-size:13px;color:var(--muted);border:1px solid var(--line);border-radius:6px;padding:2px 7px}
.sheet .price{font-family:var(--mono);font-size:20px;font-weight:700;margin:8px 0 20px}
.panel{border:1px solid var(--line);background:var(--surface-2);border-radius:12px;padding:15px 17px;margin-bottom:14px}
.panel .eyebrow{margin-bottom:8px}
.panel p{margin:0;font-size:15px;text-wrap:pretty}
.panel details{margin-top:10px}
.panel summary{cursor:pointer;color:var(--accent);font-size:13px;font-weight:600}
.panel details p{color:var(--muted);font-size:13.5px;margin-top:8px}
.chart-note{color:var(--muted);font-size:12px;margin:9px 0 0;font-family:var(--mono)}
.sheet .dis{color:var(--muted);font-size:11.5px;margin:6px 0 0}
@keyframes sheet-up{from{transform:translateY(100%)}to{transform:translateY(0)}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}

/* 스마트폰: 상세를 하단 바텀시트로, 터치 영역 확대 */
@media (max-width:560px){
  .page{padding:18px 14px 56px}
  .masthead{flex-direction:column;align-items:flex-start;gap:4px;margin-bottom:16px}
  .masthead .when{text-align:left}
  .masthead .when .d{font-size:13px}
  .row{display:flex;align-items:center;gap:12px;padding:15px 15px;min-height:60px}
  .row .spark{display:none}
  .row .id{flex:1 1 auto;min-width:0}
  .row .chg{flex:0 0 auto}
  .row .nm{font-size:15.5px}
  .row .why{font-size:12.5px;white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
  .row .chg{font-size:16px}
  .indices{margin:14px 0 22px}
  .chip{padding:7px 13px}
  /* 바텀시트 */
  .sheet{left:0;right:0;top:auto;bottom:0;transform:none;width:100%;
    max-height:90vh;border-radius:18px 18px 0 0;padding:16px 18px calc(24px + env(safe-area-inset-bottom));
    animation:sheet-up .22s ease-out}
  .sheet::before{content:"";display:block;width:40px;height:4px;border-radius:999px;
    background:var(--line);margin:0 auto 12px}
  .sheet .close{width:40px;height:40px;font-size:24px;margin-top:-4px}
  .sheet h2{font-size:21px}
}
"""


def render_single_page(brief: Brief, standalone: bool = True) -> str:
    """모든 종목 상세를 포함한 단일 자기완결 HTML (공유 링크/Artifact용).

    standalone=False 이면 <title>+<style>+본문 마크업만 반환한다(외부 스켈레톤이
    head/body 를 감싸는 Artifact 게시 환경용).
    """
    for m in brief.stocks:
        m.slug = slugify(m)
    _dedupe_slugs(brief.stocks)

    def sort_key(m: StockMention):
        pct = m.price_change_pct()
        return -(abs(pct) if pct is not None else -1)

    stocks = sorted(brief.stocks, key=sort_key)

    # 지수 칩
    chips = ""
    if brief.indices:
        parts = []
        for i in brief.indices:
            disp, cls = _fmt_pct(i.change_pct)
            parts.append(
                f'<span class="chip"><span class="nm">{html.escape(i.name)}</span>'
                f'<span class="v {cls}">{disp}</span></span>'
            )
        chips = f'<div class="indices">{"".join(parts)}</div>'

    # 종목 행
    rows = []
    for m in stocks:
        disp, cls = _fmt_pct(m.price_change_pct())
        tkr = f'<span class="tkr">{html.escape(m.ticker)}</span>' if m.ticker else ""
        spark = ""
        if m.prices and m.prices.closes:
            spark = f'<span class="spark">{chart.sparkline(m.prices.closes, up=_dir_bool(m), width=120, height=34)}</span>'
        rows.append(
            f'<a class="row" href="#s-{m.slug}">'
            f'<span class="id"><span class="nm">{html.escape(m.name)}{tkr}</span>'
            f'<span class="why">{html.escape(m.reason_summary)}</span></span>'
            f'<span class="chg {cls}">{disp}</span>{spark}</a>'
        )
    list_html = f'<div class="list">{"".join(rows)}</div>' if rows else "<p>언급된 종목이 없습니다.</p>"

    # 종목 상세 오버레이
    details = []
    for m in stocks:
        disp, cls = _fmt_pct(m.price_change_pct())
        tkr = f'<span class="tkr">{html.escape(m.ticker)}</span>' if m.ticker else ""
        if m.prices and m.prices.last_close is not None:
            price = f'{m.prices.last_close:,.2f} {m.prices.currency} <span class="{cls}">{disp}</span>'
        else:
            price = f'<span class="{cls}">{disp}</span>'
        src = ""
        if m.reason_context:
            src = (
                '<details><summary>원문 근거 보기</summary>'
                f'<p>{html.escape(m.reason_context)}</p></details>'
            )
        if m.prices and m.prices.points:
            chart_svg = chart.candlestick(m.prices.points, up=_dir_bool(m))
            n = len(m.prices.points)
            src_label = "Stooq 일봉" if m.prices.source == "stooq" else "합성 데이터(데모)"
            note = f'<p class="chart-note">최근 {n}영업일 봉차트(OHLC) · {src_label}</p>'
        else:
            chart_svg = chart.candlestick([])
            note = ""
        details.append(
            f'<div class="detail" id="s-{m.slug}"><a class="scrim" href="#top" aria-label="닫기"></a>'
            f'<div class="sheet" role="dialog" aria-label="{html.escape(m.name)} 상세">'
            f'<a class="close" href="#top" aria-label="닫기">×</a>'
            f'<h2>{html.escape(m.name)}{tkr}</h2>'
            f'<div class="price num">{price}</div>'
            f'<div class="panel"><p class="eyebrow">등락 이유</p><p>{html.escape(m.reason_summary) or "정보 없음"}</p>{src}</div>'
            f'<div class="panel"><p class="eyebrow">차트 · 봉차트(OHLC)</p>{chart_svg}{note}</div>'
            '<p class="dis">투자 참고용이며 매매 권유가 아닙니다. 합성 시세는 실제 가격과 다릅니다.</p>'
            "</div></div>"
        )

    src_badge = "Claude 요약" if brief.summarizer == "claude" else "규칙 기반 요약"
    price_badge = "Stooq 시세" if brief.price_source == "stooq" else "합성 시세(데모)"

    body = (
        '<div class="page" id="top">'
        '<header class="masthead">'
        '<div class="brand"><span class="dot"></span>Morning Brief'
        '<span class="sub">사제콩이 · 서상영</span></div>'
        f'<div class="when"><div class="d num">{html.escape(brief.date)}</div>'
        f'<div class="src">Telegram @{html.escape(brief.source_channel)}</div></div>'
        '</header>'
        f'<section class="pulse"><p class="eyebrow">시황 · {src_badge}'
        f'<span class="pill">아침 {brief.message_count}건 종합</span></p>'
        f'<p>{html.escape(brief.market_overview) or "요약 없음"}</p></section>'
        f'{chips}'
        '<div class="movers-head"><p class="eyebrow">오늘의 종목 · 등락순</p>'
        f'<span class="hint">{len(stocks)}개 · 탭하면 이유·차트 · {price_badge}</span></div>'
        f'{list_html}'
        '<p class="foot">텔레그램 브리핑 원문을 자동 요약·재구성한 참고 자료입니다. '
        '투자 자문이나 매매 권유가 아니며, 투자 판단의 책임은 이용자 본인에게 있습니다. '
        '원문 저작권은 작성자(서상영)에게 있습니다.</p>'
        '</div>'
        + "".join(details)
    )

    head = (
        f"<title>Morning Brief · {html.escape(brief.date)}</title>"
        f"<style>{_SINGLE_CSS}</style>"
    )
    if not standalone:
        return head + body
    return (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"{head}</head><body>{body}</body></html>"
    )
