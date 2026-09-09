"""텔레그램 메시지 수집.

우선순위 (PRD D3 확정)
1. 공개 채널 미리보기 `https://t.me/s/<channel>` — 자격증명 없이 최근 메시지 HTML 을 파싱한다.
2. Telethon(MTProto) 개인 세션 — TELEGRAM_API_ID/HASH/SESSION 이 있을 때 폴백.
3. 샘플 브리핑(fixture) — 개발·테스트 전용. 운영 모드(cfg.production)에서는 절대 사용하지 않는다.

초장문 브리핑은 여러 메시지로 분할 게시되므로, 대상 일자(KST) 하루 전체(00:00~24:00)에 게시된 메시지를
시간순으로 이어붙여 하나의 브리핑으로 재조립한다(당일 채널의 모든 내용을 포함).
"""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from .config import Config

_FIXTURE = Path(__file__).parent / "data" / "sample_briefing.txt"
_MSG_SEP = "\n\n"
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
_TIMEOUT = 20
DAY_END_HOUR = 24  # 대상 일자 00:00~24:00(KST) 에 게시된 모든 메시지를 포함한다


@dataclass
class Message:
    id: int
    posted_at: datetime  # tz-aware
    text: str


@dataclass
class Fetched:
    messages: list[Message] = field(default_factory=list)
    method: str = "none"  # preview | session | fixture | none
    errors: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return _MSG_SEP.join(m.text.strip() for m in self.messages if m.text.strip())

    @property
    def count(self) -> int:
        return len(self.messages)

    @property
    def ids(self) -> list[int]:
        return [m.id for m in self.messages]

    def posted_at_iso(self, tz: str) -> str:
        if not self.messages:
            return ""
        return self.messages[0].posted_at.astimezone(ZoneInfo(tz)).isoformat(timespec="seconds")

    @property
    def ok(self) -> bool:
        return bool(self.messages)


# ── 샘플(fixture) ────────────────────────────────────────────
def _fixture_parts() -> list[str]:
    raw = _FIXTURE.read_text(encoding="utf-8")
    return [p.strip() for p in raw.split("\n===\n") if p.strip()]


def load_fixture() -> str:
    return _MSG_SEP.join(_fixture_parts())


def fixture_fetched(date_str: str, tz: str = "Asia/Seoul") -> Fetched:
    base = datetime.combine(datetime.strptime(date_str, "%Y-%m-%d").date(), time(6, 5), tzinfo=ZoneInfo(tz))
    msgs = [Message(id=1000 + i, posted_at=base + timedelta(minutes=3 * i), text=t) for i, t in enumerate(_fixture_parts())]
    return Fetched(messages=msgs, method="fixture")


