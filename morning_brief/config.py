"""환경변수 기반 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    # 텔레그램 수집
    channel: str = "ehdwl"  # 사제콩이_서상영
    telegram_api_id: Optional[str] = None
    telegram_api_hash: Optional[str] = None
    telegram_session: Optional[str] = None  # Telethon StringSession

    # Claude 요약
    anthropic_api_key: Optional[str] = None
    model: str = "claude-opus-4-8"

    # 동작
    timezone: str = "Asia/Seoul"
    output_dir: str = "site"
    chart_days: int = 20

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        cfg = cls(
            channel=os.environ.get("TELEGRAM_CHANNEL", "ehdwl"),
            telegram_api_id=os.environ.get("TELEGRAM_API_ID"),
            telegram_api_hash=os.environ.get("TELEGRAM_API_HASH"),
            telegram_session=os.environ.get("TELEGRAM_SESSION"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model=os.environ.get("MORNING_BRIEF_MODEL", "claude-opus-4-8"),
            timezone=os.environ.get("MORNING_BRIEF_TZ", "Asia/Seoul"),
            output_dir=os.environ.get("MORNING_BRIEF_OUT", "site"),
            chart_days=int(os.environ.get("MORNING_BRIEF_CHART_DAYS", "20")),
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
