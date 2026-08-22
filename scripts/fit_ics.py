#!/usr/bin/env python3
"""오운완 체크 기록(JSON) → 구글/애플 캘린더 구독용 ICS 피드 생성.

입력은 둘 중 하나:
  --log log.json     기록 JSON 파일 ({"version":1,"days":{"YYYY-MM-DD":{...}}})
  --html page.html   오운완 체크 아티팩트 HTML (내장된 #log 블록에서 추출)

출력(--out)은 항상 같은 입력에 대해 바이트 단위로 동일하게 생성되므로,
git diff 로 "달라졌을 때만 커밋" 판단을 할 수 있다.

사용 예:
  python3 scripts/fit_ics.py --html artifact.html --out fit_tracker/ounwan.ics
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOG_BLOCK_RE = re.compile(
    r'<script type="application/json" id="log">(.*?)</script>', re.S
)

# 앱과 동일한 종목 정의 (체크 필드, 표시 이름)
ITEMS = [
    ("m1", "아침 — 정석 푸쉬업 15회×1세트"),
    ("m2", "아침 — 3kg 오버헤드 W-레이즈 15회×2세트"),
    ("e1", "저녁 — 8kg 원암 덤벨 로우 각 10~12회×3세트"),
    ("e2", "저녁 — 3kg 사이드 레터럴 레이즈 15회×2~3세트"),
    ("e3", "저녁 — 8kg 덤벨 이두 컬 각 10회×2세트"),
    ("c1", "슬로우 조깅 (Zone 2)"),
    ("n1", "식단 — 아침 (자연식)"),
    ("n2", "식단 — 점심 (일반식 + 단백질 음료)"),
    ("n3", "식단 — 저녁 (닭가슴살 샐러드)"),
]
CHECK_FIELDS = [k for k, _ in ITEMS]
DIET = ["n1", "n2", "n3"]


def esc(text: str) -> str:
    """RFC 5545 TEXT 이스케이프."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """75옥텟 라인 폴딩 (UTF-8 문자 경계 보존)."""
    out: list[str] = []
    cur = ""
    budget = 74
    for ch in line:
        if len((cur + ch).encode("utf-8")) > budget:
            out.append(cur)
            cur = " " + ch
            budget = 74  # 연속행은 선행 공백 포함 75옥텟
        else:
            cur += ch
    out.append(cur)
    return "\r\n".join(out)


def clean_day(raw: object) -> dict | None:
    """앱의 cleanDay 와 동일한 정제: 숫자 필드만, km은 0~99."""
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    for f in CHECK_FIELDS + ["km", "u"]:
        v = raw.get(f)
        if v is True:
            v = 1
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        if f == "km":
            out[f] = max(0.0, min(99.0, float(v)))
        elif f == "u":
            out[f] = int(v)
        else:
            out[f] = 1 if v else 0
    return out or None


def summary(d: dict) -> str:
    parts: list[str] = []
    if d.get("m1") and d.get("m2"):
        parts.append("아침")
    if d.get("e1") and d.get("e2") and d.get("e3"):
        parts.append("저녁")
    if d.get("c1"):
        km = d.get("km") or 0
        parts.append(f"조깅 {km:g}km" if km > 0 else "조깅")
    n = sum(1 for f in DIET if d.get(f))
    if n:
        parts.append(f"식단 {n}/{len(DIET)}")
    if parts:
        return "💪 오운완 — " + " · ".join(parts)
    done = sum(1 for f in CHECK_FIELDS if d.get(f))
    return f"💪 운동 기록 — {done}개 항목"


def description(d: dict) -> str:
    lines = []
    for f, label in ITEMS:
        mark = "✅" if d.get(f) else "⬜"
        if f == "c1" and d.get(f) and (d.get("km") or 0) > 0:
            label = f"{label} {d['km']:g}km"
        lines.append(f"{mark} {label}")
    lines.append("")
    lines.append("오운완 체크 앱 자동 기록")
    return "\n".join(lines)


def dtstamp(d: dict, key: str) -> str:
    """이벤트 DTSTAMP — 기록의 u(수정 시각)로 결정적 생성."""
    u = d.get("u")
    if isinstance(u, int) and u > 0:
        t = datetime.fromtimestamp(u / 1000, tz=timezone.utc)
    else:
        t = datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=KST).astimezone(timezone.utc)
    return t.strftime("%Y%m%dT%H%M%SZ")


def build_ics(state: dict) -> str:
    days = state.get("days") or {}
    events: list[str] = []
    for key in sorted(k for k in days if KEY_RE.match(k)):
        d = clean_day(days[key])
        if not d:
            continue
        if not any(d.get(f) for f in CHECK_FIELDS):
            continue
        ymd = key.replace("-", "")
        nxt = (datetime.strptime(key, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y%m%d")
        ev = [
            "BEGIN:VEVENT",
            f"UID:ounwan-{ymd}@morning-brief",
            f"DTSTAMP:{dtstamp(d, key)}",
            f"DTSTART;VALUE=DATE:{ymd}",
            f"DTEND;VALUE=DATE:{nxt}",
            fold("SUMMARY:" + esc(summary(d))),
            fold("DESCRIPTION:" + esc(description(d))),
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
        events.append("\r\n".join(ev))

    cal = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//morning_brief//ounwan-check//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        fold("X-WR-CALNAME:" + esc("오운완 기록")),
        "X-WR-TIMEZONE:Asia/Seoul",
        "REFRESH-INTERVAL;VALUE=DURATION:PT4H",
        "X-PUBLISHED-TTL:PT4H",
        *events,
        "END:VCALENDAR",
    ]
    return "\r\n".join(cal) + "\r\n"


def load_state(args: argparse.Namespace) -> dict:
    if args.log:
        with open(args.log, encoding="utf-8") as f:
            return json.load(f)
    with open(args.html, encoding="utf-8") as f:
        html = f.read()
    m = LOG_BLOCK_RE.search(html)
    if not m:
        raise SystemExit("오류: HTML에서 #log 기록 블록을 찾지 못했습니다.")
    return json.loads(m.group(1))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--log", help="기록 JSON 파일 경로")
    src.add_argument("--html", help="오운완 체크 아티팩트 HTML 경로")
    p.add_argument("--out", required=True, help="출력 ICS 경로")
    args = p.parse_args()

    state = load_state(args)
    if not isinstance(state, dict) or not isinstance(state.get("days"), dict):
        raise SystemExit("오류: 기록 JSON 형식이 아닙니다 (days 없음).")

    ics = build_ics(state)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        f.write(ics)
    n = ics.count("BEGIN:VEVENT")
    print(f"OK: 이벤트 {n}개 → {args.out}")


if __name__ == "__main__":
    main()
