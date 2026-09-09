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
            # 대표 문장에 등락률이 없으면 같은 자산을 다룬 다른 문장(예: '… 1%대 상승')에서 가져온다
            for _, other in hits[1:]:
                pct = _pct_move(other)
                if pct is not None:
                    break
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
