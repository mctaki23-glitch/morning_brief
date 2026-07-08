"""텔레그램 메시지 수집.

- 자격증명(TELEGRAM_API_ID/HASH/SESSION)이 있고 telethon이 설치돼 있으면
  대상 채널의 '그날(KST)' 메시지를 수집한다.
- 없으면 번들된 샘플 브리핑(fixture)으로 폴백하여 오프라인에서도 동작한다.

초장문(7,000~8,000자) 메시지가 여러 건으로 분할 게시될 수 있으므로,
해당 일자의 메시지를 시간순으로 이어붙여 하나의 브리핑으로 재조립한다.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Config

_FIXTURE = Path(__file__).parent / "data" / "sample_briefing.txt"


def load_fixture() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def fetch_briefing(cfg: Config, date_str: str, use_fixtures: bool = False) -> str:
    """지정 일자(KST)의 브리핑 원문을 반환. 실패 시 fixture로 폴백."""
    if use_fixtures or not cfg.has_telegram:
        return load_fixture()
    try:
        text = _fetch_from_telegram(cfg, date_str)
    except Exception as exc:  # noqa: BLE001 - 수집 실패 시 그레이스풀 폴백
        print(f"[ingest] 텔레그램 수집 실패({exc!r}); fixture로 폴백합니다.")
        return load_fixture()
    if not text.strip():
        print("[ingest] 해당 일자 메시지가 비어 있어 fixture로 폴백합니다.")
        return load_fixture()
    return text


def _fetch_from_telegram(cfg: Config, date_str: str) -> str:
    # telethon은 선택적 의존성.
    from telethon.sessions import StringSession  # type: ignore
    from telethon.sync import TelegramClient  # type: ignore

    tz = ZoneInfo(cfg.timezone)
    day = datetime.strptime(date_str, "%Y-%m-%d").date()
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(ZoneInfo("UTC"))
    end_utc = end_local.astimezone(ZoneInfo("UTC"))

    chunks: list[tuple[datetime, str]] = []
    with TelegramClient(
        StringSession(cfg.telegram_session), int(cfg.telegram_api_id), cfg.telegram_api_hash
    ) as client:
        # 최신부터 역순으로 순회하다가 대상 일자 이전이면 중단.
        for msg in client.iter_messages(cfg.channel, offset_date=end_utc):
            if msg.date is None:
                continue
            if msg.date < start_utc:
                break
            if start_utc <= msg.date < end_utc and (msg.message or "").strip():
                chunks.append((msg.date, msg.message))

    chunks.sort(key=lambda c: c[0])  # 시간 오름차순으로 재조립
    return "\n\n".join(text for _, text in chunks)
