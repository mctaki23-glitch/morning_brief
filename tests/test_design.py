"""디자인 가드레일 — 미래에셋 디자인 시스템 점검표(docs/PRD.md 5.10)를 자동 검사한다."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from morning_brief.config import Config
from morning_brief.pipeline import run
from morning_brief.theme import CSS

# 이모지 범위 (▲▼ 등 도형 기호 U+25A0–25FF 는 허용)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿\U0001F000-\U0001F2FF]")


@pytest.fixture(scope="module")
def site_html(tmp_path_factory) -> dict[str, str]:
    out = tmp_path_factory.mktemp("site")
    index = run(Config.from_env(output_dir=str(out)), date_str="2026-07-08", use_fixtures=True)
    stock = next((out / "brief" / "2026-07-08" / "stock").glob("*.html"))
    return {
        "brief": index.read_text(encoding="utf-8"),
        "stock": stock.read_text(encoding="utf-8"),
        "archive": (out / "archive" / "index.html").read_text(encoding="utf-8"),
    }


def test_css_has_signature_tokens_and_no_forbidden_effects():
    assert "#F58220" in CSS and "#FAB072" in CSS and "#043B72" in CSS  # 오렌지 룰 · 테이블 헤더 · 블루
    for forbidden in ("gradient(", "box-shadow", "prefers-color-scheme", "font-style:italic", "Pretendard", "Roboto"):
        assert forbidden not in CSS, forbidden
    # 라운드는 4px 이하 (버튼 2px, 카드 4px, 테이블 0)
    for value in re.findall(r"border-radius:\s*([^;}]+)", CSS):
        for num in re.findall(r"(\d+(?:\.\d+)?)px", value):
            assert float(num) <= 4, value
    # 승인 폰트만: KoPub돋움(자체 호스팅) → Noto Sans KR 폴백, 영문 Inter
    assert CSS.index("KoPub Dotum") < CSS.index("Noto Sans KR") and "Inter" in CSS


def test_font_face_only_when_files_exist():
    from morning_brief.theme import font_face_css
    assert font_face_css("../", []) == ""
    css = font_face_css("../", ["KoPubDotum-Medium.woff2", "KoPubDotum-Bold.woff"])
    assert "url('../assets/fonts/KoPubDotum-Medium.woff2') format('woff2')" in css
    assert "font-weight:600 700" in css and "Light" not in css


def test_rendered_pages_have_no_emoji_and_use_ci_components(site_html):
    for name, html in site_html.items():
        assert not _EMOJI.search(html), f"{name}: 이모지 사용 금지"
        assert 'class="rule"' in html or 'class="s-rule"' in html, f"{name}: 1px 오렌지 섹션 룰 누락"
        assert "fonts.googleapis.com/css2?family=Noto+Sans+KR" in html
        assert "prefers-color-scheme" not in html  # 화이트 캔버스 단일 테마
    assert "<thead>" in site_html["brief"]  # 시그니처 데이터 테이블(FAB072 헤더는 CSS 로 적용)


def test_direction_encoded_with_symbols_not_color_alone(site_html):
    html = site_html["brief"]
    assert "▲" in html and "▼" in html
    assert 'class="chg r up"' in html and 'class="chg r down"' in html


def test_chart_series_order_orange_then_blue(site_html):
    html = site_html["stock"]
    assert html.index('stroke="#F58220"') < html.index('stroke="#0086B8"')
