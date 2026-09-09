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
    # Claude Opus 5: 적응형 사고 기본. 강제 tool_choice 대신 auto + 명시 지시 (사고 모드와의 호환성 확보).
    resp = client.messages.create(
        model=cfg.model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=_SYSTEM,
        tools=[_EXTRACT_TOOL],
        tool_choice={"type": "auto", "disable_parallel_tool_use": True},
        messages=[{
            "role": "user",
            "content": ("다음은 오늘 텔레그램에 올라온 시황 브리핑 원문입니다. 반드시 extract_brief 도구를 한 번 호출해 "
                        "구조화 결과만 돌려주세요.\n\n<브리핑>\n" + text + "\n</브리핑>"),
        }],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("모델이 요청을 거부했습니다(refusal).")
    data = next((b.input for b in resp.content if b.type == "tool_use"), None)
    if not data:
        data = _json_from_text("".join(getattr(b, "text", "") for b in resp.content if b.type == "text"))
    if not data:
        raise RuntimeError("tool_use 블록(또는 JSON 응답)을 찾지 못했습니다.")

    indices = [
        IndexSnapshot(name=i.get("name", ""), value=i.get("value"), change_pct=i.get("change_pct"))
        for i in data.get("indices", []) if i.get("name")
    ]
    rule_based = {m.ticker or m.name: m for m in _extract_stocks(text, master)[0]}

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


def _json_from_text(text: str) -> Optional[dict]:
    """도구 호출 대신 본문에 JSON 을 쓴 경우의 방어적 파싱."""
    import json
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and "stocks" in data else None


# ── 규칙 기반 폴백 ───────────────────────────────────────────
# 서상영 브리핑 실제 형식(2026-09 실측):
#   제목 줄 → 도입 문단(끝에 "(다우 -1.18%, 나스닥 -0.32%, S&P500 -0.58%, 러셀2000 -0.52%, 필라델피아 반도체 지수 +1.30%)")
#   → "*변화요인: …" → "*특징 종목: …" (테마 소제목 줄 + "종목명(+5.90%)는 … 상승." 문장들)
#   → "*한국 증시 관련 수치: …" → "*FICC: …"
_INDEX_PATTERNS = [
    ("다우", r"다우(?!\s*운송)"), ("나스닥", r"나스닥"), ("S&P500", r"S&P\s*500"), ("러셀2000", r"러셀(?:\s*2000)?"),
    ("필라델피아 반도체", r"필라델피아\s*반도체"), ("코스피", r"코스피|KOSPI(?!\s*야간)"), ("코스닥", r"코스닥|KOSDAQ"),
]
_UP_WORDS = ["상승", "급등", "강세", "올랐", "올라", "반등", "상승 출발", "우호"]
_DOWN_WORDS = ["하락", "급락", "약세", "내렸", "내려", "밀렸", "부진"]
_CONNECTORS = {"여기에", "반면", "특히", "그리고", "이에", "이런", "대체로", "결국", "및", "등", "가운데", "비롯해", "이는", "한편",
               "다만", "또한", "더불어", "이날", "전일", "최근", "그러나", "이후", "동반", "특히,", "반면,", "그외", "그 외", "이에"}

_PCT_RE = re.compile(r"([+\-−]?\d+(?:\.\d+)?)\s*%")
_SIGNED_PCT_RE = re.compile(r"([+\-−]\d+(?:\.\d+)?)\s*%")
# "종목명(+5.90%)" — 이름은 1~2 단어(줄바꿈 불가), 괄호 안은 부호 있는 등락률만
_MENTION_RE = re.compile(
    r"([A-Za-z가-힣0-9&][A-Za-z가-힣0-9&\-]*(?:[ \t]+[A-Za-z가-힣0-9&][A-Za-z가-힣0-9&\-]*)?)[ \t]*\(\s*([+\-−]\d+(?:\.\d+)?)\s*%\s*\)"
)
_SENT_SPLIT = re.compile(r"(?<=[.。!?])\s+|\n+")
_MOVE_RE = re.compile(r"상승|하락|급등|급락|강세|약세|부진|반등|보합|올랐|올라|내렸|내려|견조|밀렸|출발")


def summarize_rule_based(text: str, master: StockMaster) -> SummaryResult:
    stocks, unmapped = _extract_stocks(text, master)
    return SummaryResult(
        overview=_extract_overview(text), indices=_extract_indices(text), stocks=stocks,
        summarizer="rule-based", kr_outlook=_extract_kr_outlook(text), prompt_version=PROMPT_VERSION, unmapped=unmapped,
    )


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(re.sub(r"[ \t]+", " ", text)) if s.strip()]


