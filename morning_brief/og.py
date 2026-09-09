"""공유 미리보기(Open Graph) 카드 — 1200×630, 미래에셋 CI.

카드 HTML을 headless Chrome/Chromium 으로 캡처해 PNG 를 만든다(GitHub Actions ubuntu 러너에는
Chrome 이 기본 설치돼 있다). 브라우저가 없거나 캡처에 실패하면 번들된 정적 기본 카드
(`assets/og-default.png`)를 복사한다. 표준 라이브러리만 사용한다.
"""

from __future__ import annotations

import glob
import html
import os
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path
from typing import Optional

from .theme import FONTS_HTML

ASSETS = Path(__file__).parent / "assets"
DEFAULT_PNG = ASSETS / "og-default.png"

_CARD_CSS = """
*{box-sizing:border-box}html,body{margin:0;width:1200px;height:900px;overflow:hidden}
body{background:#FFFFFF;color:#1A1A1A;font-family:'KoPub Dotum','KoPubDotum','Noto Sans KR','Spoqa Han Sans Neo','Apple SD Gothic Neo','Malgun Gothic',sans-serif;
-webkit-font-smoothing:antialiased;position:relative}
.card{position:absolute;left:0;top:0;width:1200px;height:630px;overflow:hidden;padding:64px 72px 0;background:#FFFFFF}
.eyebrow{font-family:'Inter','Aptos',system-ui,sans-serif;font-size:22px;letter-spacing:1.5px;text-transform:uppercase;color:#6C6C6C;font-weight:600}
.date{font-family:'Inter','Aptos',system-ui,sans-serif;font-size:44px;font-weight:700;color:#043B72;margin-top:14px;letter-spacing:-.5px}
.date .wd{font-family:'KoPub Dotum','Noto Sans KR',sans-serif;font-size:30px;font-weight:500;color:#6C6C6C;margin-left:10px}
.rule{height:2px;background:#F58220;margin:28px 0 32px}
.headline{font-size:46px;line-height:1.3;font-weight:700;color:#1A1A1A;letter-spacing:-.6px;max-height:240px;overflow:hidden}
.sub{font-size:26px;line-height:1.5;color:#3D3D3D;margin-top:18px}
.foot{position:absolute;left:72px;right:72px;top:546px;display:flex;justify-content:space-between;align-items:baseline;
font-size:22px;color:#6C6C6C}
.foot b{color:#1A1A1A;font-weight:700}
.band{position:absolute;left:0;right:0;top:618px;height:12px;background:#F58220}
"""


def card_html(date_label: str, headline: str, sub: str = "", foot_left: str = "", foot_right: str = "Morning Brief", weekday: str = "") -> str:
    wd = f'<span class="wd">({html.escape(weekday)})</span>' if weekday else ""
    sub_html = f'<div class="sub">{html.escape(sub)}</div>' if sub else ""
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f"{FONTS_HTML}<style>{_CARD_CSS}</style></head><body><div class=\"card\">"
        '<div class="eyebrow">Morning Brief · 서상영 시황 브리핑 데일리 리포트</div>'
        f'<div class="date">{html.escape(date_label)}{wd}</div>'
        '<div class="rule"></div>'
        f'<div class="headline">{html.escape(headline)}</div>{sub_html}'
        f'<div class="foot"><span>{html.escape(foot_left)}</span><span><b>{html.escape(foot_right)}</b></span></div>'
        '<div class="band"></div></div></body></html>'
    )


def find_chrome() -> Optional[str]:
    """실행 가능한 Chrome/Chromium 바이너리 경로. 환경변수 MORNING_BRIEF_CHROME 이 우선."""
    env = os.environ.get("MORNING_BRIEF_CHROME")
    if env and Path(env).exists():
        return env
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "headless_shell"):
        found = shutil.which(name)
        if found:
            return found
    for pattern in ("/opt/pw-browsers/*/chrome-linux/headless_shell", "/opt/pw-browsers/*/chrome-linux/chrome"):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    return None


