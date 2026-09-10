"""구조화된 Brief → 미래에셋 CI 정적 사이트 (인라인 CSS/SVG, 외부 요청은 Google Fonts 만).

산출물 구조:
  <out>/index.html                       최신 브리핑으로 이동(고정 공유 링크) 또는 상태 페이지
  <out>/brief/<date>/index.html          데일리 브리핑 페이지(시황 · 지수 · 종목 리스트 · 종목 시트 · 관전 포인트)
  <out>/brief/<date>/stock/<slug>.html   종목 서머리 딥링크(개별 공유용)
  <out>/brief/<date>/data.json           구조화 데이터(원문 제외)
  <out>/brief/<date>/og.png              공유 미리보기 카드
  <out>/archive/index.html               날짜별 아카이브 + 종목 검색
  <out>/robots.txt                       검색 크롤링 차단(공개 링크지만 검색 유입은 의도하지 않음)
"""

from __future__ import annotations

import html
import json
import re
import shutil
from dataclasses import asdict
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import chart, og
from .models import Brief, StockMention
from .theme import CSS, FONTS_HTML, font_face_css

_WEEKDAYS = "월화수목금토일"
PRODUCT = "Morning Brief"
CHANNEL_TITLE = "사제콩이_서상영"
DISCLAIMER = (
    "본 페이지는 텔레그램 브리핑 원문을 자동 요약·재구성한 참고 자료이며, 투자 자문이나 매매 권유가 아닙니다. "
    "투자 판단의 책임은 이용자 본인에게 있습니다. 원문 저작권은 작성자(서상영)에게 있습니다."
)
_SOURCE_LABEL = {
    "stooq": "Stooq 일봉", "yahoo": "Yahoo Finance 일봉", "naver": "네이버 금융 일봉", "nasdaq": "Nasdaq 일봉", "investing": "Investing.com 일봉",
    "nasdaq+naver": "Nasdaq 일봉 + 네이버 최신 봉",
    "cache": "캐시(전일 기준)", "synthetic": "합성 데이터(데모)", "none": "시세 없음",
    "fred": "FRED(세인트루이스 연준)", "coingecko": "CoinGecko",
}
_FETCH_LABEL = {"preview": "공개 미리보기 수집", "session": "텔레그램 세션 수집", "fixture": "샘플 데이터(데모)"}


# ── 포맷 유틸 ──────────────────────────────────────────────────
def weekday_kr(date_str: str) -> str:
    try:
        return _WEEKDAYS[_date.fromisoformat(date_str).weekday()]
    except ValueError:
        return ""


def fmt_pct(pct: Optional[float]) -> tuple[str, str]:
    """(표시문자열, css클래스). ▲▼ 기호 + 색으로 이중 인코딩."""
    if pct is None:
        return ("—", "flat")
    if pct > 0:
        return (f"▲{pct:.2f}%", "up")
    if pct < 0:
        return (f"▼{abs(pct):.2f}%", "down")
    return ("0.00%", "flat")


def fmt_index_value(v: Optional[float]) -> str:
    if v is None:
        return ""
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}"


def hhmm(iso: str) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except ValueError:
        return iso[11:16] if len(iso) >= 16 else iso


def slugify(mention: StockMention) -> str:
    base = mention.ticker or mention.name
    s = re.sub(r"[^0-9A-Za-z가-힣]+", "-", base).strip("-").lower()
    return s or "stock"


def _dedupe_slugs(stocks: list[StockMention]) -> None:
    seen: dict[str, int] = {}
    for m in stocks:
        m.slug = slugify(m)
    for m in stocks:
        if m.slug in seen:
            seen[m.slug] += 1
            m.slug = f"{m.slug}-{seen[m.slug]}"
        else:
            seen[m.slug] = 1


def _dir_pct(m: StockMention) -> Optional[float]:
    pct = m.price_change_pct()
    if pct is None and m.direction != "FLAT":
        return 1.0 if m.direction == "UP" else -1.0
    return pct


def _esc(s: Optional[str]) -> str:
    return html.escape(s or "")


def _join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}" if base else path


# ── 문서 골격 ──────────────────────────────────────────────────
def _page(title: str, body: str, *, description: str = "", url: str = "", og_image: str = "", extra_head: str = "", script: str = "",
          root: str = "", fonts=()) -> str:
    og_tags = (
        f'<meta property="og:type" content="article"><meta property="og:title" content="{_esc(title)}">'
        f'<meta property="og:description" content="{_esc(description)}"><meta property="og:site_name" content="{PRODUCT}">'
        + (f'<meta property="og:url" content="{_esc(url)}"><link rel="canonical" href="{_esc(url)}">' if url else "")
        + (f'<meta property="og:image" content="{_esc(og_image)}"><meta property="og:image:width" content="1200">'
           f'<meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image">' if og_image else "")
    )
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(title)}</title>"
        f'<meta name="description" content="{_esc(description)}">'
        '<meta name="robots" content="noindex, nofollow">'
        f"{og_tags}{FONTS_HTML}<style>{font_face_css(root, fonts)}{CSS}</style>{extra_head}</head>"
        f"<body>{body}{script}</body></html>"
    )