# ── 공개 미리보기 파서 ───────────────────────────────────────
class _PreviewParser(HTMLParser):
    """t.me/s/<channel> HTML 에서 (message_id, datetime, text) 를 뽑는다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: list[tuple[int, Optional[str], str]] = []
        self._post_id: Optional[int] = None
        self._time: Optional[str] = None
        self._text_parts: list[str] = []
        self._in_text = 0  # message_text div 안의 중첩 깊이
        self._depth = 0
        self._post_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "") or ""
        self._depth += 1
        if "js-widget_message" in cls and a.get("data-post"):
            self._flush()
            m = re.search(r"/(\d+)$", a["data-post"])
            self._post_id = int(m.group(1)) if m else None
            self._post_depth = self._depth
        if self._in_text:
            self._in_text += 1
            if tag == "br":
                self._text_parts.append("\n")
                self._in_text -= 1  # br 은 닫히지 않음
            return
        if tag == "div" and "tgme_widget_message_text" in cls and "reply" not in cls:
            self._in_text = 1
            self._text_parts = []
        if tag == "time" and a.get("datetime") and self._post_id is not None:
            self._time = a["datetime"]

    def handle_startendtag(self, tag, attrs):
        if self._in_text and tag == "br":
            self._text_parts.append("\n")
        else:
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self._in_text:
            self._in_text -= 1
            if self._in_text == 0 and self._post_id is not None:
                text = "".join(self._text_parts).strip()
                # 같은 메시지에 텍스트 div 가 둘 이상이면 이어붙인다
                self.messages.append((self._post_id, None, text))
        self._depth -= 1
        if self._post_id is not None and self._depth < self._post_depth:
            self._flush()

    def handle_data(self, data):
        if self._in_text:
            self._text_parts.append(data)

    def _flush(self):
        if self._post_id is not None:
            # 시간 정보를 해당 메시지의 텍스트 레코드에 채운다
            for i in range(len(self.messages) - 1, -1, -1):
                pid, t, text = self.messages[i]
                if pid != self._post_id:
                    break
                if t is None:
                    self.messages[i] = (pid, self._time, text)
        self._post_id = None
        self._time = None

    def close(self):
        super().close()
        self._flush()


def parse_preview(html_text: str) -> list[Message]:
    parser = _PreviewParser()
    parser.feed(html_text)
    parser.close()
    merged: dict[int, Message] = {}
    for pid, t, text in parser.messages:
        if not text:
            continue
        posted = _parse_dt(t)
        if posted is None:
            continue
        if pid in merged:
            merged[pid].text += "\n" + text
        else:
            merged[pid] = Message(id=pid, posted_at=posted, text=html.unescape(text))
    return sorted(merged.values(), key=lambda m: m.id)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "ko,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_preview(channel: str, start: datetime, end: datetime, max_pages: int = 3) -> list[Message]:
    """공개 미리보기에서 [start, end) 구간 메시지를 수집. 필요하면 ?before= 로 과거 페이지를 더 읽는다."""
    collected: dict[int, Message] = {}
    url = f"https://t.me/s/{channel}"
    for _ in range(max_pages):
        page = _http_get(url)
        msgs = parse_preview(page)
        if not msgs:
            break
        for m in msgs:
            if start <= m.posted_at < end:
                collected[m.id] = m
        oldest = msgs[0]
        if oldest.posted_at < start:
            break  # 대상 구간 이전까지 읽었음
        url = f"https://t.me/s/{channel}?before={oldest.id}"
    return sorted(collected.values(), key=lambda m: m.id)


# ── Telethon 세션 ─────────────────────────────────────────────
def fetch_session(cfg: Config, start: datetime, end: datetime) -> list[Message]:
    from telethon.sessions import StringSession  # type: ignore
    from telethon.sync import TelegramClient  # type: ignore

    out: list[Message] = []
    with TelegramClient(StringSession(cfg.telegram_session), int(cfg.telegram_api_id), cfg.telegram_api_hash) as client:
        for msg in client.iter_messages(cfg.channel, offset_date=end):
            if msg.date is None:
                continue
            if msg.date < start:
                break
            if start <= msg.date < end and (msg.message or "").strip():
                out.append(Message(id=msg.id, posted_at=msg.date, text=msg.message))
    return sorted(out, key=lambda m: m.id)


# ── 진입점 ────────────────────────────────────────────────────
def day_window(date_str: str, tz: str, end_hour: int = DAY_END_HOUR) -> tuple[datetime, datetime]:
    day = datetime.strptime(date_str, "%Y-%m-%d").date()
    start = datetime.combine(day, time.min, tzinfo=ZoneInfo(tz))
    return start, start + timedelta(hours=end_hour)


def fetch_day(cfg: Config, date_str: str, use_fixtures: bool = False) -> Fetched:
    """대상 일자(KST 하루 전체)의 채널 메시지를 수집한다.

    운영 모드에서는 수집 실패·미게시 시 빈 결과를 돌려주고(호출자가 '대기 중' 처리), 샘플로 대체하지 않는다.
    """
    if use_fixtures:
        return fixture_fetched(date_str, cfg.timezone)
    start, end = day_window(date_str, cfg.timezone)
    errors: list[str] = []

    try:
        msgs = fetch_preview(cfg.channel, start, end)
        if msgs:
            return Fetched(messages=msgs, method="preview")
        errors.append("preview: 대상 구간 메시지 없음")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        errors.append(f"preview: {exc!r}")
        print(f"[ingest] 공개 미리보기 수집 실패({exc!r})")

    if cfg.has_telegram:
        try:
            msgs = fetch_session(cfg, start, end)
            if msgs:
                return Fetched(messages=msgs, method="session")
            errors.append("session: 대상 구간 메시지 없음")
        except Exception as exc:  # noqa: BLE001 - 외부 라이브러리 예외 전반
            errors.append(f"session: {exc!r}")
            print(f"[ingest] 텔레그램 세션 수집 실패({exc!r})")

    if cfg.production:
        return Fetched(messages=[], method="none", errors=errors)
    print("[ingest] 수집 결과가 없어 샘플 브리핑으로 폴백합니다(개발 모드).")
    fx = fixture_fetched(date_str, cfg.timezone)
    fx.errors = errors
    return fx


def fetch_briefing(cfg: Config, date_str: str, use_fixtures: bool = False) -> tuple[str, int]:
    """(원문, 메시지 수) — 이전 인터페이스 호환용."""
    f = fetch_day(cfg, date_str, use_fixtures=use_fixtures)
    return f.text, f.count