def render_png(doc_html: str, out_png: Path, timeout: int = 90) -> bool:
    """HTML 문서를 1200×630 PNG 로 캡처. 성공 시 True."""
    chrome = find_chrome()
    if not chrome:
        return False
    out_png.parent.mkdir(parents=True, exist_ok=True)
    out_png.unlink(missing_ok=True)  # Chrome --screenshot 은 기존 파일을 덮어쓰지 않으므로 먼저 제거
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "card.html"
        src.write_text(doc_html, encoding="utf-8")
        # 주의: --force-device-scale-factor / --user-data-dir 를 주면 headless_shell 에서 하단 절대배치
        # 요소가 캡처되지 않는 사례가 있어 최소 옵션만 사용한다.
        # 새 headless 모드는 --window-size 높이보다 뷰포트가 작게 잡히는 경우가 있어(하단 잘림),
        # 넉넉한 높이로 캡처한 뒤 1200×630 으로 크롭한다.
        cmd = [
            chrome, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
            "--window-size=1200,900", "--virtual-time-budget=5000",
            f"--screenshot={out_png}", src.as_uri(),
        ]
        try:
            subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
        except (subprocess.SubprocessError, OSError) as exc:  # noqa: PERF203
            print(f"[og] 캡처 실패({exc!r})")
            return False
    if not (out_png.exists() and out_png.stat().st_size > 1024):
        return False
    try:
        crop_png(out_png, 1200, 630)
    except Exception as exc:  # noqa: BLE001 - 크롭 실패 시 원본 유지(비율만 다름)
        print(f"[og] 크롭 실패({exc!r})")
    return True


# ── 표준 라이브러리 PNG 크롭 (8비트 RGB/RGBA, 비인터레이스) ─────────
def _png_chunks(data: bytes):
    pos = 8
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        yield ctype, data[pos + 8:pos + 8 + length]
        pos += 12 + length


def _unfilter(raw: bytes, width: int, height: int, bpp: int) -> list[bytes]:
    stride = width * bpp
    rows: list[bytes] = []
    prev = bytearray(stride)
    i = 0
    for _ in range(height):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        if f == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 255
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + (a + prev[x]) // 2) & 255
        elif f == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 255
        rows.append(bytes(line))
        prev = line
    return rows


def _chunk(ctype: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + ctype + payload + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF)


def crop_png(path: Path, width: int, height: int) -> None:
    """PNG 를 좌상단 기준 width×height 로 크롭해 같은 경로에 저장한다."""
    data = path.read_bytes()
    idat = b""
    w = h = 0
    ctype_color = 6
    for ctype, payload in _png_chunks(data):
        if ctype == b"IHDR":
            w, h, depth, ctype_color, _, _, interlace = struct.unpack(">IIBBBBB", payload)
            if depth != 8 or interlace != 0 or ctype_color not in (2, 6):
                raise ValueError("지원하지 않는 PNG 형식")
        elif ctype == b"IDAT":
            idat += payload
    if w < width or h < height:
        raise ValueError(f"크롭 대상보다 작은 이미지 {w}x{h}")
    if (w, h) == (width, height):
        return
    bpp = 3 if ctype_color == 2 else 4
    rows = _unfilter(zlib.decompress(idat), w, h, bpp)
    body = b"".join(b"\x00" + row[: width * bpp] for row in rows[:height])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, ctype_color, 0, 0, 0)
    out = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(body, 6)) + _chunk(b"IEND", b"")
    path.write_bytes(out)


def write_default_fallback(out_png: Path) -> bool:
    if DEFAULT_PNG.exists():
        out_png.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DEFAULT_PNG, out_png)
        return True
    return False


def write_og_card(out_png: Path, *, date_label: str, headline: str, sub: str = "", foot_left: str = "", weekday: str = "") -> str:
    """브리핑용 OG 카드 생성. 반환값: 'chrome' | 'default' | 'none'."""
    if os.environ.get("MORNING_BRIEF_OG", "").lower() not in ("", "on", "1", "true"):
        return "default" if write_default_fallback(out_png) else "none"
    doc = card_html(date_label, headline, sub, foot_left, weekday=weekday)
    if render_png(doc, out_png):
        return "chrome"
    return "default" if write_default_fallback(out_png) else "none"


def default_card_html() -> str:
    """번들 기본 카드(날짜 무관) — 저장소에 정적 PNG 로 포함된다."""
    return card_html(
        "Morning Brief",
        "서상영 시황 브리핑, 링크 하나로 정리된 아침 리포트",
        "매일 아침 06:30 · 시황 요약 · 주요 지수 · 종목별 캔들차트와 등락 이유",
        "텔레그램 사제콩이_서상영 채널 브리핑 기반 · 투자 참고용",
    )
