"""브리핑 원문 → 시황 요약 + 지수 + 종목별 등락 이유(원문 근거 포함) + 한국 증시 관전 포인트.

- ANTHROPIC_API_KEY 가 있고 anthropic SDK 가 설치돼 있으면 Claude 도구 호출(구조화 출력)로 추출한다.
  추출된 근거 발췌(evidence)는 원문과 문자열 대조로 검증하고, 실패한 종목은 규칙 기반 발췌로 대체한다.
- 없으면 규칙 기반(rule-based) 폴백: 종목 마스터로 언급 종목을 찾고 주변 문장을 등락 이유·근거로 쓴다.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Optional

from .config import Config
from .models import IndexSnapshot, StockMention
from .stock_master import StockEntry, StockMaster

PROMPT_VERSION = "2026-09-09.1"


@dataclass
class SummaryResult:
    overview: str
    indices: list[IndexSnapshot]
    stocks: list[StockMention]
    summarizer: str  # claude | rule-based
    kr_outlook: str = ""
    model: str = ""
    prompt_version: str = ""
    unmapped: list[str] = field(default_factory=list)
    evidence_failures: list[str] = field(default_factory=list)


def summarize(text: str, cfg: Config, master: StockMaster) -> SummaryResult:
    if cfg.has_claude:
        try:
            return _summarize_with_claude(text, cfg, master)
        except Exception as exc:  # noqa: BLE001 - LLM 실패 시 규칙 기반 폴백
            print(f"[summarize] Claude 요약 실패({exc!r}); 규칙 기반으로 폴백합니다.")
    return summarize_rule_based(text, master)


# ── 근거 검증 ──────────────────────────────────────────────────
def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s or "").lower()


def verify_evidence(evidence: str, raw: str) -> bool:
    """근거 발췌가 원문에 실제로 존재하는지 확인. 공백·문장부호 차이는 무시하고,
    부분 인용은 원문 문장과의 유사도(0.85 이상)로 허용한다."""
    ev = _norm(evidence)
    if len(ev) < 6:
        return False
    body = _norm(raw)
    if ev in body:
        return True
    # 문장 단위 유사도 (LLM 이 따옴표·조사 등을 살짝 바꾼 경우)
    for sent in _sentences(raw):
        ns = _norm(sent)
        if not ns:
            continue
        if ev in ns or ns in ev:
            return True
        if difflib.SequenceMatcher(None, ev, ns).ratio() >= 0.85:
            return True
    return False


# ── Claude 기반 구조화 추출 ───────────────────────────────────
_EXTRACT_TOOL = {
    "name": "extract_brief",
    "description": "주식 시황 브리핑에서 시황 요약, 주요 지수, 언급 종목과 등락 이유(원문 근거 포함), 한국 증시 관전 포인트를 추출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "market_overview": {"type": "string", "description": "당일 미국 증시 시황을 2~4문장으로 요약 (한국어)."},
            "kr_outlook": {"type": "string", "description": "한국 증시 관전 포인트·투자심리 지표 요약 1~3문장 (한국어). 없으면 빈 문자열."},
            "indices": {
                "type": "array",
                "description": "주요 지수 스냅샷 (다우/S&P500/나스닥/필라델피아 반도체/러셀2000/코스피/코스닥 등). 이름은 한글 표기.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "value": {"type": "number", "description": "지수 값(알면)."},
                        "change_pct": {"type": "number", "description": "등락률(%). 상승은 양수, 하락은 음수."},
                    },
                    "required": ["name"],
                },
            },
            "stocks": {
                "type": "array",
                "description": "브리핑에서 등락 이유와 함께 언급된 개별 종목 (지수·ETF·업종명은 제외). 본문 등장 순서대로.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "종목명(한글 우선)."},
                        "ticker": {"type": "string", "description": "티커(미국) 또는 6자리 종목코드(한국). 확실할 때만."},
                        "market": {"type": "string", "enum": ["US", "KR"]},
                        "direction": {"type": "string", "enum": ["UP", "DOWN", "FLAT"]},
                        "change_pct": {"type": "number", "description": "본문에 명시된 등락률(%). 명시된 경우만."},
                        "reason": {"type": "string", "description": "등락 이유를 1~2문장으로 요약(한국어). 원문에 없는 내용 금지."},
                        "evidence": {"type": "string", "description": "등락 이유의 근거가 되는 원문 문장을 그대로 발췌(1~2문장, 수정 금지)."},
                    },
                    "required": ["name", "market", "direction", "reason", "evidence"],
                },
            },
        },
        "required": ["market_overview", "kr_outlook", "indices", "stocks"],
    },
}

_SYSTEM = (
    "당신은 증권사 리서치 어시스턴트입니다. 서상영 애널리스트의 미국 증시 시황 브리핑(초장문 한국어) 원문을 읽고, "
    "시황 요약과 언급 종목별 등락 이유를 정확히 추출합니다. 원문에 없는 사실을 지어내지 말고, 등락 방향과 이유는 "
    "본문 근거에 충실하게 작성하세요. evidence 는 원문 문장을 글자 그대로 발췌해야 합니다. "
    "투자 추천/매매 의견은 넣지 마세요."
)


def _summarize_with_claude(text: str, cfg: Config, master: StockMaster) -> SummaryResult:
    import anthropic  # 선택적 의존성

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    resp = client.messages.create(
        model=cfg.model,
        max_tokens=16000,
        system=_SYSTEM,
        tools=[_EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_brief"},
        messages=[{
            "role": "user",
            "content": ("다음은 오늘 텔레그램에 올라온 시황 브리핑 원문입니다. extract_brief 도구로 구조화해 주세요.\n\n"
                        "<브리핑>\n" + text + "\n</브리핑>"),
        }],
    )
    data = next((b.input for b in resp.content if b.type == "tool_use"), None)
    if not data:
        raise RuntimeError("tool_use 블록을 찾지 못했습니다.")

    indices = [
        IndexSnapshot(name=i.get("name", ""), value=i.get("value"), change_pct=i.get("change_pct"))
        for i in data.get("indices", []) if i.get("name")
    ]
    rule_based = {m.ticker or m.name: m for m in _extract_stocks(text, master)}

    stocks: list[StockMention] = []
    unmapped: list[str] = []
    failures: list[str] = []
    for order, s in enumerate(data.get("stocks", [])):
        entry = master.resolve(s.get("ticker") or s.get("name"))
        ticker = (s.get("ticker") or (entry.ticker if entry else None)) or None
        if ticker and entry is None:
            entry = master.resolve(ticker)
        name = s.get("name") or (entry.display_name if entry else "?")
        if not ticker:
            unmapped.append(name)
        evidence = (s.get("evidence") or "").strip()
        verified = verify_evidence(evidence, text)
        reason = (s.get("reason") or "").strip()
        if not verified:
            failures.append(name)
            fallback = rule_based.get(ticker or name)
            if fallback is not None:
                evidence, reason = fallback.evidence, fallback.reason_summary or reason
                verified = True
        stocks.append(StockMention(
            name=name, ticker=ticker, market=s.get("market") or (entry.market if entry else "US"),
            direction=s.get("direction", "FLAT"), change_pct=s.get("change_pct"),
            reason_summary=reason, evidence=evidence, evidence_verified=verified,
            order=_first_position(text, entry, name, default=order),
        ))

    return SummaryResult(
        overview=(data.get("market_overview") or "").strip(), indices=indices, stocks=stocks,
        summarizer="claude", kr_outlook=(data.get("kr_outlook") or "").strip(), model=cfg.model,
        prompt_version=PROMPT_VERSION, unmapped=unmapped, evidence_failures=failures,
    )


# ── 규칙 기반 폴백 ───────────────────────────────────────────
_INDEX_NAMES = ["다우", "S&P500", "S&P", "나스닥", "필라델피아 반도체", "SOX", "러셀", "코스피", "코스닥"]
_UP_WORDS = ["상승", "급등", "강세", "올랐", "올라", "반등", "상승 출발", "우호"]
_DOWN_WORDS = ["하락", "급락", "약세", "내렸", "내려", "밀렸", "부진"]

_PCT_RE = re.compile(r"([+\-−]?\d+(?:\.\d+)?)\s*%")
_SENT_SPLIT = re.compile(r"(?<=[.。!?\n])\s+")


def summarize_rule_based(text: str, master: StockMaster) -> SummaryResult:
    return SummaryResult(
        overview=_extract_overview(text), indices=_extract_indices(text), stocks=_extract_stocks(text, master),
        summarizer="rule-based", kr_outlook=_extract_kr_outlook(text), prompt_version=PROMPT_VERSION,
    )


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(re.sub(r"[ \t]+", " ", text)) if s.strip()]


def _extract_overview(text: str) -> str:
    """'시황 요약' 섹션이 있으면 그 문단을, 없으면 앞부분 문장을 사용."""
    m = re.search(r"시황\s*요약\s*\n?(.+?)(?:\n\s*\n|\n■|\n-)", text, re.DOTALL)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:400]
    body = re.sub(r"\s+", " ", text).strip()
    return " ".join(_SENT_SPLIT.split(body)[:3])[:400]


def _extract_kr_outlook(text: str) -> str:
    m = re.search(r"한국\s*증시[^\n]*(?:관전|포인트|전망)[^\n]*\n(.+?)(?:\n\s*※|\Z)", text, re.DOTALL)
    if not m:
        return ""
    return re.sub(r"[ \t]+", " ", m.group(1)).strip()[:600]


def _extract_indices(text: str) -> list[IndexSnapshot]:
    result: list[IndexSnapshot] = []
    seen: set[str] = set()
    for name in _INDEX_NAMES:
        if name == "S&P" and "S&P500" in text:
            continue
        if name == "SOX" and "필라델피아 반도체" in text:
            continue  # 동일 지수 중복 제거
        idx = text.find(name)
        if idx == -1 or name in seen:
            continue
        pct = _first_pct(text[idx: idx + 40])
        result.append(IndexSnapshot(name=("S&P500" if name == "S&P" else name), change_pct=pct))
        seen.add(name)
    return result


def _extract_stocks(text: str, master: StockMaster) -> list[StockMention]:
    blocks = _split_blocks(text)
    mentions: list[StockMention] = []
    for entry in master.scan(text):
        ctx_blocks = [b for b in blocks if _mentions_entry(b, entry)]
        if not ctx_blocks:
            continue
        first_block = ctx_blocks[0]
        context = " ".join(ctx_blocks).strip()
        reason = _SENT_SPLIT.split(first_block)[0].strip() or first_block
        direction = _direction(context)
        mentions.append(StockMention(
            name=entry.display_name, ticker=entry.ticker, market=entry.market, direction=direction,
            change_pct=_signed_pct(context, direction), reason_summary=_clean_reason(reason),
            evidence=first_block[:400], evidence_verified=True, order=_first_position(text, entry, entry.display_name),
        ))
    mentions.sort(key=lambda m: m.order)
    return mentions


def _first_position(text: str, entry: Optional[StockEntry], name: str, default: int = 10**9) -> int:
    candidates = list(entry.names) if entry else []
    if name:
        candidates.append(name)
    positions = []
    low = text.lower()
    for alias in candidates:
        if not alias or (len(alias) <= 1):
            continue
        i = low.find(alias.lower())
        if i != -1:
            positions.append(i)
    return min(positions) if positions else default


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
        if line[0] in "-•·■※▶":
            flush()
            cur.append(line.lstrip("-•·■※▶ \t").strip())
        else:
            cur.append(line)
    flush()
    return [b for b in blocks if b]


def _mentions_entry(block: str, entry: StockEntry) -> bool:
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
    if pct == abs(pct) and direction == "DOWN":
        return -abs(pct)
    return pct


def _first_pct(s: str) -> Optional[float]:
    m = _PCT_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(1).replace("−", "-"))
    except ValueError:
        return None


def _clean_reason(sentence: str) -> str:
    return re.sub(r"\s+", " ", sentence).strip()[:200]
