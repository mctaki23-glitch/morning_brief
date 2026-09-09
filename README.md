# Morning Brief

텔레그램 **"사제콩이_서상영"**(`@ehdwl`) 채널에 매일 새벽 올라오는 미국 증시 시황 브리핑을 자동으로 수집·구조화하여,
**매일 06:30(KST) 링크 하나로 열어 보는 미래에셋증권 CI 데일리 리포트**를 생성합니다.

- 제품 요구사항: [`docs/PRD.md`](docs/PRD.md) (v2.0 확정) · 이전 버전 [`docs/PRD-v1.0.md`](docs/PRD-v1.0.md)
- 운영 URL: https://mctaki23-glitch.github.io/morning_brief/ (고정 링크 → 항상 최신 브리핑)
- 핵심 화면: 시황 요약 → 주요 지수 → 오늘의 종목 → **종목 서머리 = 캔들차트(거래량·MA5/20) + 등락 이유 + 원문 근거** → 금리·유가·금·환율 서머리(차트 + 브리핑 코멘트)

## 파이프라인

```
텔레그램 채널 ─① 수집─▶ 공개 미리보기(t.me/s) → Telethon 세션 폴백
                        │
        ② 구조화 ──────▶ Claude Opus 5 도구 호출(근거 발췌 검증) → 실패 시 규칙 기반
                        │
        ③ 시세 ────────▶ 미국 Nasdaq→네이버 해외주식→investing.com→Stooq→Yahoo · 한국 네이버→Yahoo · archive 캐시 폴백
                        │
        ④ 아카이브 ────▶ archive/<date>/{raw.txt, meta.json, brief.json, prices/}  (리포지토리 커밋 = 소스 오브 트루스)
                        │
        ⑤ 렌더 ────────▶ site/  정적 사이트 (미래에셋 CI, 모바일 우선, Google Fonts 외 외부 요청 없음)
                        │
        ⑥ 배포 ────────▶ GitHub Pages  +  status.json · 알림(옵션)
```

산출물 구조:

```
site/index.html                      최신 브리핑으로 이동 (미게시 시 '대기 중' 상태 페이지)
site/brief/<date>/index.html         데일리 브리핑 페이지 (종목명을 누르면 종목 서머리 시트)
site/brief/<date>/stock/<ticker>.html 종목 서머리 딥링크
site/brief/<date>/data.json          구조화 데이터 (원문 제외)
site/brief/<date>/og.png             공유 미리보기 카드 (1200×630)
site/archive/index.html              날짜별 아카이브 + 종목 검색
site/status.json                     마지막 실행 상태
site/robots.txt                      검색 크롤링 차단 (링크 공유용 공개 페이지)
```

## 빠른 시작 (자격증명 불필요)

```bash
python -m morning_brief run --fixtures --out site     # 샘플 브리핑으로 사이트 생성
python -m morning_brief.cli serve --out site           # http://localhost:8000
python -m pytest tests/ -q                             # 테스트 (네트워크 불필요)
```

핵심 파이프라인은 **표준 라이브러리만으로** 동작합니다. `telethon`, `anthropic` 은 선택 의존성입니다.

## 운영 실행

```bash
cp .env.example .env            # 값 채우기 (아래 표)
pip install -r requirements.txt
python -m morning_brief run --production              # 오늘 브리핑 즉시 1회 수집·생성
python -m morning_brief run --production --scheduled  # 06:30 목표 게시 감지 대기 루프
python -m morning_brief run --production --date 2026-09-08   # 과거 일자 재생성
python -m morning_brief rebuild                       # 아카이브 전체로 사이트 재생성
# GitHub Actions 수동 실행 입력: date(과거 일자 재생성) · scheduled(대기 루프) · probe(시세 소스 점검만) · rebuild(수집 없이 사이트만 재생성·배포)
```

| 환경변수 | 설명 |
| --- | --- |
| `TELEGRAM_CHANNEL` | 채널 username (기본 `ehdwl`). 공개 미리보기 수집은 자격증명이 필요 없습니다 |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION` | (폴백) Telethon 세션. 전용 계정 권장. 발급 방법은 `.env.example` |
| `ANTHROPIC_API_KEY`, `MORNING_BRIEF_MODEL` | Claude 구조화 요약 (기본 `claude-opus-5`). 없으면 규칙 기반 요약 |
| `MORNING_BRIEF_ENV=production` | 운영 모드: 샘플·합성 데이터 폴백 금지 (미게시면 '대기 중' 페이지) |
| `MORNING_BRIEF_BASE_URL` | 사이트 기본 URL (공유 카드 절대 링크) |
| `MORNING_BRIEF_LOGO` | 공식 로고 SVG 경로. 없으면 로고 영역을 비웁니다(워드마크 흉내 금지) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_NOTIFY_CHAT_ID` | (옵션) 실패·미게시 알림 봇 |

