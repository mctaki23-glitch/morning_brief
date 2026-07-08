"""브리핑 원문 → 시황 요약 + 종목별 등락 이유 구조화.

- ANTHROPIC_API_KEY가 있고 anthropic SDK가 설치돼 있으면 Claude로 구조화 추출.
- 없으면 규칙 기반(rule-based) 폴백: 종목 마스터로 언급 종목을 찾고,
  주변 문장을 등락 이유로 추출한다. (오프라인/무키 환경에서도 동작)
"""

from __future__ import annotations

import re
from typing import Optional

from .config import Config
from .models import IndexSnapshot, StockMention
from .stock_master import StockMaster

# ── 결과 컨테이너 ─────────────────────────────────────────────
class SummaryResult:
    def __init__(
        self,
        overview: str,
        indices: list[IndexSnapshot],
        stocks: list[StockMention],
        summarizer: str,
    ):
        self.overview = overview
        self.indices = indices
        self.stocks = stocks
        self.summarizer = summarizer


def summarize(text: str, cfg: Config, master: StockMaster) -> SummaryResult:
    if cfg.has_claude:
        try:
            return _summarize_with_claude(text, cfg, master)
        except Exception as exc:  # noqa: BLE001 - LLM 실패 시 규칙 기반 폴백
            print(f"[summarize] Claude 요약 실패({exc!r}); 규칙 기반으로 폴백합니다.")
    return _summarize_rule_based(text, master)


# ── Claude 기반 구조화 추출 ───────────────────────────────────
_EXTRACT_TOOL = {
    "name": "extract_brief",
    "description": "주식 브리핑에서 시황 요약, 주요 지수, 언급 종목과 등락 이유를 추출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "market_overview": {
                "type": "string",
                "description": "당일 시황을 2~4문장으로 요약 (한국어).",
            },
            "indices": {
                "type": "array",
                "description": "주요 지수 스냅샷 (다우/S&P500/나스닥/SOX/코스피 등).",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "change_pct": {"type": "number", "description": "등락률(%). 상승은 양수, 하락은 음수."},
                    },
                    "required": ["name"],
                },
            },
            "stocks": {
                "type": "array",
                "description": "브리핑에서 언급된 종목들.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "종목명(한글 우선)."},
                        "ticker": {"type": "string", "description": "티커/종목코드(알면)."},
                        "market": {"type": "string", "enum": ["US", "KR"]},
                        "direction": {"type": "string", "enum": ["UP", "DOWN", "FLAT"]},
                        "change_pct": {"type": "number", "description": "등락률(%). 알면."},
                        "reason": {"type": "string", "description": "등락 이유를 1~2문장으로 요약(한국어)."},
                    },
                    "required": ["name", "direction", "reason"],
                },
            },
        },
        "required": ["market_overview", "indices", "stocks"],
    },
}

_SYSTEM = (
    "당신은 증권사 리서치 어시스턴트입니다. 서상영 애널리스트의 미국 증시 시황 브리핑(초장문 한국어) "
    "원문을 읽고, 시황 요약과 언급 종목별 등락 이유를 정확히 추출합니다. "
    "원문에 없는 사실을 지어내지 말고, 등락 방향과 이유는 본문 근거에 충실하게 작성하세요. "
    "투자 추천/매매 의견은 넣지 마세요."
)


