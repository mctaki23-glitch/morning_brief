"""환경변수 기반 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_BASE_URL = "https://mctaki23-glitch.github.io/morning_brief"
DEFAULT_MODEL = "claude-opus-5"


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on", "production")


@dataclass
class Config:
    # 텔레그램 수집
    channel: str = "ehdwl"  # 사제콩이_서상영
    telegram_api_id: Optional[str] = None
    telegram_api_hash: Optional[str] = None
    telegram_session: Optional[str] = None  # Telethon StringSession

    # Claude 요약
    anthropic_api_key: Optional[str] = None
    model: str = DEFAULT_MODEL

    # 동작
    timezone: str = "Asia/Seoul"
    output_dir: str = "site"
    archive_dir: str = "archive"
    base_url: str = DEFAULT_BASE_URL  # OG 절대 URL 용
    logo_path: Optional[str] = None  # 공식 로고 SVG 경로 (없으면 로고 영역 비움)
    chart_window: int = 20  # 표시 봉 수
    production: bool = False  # 운영 모드: 샘플·합성 데이터 폴백 금지

    @property
    def price_days(self) -> int:
        """시세 조회 일수: 표시 창 + MA20 계산 여유."""
        return self.chart_window + 25

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        cfg = cls(
            channel=os.environ.get("TELEGRAM_CHANNEL", "ehdwl"),
            telegram_api_id=os.environ.get("TELEGRAM_API_ID") or None,
            telegram_api_hash=os.environ.get("TELEGRAM_API_HASH") or None,
            telegram_session=os.environ.get("TELEGRAM_SESSION") or None,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            model=os.environ.get("MORNING_BRIEF_MODEL") or DEFAULT_MODEL,
            timezone=os.environ.get("MORNING_BRIEF_TZ", "Asia/Seoul"),
            output_dir=os.environ.get("MORNING_BRIEF_OUT", "site"),
            archive_dir=os.environ.get("MORNING_BRIEF_ARCHIVE", "archive"),
            base_url=os.environ.get("MORNING_BRIEF_BASE_URL", DEFAULT_BASE_URL),
            logo_path=os.environ.get("MORNING_BRIEF_LOGO") or None,
            chart_window=int(os.environ.get("MORNING_BRIEF_CHART_DAYS", "20")),
            production=_env_bool("MORNING_BRIEF_ENV") or _env_bool("MORNING_BRIEF_PRODUCTION"),
        )
        for key, value in overrides.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_api_id and self.telegram_api_hash and self.telegram_session)

    @property
    def has_claude(self) -> bool:
        return bool(self.anthropic_api_key)

    def logo_svg(self) -> Optional[str]:
        """로고 SVG 파일 내용. 미설정·미존재면 None (로고 영역 비움, 워드마크 흉내 금지)."""
        if not self.logo_path:
            return None
        p = Path(self.logo_path)
        if p.exists() and p.suffix.lower() == ".svg":
            return p.read_text(encoding="utf-8")
        return None