## 매일 06:30 자동 실행 (GitHub Actions + Pages)

[`.github/workflows/daily-brief.yml`](.github/workflows/daily-brief.yml) 은 **05:00~08:30 KST 30분 간격 8개 예약**으로 실행됩니다.
GitHub 예약 실행이 1.5~2시간 지연되는 점을 감안한 설계입니다(PRD 8장). 각 잡은:

1. 오늘 아카이브가 이미 있으면 사이트만 재생성하고 즉시 종료 (idempotent)
2. 5분 간격으로 게시를 감지하고, 분할 게시 완료를 5분 기다린 뒤 생성 · 아카이브 커밋 · 배포
3. 06:30 이후에도 미게시면 '대기 중' 페이지를 게시하고 종료 → 다음 예약 잡이 이어서 감지
4. 09:00 이후 미게시면 '브리핑 없음' 으로 종료 (미국 휴장 등)

설정:
1. **Settings → Pages → Source: GitHub Actions**
2. (옵션) **Settings → Secrets and variables → Actions** 에 `ANTHROPIC_API_KEY`, `TELEGRAM_*` 등록.
   시크릿이 없어도 공개 미리보기 수집 + 규칙 기반 요약으로 동작하며, 운영 모드에서는 샘플 데이터가 게시되지 않습니다.
3. `Actions` 탭 → **Run workflow** (`date` 입력으로 과거 일자 재생성 가능)

자체 서버 cron: `./scripts/install_cron.sh` (매일 06:00 부터 대기 루프 실행)

## 디자인 (미래에셋증권 CI)

- 화이트 캔버스 단일 테마, Mirae Asset Orange `#F58220`(1px 섹션 룰 · 활성 상태) / Blue `#043B72`(강조 수치 · 하락)
- 등락 색은 한국식(상승 `#C62828` / 하락 `#043B72`) + ▲▼ 기호 병기. 이동평균은 차트 페어(MA5 오렌지 / MA20 블루)
- 폰트: **KoPub돋움체** 자체 호스팅(`morning_brief/assets/fonts/`, 없으면 Noto Sans KR 폴백) · 영문/숫자 Inter
- 모서리 sharp(≤4px), 그라데이션·이모지·드롭섀도 없음 — `tests/test_design.py` 가 자동 점검
- 모바일 우선: 종목 테이블은 카드로 전환, 종목 서머리는 바텀시트, 차트는 모바일 전용 폭으로 별도 렌더

## 프로젝트 구조

```
morning_brief/
  ingest.py       텔레그램 수집 (공개 미리보기 파서 → 세션 폴백 → 샘플[개발 전용])
  summarize.py    Claude 구조화(근거 검증) + 규칙 기반 폴백
  stock_master.py 종목명·별칭 ↔ 티커/거래소 매핑 (data/stocks.json)
  prices.py       시세 어댑터(Nasdaq/네이버/investing.com/Stooq/Yahoo) + 아카이브 캐시 + 합성[개발 전용]
  macro.py        매크로 자산(금리·유가·금·환율·원자재·비트코인) 언급 추출 (data/macro.json)
  macro_prices.py 매크로 시세 어댑터(네이버 시장지표 원자재·국채 OHLC → 미 재무부 수익률 CSV → CoinGecko → FRED 폴백)
  chart.py        인라인 SVG 캔들차트(거래량·MA·툴팁) / 미니 캔들
  theme.py        미래에셋 CI 토큰·CSS·폰트
  render.py       정적 사이트(브리핑 · 종목 · 아카이브 · 상태 페이지 · OG 메타)
  og.py           공유 카드 PNG (headless Chrome, 기본 카드 폴백)
  archive.py      archive/<date> 저장·복원, index.json
  pipeline.py     수집→요약→시세→아카이브→렌더→상태
  scheduler.py    06:30 게시 감지 대기 루프
  notify.py       텔레그램 봇 알림(옵션)
  cli.py          run / rebuild / notify / serve
  assets/         og-default.png, fonts/ (KoPub돋움 파일 위치)
archive/          날짜별 브리핑 데이터 (워크플로우가 커밋)
docs/PRD.md       제품 요구사항 v2.0
```

## 유의사항
투자 참고용 자동 생성 자료이며 매매 권유가 아닙니다. 브리핑 원문 저작권은 작성자(서상영)에게 있으며 페이지는 요약과
근거 발췌, 원문 링크만 제공합니다. 공개 링크 운영 전 저작권 동의·준법감시 확인·CI 사용 승인(PRD D11)을 확인하세요.
