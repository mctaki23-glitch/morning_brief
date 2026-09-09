"""운영 알림 (옵션) — 텔레그램 봇으로 실패·미게시 알림. 토큰이 없으면 조용히 건너뛴다."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional


def send_telegram(text: str, token: Optional[str] = None, chat_id: Optional[str] = None, timeout: int = 15) -> bool:
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_NOTIFY_CHAT_ID")
    if not token or not chat_id:
        print("[notify] 봇 토큰/채팅 ID 미설정 — 알림 생략")
        return False
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except OSError as exc:
        print(f"[notify] 전송 실패({exc!r})")
        return False


def message_from_status(status_path: Path, site_url: str = "") -> Optional[str]:
    """status.json 을 읽어 알림이 필요한 경우 메시지를 만든다(성공 시 None)."""
    if not status_path.exists():
        return f"[Morning Brief] 실행 상태 파일이 없습니다 ({status_path})"
    st = json.loads(status_path.read_text(encoding="utf-8"))
    result = st.get("result")
    if result == "published":
        warn = st.get("warnings") or []
        unmapped = st.get("unmapped") or []
        fails = st.get("evidence_failures") or []
        if not (warn or unmapped or fails):
            return None
        bits = [f"[Morning Brief] {st.get('brief_date')} 생성 완료(경고 있음)"]
        if unmapped:
            bits.append(f"- 미매핑 종목: {', '.join(unmapped)}")
        if fails:
            bits.append(f"- 근거 미검증: {', '.join(fails)}")
        if warn:
            bits.append(f"- 경고: {'; '.join(str(w) for w in warn[:3])}")
        return "\n".join(bits + ([site_url] if site_url else []))
    if result == "no_briefing":
        return f"[Morning Brief] {st.get('brief_date')} 브리핑이 마감 시각까지 게시되지 않았습니다(휴장 가능). 확인: {site_url}"
    if result == "waiting":
        return None  # 대기 상태는 정상 흐름(다음 예약 잡이 이어감)
    if result in ("skipped", "pending"):
        return None
    return f"[Morning Brief] 실행 결과: {result} ({st.get('brief_date')})"
