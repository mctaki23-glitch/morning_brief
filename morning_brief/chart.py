"""인라인 SVG 캔들차트 (외부 라이브러리·JS·CDN 불필요) — 미래에셋 CI.

- 종목 서머리용 `candlestick()`: 최근 N영업일 캔들 + 하단 거래량 바 + 5일/20일 이동평균선
  + 우측 가격축·점선 그리드 + 날짜축 + 최고/최저/최근 종가 라벨 + 봉별 툴팁(<title>).
- 목록용 `candlestick(compact=True)`: 축·라벨 없는 미니 캔들.

색상 규칙
- 양봉/음봉은 페이지 CSS 변수(--up/--down)를 따른다. 기본은 한국식(상승 #C62828, 하락 #043B72).
- 이동평균선은 차트 페어 규칙: 시리즈 1 오렌지(#F58220), 시리즈 2 블루(#0086B8). 브랜드 오렌지는
  등락 표시에 쓰지 않는다.
- 텍스트(라벨·축)는 텍스트 토큰(#6C6C6C, #1A1A1A)만 사용한다.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional

from .models import PricePoint

UP = "var(--up, #C62828)"
DOWN = "var(--down, #043B72)"
MA_COLORS = {5: "#F58220", 20: "#0086B8"}  # 시리즈 1 오렌지 → 시리즈 2 블루 (고정 순서)
GRID, AXIS, LABEL, INK = "#A0A6A8", "#49535B", "#6C6C6C", "#1A1A1A"
VOL, VOL_LAST = "#D7D7D7", "#84888B"
FONT = "Inter, system-ui, sans-serif"
FONT_KR = "'KoPub Dotum', 'Noto Sans KR', Inter, system-ui, sans-serif"


# ── 포맷 유틸 ──────────────────────────────────────────────────
def fmt_price(value: float, currency: str = "USD") -> str:
    """가격 표기: KRW는 정수, 그 외 소수 2자리. 천 단위 콤마."""
    if currency == "KRW":
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def fmt_volume(volume: float) -> str:
    if volume >= 1e8:
        return f"{volume / 1e8:.1f}억"
    if volume >= 1e4:
        return f"{volume / 1e4:.0f}만"
    return f"{volume:,.0f}"


def _fmt_tick(value: float, currency: str, span: float) -> str:
    if currency == "KRW":
        return f"{value:,.0f}"
    if span < 5:
        return f"{value:,.2f}"
    if span < 50:
        return f"{value:,.1f}"
    return f"{value:,.0f}"


def fmt_ymd(d: str) -> str:
    """'2026-09-08' → '2026.09.08'. ISO 형식이 아니면 빈 문자열(합성 데이터의 D-3 등)."""
    if len(d) == 10 and d[4] == "-" and d[7] == "-":
        return d.replace("-", ".")
    return ""


def fmt_range(points: Iterable[PricePoint], window: int = 20) -> str:
    """차트 하단 기간 표기: '2026.08.12 – 2026.09.09' (표시 구간의 첫 봉 ~ 마지막 봉). 날짜를 알 수 없으면 빈 문자열."""
    shown = list(points)[-window:]
    if not shown:
        return ""
    a, b = fmt_ymd(shown[0].date), fmt_ymd(shown[-1].date)
    if not a or not b:
        return ""
    return a if a == b else f"{a} – {b}"


def _short_date(d: str) -> str:
    """'2026-09-08' → '09-08'. 그 외 형식(D-3 등)은 그대로."""
    if len(d) == 10 and d[4] == "-" and d[7] == "-":
        return d[5:]
    return d


def moving_average(values: list[float], n: int) -> list[Optional[float]]:
    """단순 이동평균. 데이터가 n개 미만인 구간은 None."""
    out: list[Optional[float]] = []
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= n:
            running -= values[i - n]
        out.append(running / n if i >= n - 1 else None)
    return out


def _nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = mag * 10
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            step = m * mag
            break
    t = math.ceil(lo / step) * step
    ticks: list[float] = []
    while t < hi and len(ticks) < 12:
        ticks.append(t)
        t += step
    return ticks


def _label_w(*labels: str) -> float:
    """12px 숫자 라벨의 대략적인 폭(px). 우측 여백을 가장 긴 라벨에 맞추기 위해 사용."""
    return max((sum(4.0 if ch in ".,%¢$ " else 7.0 for ch in s) for s in labels), default=0.0)


def _text(x: float, y: float, s: str, anchor: str = "start", font: str = FONT, fill: str = LABEL, weight: str = "") -> str:
    w = f' font-weight="{weight}"' if weight else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="12" text-anchor="{anchor}" fill="{fill}" font-family="{font}"{w}>{s}</text>'


def empty(width: int = 680, height: int = 300, message: str = "차트 데이터 없음") -> str:
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" aria-label="{message}" '
        f'style="max-width:100%;height:auto;display:block">'
        f'<text x="{width / 2}" y="{height / 2}" font-size="13" text-anchor="middle" fill="{LABEL}" font-family="{FONT_KR}">{message}</text></svg>'
    )


# ── 캔들차트 ───────────────────────────────────────────────────
def candlestick(
    points: Iterable[PricePoint],
    *,
    currency: str = "USD",
    window: int = 20,
    width: int = 680,
    height: int = 300,
    ma_periods: tuple[int, ...] = (5, 20),
    volume: bool = True,
    compact: bool = False,
    change_pct: Optional[float] = None,
) -> str:
    """OHLCV 리스트 → 인라인 SVG. 이동평균은 전체 시계열로 계산하고 마지막 `window`개 봉을 표시한다."""
    pts = list(points)
    if not pts:
        return empty(width, height)
    if compact:
        return _compact(pts[-window:], width, height)

    shown = pts[-window:]
    n = len(shown)
    closes_all = [p.close for p in pts]
    mas = {k: moving_average(closes_all, k)[-n:] for k in ma_periods}
    show_vol = volume and any(p.volume > 0 for p in shown)

    ma_vals = [v for vs in mas.values() for v in vs if v is not None]
    hi = max([p.high for p in shown] + ma_vals)
    lo = min([p.low for p in shown] + ma_vals)
    pad = (hi - lo) * 0.08 or hi * 0.01 or 1.0
    hi, lo = hi + pad, lo - pad
    span = hi - lo
    ticks = _nice_ticks(lo, hi, 4)
    last = shown[-1].close
    tag_label = fmt_price(last, currency)

    # 우측 여백은 가장 긴 라벨(눈금·최근가 태그)에 맞춘다 — 값이 길어도 겹치거나 잘리지 않게
    ml, mt, mb = 10.0, 32.0, 26.0
    mr = max(56.0 if width < 480 else 70.0, _label_w(tag_label, *(_fmt_tick(t, currency, span) for t in ticks)) + 18.0)
    gap, vol_h = (10.0, (40.0 if width < 480 else 48.0)) if show_vol else (0.0, 0.0)
    plot_w = width - ml - mr
    price_h = height - mt - mb - vol_h - gap

    def y(v: float) -> float:
        return round(mt + price_h * (1 - (v - lo) / span), 1)

    slot = plot_w / n
    body_w = max(2.0, min(16.0, slot * 0.62))

    def x(i: int) -> float:
        return round(ml + slot * (i + 0.5), 1)

    parts: list[str] = []

    # 그리드 + 우측 가격축 (최근가 태그와 겹치는 눈금 라벨은 생략)
    ly = y(last)
    for t in ticks:
        yy = y(t)
        parts.append(f'<line x1="{ml}" x2="{width - mr}" y1="{yy}" y2="{yy}" stroke="{GRID}" stroke-width="1" stroke-dasharray="3 4"/>')
        if abs(yy - ly) >= 14:
            parts.append(_text(width - mr + 8, yy + 4, _fmt_tick(t, currency, span)))

    # 거래량 (하단 영역, 봉 사이 2px 간격, 마지막 봉만 진하게)
    if show_vol:
        vmax = max(p.volume for p in shown) or 1.0
        vy0 = mt + price_h + gap
        bwv = max(1.0, slot - 2)
        for i, p in enumerate(shown):
            vy = round(vy0 + vol_h * (1 - p.volume / vmax), 1)
            parts.append(
                f'<rect x="{x(i) - bwv / 2:.1f}" y="{vy}" width="{bwv:.1f}" height="{round(vy0 + vol_h - vy, 1)}" '
                f'fill="{VOL_LAST if i == n - 1 else VOL}"/>'
            )
        base_y = vy0 + vol_h
    else:
        base_y = mt + price_h

    # 캔들 (심지 + 몸통) + 봉별 툴팁
    for i, p in enumerate(shown):
        col = UP if p.close >= p.open else DOWN
        cx = x(i)
        top = y(max(p.open, p.close))
        body_h = max(1.0, round(y(min(p.open, p.close)) - top, 1))
        tip = (
            f"{_short_date(p.date)} · 시 {fmt_price(p.open, currency)} 고 {fmt_price(p.high, currency)} "
            f"저 {fmt_price(p.low, currency)} 종 {fmt_price(p.close, currency)}"
        )
        if p.volume:
            tip += f" · 거래량 {fmt_volume(p.volume)}"
        parts.append(
            f"<g><title>{tip}</title>"
            f'<line x1="{cx}" x2="{cx}" y1="{y(p.high)}" y2="{y(p.low)}" stroke="{col}" stroke-width="1.2"/>'
            f'<rect x="{cx - body_w / 2:.1f}" y="{top}" width="{body_w:.1f}" height="{body_h}" fill="{col}"/></g>'
        )

    # 이동평균선
    for k, vs in mas.items():
        coords = [f"{x(i)},{y(v)}" for i, v in enumerate(vs) if v is not None]
        if len(coords) >= 2:
            parts.append(
                f'<polyline fill="none" stroke="{MA_COLORS.get(k, VOL_LAST)}" stroke-width="1.5" '
                f'stroke-linejoin="round" stroke-linecap="round" points="{" ".join(coords)}"/>'
            )

    # 최고·최저 라벨 (가장자리 봉은 안쪽으로 정렬해 축 눈금과 겹치지 않게)
    def anchor(i: int) -> tuple[str, float]:
        if n < 6:
            return "middle", 0.0
        if i >= n - 3:
            return "end", -4.0
        if i <= 2:
            return "start", 4.0
        return "middle", 0.0

    ih = max(range(n), key=lambda i: shown[i].high)
    il = min(range(n), key=lambda i: shown[i].low)
    ah, dh = anchor(ih)
    al, dl = anchor(il)
    parts.append(_text(x(ih) + dh, y(shown[ih].high) - 6, fmt_price(shown[ih].high, currency), ah))
    parts.append(_text(x(il) + dl, y(shown[il].low) + 14, fmt_price(shown[il].low, currency), al))

    # 최근 종가 태그
    parts.append(f'<line x1="{x(n - 1)}" x2="{width - mr}" y1="{ly}" y2="{ly}" stroke="{INK}" stroke-width="1" stroke-dasharray="2 3"/>')
    parts.append(f'<rect x="{width - mr + 4}" y="{ly - 10}" width="{mr - 8}" height="20" fill="{INK}"/>')
    parts.append(_text(width - mr + 8, ly + 4, tag_label, "start", fill="#FFFFFF", weight="700"))

    # 날짜축 + 기준선
    idxs = sorted({0, n // 4, n // 2, (3 * n) // 4, n - 1}) if n >= 5 else list(range(n))
    for i in idxs:
        parts.append(_text(x(i), height - 8, _short_date(shown[i].date), "middle"))
    parts.append(f'<line x1="{ml}" x2="{width - mr}" y1="{base_y:.1f}" y2="{base_y:.1f}" stroke="{AXIS}" stroke-width="1"/>')

    # 범례 (좁은 폭에서는 간격 축소, 거래량 안내 생략)
    narrow = width < 480
    lx = ml
    for k in ma_periods:
        label = f"MA{k}"
        parts.append(f'<line x1="{lx:.1f}" x2="{lx + 18:.1f}" y1="14" y2="14" stroke="{MA_COLORS.get(k, VOL_LAST)}" stroke-width="2"/>')
        parts.append(_text(lx + 24, 18, label))
        lx += 24 + 8 * len(label) + (10 if narrow else 16)
    up_label, down_label = ("양봉", "음봉") if narrow else ("양봉 · 상승", "음봉 · 하락")
    parts.append(f'<rect x="{lx:.1f}" y="8" width="10" height="12" fill="{UP}"/>')
    parts.append(_text(lx + 16, 18, up_label, font=FONT_KR))
    lx += 16 + (28 if narrow else 76) + (10 if narrow else 16)
    parts.append(f'<rect x="{lx:.1f}" y="8" width="10" height="12" fill="{DOWN}"/>')
    parts.append(_text(lx + 16, 18, down_label, font=FONT_KR))
    if show_vol and not narrow:
        parts.append(_text(width - mr, 18, "하단: 거래량", "end", font=FONT_KR))

    chg = ""
    if change_pct is not None:
        chg = f", 전일 대비 {'상승' if change_pct > 0 else '하락' if change_pct < 0 else '보합'} {abs(change_pct):.1f}퍼센트"
    aria = f"최근 {n}영업일 캔들차트. 최근 종가 {fmt_price(last, currency)}{chg}. 이동평균선 {', '.join(f'MA{k}' for k in ma_periods)}"
    aria += " 및 거래량 포함." if show_vol else " 포함."
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" aria-label="{aria}" '
        f'xmlns="http://www.w3.org/2000/svg" style="max-width:100%;height:auto;display:block">{"".join(parts)}</svg>'
    )


def _compact(shown: list[PricePoint], width: int, height: int) -> str:
    n = len(shown)
    hi = max(p.high for p in shown)
    lo = min(p.low for p in shown)
    span = (hi - lo) or 1.0
    slot = width / n
    body_w = max(1.5, min(10.0, slot * 0.6))

    def y(v: float) -> float:
        return round(3 + (height - 6) * (1 - (v - lo) / span), 1)

    parts = [f'<line x1="0" x2="{width}" y1="{height - 0.5}" y2="{height - 0.5}" stroke="{GRID}" stroke-width="1" vector-effect="non-scaling-stroke"/>']
    for i, p in enumerate(shown):
        col = UP if p.close >= p.open else DOWN
        cx = round(slot * (i + 0.5), 1)
        top = y(max(p.open, p.close))
        body_h = max(1.0, round(y(min(p.open, p.close)) - top, 1))
        parts.append(
            f'<line x1="{cx}" x2="{cx}" y1="{y(p.high)}" y2="{y(p.low)}" stroke="{col}" stroke-width="1" vector-effect="non-scaling-stroke"/>'
            f'<rect x="{cx - body_w / 2:.1f}" y="{top}" width="{body_w:.1f}" height="{body_h}" fill="{col}"/>'
        )
    # 비율 유지 스케일: 목록에서는 작게, 모바일에서는 셀 폭에 맞춰 크게 — 늘려 그리지 않으므로 캔들 비례가 유지된다.
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
        f'aria-label="최근 {n}영업일 미니 캔들차트" style="max-width:100%;height:auto;display:block">{"".join(parts)}</svg>'
    )


def data_table(points: Iterable[PricePoint], currency: str = "USD", window: int = 20) -> str:
    """차트 대안 텍스트용 OHLCV 표 (접근성)."""
    rows = "".join(
        f"<tr><td>{p.date}</td><td>{fmt_price(p.open, currency)}</td><td>{fmt_price(p.high, currency)}</td>"
        f"<td>{fmt_price(p.low, currency)}</td><td>{fmt_price(p.close, currency)}</td><td>{fmt_volume(p.volume) if p.volume else '—'}</td></tr>"
        for p in list(points)[-window:]
    )
    return (
        '<table class="ohlcv"><thead><tr><th>일자</th><th>시가</th><th>고가</th><th>저가</th><th>종가</th><th>거래량</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


# ── 라인 차트 (종가만 있는 시계열: 금리 · 환율 · 지수) ───────────
def fmt_unit(value: float, unit: str) -> str:
    """매크로 자산 값 표기. %는 소수 둘째 자리, 원화는 콤마+원, 달러 계열은 $."""
    if unit == "%":
        return f"{value:.2f}%"
    if unit == "KRW":
        return f"{value:,.2f}원"
    if unit == "USD":
        return f"${value:,.0f}" if abs(value) >= 1000 else f"${value:,.2f}"
    if unit.startswith("USD"):
        return f"${value:,.2f}"
    if unit.startswith("USc"):
        return f"{value:,.2f}¢"
    return f"{value:,.2f}"


def _fmt_unit_tick(value: float, unit: str, span: float) -> str:
    """라인 차트 눈금 라벨: 단위 기호 없이 짧게, 소수 자릿수는 값 범위에 맞춘다."""
    if unit == "%":
        return f"{value:.2f}"
    if unit == "KRW":
        return f"{value:,.0f}"
    return _fmt_tick(value, "USD", span)


def line_chart(points: Iterable[PricePoint], *, unit: str = "", window: int = 20, width: int = 680, height: int = 260,
               compact: bool = False, change_pct: Optional[float] = None, color: Optional[str] = None) -> str:
    """종가 라인 차트 — 네이비 선, 점선 그리드, 우측 값축, 날짜축, 최근값 태그. compact 는 목록용 스파크라인."""
    pts = list(points)
    if not pts:
        return empty(width, height)
    shown = pts[-window:]
    n = len(shown)
    vals = [p.close for p in shown]
    if compact:
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or abs(hi) * 0.01 or 1.0
        xs = [round(width / max(1, n - 1) * i, 1) for i in range(n)]
        ys = [round(2 + (height - 4) * (1 - (v - lo) / span), 1) for v in vals]
        col = color or (UP if vals[-1] >= vals[0] else DOWN)
        pl = " ".join(f"{x},{y}" for x, y in zip(xs, ys))
        return (f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
                f'aria-label="최근 {n}일 추이" style="max-width:100%;height:auto;display:block">'
                f'<line x1="0" x2="{width}" y1="{height - 0.5}" y2="{height - 0.5}" stroke="{GRID}" stroke-width="1" vector-effect="non-scaling-stroke"/>'
                f'<polyline fill="none" stroke="{col}" stroke-width="2" stroke-linejoin="round" vector-effect="non-scaling-stroke" points="{pl}"/>'
                f'<circle cx="{xs[-1]}" cy="{ys[-1]}" r="3.5" fill="{col}"/></svg>')

    hi, lo = max(vals), min(vals)
    pad = (hi - lo) * 0.1 or abs(hi) * 0.01 or 1.0
    hi, lo = hi + pad, lo - pad
    span = hi - lo
    ticks = _nice_ticks(lo, hi, 4)
    last = vals[-1]
    tag_label = fmt_unit(last, unit)
    tick_labels = [_fmt_unit_tick(t, unit, span) for t in ticks]
    ml, mt, mb = 10.0, 18.0, 26.0
    mr = max(62.0 if width < 480 else 76.0, _label_w(tag_label, *tick_labels) + 18.0)
    plot_w, plot_h = width - ml - mr, height - mt - mb

    def y(v: float) -> float:
        return round(mt + plot_h * (1 - (v - lo) / span), 1)

    def x(i: int) -> float:
        return round(ml + plot_w * (i / max(1, n - 1)), 1)

    parts: list[str] = []
    ly = y(last)
    for tick, label in zip(ticks, tick_labels):
        yy = y(tick)
        parts.append(f'<line x1="{ml}" x2="{width - mr}" y1="{yy}" y2="{yy}" stroke="{GRID}" stroke-width="1" stroke-dasharray="3 4"/>')
        if abs(yy - ly) >= 14:  # 최근값 태그와 겹치는 눈금 라벨은 생략
            parts.append(_text(width - mr + 8, yy + 4, label))
    pl = " ".join(f"{x(i)},{y(v)}" for i, v in enumerate(vals))
    parts.append(f'<polyline fill="none" stroke="#043B72" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" points="{pl}"/>')
    for i, p in enumerate(shown):
        parts.append(f'<g><title>{_short_date(p.date)} · {fmt_unit(p.close, unit)}</title>'
                     f'<circle cx="{x(i)}" cy="{y(p.close)}" r="{3 if i == n - 1 else 2}" fill="#043B72"/></g>')
    parts.append(f'<rect x="{width - mr + 4}" y="{ly - 10}" width="{mr - 8}" height="20" fill="{INK}"/>')
    parts.append(_text(width - mr + 8, ly + 4, tag_label, "start", fill="#FFFFFF", weight="700"))
    idxs = sorted({0, n // 4, n // 2, (3 * n) // 4, n - 1}) if n >= 5 else list(range(n))
    for i in idxs:
        parts.append(_text(x(i), height - 8, _short_date(shown[i].date), "middle"))
    parts.append(f'<line x1="{ml}" x2="{width - mr}" y1="{mt + plot_h:.1f}" y2="{mt + plot_h:.1f}" stroke="{AXIS}" stroke-width="1"/>')
    chg = ""
    if change_pct is not None:
        chg = f", 전일 대비 {'상승' if change_pct > 0 else '하락' if change_pct < 0 else '보합'}"
    aria = f"최근 {n}일 추이 라인 차트. 최근 값 {fmt_unit(last, unit)}{chg}."
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" aria-label="{aria}" '
            f'xmlns="http://www.w3.org/2000/svg" style="max-width:100%;height:auto;display:block">{"".join(parts)}</svg>')
