"""간단한 인라인 SVG 차트 생성 (외부 라이브러리/JS/CDN 불필요).

생성된 SVG는 정적 HTML에 그대로 삽입되어 오프라인에서도 렌더링된다.
상승/하락 색상은 CSS 변수(--up / --down)를 참조하여 라이트/다크 모두 대응.
"""

from __future__ import annotations

from typing import Optional

_UP = "var(--up, #16a34a)"
_DOWN = "var(--down, #dc2626)"
_FLAT = "var(--muted, #6b7280)"


def _color(up: Optional[bool]) -> str:
    if up is None:
        return _FLAT
    return _UP if up else _DOWN


def _points(values: list[float], width: float, height: float, pad: float) -> list[tuple[float, float]]:
    n = len(values)
    if n == 0:
        return []
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad
    if n == 1:
        return [(width / 2, height / 2)]
    coords = []
    for i, v in enumerate(values):
        x = pad + inner_w * (i / (n - 1))
        y = pad + inner_h * (1 - (v - lo) / span)
        coords.append((round(x, 2), round(y, 2)))
    return coords


def sparkline(values: list[float], up: Optional[bool] = None, width: int = 160, height: int = 44) -> str:
    """카드용 미니 스파크라인 (축/라벨 없음)."""
    if not values:
        return _empty(width, height)
    pad = 3.0
    coords = _points(values, width, height, pad)
    color = _color(up)
    line = " ".join(f"{x},{y}" for x, y in coords)
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'preserveAspectRatio="none" role="img" aria-label="가격 추이 스파크라인" '
        f'style="max-width:100%;height:auto">'
        f'<polyline fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{line}"/>'
        f"</svg>"
    )


def line_chart(
    values: list[float],
    dates: Optional[list[str]] = None,
    up: Optional[bool] = None,
    width: int = 680,
    height: int = 260,
) -> str:
    """상세 페이지용 종가 라인 차트 (면 그라데이션 + 최소 축 라벨)."""
    if not values:
        return _empty(width, height)
    pad = 40.0  # 좌측 y축 값 라벨이 잘리지 않도록 여유 확보
    coords = _points(values, width, height, pad)
    color = _color(up)
    line = " ".join(f"{x},{y}" for x, y in coords)

    # 면(area) 채우기 경로
    first_x = coords[0][0]
    last_x = coords[-1][0]
    base_y = height - pad
    area = f"M {first_x},{base_y} " + " ".join(f"L {x},{y}" for x, y in coords) + f" L {last_x},{base_y} Z"

    lo, hi = min(values), max(values)
    grad_id = f"g{abs(hash((round(lo, 3), round(hi, 3), len(values)))) % 100000}"

    # 최저/최고 값 라벨 (좌측 여백 안쪽에 정렬)
    labels = []
    labels.append(_axis_label(4, pad + 4, f"{hi:,.2f}", anchor="start"))
    labels.append(_axis_label(4, height - pad + 4, f"{lo:,.2f}", anchor="start"))
    if dates and len(dates) == len(values):
        labels.append(_axis_label(coords[0][0], height - 6, dates[0], anchor="start"))
        labels.append(_axis_label(coords[-1][0], height - 6, dates[-1], anchor="end"))

    # 마지막 점 강조
    lx, ly = coords[-1]
    dot = f'<circle cx="{lx}" cy="{ly}" r="3.5" fill="{color}"/>'

    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="최근 종가 추이 차트" '
        f'style="max-width:100%;height:auto;display:block">'
        f'<defs><linearGradient id="{grad_id}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.28"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/>'
        f"</linearGradient></defs>"
        f'<path d="{area}" fill="url(#{grad_id})" stroke="none"/>'
        f'<polyline fill="none" stroke="{color}" stroke-width="2.2" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{line}"/>'
        f"{dot}"
        f"{''.join(labels)}"
        f"</svg>"
    )


def _axis_label(x: float, y: float, text: str, anchor: str = "start") -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="10" text-anchor="{anchor}" '
        f'fill="var(--muted, #6b7280)" font-family="inherit">{text}</text>'
    )


def _empty(width: int, height: int) -> str:
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="차트 없음" style="max-width:100%;height:auto">'
        f'<text x="{width/2}" y="{height/2}" font-size="12" text-anchor="middle" '
        f'fill="var(--muted, #6b7280)">차트 데이터 없음</text></svg>'
    )


def candlestick(points, up: Optional[bool] = None, width: int = 680, height: int = 280) -> str:
    """OHLC 봉차트(캔들스틱). points: PricePoint 리스트.

    각 봉은 자기 자신의 시가/종가로 색이 결정된다(양봉=상승색, 음봉=하락색).
    상승/하락 색은 페이지 CSS 변수(--up/--down)를 따르므로 한국식(상승 빨강/
    하락 파랑) 등 페이지 설정을 그대로 반영한다.
    """
    if not points:
        return _empty(width, height)

    pad_l, pad_r, pad_t, pad_b = 46.0, 10.0, 12.0, 26.0
    highs = [p.high for p in points]
    lows = [p.low for p in points]
    hi, lo = max(highs), min(lows)
    span = (hi - lo) or 1.0
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    n = len(points)
    slot = inner_w / n if n else inner_w
    body_w = max(2.0, min(16.0, slot * 0.62))

    def y(v: float) -> float:
        return round(pad_t + inner_h * (1 - (v - lo) / span), 2)

    parts: list[str] = []
    for i, p in enumerate(points):
        cx = round(pad_l + slot * (i + 0.5), 2)
        rising = p.close >= p.open
        col = _UP if rising else _DOWN
        yh, yl = y(p.high), y(p.low)
        yo, yc = y(p.open), y(p.close)
        top = min(yo, yc)
        bh = max(1.0, round(max(yo, yc) - top, 2))
        x0 = round(cx - body_w / 2, 2)
        # 심지(고가~저가) + 몸통(시가~종가)
        parts.append(
            f'<line x1="{cx}" y1="{yh}" x2="{cx}" y2="{yl}" stroke="{col}" stroke-width="1.2"/>'
        )
        parts.append(
            f'<rect x="{x0}" y="{top}" width="{round(body_w,2)}" height="{bh}" fill="{col}" rx="1"/>'
        )

    labels = [
        _axis_label(4, pad_t + 4, f"{hi:,.2f}", anchor="start"),
        _axis_label(4, height - pad_b + 4, f"{lo:,.2f}", anchor="start"),
        _axis_label(pad_l, height - 6, points[0].date, anchor="start"),
        _axis_label(width - pad_r, height - 6, points[-1].date, anchor="end"),
    ]

    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="최근 종가 봉차트" '
        f'style="max-width:100%;height:auto;display:block">'
        f"{''.join(parts)}{''.join(labels)}"
        f"</svg>"
    )
