# Morning Brief 📈

텔레그램 **"사제콩이_서상영"**(`@ehdwl`) 채널에 매일 새벽 올라오는 미국 증시 시황 브리핑을
자동으로 수집·요약하여, **링크 하나로 시황 정리 + 종목별 서머리(등락 이유 + 간단 차트)** 를
확인할 수 있는 정적 웹 사이트를 생성합니다.

- 📄 제품 요구사항: [`docs/PRD.md`](docs/PRD.md)
- ⏰ 매일 **아침 06:30(KST)** 에 그날 올라온 메시지를 기반으로 자동 생성 (GitHub Actions / cron)

## 무엇을 만드나

```
텔레그램 브리핑 원문
      │  수집(ingest)
      ▼
시황 요약 + 언급 종목 추출 (요약/구조화)   ← 규칙 기반 또는 Claude
      │
      ▼
종목별 시세·차트 (Stooq 일봉 / 합성 폴백)
      │
      ▼
정적 HTML 사이트
  /index.html                        지난 브리핑 아카이브
  /brief/<날짜>/index.html           시황 정리 (지수·종목 카드)
  /brief/<날짜>/stock/<slug>.html    종목별 서머리 (등락 이유 + 차트)
  /brief/<날짜>/onepage.html         단일 파일 공유용 (모든 종목 상세 포함, 링크 하나로 전달)
  /brief/<날짜>/data.json            구조화 데이터
```

시황 페이지와 종목 상세 페이지는 **인라인 CSS/SVG로 완전히 자기완결적**입니다
(외부 JS/CDN 없음, 라이트·다크 테마 대응, 색맹 대비 ▲▼ 기호 + 색상, 모바일 반응형).

## 빠른 시작 (자격증명 불필요)

핵심 파이프라인은 **표준 라이브러리만으로** 동작합니다. 자격증명이 없으면 번들된
샘플 브리핑으로 데모 사이트를 생성합니다.

```bash
# 1) 샘플 데이터로 사이트 생성
python -m morning_brief run --fixtures --out site

# 2) 로컬에서 확인
python -m morning_brief.cli serve --out site
#   → http://localhost:8000
```

## 라이브 모드 (실제 수집 + Claude 요약)

`.env.example` 를 참고해 환경변수를 설정하면 자동으로 라이브 모드로 전환됩니다.

```bash
pip install -r requirements.txt      # telethon + anthropic
cp .env.example .env                  # 값 채우기
python -m morning_brief run           # 오늘(KST) 브리핑 생성
```

| 환경변수 | 설명 |
| --- | --- |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION` | 텔레그램 수집(MTProto). `.env.example` 에 세션 발급 방법 포함 |
| `ANTHROPIC_API_KEY`, `MORNING_BRIEF_MODEL` | Claude 구조화 요약 (기본 모델 `claude-opus-4-8`) |

- 자격증명이 없으면 해당 단계는 폴백됩니다: 수집→샘플, 요약→규칙 기반, 시세→합성.
- 초장문(7,000~8,000자)이 여러 건으로 분할 게시돼도 그날 메시지를 시간순으로 재조립합니다.

## 매일 06:30 자동 실행

### 방법 A — GitHub Pages (권장)
[`.github/workflows/daily-brief.yml`](.github/workflows/daily-brief.yml) 가 매일
**21:30 UTC(=06:30 KST)** 에 실행되어 사이트를 생성하고 GitHub Pages 로 배포합니다.

1. 리포지토리 **Settings → Pages → Source: GitHub Actions** 활성화
2. **Settings → Secrets and variables → Actions** 에 시크릿 등록
   (`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION`, `ANTHROPIC_API_KEY`)
3. `Actions` 탭에서 **Run workflow** 로 수동 실행해 확인

> 시크릿이 없어도 워크플로우는 샘플 기반으로 동작해 CI가 깨지지 않습니다.

### 방법 B — 자체 서버 cron
```bash
./scripts/install_cron.sh   # 매일 06:30 에 scripts/run_daily.sh 실행하도록 등록
```

## 개발

```bash
pip install pytest
python -m pytest tests/ -q
```

## 프로젝트 구조

```
morning_brief/
  ingest.py        텔레그램 수집(+fixture 폴백)
  summarize.py     시황/종목 구조화 (Claude + 규칙 기반)
  stock_master.py  종목명↔티커 매핑/본문 스캔
  prices.py        Stooq 시세 + 합성 폴백
  chart.py         인라인 SVG 라인/스파크라인 차트
  render.py        정적 HTML 사이트 생성
  pipeline.py      수집→요약→시세→렌더 오케스트레이션
  cli.py           run / serve 명령
  data/            종목 마스터, 샘플 브리핑
.github/workflows/daily-brief.yml   매일 06:30 KST 자동 실행
docs/PRD.md        제품 요구사항 문서
```

## 유의사항
투자 참고용 자동 생성 자료이며 매매 권유가 아닙니다. 브리핑 원문 저작권은 작성자(서상영)에게
있으므로, 요약·재배포 시 사전 동의와 출처 표기를 권장합니다(자세한 내용은 PRD의 리스크 섹션 참고).