def _summarize_with_claude(text: str, cfg: Config, master: StockMaster) -> SummaryResult:
    import anthropic  # 선택적 의존성

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    resp = client.messages.create(
        model=cfg.model,
        max_tokens=8000,
        system=_SYSTEM,
        tools=[_EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_brief"},
        messages=[
            {
                "role": "user",
                "content": (
                    "다음은 오늘 텔레그램에 올라온 시황 브리핑 원문입니다. "
                    "extract_brief 도구로 구조화해 주세요.\n\n<브리핑>\n" + text + "\n</브리핑>"
                ),
            }
        ],
    )
    data = next((b.input for b in resp.content if b.type == "tool_use"), None)
    if not data:
        raise RuntimeError("tool_use 블록을 찾지 못했습니다.")

    indices = [
        IndexSnapshot(name=i.get("name", ""), change_pct=i.get("change_pct"))
        for i in data.get("indices", [])
        if i.get("name")
    ]

    stocks: list[StockMention] = []
    for s in data.get("stocks", []):
        entry = master.resolve(s.get("ticker") or s.get("name"))
        ticker = (s.get("ticker") or (entry.ticker if entry else None)) or None
        market = s.get("market") or (entry.market if entry else "US")
        stocks.append(
            StockMention(
                name=s.get("name", entry.display_name if entry else "?"),
                ticker=ticker,
                market=market,
                direction=s.get("direction", "FLAT"),
                change_pct=s.get("change_pct"),
                reason_summary=s.get("reason", ""),
                reason_context="",
            )
        )

    return SummaryResult(
        overview=data.get("market_overview", "").strip(),
        indices=indices,
        stocks=stocks,
        summarizer="claude",
    )


# ── 규칙 기반 폴백 ───────────────────────────────────────────
_INDEX_NAMES = ["다우", "S&P500", "S&P", "나스닥", "필라델피아 반도체", "SOX", "코스피", "코스닥", "러셀"]
_UP_WORDS = ["상승", "급등", "강세", "올랐", "올라", "반등", "상승 출발", "우호"]
_DOWN_WORDS = ["하락", "급락", "약세", "내렸", "내려", "밀렸", "부진"]

_PCT_RE = re.compile(r"([+\-−]?\d+(?:\.\d+)?)\s*%")
_SENT_SPLIT = re.compile(r"(?<=[.。!?\n])\s+")


def _summarize_rule_based(text: str, master: StockMaster) -> SummaryResult:
    overview = _extract_overview(text)
    indices = _extract_indices(text)
    stocks = _extract_stocks(text, master)
    return SummaryResult(overview=overview, indices=indices, stocks=stocks, summarizer="rule-based")


def _extract_overview(text: str) -> str:
    """'시황 요약' 섹션이 있으면 그 문단을, 없으면 앞부분 문장을 사용."""
    m = re.search(r"시황\s*요약\s*\n?(.+?)(?:\n\s*\n|\n■|\n-)", text, re.DOTALL)
    if m:
        body = re.sub(r"\s+", " ", m.group(1)).strip()
        return body[:400]
    # 폴백: 앞부분에서 의미있는 문장 2~3개
    body = re.sub(r"\s+", " ", text).strip()
    sentences = _SENT_SPLIT.split(body)
    picked = " ".join(sentences[:3])
    return picked[:400]


def _extract_indices(text: str) -> list[IndexSnapshot]:
    result: list[IndexSnapshot] = []
    seen: set[str] = set()
    for name in _INDEX_NAMES:
        if name == "S&P" and "S&P500" in text:
            continue
        if name == "SOX" and "필라델피아 반도체" in text:
            continue  # 필라델피아 반도체지수와 동일 → 중복 제거
        idx = text.find(name)
        if idx == -1 or name in seen:
            continue
        window = text[idx : idx + 40]
        pct = _first_pct(window)
        result.append(IndexSnapshot(name=("S&P500" if name == "S&P" else name), change_pct=pct))
        seen.add(name)
    return result


def _extract_stocks(text: str, master: StockMaster) -> list[StockMention]:
    entries = master.scan(text)
    blocks = _split_blocks(text)  # 소프트 랩된 불릿/문단을 하나의 논리 블록으로
    mentions: list[StockMention] = []
    for entry in entries:
        ctx_blocks = [b for b in blocks if _mentions_entry(b, entry)]
        if not ctx_blocks:
            continue
        context = " ".join(ctx_blocks).strip()
        # 이유 요약: 종목이 언급된 첫 블록의 첫 문장
        first_block = ctx_blocks[0]
        reason = _SENT_SPLIT.split(first_block)[0].strip() or first_block
        direction = _direction(context)
        pct = _signed_pct(context, direction)
        mentions.append(
            StockMention(
                name=entry.display_name,
                ticker=entry.ticker,
                market=entry.market,
                direction=direction,
                change_pct=pct,
                reason_summary=_clean_reason(reason),
                reason_context=context[:600],
            )
        )
    return mentions


def _split_blocks(text: str) -> list[str]:
    """텍스트를 논리 블록(불릿 항목/문단)으로 분할. 소프트 랩된 줄은 이어붙인다."""
    blocks: list[str] = []
    cur: list[str] = []

    def flush() -> None:
        if cur:
            blocks.append(" ".join(cur).strip())
            cur.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line[0] in "-•·■※▶":  # 새 불릿/섹션 → 새 블록 시작
            flush()
            cur.append(line.lstrip("-•·■※▶ \t").strip())
        else:
            cur.append(line)  # 연속 줄은 현재 블록에 이어붙임
    flush()
    return [b for b in blocks if b]


def _mentions_entry(block: str, entry) -> bool:
    low = block.lower()
    for alias in entry.names:
        if re.fullmatch(r"[A-Za-z]+", alias):
            if re.search(r"\b" + re.escape(alias.lower()) + r"\b", low):
                return True
        elif len(alias) <= 1:
            continue
        elif alias in block:
            return True
    return False


def _direction(context: str) -> str:
    up = sum(context.count(w) for w in _UP_WORDS)
    down = sum(context.count(w) for w in _DOWN_WORDS)
    pct = _first_pct(context)
    if pct is not None:
        if pct > 0:
            up += 2
        elif pct < 0:
            down += 2
    if up > down:
        return "UP"
    if down > up:
        return "DOWN"
    return "FLAT"


def _signed_pct(context: str, direction: str) -> Optional[float]:
    pct = _first_pct(context)
    if pct is None:
        return None
    # '-1.3%' 처럼 명시 부호가 있으면 그대로, 없으면 방향으로 부호 부여
    if pct == abs(pct) and direction == "DOWN":
        return -abs(pct)
    return pct


def _first_pct(s: str) -> Optional[float]:
    m = _PCT_RE.search(s)
    if not m:
        return None
    raw = m.group(1).replace("−", "-")
    try:
        return float(raw)
    except ValueError:
        return None


def _clean_reason(sentence: str) -> str:
    s = re.sub(r"\s+", " ", sentence).strip()
    return s[:200]
