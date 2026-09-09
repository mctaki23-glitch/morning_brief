"""테스트 공통 설정: OG 카드는 번들 기본 PNG 로 대체해 headless Chrome 캡처(~13초/회)를 건너뛴다."""

import os

os.environ.setdefault("MORNING_BRIEF_OG", "off")
