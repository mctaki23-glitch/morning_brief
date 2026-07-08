"""종목 마스터: 종목명(별칭 포함) ↔ 티커 매핑 및 본문 스캔."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_DATA = Path(__file__).parent / "data" / "stocks.json"


@dataclass
class StockEntry:
    ticker: str
    market: str
    names: list[str]

    @property
    def display_name(self) -> str:
        return self.names[0]


class StockMaster:
    def __init__(self, entries: list[StockEntry]):
        self.entries = entries
        self._by_ticker: dict[str, StockEntry] = {e.ticker: e for e in entries}
        # 별칭 → 엔트리. 긴 별칭 우선 매칭을 위해 길이 내림차순 정렬.
        self._alias_pairs: list[tuple[str, StockEntry]] = []
        for entry in entries:
            for name in entry.names:
                self._alias_pairs.append((name, entry))
        self._alias_pairs.sort(key=lambda p: len(p[0]), reverse=True)
        self._alias_lower: dict[str, StockEntry] = {
            name.lower(): entry for name, entry in self._alias_pairs
        }

    @classmethod
    def load(cls, path: Path | str = _DATA) -> "StockMaster":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        entries = [StockEntry(ticker=r["ticker"], market=r["market"], names=r["names"]) for r in raw]
        return cls(entries)

    def resolve(self, name_or_ticker: Optional[str]) -> Optional[StockEntry]:
        """이름/티커 문자열을 엔트리로 해석."""
        if not name_or_ticker:
            return None
        key = name_or_ticker.strip()
        if key in self._by_ticker:
            return self._by_ticker[key]
        entry = self._alias_lower.get(key.lower())
        if entry:
            return entry
        # 부분 포함 (예: "삼성전자우" → 삼성전자)
        for alias, entry in self._alias_pairs:
            if alias.lower() in key.lower():
                return entry
        return None

    def scan(self, text: str) -> list[StockEntry]:
        """본문에서 언급된 종목 엔트리를 등장 순서대로 (중복 제거) 반환."""
        found: list[StockEntry] = []
        seen: set[str] = set()
        lower = text.lower()
        for alias, entry in self._alias_pairs:
            if entry.ticker in seen:
                continue
            # 영문 티커/약칭은 단어 경계로, 한글명은 부분 매칭 허용.
            if re.fullmatch(r"[A-Za-z]+", alias):
                pattern = r"\b" + re.escape(alias.lower()) + r"\b"
                hit = re.search(pattern, lower) is not None
            elif len(alias) <= 1:
                # 1글자 한글 별칭은 다른 단어의 일부로 오탐하기 쉬워 제외.
                hit = False
            else:
                hit = alias in text
            if hit:
                found.append(entry)
                seen.add(entry.ticker)
        return found