def _mast(brief: Optional[Brief], root: str, logo_svg: Optional[str], *, sub: str = "", date_label: str = "") -> str:
    logo = logo_svg or ""
    if brief is not None:
        bits = [f"{CHANNEL_TITLE} 브리핑"]
        if brief.posted_at:
            bits.append(f"게시 {hhmm(brief.posted_at)}")
        if brief.generated_at:
            bits.append(f"생성 {hhmm(brief.generated_at)}")
        sub = sub or " · ".join(bits)
        wd = weekday_kr(brief.date)
        date_label = date_label or f'{_esc(brief.date)}<span class="wd">({wd})</span>'
    links = f'<a href="{root}archive/">지난 브리핑</a><a href="{root}">최신 브리핑</a>'
    return (
        '<header class="mast">'
        f'<div class="brand"><div class="logo-slot">{logo}</div>'
        f'<div class="title"><a href="{root}">{PRODUCT}</a></div><div class="sub">{_esc(sub) if brief is None else sub}</div></div>'
        f'<div class="when"><div class="date">{date_label}</div><div class="links">{links}</div></div>'
        "</header>"
    )


def _quality_tags(brief: Brief) -> str:
    tags = []
    if brief.summarizer == "claude":
        tags.append(f'<span class="tag ok">Claude 요약{(" · " + _esc(brief.model)) if brief.model else ""}</span>')
    else:
        tags.append('<span class="tag warn">규칙 기반 요약</span>')
    fetch = _FETCH_LABEL.get(brief.fetch_method, brief.fetch_method)
    tags.append(f'<span class="tag {"warn" if brief.fetch_method == "fixture" else ""}">{_esc(fetch)}</span>')
    src = _SOURCE_LABEL.get(brief.price_source, brief.price_source)
    tags.append(f'<span class="tag {"warn" if brief.price_source in ("synthetic", "none") else ""}">시세 {_esc(src)}</span>')
    tags.append(f'<span class="tag">메시지 {brief.message_count}건 종합</span>')
    if brief.generated_at:
        tags.append(f'<span class="tag">생성 {hhmm(brief.generated_at)}</span>')
    if brief.evidence_failures:
        tags.append(f'<span class="tag warn">근거 미검증 {len(brief.evidence_failures)}건</span>')
    return f'<div class="tags">{"".join(tags)}</div>'


def _foot(brief: Optional[Brief]) -> str:
    src = ""
    if brief is not None:
        src = (f'<p>출처: 텔레그램 <a href="{_esc(brief.message_url)}" target="_blank" rel="noopener">{CHANNEL_TITLE} (@{_esc(brief.source_channel)})</a> · '
               f"원문 요약·재구성</p>{_quality_tags(brief)}")
    return f'<footer class="foot">{src}<p>{DISCLAIMER}</p></footer>'


# ── 데일리 브리핑 페이지 ───────────────────────────────────────
def _indices(brief: Brief) -> str:
    if not brief.indices:
        return '<p class="empty">지수 정보가 없습니다.</p>'
    tiles = []
    for i in brief.indices:
        disp, cls = fmt_pct(i.change_pct)
        spark, note = "", ""
        if i.prices and len(i.prices.points) >= 2:
            col = {"up": chart.UP, "down": chart.DOWN}.get(cls, chart.DOWN)
            spark = f'<div class="spark">{chart.line_chart(i.prices.points, compact=True, width=300, height=72, color=col)}</div>'
            if i.prices.source.startswith("proxy:"):
                note = f'<div class="note">{_esc(i.prices.source.split(":", 1)[1])} ETF 추이</div>'
            else:
                note = '<div class="note">최근 20일</div>'
        tiles.append(
            f'<div class="tile"><div class="t-head"><div class="l">{_esc(i.name)}</div><div class="c {cls}">{disp}</div></div>'
            f'<div class="v">{fmt_index_value(i.value)}</div>{spark}{note}</div>'
        )
    return f'<div class="tiles">{"".join(tiles)}</div>'


