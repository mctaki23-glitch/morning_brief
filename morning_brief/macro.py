"""매크로 자산(금리 · 유가 · 금 · 환율 · 원자재 · 비트코인) 언급 추출.

브리핑의 FICC 문단 등에서 자산별 코멘트 문장을 찾아 종목 서머리와 같은 구조(StockMention, kind="macro")로 만든다.
시세는 macro_prices 가 채운다. 자산 정의는 data/macro.json.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import summarize as _s
from .models import StockMention

_DATA = Path(__file__).parent / "data" / "macro.json"
_PCT_MOVE_RE = re.compile(r"([+\-−]?\d+(?:\.\d+)?)\s*%\s*대?\s*(?:가까이|넘게|이상)?\s*(상승|하락|급등|급락|강세|약세|올|내|반등|밀)")


@dataclass
class MacroInstrument:
    id: str
    name: str
    unit: str
    aliases: list[str] = field(default_factory=list)
    pattern: str = ""
    sources: list[list[str]] = field(default_factory=list)

    def regex(self) -> re.Pattern:
        if self.pattern:
            return re.compile(self.pattern)
        return re.compile("|".join(re.escape(a) for a in sorted(self.aliases, key=len, reverse=True)))


def load_instruments(path: Path | str = _DATA) -> list[MacroInstrument]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [MacroInstrument(id=r["id"], name=r["name"], unit=r.get("unit", ""), aliases=r.get("aliases", []),
                            pattern=r.get("pattern", ""), sources=r.get("sources", [])) for r in raw]


def by_id(instruments: list[MacroInstrument]) -> dict[str, MacroInstrument]:
    return {i.id: i for i in instruments}


def _section_start(text: str, marker: str) -> int:
    m = re.search(marker, text)
    return m.start() if m else -1


def extract_macros(text: str, instruments: Optional[list[MacroInstrument]] = None) -> list[StockMention]:
    """자산별로 가장 알맞은 문장(FICC 섹션 · 등락 서술 우선)을 골라 코멘트로 삼는다. 언급이 없으면 제외."""
    instruments = instruments or load_instruments()
    text = _s._normalize(text)
    spans = _s._sentence_spans(text)
    ficc = _section_start(text, r"\n\s*\*\s*FICC")
    others = [(i.id, i.regex()) for i in instruments]
    out: list[StockMention] = []
    for inst in instruments:
        rx = inst.regex()
        hits = [(a, s) for a, b, s in spans if rx.search(s) and not _s._is_header(s)]
        if not hits:
            continue

        def score(h):
            a, s = h
            return (0 if (ficc >= 0 and a >= ficc) else 1, 0 if _s._MOVE_RE.search(s) else 1, a)

        hits.sort(key=score)
        pos, sent = hits[0]
        pct = None if inst.unit in ("%", "pt") else _pct_move(sent)
        if pct is None and inst.unit not in ("%", "pt"):
            # 대표 문장에 등락률이 없으면 바로 뒤에 이어지는 같은 문단의 문장(예: '장 마감 앞두고 … 1%대 상승')에서 가져온다.
            # 다른 자산을 언급하는 문장(예: '금은 … 0.8% 하락')이 나오면 거기서 멈춘다.
            pct = _continuation_pct(text, spans, pos, [r for i2, r in others if i2 != inst.id])
        if pct is not None and pct != 0:
            direction = "UP" if pct > 0 else "DOWN"  # 명시 등락률이 있으면 그 부호가 방향
        else:
            direction = _s._direction(sent)
        out.append(StockMention(
            name=inst.name, ticker=inst.id, market="MACRO", kind="macro", unit=inst.unit, direction=direction,
            change_pct=pct, reason_summary=_s._clean_reason(sent), evidence=sent[:400], evidence_verified=True, order=pos,
        ))
    out.sort(key=lambda m: m.order)
    return out


def _continuation_pct(text: str, spans: list[tuple[int, int, str]], start: int, other_rx: list[re.Pattern]) -> Optional[float]:
    """start 위치 문장 뒤에 같은 문단(줄바꿈 없이)으로 이어지는 문장들에서 등락률을 찾는다. 다른 자산이 등장하면 중단."""
    idx = next((k for k, (a, _, _) in enumerate(spans) if a == start), None)
    if idx is None:
        return None
    prev_end = spans[idx][1]
    for a, b, sent in spans[idx + 1:]:
        if "\n" in text[prev_end:a] or _s._is_header(sent) or any(rx.search(sent) for rx in other_rx):
            return None
        pct = _pct_move(sent)
        if pct is not None:
            return pct
        prev_end = b
    return None


def _pct_move(sentence: str) -> Optional[float]:
    """'2% 하락', '4%대 상승', '1%대 상승' → 부호 있는 등락률. 수준 표기(4.8%를 기록)는 제외."""
    m = _PCT_MOVE_RE.search(sentence)
    if not m:
        return None
    try:
        v = abs(float(m.group(1).replace("−", "-")))
    except ValueError:
        return None
    return -v if m.group(2) in ("하락", "급락", "약세", "내", "밀") else v