def _sentence_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, 문장) — 문장 위치 기반으로 언급 종목의 문맥을 찾기 위해 사용."""
    spans = []
    pos = 0
    for part in re.split(r"(?<=[.。!?])\s+|\n+", text):
        if not part:
            continue
        i = text.find(part, pos)
        if i < 0:
            continue
        spans.append((i, i + len(part), part.strip()))
        pos = i + len(part)
    return spans


def _is_header(line: str) -> bool:
    t = line.strip()
    if not t:
        return False
    if t.startswith(("*", "[", "■", "▶")):
        return True
    head = t[:40]
    return ":" in head and (" Vs" in t or (len(t) < 80 and not t.endswith(".")))


def _extract_overview(text: str) -> str:
    """제목 줄 + 첫 헤더('*') 전까지의 도입 문단. '시황 요약' 섹션이 있으면 그 문단."""
    m = re.search(r"시황\s*요약\s*\n?(.+?)(?:\n\s*\n|\n■|\n-)", text, re.DOTALL)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:600]
    lead = re.split(r"\n\s*\*", text, maxsplit=1)[0]
    paras = [re.sub(r"[ \t]+", " ", p).strip() for p in re.split(r"\n\s*\n", lead) if p.strip()]
    out = "\n\n".join(paras)
    if len(out) > 900:
        out = out[:900].rsplit(" ", 1)[0] + "…"
    return out


def _extract_kr_outlook(text: str) -> str:
    """'*한국 증시 …' 또는 '한국 증시 관전 포인트' 섹션(헤더 포함) → 다음 헤더/※ 전까지."""
    m = re.search(r"^[ \t]*\*?\s*(\[[^\]]*\]\s*)?(한국\s*증시[^\n]*)\n(.*?)(?=\n\s*\*|\n\s*※|\Z)", text, re.S | re.M)
    if not m:
        return ""
    header = m.group(2).strip().lstrip("*").strip()
    header = header.split(":", 1)[1].strip() if ":" in header and not header.startswith("[") else ""
    body = re.sub(r"[ \t]+", " ", m.group(3)).strip()
    parts = [p for p in (header, body) if p]
    return "\n\n".join(parts)[:900]


def _extract_indices(text: str) -> list[IndexSnapshot]:
    result: list[IndexSnapshot] = []
    for name, pat in _INDEX_PATTERNS:
        m = re.search(pat + r"[^\n%]{0,14}?" + _SIGNED_PCT_RE.pattern, text)
        if not m:
            continue
        pct = _to_float(m.group(m.lastindex))
        if pct is not None:
            result.append(IndexSnapshot(name=name, change_pct=pct))
    return result


def _to_float(raw: str) -> Optional[float]:
    try:
        return float(raw.replace("−", "-").replace("+", ""))
    except (TypeError, ValueError):
        return None


def _normalize(text: str) -> str:
    """들여쓴 연속 줄(소프트 랩)을 앞 줄에 이어붙인다. 문장 분할이 줄바꿈에서 끊기지 않게 한다."""
    return re.sub(r"\n[ \t]+(?=\S)", " ", text)


def _extract_stocks(text: str, master: StockMaster) -> tuple[list[StockMention], list[str]]:
    text = _normalize(text)
    spans = _sentence_spans(text)

    def sentence_at(pos: int) -> str:
        for a, b, s in spans:
            if a <= pos < b:
                return s
        return ""

    mentions: dict[str, StockMention] = {}  # key: ticker 또는 정규화 이름
    unmapped: list[str] = []

    # 1) "종목명(+x.xx%)" 패턴 — 등락률이 명시된 언급을 모두 포착 (마스터에 없어도 포함)
    for m in _MENTION_RE.finditer(text):
        raw_name, pct_raw = m.group(1).strip(), m.group(2)
        name, entry = _resolve_name(raw_name, master)
        if not name:
            continue
        pct = _to_float(pct_raw)
        key = entry.ticker if entry else _norm(name)
        sent = sentence_at(m.start()) or raw_name
        direction = "UP" if (pct or 0) > 0 else "DOWN" if (pct or 0) < 0 else "FLAT"
        if key in mentions:
            cur = mentions[key]
            if cur.change_pct is None:
                cur.change_pct, cur.direction, cur.reason_summary, cur.evidence = pct, direction, _clean_reason(sent), sent[:400]
            continue
        mentions[key] = StockMention(
            name=entry.display_name if entry else name, ticker=entry.ticker if entry else None,
            market=entry.market if entry else "US", direction=direction, change_pct=pct,
            reason_summary=_clean_reason(sent), evidence=sent[:400], evidence_verified=True, order=m.start(),
        )
        if not entry:
            unmapped.append(name)

    # 2) 종목 마스터 스캔 — 등락률 표기 없이 '종목으로서' 언급된 경우만 보완 (예: 한국 종목).
    #    다른 종목의 명시 등락률이 있는 문장(문맥 언급), 헤더, 등락 서술이 없는 문장, 'X의 …'(소유격) 언급은 제외한다.
    for entry in master.scan(text):
        if entry.ticker in mentions:
            continue
        sent, pos = _best_sentence(text, spans, entry)
        if not sent or _is_header(sent) or _MENTION_RE.search(sent) or not _MOVE_RE.search(sent):
            continue
        if _possessive_only(sent, entry):
            continue
        direction = _direction(sent)
        others = [e for e in master.scan(sent) if e.ticker != entry.ticker]
        pct = _signed_pct(sent, direction) if not others else None
        mentions[entry.ticker] = StockMention(
            name=entry.display_name, ticker=entry.ticker, market=entry.market, direction=direction,
            change_pct=pct, reason_summary=_clean_reason(sent), evidence=sent[:400], evidence_verified=True, order=pos,
        )

    ordered = sorted(mentions.values(), key=lambda x: x.order)
    return ordered, unmapped


def _resolve_name(raw: str, master: StockMaster):
    """캡처된 이름(1~2 단어)에서 접속어를 떼고 마스터에 매핑. (표시 이름, 엔트리|None) — 이름이 비면 ('', None)."""
    tokens = raw.split()
    candidates = []
    if len(tokens) == 2:
        first = tokens[0].rstrip(",")
        if first not in _CONNECTORS and not first.endswith(","):
            candidates.append(" ".join(tokens))
        candidates.append(tokens[1])
    else:
        candidates.append(raw)
    for cand in candidates:
        entry = master.resolve(cand)
        if entry:
            return cand, entry
    name = candidates[-1] if len(tokens) == 2 and tokens[0].rstrip(",") in _CONNECTORS else candidates[0]
    name = name.strip(",.")
    if len(name) < 2 or name.isdigit():
        return "", None
    return name, None


def _possessive_only(sentence: str, entry: StockEntry) -> bool:
    """문장 안의 모든 언급이 'X의'(소유격) 형태면 종목 등락이 아닌 문맥 언급으로 본다."""
    found = False
    for alias in entry.names:
        if len(alias) <= 1:
            continue
        for m in re.finditer(re.escape(alias), sentence):
            found = True
            tail = sentence[m.end():m.end() + 2]
            if not tail.startswith("의"):
                return False
    return found


def _best_sentence(text: str, spans, entry: StockEntry) -> tuple[str, int]:
    """종목이 언급된 문장 중 헤더가 아닌 첫 문장(등락률 포함 문장 우선)."""
    hits = []
    for a, b, s in spans:
        if _mentions_entry(s, entry):
            hits.append((a, s))
    if not hits:
        return "", 10**9
    for a, s in hits:
        if not _is_header(s) and _PCT_RE.search(s):
            return s, a
    for a, s in hits:
        if not _is_header(s):
            return s, a
    return hits[0][1], hits[0][0]


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


_TAIL_UP = ("상승", "급등", "강세", "반등", "올랐", "견조")
_TAIL_DOWN = ("하락", "급락", "약세", "부진", "내렸", "밀렸")
_TAIL_FLAT = ("보합", "혼조")


def _direction(context: str) -> str:
    """등락 방향. 한국어 문장은 마지막 서술어가 결론이므로 문장 끝(마지막 14자)의 등락 표현을 우선한다.
    그다음 명시적 부호가 있는 등락률, 마지막으로 키워드 빈도."""
    tail = re.sub(r"[\s.。!?\"'”’)]+$", "", context)[-14:]
    for words, d in ((_TAIL_FLAT, "FLAT"), (_TAIL_UP, "UP"), (_TAIL_DOWN, "DOWN")):
        if any(w in tail for w in words):
            # 끝부분에 상승·하락이 함께 있으면(예: '하락 전환') 더 뒤에 나오는 표현을 택한다
            last_up = max((tail.rfind(w) for w in _TAIL_UP), default=-1)
            last_down = max((tail.rfind(w) for w in _TAIL_DOWN), default=-1)
            if d == "FLAT":
                return "FLAT"
            return "UP" if last_up > last_down else "DOWN"
    m = _SIGNED_PCT_RE.search(context)
    if m:
        v = _to_float(m.group(1))
        if v is not None and v != 0:
            return "UP" if v > 0 else "DOWN"
    up = sum(context.count(w) for w in _UP_WORDS)
    down = sum(context.count(w) for w in _DOWN_WORDS)
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
    return _to_float(m.group(1)) if m else None


def _clean_reason(sentence: str) -> str:
    s = re.sub(r"\s+", " ", sentence).strip()
    if len(s) > 240:
        s = s[:240].rsplit(" ", 1)[0] + "…"
    return s