def _stock_table(brief: Brief, stocks: list[StockMention]) -> str:
    if not stocks:
        return '<p class="empty">언급된 종목이 없습니다.</p>'
    rows = []
    for m in stocks:
        pct = m.price_change_pct()
        disp, cls = fmt_pct(pct)
        mini = _mini_link(f"#s-{m.slug}", m.name, chart.candlestick(m.prices.points, compact=True, width=MINI_W, height=MINI_H)
                          if m.prices and m.prices.points else "")
        tk = f'<span class="tk">{_esc(m.ticker)}</span>' if m.ticker else ""
        mk = f'<span class="mk">{"미국" if m.market == "US" else "한국"}</span>'
        warn = "" if m.evidence_verified else '<span class="badge-warn">근거 미검증</span>'
        rows.append(
            f'<tr data-order="{m.order}" data-pct="{pct if pct is not None else ""}" data-market="{m.market}">'
            f'<td class="nm-cell"><span class="nm">{_esc(m.name)}</span>{tk}{mk}</td>'
            f'<td class="chg r {cls}">{disp}</td>'
            f'<td class="mini">{mini}</td>'
            f'<td class="why">{_esc(m.reason_summary) or "—"}{warn}</td>'
            f'<td class="more">{_more_button(f"#s-{m.slug}", m.name)}</td></tr>'
        )
    return (
        '<div class="tbl stocks"><table id="stocks"><thead><tr><th>종목</th><th class="r">등락</th><th>최근 20일</th>'
        f'<th>등락 이유</th><th class="r">상세</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


MINI_W, MINI_H = 320, 110          # 목록 미니 차트 원본 크기(비율 유지 스케일: PC 150px, 모바일 셀 폭)
CHART_LG, CHART_SM = (680, 380), (360, 330)  # 시트 차트: PC · 모바일 — 세로를 넉넉히 잡아 등락 움직임이 보이게


def _more_button(href: str, name: str) -> str:
    """상세 시트를 여는 버튼(종목명은 링크가 아니라 이 버튼과 차트가 열게 한다)."""
    return f'<a class="btn-more" href="{href}" aria-label="{_esc(name)} 상세 보기">상세 보기<span aria-hidden="true"> ›</span></a>'


def _mini_link(href: str, name: str, svg: str) -> str:
    if not svg:
        return ""
    return f'<a class="mini-link" href="{href}" aria-label="{_esc(name)} 차트 크게 보기">{svg}</a>'


def _sheet_body(brief: Brief, m: StockMention, *, share_href: str = "") -> str:
    pct = m.price_change_pct()
    disp, cls = fmt_pct(pct)
    tk = f'<span class="tk">{_esc(m.ticker)}</span>' if m.ticker else ""
    mk = f'<span class="mk">{"미국" if m.market == "US" else "한국"}</span>'
    share = f'<a class="tk" href="{share_href}">공유 링크</a>' if share_href else ""

    if m.prices and m.prices.last_close is not None:
        cur = m.prices.currency
        delta = ""
        if m.prices.change is not None:
            sign = "+" if m.prices.change >= 0 else "−"
            delta = f"<small>({sign}{chart.fmt_price(abs(m.prices.change), cur)})</small>"
        price = (f'<span class="num">{chart.fmt_price(m.prices.last_close, cur)} <small>{_esc(cur)}</small></span>'
                 f'<span class="chg {cls}">{disp}</span>{delta}')
    else:
        price = f'<span class="chg {cls}">{disp}</span>'

    if m.prices and m.prices.points:
        svg = (f'<div class="chart-lg">{chart.candlestick(m.prices.points, currency=m.prices.currency, change_pct=pct, width=CHART_LG[0], height=CHART_LG[1])}</div>'
               f'<div class="chart-sm">{chart.candlestick(m.prices.points, currency=m.prices.currency, change_pct=pct, width=CHART_SM[0], height=CHART_SM[1])}</div>')
        n = min(20, len(m.prices.points))
        src = _SOURCE_LABEL.get(m.prices.source, m.prices.source)
        as_of = m.prices.as_of or m.prices.points[-1].date
        basis = f"{_esc(as_of)} {'장중 시세' if as_of == brief.date else '종가'} 기준"
        note = f'<p class="chart-note">최근 {n}영업일 · 거래량 · MA5/MA20 · {_esc(src)} · {basis}</p>'
        table = f'<details class="data"><summary>데이터 표(OHLCV)</summary>{chart.data_table(m.prices.points, m.prices.currency)}</details>'
    else:
        svg = chart.empty(message="시세 준비 중")
        note = '<p class="chart-note">시세를 가져오지 못했습니다. 텍스트 요약만 제공합니다.</p>'
        table = ""

    quote = ""
    if m.evidence:
        warn = "" if m.evidence_verified else '<span class="badge-warn">근거 미검증</span>'
        msg_url = f"https://t.me/{brief.source_channel}/{m.message_id}" if m.message_id else brief.message_url
        quote = (f'<blockquote class="quote">“{_esc(m.evidence)}”{warn}'
                 f'<a class="src" href="{_esc(msg_url)}" target="_blank" rel="noopener">원문 메시지 보기</a></blockquote>')
    dis = "투자 참고용 자동 생성 자료이며 매매 권유가 아닙니다."
    if m.prices and not m.prices.is_real:
        dis += " 표시된 시세는 합성(데모) 데이터로 실제 가격과 다릅니다."
    return (
        f'<div class="s-head"><h2>{_esc(m.name)}</h2>{tk}{mk}{share}</div>'
        f'<div class="price">{price}</div>'
        '<div class="s-rule"></div><h3 class="s-h">캔들차트</h3>'
        f'<div class="chart-card">{svg}</div>{note}{table}'
        '<div class="s-rule"></div><h3 class="s-h">등락 이유</h3>'
        f'<p class="reason">{_esc(m.reason_summary) or "등락 이유 정보가 없습니다."}</p>{quote}'
        f'<p class="s-dis">{dis}</p>'
    )


def _sheet_overlay(brief: Brief, m: StockMention) -> str:
    if m.kind == "macro":
        return (
            f'<div class="detail" id="x-{m.slug}" role="dialog" aria-modal="true" aria-label="{_esc(m.name)} 서머리">'
            '<a class="scrim" href="#top" aria-label="닫기"></a>'
            f'<div class="sheet"><a class="close" href="#top" aria-label="닫기">×</a>{_macro_sheet_body(brief, m)}</div></div>'
        )
    return (
        f'<div class="detail" id="s-{m.slug}" role="dialog" aria-modal="true" aria-label="{_esc(m.name)} 종목 서머리">'
        '<a class="scrim" href="#top" aria-label="닫기"></a>'
        f'<div class="sheet"><a class="close" href="#top" aria-label="닫기">×</a>{_sheet_body(brief, m, share_href=f"stock/{m.slug}.html")}</div></div>'
    )


_BRIEF_JS = """<script>
(function(){
  /* 상세 시트: JS 가 있으면 클래스로 열고 닫는다(:target 은 무JS 폴백). 닫을 때 #top 으로 점프하지 않아 스크롤 위치가 유지된다. */
  document.documentElement.classList.add('js');
  var open=null;
  function el(id){return id?document.getElementById(id):null;}
  function isSheet(id){return /^[sx]-/.test(id)&&!!el(id)&&el(id).classList.contains('detail');}
  function show(id,push){
    if(open&&open!==id){var prev=el(open); if(prev) prev.classList.remove('open');}
    var d=el(id); d.classList.add('open'); document.body.classList.add('sheet-open'); open=id;
    var sh=d.querySelector('.sheet'); if(sh) sh.scrollTop=0;
    if(push){try{history.pushState({sheet:id},'','#'+id);}catch(e){}}
    var c=d.querySelector('.close'); if(c){try{c.focus({preventScroll:true});}catch(e){}}
  }
  function hide(viaHistory){
    if(!open) return;
    var d=el(open); if(d) d.classList.remove('open');
    document.body.classList.remove('sheet-open'); open=null;
    if(viaHistory){
      if(history.state&&history.state.sheet){history.back();}
      else{try{history.replaceState(null,'',location.pathname+location.search);}catch(e){}}
    }
  }
  document.addEventListener('click',function(e){
    var a=e.target.closest?e.target.closest('a[href^="#"]'):null; if(!a) return;
    var id=a.getAttribute('href').slice(1);
    if(isSheet(id)){e.preventDefault(); show(id,true); return;}
    if(id==='top'&&a.closest('.detail')){e.preventDefault(); hide(true);}
  });
  window.addEventListener('popstate',function(){var id=location.hash.slice(1); if(isSheet(id)) show(id,false); else hide(false);});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&open) hide(true);});
  var initial=location.hash.slice(1); if(isSheet(initial)) show(initial,false);
})();
(function(){
  var table=document.getElementById('stocks'); if(!table) return;
  var body=table.querySelector('tbody'); var rows=Array.prototype.slice.call(body.querySelectorAll('tr'));
  var sort='order', market='all';
  function apply(){
    rows.sort(function(a,b){
      if(sort==='pct'){var pa=parseFloat(a.dataset.pct),pb=parseFloat(b.dataset.pct);
        if(isNaN(pa))pa=-Infinity; if(isNaN(pb))pb=-Infinity; return pb-pa;}
      return (+a.dataset.order)-(+b.dataset.order);
    });
    var shown=0;
    rows.forEach(function(r){body.appendChild(r);var ok=(market==='all'||r.dataset.market===market);r.hidden=!ok;if(ok)shown++;});
    var n=document.getElementById('stock-count'); if(n) n.textContent=shown;
  }
  function bind(attr,set){
    document.querySelectorAll('['+attr+']').forEach(function(b){
      b.addEventListener('click',function(){set(b.getAttribute(attr));
        b.parentNode.querySelectorAll('button').forEach(function(x){x.setAttribute('aria-pressed',String(x===b));});apply();});
    });
  }
  bind('data-sort',function(v){sort=v;}); bind('data-market',function(v){market=v;});
})();
</script>"""


def render_brief(brief: Brief, *, base_url: str = "", logo_svg: Optional[str] = None, fonts=()) -> str:
    _dedupe_slugs(brief.stocks)
    for m in brief.macros:
        m.slug = slugify(m)
    stocks = sorted(brief.stocks, key=lambda m: m.order)
    root = "../../"
    page_url = _join_url(base_url, f"brief/{brief.date}/")
    og_url = _join_url(base_url, f"brief/{brief.date}/og.png")

    paras = _paragraphs(brief.market_overview)
    overview = ""
    for i, p in enumerate(paras):
        cls = "lead headline" if (i == 0 and len(paras) > 1 and len(p) <= 90) else "lead"
        overview += f'<p class="{cls}">{_esc(p)}</p>'
    overview = overview or '<p class="empty">시황 요약이 없습니다.</p>'
    outlook = ""
    if brief.kr_outlook:
        outlook = ('<section class="sec outlook" id="kr"><div class="rule"></div><h2>한국 증시 관전 포인트</h2>'
                   + "".join(f"<p>{_esc(p)}</p>" for p in _paragraphs(brief.kr_outlook)) + "</section>")

    macro_section = _macro_section(brief)
    controls = (
        '<div class="controls">'
        '<div class="seg" role="group" aria-label="정렬"><button type="button" data-sort="order" aria-pressed="true">언급순</button>'
        '<button type="button" data-sort="pct" aria-pressed="false">등락순</button></div>'
        '<div class="seg" role="group" aria-label="시장"><button type="button" data-market="all" aria-pressed="true">전체</button>'
        '<button type="button" data-market="US" aria-pressed="false">미국</button>'
        '<button type="button" data-market="KR" aria-pressed="false">한국</button></div></div>'
    )
    body = (
        f'<div class="page" id="top">{_mast(brief, root, logo_svg)}'
        f'<section class="sec" id="overview"><div class="rule"></div><h2>시황 요약</h2>{overview}</section>'
        f'<section class="sec" id="indices"><div class="rule"></div><h2>주요 지수</h2>{_indices(brief)}</section>'
        f'<section class="sec" id="stocks-sec"><div class="rule"></div><div class="sec-head">'
        f'<h2>오늘의 종목<span class="n" id="stock-count">{len(stocks)}</span></h2>{controls}</div>{_stock_table(brief, stocks)}</section>'
        f"{macro_section}{outlook}{_foot(brief)}</div>"
        + "".join(_sheet_overlay(brief, m) for m in stocks)
        + "".join(_sheet_overlay(brief, m) for m in brief.macros)
    )
    desc = _first_sentence(brief.market_overview, 120) or f"{brief.date} 시황 정리 및 종목별 서머리"
    return _page(f"{PRODUCT} · {brief.date}", body, description=desc, url=page_url, og_image=og_url, script=_BRIEF_JS, root=root, fonts=fonts)


def render_stock(brief: Brief, m: StockMention, *, base_url: str = "", logo_svg: Optional[str] = None, fonts=()) -> str:
    root = "../../../"
    body = (
        f'<div class="page stock-page" id="top">{_mast(brief, root, logo_svg)}'
        f'<div class="sec"><a class="back" href="../">← {brief.date} 브리핑으로</a>'
        f'<div class="sheet">{_sheet_body(brief, m)}</div></div>{_foot(brief)}</div>'
    )
    return _page(
        f"{_esc(m.name)} · {PRODUCT} {brief.date}", body,
        description=m.reason_summary or f"{m.name} 등락 이유 및 캔들차트 ({brief.date})",
        url=_join_url(base_url, f"brief/{brief.date}/stock/{m.slug}.html"),
        og_image=_join_url(base_url, f"brief/{brief.date}/og.png"), root=root, fonts=fonts,
    )


def _macro_change(m: StockMention) -> tuple[str, str, str]:
    """(등락 표시, css, 보조 표기) — 데이터 기준 전일 대비. 금리(%)는 bp 로 표기."""
    if m.prices is None or m.prices.change is None:
        disp, cls = fmt_pct(m.change_pct)
        return disp, cls, ""
    diff, pct = m.prices.change, m.prices.change_pct
    if m.unit == "%":
        bp = diff * 100
        cls = "up" if bp > 0 else "down" if bp < 0 else "flat"
        arrow = "▲" if bp > 0 else "▼" if bp < 0 else ""
        return f"{arrow}{abs(bp):.0f}bp", cls, ""
    disp, cls = fmt_pct(pct)
    sign = "+" if diff >= 0 else "−"
    return disp, cls, f"({sign}{chart.fmt_unit(abs(diff), m.unit).lstrip('$')})"


def _macro_chart(m: StockMention, *, width: int = 680, height: int = 380) -> str:
    from .macro_prices import is_close_only

    pts = m.prices.points if m.prices else []
    if not pts:
        return chart.empty(message="시세 준비 중")
    pct = m.prices.change_pct if m.prices else None
    if is_close_only(m.prices):
        return chart.line_chart(pts, unit=m.unit, width=width, height=height - 40, change_pct=pct)
    return chart.candlestick(pts, currency=m.prices.currency, change_pct=pct, width=width, height=height)


def _macro_mini(m: StockMention) -> str:
    from .macro_prices import is_close_only

    if not (m.prices and m.prices.points):
        return ""
    if is_close_only(m.prices):
        return chart.line_chart(m.prices.points, unit=m.unit, compact=True, width=MINI_W, height=MINI_H)
    return chart.candlestick(m.prices.points, compact=True, width=MINI_W, height=MINI_H)


def _macro_section(brief: Brief) -> str:
    """금리 · 유가 · 금 · 환율 등 매크로 자산 — 브리핑 코멘트 + 차트(종목 서머리와 같은 시트)."""
    if not brief.macros:
        return ""
    rows = []
    for m in brief.macros:
        disp, cls, sub = _macro_change(m)
        value = chart.fmt_unit(m.prices.last_close, m.unit) if (m.prices and m.prices.last_close is not None) else "—"
        rows.append(
            f'<tr><td class="nm-cell"><span class="nm">{_esc(m.name)}</span><span class="tk">{_esc(m.unit)}</span></td>'
            f'<td class="val r">{_esc(value)}</td><td class="chg r {cls}">{disp}</td>'
            f'<td class="mini">{_mini_link(f"#x-{m.slug}", m.name, _macro_mini(m))}</td><td class="why">{_esc(m.reason_summary) or "—"}</td>'
            f'<td class="more">{_more_button(f"#x-{m.slug}", m.name)}</td></tr>'
        )
    return (
        '<section class="sec" id="macro"><div class="rule"></div><div class="sec-head">'
        f'<h2>금리 · 유가 · 금 · 환율<span class="n">{len(brief.macros)}</span></h2>'
        '<span class="empty">브리핑에 언급된 매크로 자산 · 등락은 데이터 기준 전일 대비</span></div>'
        '<div class="tbl stocks macro"><table><thead><tr><th>자산</th><th class="r">현재값</th><th class="r">전일 대비</th>'
        f'<th>최근 20일</th><th>브리핑 코멘트</th><th class="r">상세</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>'
    )


def _macro_sheet_body(brief: Brief, m: StockMention) -> str:
    disp, cls, sub = _macro_change(m)
    if m.prices and m.prices.last_close is not None:
        price = (f'<span class="num">{_esc(chart.fmt_unit(m.prices.last_close, m.unit))}</span>'
                 f'<span class="chg {cls}">{disp}</span>' + (f"<small>{_esc(sub)}</small>" if sub else ""))
        src = _SOURCE_LABEL.get(m.prices.source, m.prices.source)
        n = min(20, len(m.prices.points))
        note = f'<p class="chart-note">최근 {n}일 · {_esc(src)} · {_esc(m.prices.as_of or m.prices.points[-1].date)} 기준</p>'
        table = f'<details class="data"><summary>데이터 표</summary>{chart.data_table(m.prices.points, m.prices.currency)}</details>'
    else:
        price = f'<span class="chg {cls}">{disp}</span>'
        note = '<p class="chart-note">시세를 가져오지 못했습니다. 브리핑 코멘트만 제공합니다.</p>'
        table = ""
    svg = (f'<div class="chart-lg">{_macro_chart(m, width=CHART_LG[0], height=CHART_LG[1])}</div>'
           f'<div class="chart-sm">{_macro_chart(m, width=CHART_SM[0], height=CHART_SM[1])}</div>')
    quote = ""
    if m.evidence:
        quote = (f'<blockquote class="quote">“{_esc(m.evidence)}”'
                 f'<a class="src" href="{_esc(brief.message_url)}" target="_blank" rel="noopener">원문 메시지 보기</a></blockquote>')
    return (
        f'<div class="s-head"><h2>{_esc(m.name)}</h2><span class="tk">{_esc(m.unit)}</span><span class="mk">매크로</span></div>'
        f'<div class="price">{price}</div>'
        '<div class="s-rule"></div><h3 class="s-h">차트</h3>'
        f'<div class="chart-card">{svg}</div>{note}{table}'
        '<div class="s-rule"></div><h3 class="s-h">브리핑 코멘트</h3>'
        f'<p class="reason">{_esc(m.reason_summary) or "코멘트가 없습니다."}</p>{quote}'
        '<p class="s-dis">투자 참고용 자동 생성 자료이며 매매 권유가 아닙니다.</p>'
    )


# ── 아카이브 · 루트 · 상태 ─────────────────────────────────────
def collect_archive(out: Path) -> list[dict]:
    """site/brief/*/data.json 을 읽어 아카이브 목록(최신순)을 만든다."""
    entries = []
    briefs_dir = out / "brief"
    if not briefs_dir.exists():
        return entries
    for d in sorted((p for p in briefs_dir.iterdir() if p.is_dir()), reverse=True):
        data_path = d / "data.json"
        if not data_path.exists():
            continue
        try:
            data = json.loads(data_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        stocks = sorted(data.get("stocks", []), key=lambda s: s.get("order", 0))
        entries.append({
            "date": data.get("date", d.name),
            "overview": _first_sentence(data.get("market_overview", ""), 90),
            "count": len(stocks),
            "names": [s.get("name", "") for s in stocks[:4]],
            "all_names": " ".join(f"{s.get('name', '')} {s.get('ticker') or ''}" for s in stocks),
        })
    return entries


_ARCHIVE_JS = """<script>
(function(){
  var q=document.getElementById('q'); if(!q) return;
  var rows=Array.prototype.slice.call(document.querySelectorAll('.arc'));
  var months=Array.prototype.slice.call(document.querySelectorAll('.arc-month'));
  q.addEventListener('input',function(){
    var s=q.value.trim().toLowerCase();
    rows.forEach(function(r){r.hidden=!!s&&r.dataset.q.indexOf(s)<0;});
    months.forEach(function(m){var any=false,el=m.nextElementSibling;
      while(el&&!el.classList.contains('arc-month')){if(el.classList.contains('arc')&&!el.hidden)any=true;el=el.nextElementSibling;}
      m.hidden=!any;});
  });
})();
</script>"""


def render_archive(entries: list[dict], *, logo_svg: Optional[str] = None, fonts=()) -> str:
    root = "../"
    if not entries:
        listing = '<p class="empty">아직 브리핑이 없습니다.</p>'
    else:
        parts = []
        current = None
        for e in entries:
            month = f"{e['date'][:4]}년 {int(e['date'][5:7])}월" if len(e["date"]) >= 7 else "기타"
            if month != current:
                parts.append(f'<h3 class="arc-month">{month}</h3>')
                current = month
            names = " · ".join(_esc(n) for n in e["names"] if n)
            q = _esc(f"{e['date']} {e['all_names']} {e['overview']}".lower())
            parts.append(
                f'<a class="arc" href="{root}brief/{_esc(e["date"])}/" data-q="{q}">'
                f'<span class="d">{_esc(e["date"])}<span class="wd">({weekday_kr(e["date"])})</span></span>'
                f'<span class="o">{_esc(e["overview"]) or "시황 요약 없음"}<span class="names">{names}</span></span>'
                f'<span class="c">종목 {e["count"]}</span></a>'
            )
        listing = "".join(parts)
    body = (
        f'<div class="page" id="top">{_mast(None, root, logo_svg, sub=f"{CHANNEL_TITLE} 브리핑 아카이브", date_label="지난 브리핑")}'
        '<section class="sec"><div class="rule"></div><div class="sec-head"><h2>지난 브리핑'
        f'<span class="n">{len(entries)}</span></h2>'
        '<input class="search" id="q" type="search" placeholder="날짜 또는 종목명으로 검색" aria-label="아카이브 검색"></div>'
        f"{listing}</section>{_foot(None)}</div>"
    )
    return _page(f"{PRODUCT} · 지난 브리핑", body, description="시황 브리핑 아카이브", script=_ARCHIVE_JS, root=root, fonts=fonts)


def render_redirect(target: str) -> str:
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<meta http-equiv="refresh" content="0; url={_esc(target)}"><link rel="canonical" href="{_esc(target)}">'
        '<meta name="robots" content="noindex, nofollow">'
        f"<title>{PRODUCT}</title><style>body{{font-family:'Noto Sans KR',sans-serif;color:#3D3D3D;background:#FFFFFF;"
        "display:grid;place-items:center;height:100vh;margin:0;font-size:17px}a{color:#043B72}</style></head>"
        f'<body><p>최신 브리핑으로 이동 중… <a href="{_esc(target)}">열리지 않으면 여기를 누르세요</a></p></body></html>'
    )


def render_status(date_str: str, status: str, *, latest: Optional[str] = None, checked_at: str = "", logo_svg: Optional[str] = None, refresh_sec: int = 300, fonts=()) -> str:
    """브리핑 대기/없음 상태 페이지 (루트 index.html 로 게시)."""
    wd = weekday_kr(date_str)
    if status == "waiting":
        title, msg = "오늘 브리핑 대기 중", "채널에 아직 오늘 브리핑이 게시되지 않았습니다. 게시가 감지되면 자동으로 생성되어 이 페이지가 갱신됩니다."
    else:
        title, msg = "오늘은 브리핑이 없습니다", "미국 휴장 등으로 채널에 브리핑이 게시되지 않았습니다."
    latest_link = f'<p><a href="brief/{_esc(latest)}/">최근 브리핑({_esc(latest)}) 보기 →</a></p>' if latest else ""
    checked = f"<p>마지막 확인 {_esc(hhmm(checked_at))} (KST)</p>" if checked_at else ""
    date_label = f'{_esc(date_str)}<span class="wd">({wd})</span>' if date_str else "—"
    body = (
        f'<div class="page" id="top">{_mast(None, "", logo_svg, sub=f"{CHANNEL_TITLE} 브리핑", date_label=date_label)}'
        f'<div class="status"><h2>{title}</h2><p>{msg}</p>{checked}{latest_link}</div>{_foot(None)}</div>'
    )
    extra = f'<meta http-equiv="refresh" content="{refresh_sec}">' if status == "waiting" else ""
    return _page(f"{PRODUCT} · {title}", body, description=msg, extra_head=extra, root="", fonts=fonts)


# ── 사이트 생성 ────────────────────────────────────────────────
def render_site(brief: Brief, out_dir: str | Path, *, base_url: str = "", logo_svg: Optional[str] = None) -> Path:
    out = Path(out_dir)
    date_dir = out / "brief" / brief.date
    stock_dir = date_dir / "stock"
    stock_dir.mkdir(parents=True, exist_ok=True)

    fonts = install_fonts(out)
    _dedupe_slugs(brief.stocks)
    for m in brief.stocks:
        (stock_dir / f"{m.slug}.html").write_text(render_stock(brief, m, base_url=base_url, logo_svg=logo_svg, fonts=fonts), encoding="utf-8")
    date_dir.joinpath("index.html").write_text(render_brief(brief, base_url=base_url, logo_svg=logo_svg, fonts=fonts), encoding="utf-8")
    date_dir.joinpath("data.json").write_text(dump_json(brief), encoding="utf-8")

    headline = _first_sentence(brief.market_overview, 70) or "시황 요약"
    og.write_og_card(
        date_dir / "og.png", date_label=brief.date, weekday=weekday_kr(brief.date), headline=headline,
        foot_left=f"텔레그램 {CHANNEL_TITLE} · 종목 {len(brief.stocks)}개",
    )
    write_shared_pages(out, logo_svg=logo_svg, fonts=fonts)
    return date_dir / "index.html"


FONT_SRC_DIR = Path(__file__).parent / "assets" / "fonts"


def install_fonts(out: Path) -> list[str]:
    """assets/fonts 의 KoPub돋움 파일을 사이트로 복사하고 파일명 목록을 돌려준다(없으면 빈 목록 → Noto Sans KR 폴백)."""
    names: list[str] = []
    if FONT_SRC_DIR.exists():
        dest = out / "assets" / "fonts"
        for f in sorted(FONT_SRC_DIR.iterdir()):
            if f.suffix.lower() in (".woff2", ".woff", ".ttf", ".otf"):
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dest / f.name)
                names.append(f.name)
    return names


def write_shared_pages(out: Path, *, logo_svg: Optional[str] = None, root_html: Optional[str] = None, fonts=None) -> None:
    """아카이브 · 루트 리다이렉트 · robots.txt (모든 실행에서 재생성)."""
    if fonts is None:
        fonts = install_fonts(out)
    entries = collect_archive(out)
    (out / "archive").mkdir(parents=True, exist_ok=True)
    (out / "archive" / "index.html").write_text(render_archive(entries, logo_svg=logo_svg, fonts=fonts), encoding="utf-8")
    if root_html is None:
        root_html = render_redirect(f"brief/{entries[0]['date']}/") if entries else render_status("", "no_briefing", logo_svg=logo_svg, fonts=fonts)
    (out / "index.html").write_text(root_html, encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")


def dump_json(brief: Brief) -> str:
    data = asdict(brief)
    data.pop("raw_text", None)  # 원문 전문은 공개 데이터에서 제외(요약 + 근거 발췌만 제공)
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# ── 텍스트 유틸 ────────────────────────────────────────────────
def _paragraphs(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n|\n", text or "") if p.strip()]


def _first_sentence(text: str, limit: int) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    m = re.match(r"(.+?[.!?。])(\s|$)", t)
    s = m.group(1) if m else t
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"
