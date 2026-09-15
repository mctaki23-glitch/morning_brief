"""미래에셋 CI 테마 — 정적 사이트 공용 CSS·폰트 링크.

디자인 시스템 요약 (docs/PRD.md 5장)
- 화이트 캔버스 단일 테마(다크모드 없음). 오렌지는 섹션 룰·활성 상태에만, 블루는 강조 수치·하락.
- 모서리 sharp(카드 4px 이하, 버튼 2px, 테이블 0). 그라데이션·이모지·드롭섀도·이탤릭 없음.
- 한국어 본문·제목 KoPub돋움체(정식 고딕, 자체 호스팅 @font-face: assets/fonts 에 파일이 있을 때) → 폴백 Noto Sans KR(Google Fonts),
  영문·숫자 Inter, tabular-nums.
- 시그니처: 1px 오렌지 섹션 룰, #FAB072 테이블 헤더.
"""

FONTS_HTML = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700'
    '&family=Inter:wght@400;500;600;700&display=swap">'
)

TOKENS = {
    "orange": "#F58220", "navy": "#043B72", "soft": "#FAB072", "active": "#CB6015", "highlight": "#D7D7D7",
    "canvas": "#FFFFFF", "surface_soft": "#ECEFF4", "surface_subtle": "#F7F8FA",
    "hairline": "#CDCECB", "hairline_soft": "#E5E4E1",
    "ink": "#1A1A1A", "body": "#3D3D3D", "muted": "#6C6C6C", "muted_soft": "#84888B",
    "up": "#C62828", "down": "#043B72", "flat": "#84888B",
}

CSS = r"""
:root{--orange:#F58220;--navy:#043B72;--soft:#FAB072;--active:#CB6015;--hl:#D7D7D7;--canvas:#FFFFFF;
--s1:#ECEFF4;--s2:#F7F8FA;--hair:#CDCECB;--hair2:#E5E4E1;--ink:#1A1A1A;--body:#3D3D3D;--muted:#6C6C6C;--muted2:#84888B;
--up:#C62828;--down:#043B72;--flat:#84888B;--gutter:32px;
--kr:'KoPub Dotum','KoPubDotum','KoPub Dotum Pro','KoPubDotum_Pro','Noto Sans KR','Spoqa Han Sans Neo','Apple SD Gothic Neo','Malgun Gothic',sans-serif;
--en:'Inter','Aptos','Segoe UI',system-ui,sans-serif}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scrollbar-gutter:stable}
body{margin:0;background:var(--canvas);color:var(--body);font-family:var(--kr);font-size:17px;line-height:1.65;
-webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums;overflow-x:hidden}
body::before{content:"";display:block;height:4px;background:var(--orange)}
body.sheet-open{overflow:hidden}
a{color:var(--navy);text-decoration:none}
a:hover{color:var(--active)}
a:focus-visible,button:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid var(--orange);outline-offset:2px}
.num{font-family:var(--en);font-variant-numeric:tabular-nums}
.up{color:var(--up)} .down{color:var(--down)} .flat{color:var(--flat)}
.page{max-width:1200px;margin:0 auto;padding:22px var(--gutter) 72px}

/* 헤더 — 1행: 브랜드 | 날짜, 2행: 출처·시각 | 이동 링크 */
.mast{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:end;gap:4px 24px;padding-bottom:14px;border-bottom:1px solid var(--hair)}
.brand{display:flex;align-items:center;gap:14px;min-width:0}
.logo-slot{height:26px;display:flex;align-items:center}
.logo-slot:empty{display:none}
.logo-slot svg,.logo-slot img{height:26px;width:auto;display:block}
.brand .title{font-size:26px;font-weight:700;color:var(--ink);line-height:1.15;letter-spacing:-.5px}
.brand .title a{color:inherit}
.when{text-align:right;line-height:1.15}
.when .date{font-family:var(--en);font-size:24px;font-weight:700;color:var(--ink);letter-spacing:-.3px}
.when .date .wd{font-family:var(--kr);font-size:15px;font-weight:500;color:var(--muted);margin-left:6px;letter-spacing:0}
.mast-meta{grid-column:1/-1;display:flex;justify-content:space-between;align-items:baseline;gap:8px 24px;flex-wrap:wrap;margin-top:4px}
.mast .sub{font-size:13.5px;color:var(--muted);letter-spacing:.1px}
.mast .links{display:flex;font-size:13.5px;line-height:1.2}
.mast .links a{padding:0 12px;border-left:1px solid var(--hair);color:var(--navy);font-weight:500;white-space:nowrap}
.mast .links a:first-child{border-left:0;padding-left:0}
.mast .links a:last-child{padding-right:0}

/* 과거 브리핑 페이지 상단 안내(최신 브리핑 링크) */
.newer{display:block;margin-top:16px;padding:10px 14px;border:1px solid var(--orange);border-radius:2px;background:var(--s2);color:var(--body);font-size:14.5px;line-height:1.5}
.newer strong{color:var(--navy);font-weight:700}
.newer:hover{background:var(--s1)}

/* 섹션 */
.sec{margin-top:56px}
.rule{height:1px;background:var(--orange);margin-bottom:14px}
.sec h2{font-size:22px;line-height:1.3;font-weight:700;color:var(--ink);margin:0 0 16px;letter-spacing:-.3px}
.sec h2 .n{font-family:var(--en);font-weight:600;color:var(--muted);font-size:14px;margin-left:8px;letter-spacing:0}
.sec-head{display:flex;justify-content:space-between;align-items:baseline;gap:10px 20px;flex-wrap:wrap;margin-bottom:14px}
.sec-head h2{margin:0}
.sec-meta{font-size:13.5px;color:var(--muted);margin:0}
.lead{font-size:19px;line-height:1.75;margin:0;max-width:66ch;color:var(--body)}
.lead+.lead{margin-top:14px}
.lead.headline{font-size:24px;font-weight:700;color:var(--ink);line-height:1.4;letter-spacing:-.4px;max-width:56ch;text-wrap:balance}
.empty{color:var(--muted);font-size:15px;margin:0}

/* 지수 보드 */
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(176px,1fr));gap:12px}
.tile{border:1px solid var(--hair);border-radius:6px;padding:14px 16px 12px;background:var(--canvas);min-width:0;display:flex;flex-direction:column}
.tile .t-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.tile .l{font-size:13px;font-weight:600;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tile .v{font-family:var(--en);font-size:26px;font-weight:700;color:var(--ink);line-height:1.1;margin:8px 0 0;letter-spacing:-.3px}
.tile .v:empty{display:none}
.tile .c{font-family:var(--en);font-size:14px;font-weight:700;white-space:nowrap}
.tile .spark{margin-top:12px;padding-top:10px;border-top:1px solid var(--hair2)}
.tile .spark svg{display:block;width:100%;height:auto}
.tile .note{font-size:11.5px;color:var(--muted2);margin-top:6px;font-family:var(--en)}

/* 컨트롤 (세그먼트) */
.controls{display:flex;gap:8px;flex-wrap:wrap}
.seg{display:inline-flex;border:1px solid var(--hair);border-radius:2px;overflow:hidden;background:var(--canvas)}
.seg button{appearance:none;border:0;background:var(--canvas);color:var(--muted);font:inherit;font-size:13px;font-weight:500;padding:5px 11px;cursor:pointer;line-height:1.3}
.seg button+button{border-left:1px solid var(--hair)}
.seg button:hover{background:var(--s2);color:var(--ink)}
.seg button[aria-pressed="true"]{background:var(--orange);color:#FFFFFF;font-weight:600}

/* 종목 카드 — 카드 어디를 눌러도 상세, 누르는 동안 하이라이트(.pressed / :active). PC 2열 · 960px 이하 1열 */
.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.card{border:1px solid var(--hair);border-radius:6px;background:var(--canvas);padding:14px 16px;min-width:0;cursor:pointer;
-webkit-tap-highlight-color:transparent;transition:background-color .15s,border-color .15s}
.card[hidden]{display:none}
.card:hover{background:var(--s2)}
.card.pressed,.card:active{background:var(--s1);border-color:var(--orange)}
.card:focus-visible{outline:2px solid var(--orange);outline-offset:2px}
.c-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.card .nm{display:block;font-weight:700;color:var(--ink);font-size:16px;line-height:1.3}
.card .meta{display:block;font-size:12.5px;color:var(--muted);margin-top:2px;letter-spacing:.1px;line-height:1.3}
.card .meta .tk{font-family:var(--en);font-weight:500}
.card .chg{font-family:var(--en);font-weight:700;white-space:nowrap;font-size:17px;line-height:1.3}
.c-body{display:grid;grid-template-columns:200px minmax(0,1fr);grid-template-areas:"mini why";gap:6px 18px;align-items:center;margin-top:10px;padding-top:10px;border-top:1px solid var(--hair2)}
.card .mini{grid-area:mini;min-width:0}
.card .mini:empty{display:none}
.card .mini:empty+.why{grid-column:1/-1}
.card .mini-link{display:block}
.card .mini svg{display:block;width:100%;height:auto}
.card .why{grid-area:why;margin:0;color:var(--body);font-size:14.5px;line-height:1.6}
tr[data-sheet]{-webkit-tap-highlight-color:transparent}
tr[data-sheet].pressed td{background:var(--s1)}

/* 매크로 테이블 — 헤어라인 행, 이름 / 단위 2줄 */
.tbl{border:1px solid var(--hair);overflow-x:auto;background:var(--canvas)}
table{border-collapse:collapse;width:100%;font-size:15px;line-height:1.5}
thead th{background:var(--soft);color:var(--ink);font-weight:700;text-align:left;padding:9px 14px;border-bottom:1px solid var(--hair);white-space:nowrap;font-size:13px;letter-spacing:.2px}
tbody td{padding:12px 14px;border-bottom:1px solid var(--hair2);vertical-align:middle}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:var(--s2)}
th.r,td.r{text-align:right}
.stocks tr[hidden]{display:none}
.stocks .nm{display:block;font-weight:700;color:var(--ink);font-size:15.5px;line-height:1.3}
.stocks .meta{display:block;font-size:12.5px;color:var(--muted);margin-top:3px;letter-spacing:.1px;line-height:1.3}
.stocks .meta .tk{font-family:var(--en);font-weight:500}
.stocks td.nm-cell{white-space:nowrap;min-width:150px}
.stocks .chg{font-family:var(--en);font-weight:700;white-space:nowrap;font-size:15.5px}
.macro td.val{font-family:var(--en);font-weight:600;color:var(--ink);white-space:nowrap}
.stocks .why{color:var(--body);font-size:14.5px;line-height:1.6}
.stocks td.mini{width:176px}
.stocks .mini-link{display:block;width:160px}
.stocks .mini svg{display:block;width:100%;height:auto}
.c-dates{font-family:var(--en);font-size:10.5px;line-height:1.2;color:var(--muted2);margin-top:4px;white-space:nowrap;letter-spacing:.1px}
.stocks tbody tr[data-sheet]{cursor:pointer}
.stocks tbody tr[data-sheet]:focus-visible{outline:2px solid var(--orange);outline-offset:-2px}
.badge-warn{display:inline-block;font-size:11px;color:var(--muted);border:1px solid var(--hair);padding:0 5px;margin-left:6px;vertical-align:1px}

/* 관전 포인트 · 원문 */
.outlook p{font-size:17px;line-height:1.75;margin:0 0 12px;max-width:70ch}
details.raw{margin-top:18px;border:1px solid var(--hair2);padding:10px 14px;background:var(--s2)}
details.raw summary{cursor:pointer;font-size:14px;color:var(--navy);font-weight:600}
details.raw pre{white-space:pre-wrap;font-family:inherit;font-size:14px;line-height:1.6;color:var(--body);margin:10px 0 0}

/* 푸터 — 출처·품질 태그 한 줄, 고지 한 줄 */
.foot{margin-top:64px;border-top:1px solid var(--hair2);padding-top:16px;font-size:13.5px;line-height:1.6;color:var(--muted)}
.foot p{margin:0}
.foot-row{display:flex;justify-content:space-between;align-items:baseline;gap:8px 24px;flex-wrap:wrap;margin-bottom:10px}
.foot .dis{max-width:90ch;font-size:12.5px;color:var(--muted2)}
.tags{display:flex;gap:6px;flex-wrap:wrap;margin:0}
.tag{display:inline-block;font-size:12px;color:var(--muted);border:1px solid var(--hair);padding:1px 8px;border-radius:2px;background:var(--canvas);white-space:nowrap}
.tag.ok{color:var(--navy);border-color:var(--navy)}
.tag.warn{color:var(--active);border-color:var(--active)}

/* 종목 서머리 (오버레이 시트, :target 기반 — JS 없이 동작) — PC 는 차트 | 등락 이유 2열 */
.detail{position:fixed;inset:0;z-index:50;display:none}
.detail:target{display:block}
html.js .detail:target:not(.open){display:none}
html.js .detail.open{display:block}
.detail .scrim{position:absolute;inset:0;background:rgba(26,26,26,.55)}
.sheet{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(960px,calc(100vw - 32px));max-height:calc(100vh - 48px);
overflow:auto;overscroll-behavior:contain;background:var(--canvas);border:1px solid var(--hair);border-radius:6px;padding:22px 28px 24px}
.sheet .close{position:absolute;top:10px;right:10px;width:40px;height:40px;display:grid;place-items:center;color:var(--muted);font-size:22px;line-height:1;border:1px solid transparent;border-radius:2px}
.sheet .close:hover{color:var(--ink);border-color:var(--hair)}
.s-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;padding-right:48px}
.s-head h2{font-size:24px;font-weight:700;color:var(--ink);margin:0;letter-spacing:-.4px;line-height:1.2}
.s-head .s-meta{font-size:13.5px;color:var(--muted);font-weight:500}
.s-head .s-meta .tk{font-family:var(--en)}
.s-head .share{font-size:13px;color:var(--navy);font-weight:500;border-bottom:1px solid var(--hair)}
.price{font-family:var(--en);font-size:28px;font-weight:700;color:var(--ink);margin:8px 0 16px;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;letter-spacing:-.3px;line-height:1.15}
.price small{font-size:14px;font-weight:500;color:var(--muted);letter-spacing:0}
.price .chg{font-weight:700;font-size:22px}
.price small.stale{color:var(--active);font-weight:600}
.s-rule{height:1px;background:var(--orange);margin:0 0 18px}
.s-grid{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:24px;align-items:start}
.s-side{background:var(--s2);border:1px solid var(--hair2);border-radius:6px;padding:16px 18px 18px;min-width:0}
.s-h{font-size:13px;font-weight:700;color:var(--muted);margin:0 0 10px;letter-spacing:.3px}
.chart-card{background:var(--canvas);border:1px solid var(--hair2);padding:8px}
.chart-card svg{display:block;width:100%;height:auto}
.chart-sm{display:none}
.chart-note{font-size:12.5px;color:var(--muted);margin:8px 0 0;line-height:1.55}
.reason{font-size:16px;line-height:1.7;margin:0;color:var(--body)}
.quote{margin:14px 0 0;padding:2px 0 2px 12px;border-left:2px solid var(--soft);font-size:14px;line-height:1.65;color:var(--muted)}
.quote .src{display:block;margin-top:6px;font-size:13px}
details.data{margin-top:10px}
details.data summary{cursor:pointer;font-size:13px;color:var(--navy);font-weight:600}
table.ohlcv{font-size:12.5px;margin-top:8px;font-family:var(--en)}
table.ohlcv th,table.ohlcv td{padding:4px 8px;text-align:right}
table.ohlcv th:first-child,table.ohlcv td:first-child{text-align:left}
.s-dis{font-size:12.5px;color:var(--muted2);margin:18px 0 0}
.stock-page .sheet{position:static;transform:none;width:auto;max-height:none;margin-top:20px}
.back{display:inline-block;font-size:14px;margin-bottom:8px}

/* 아카이브 */
.search{width:100%;max-width:420px;font:inherit;font-size:15px;padding:8px 12px;border:1px solid var(--hair);border-radius:2px;color:var(--ink);background:var(--canvas)}
.arc-month{font-size:15px;font-weight:700;color:var(--muted);margin:24px 0 8px;letter-spacing:.2px}
.arc{display:grid;grid-template-columns:120px minmax(0,1fr) auto;gap:14px;align-items:baseline;padding:12px 4px;border-bottom:1px solid var(--hair2)}
.arc[hidden]{display:none}
.arc .d{font-family:var(--en);font-weight:600;color:var(--ink)}
.arc .d .wd{font-family:var(--kr);font-weight:400;color:var(--muted);margin-left:4px}
.arc .o{color:var(--body);font-size:15px}
.arc .o .names{display:block;color:var(--muted);font-size:13.5px;margin-top:2px}
.arc .c{font-family:var(--en);font-size:13px;color:var(--muted);white-space:nowrap}

/* 상태 페이지 (대기 · 브리핑 없음) */
.status{border:1px solid var(--hair);padding:28px;margin-top:32px;max-width:720px}
.status h2{font-size:22px;color:var(--ink);margin:0 0 8px}
.status p{margin:0 0 10px;font-size:16px}

/* 반응형 */
@media(max-width:960px){
 .cards{grid-template-columns:minmax(0,1fr)}
}
@media(max-width:768px){
 :root{--gutter:20px}
 .page{padding:16px var(--gutter) 56px}
 .mast{gap:2px 12px;padding-bottom:12px}
 .brand .title{font-size:21px;letter-spacing:-.4px}
 .when .date{font-size:17px} .when .date .wd{font-size:13px;margin-left:4px}
 .mast-meta{flex-direction:column;align-items:flex-start;gap:6px}
 .sec{margin-top:40px} .sec h2{font-size:20px} .lead{font-size:17px;line-height:1.7} .lead.headline{font-size:21px}
 .tile .v{font-size:22px}
 .s-grid{grid-template-columns:minmax(0,1fr);gap:18px}
 .s-head h2{font-size:21px} .price{font-size:24px} .price .chg{font-size:19px}
}
@media(max-width:640px){
 .stocks thead{display:none}
 .tbl.stocks{border-width:1px 0}
 .stocks tbody tr{display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"nm chg" "why why" "mini mini";gap:4px 12px;padding:14px 0;border-bottom:1px solid var(--hair2)}
 .stocks tbody tr:last-child{border-bottom:0}
 .macro tbody tr{grid-template-areas:"nm chg" "val val" "why why" "mini mini"}
 .macro td.val{grid-area:val;text-align:left;font-size:18px}
 .stocks tbody tr[hidden]{display:none}
 .stocks tbody td{display:block;padding:0;border:0}
 .stocks tbody tr:hover td{background:transparent}
 .cards{gap:10px}
 .card{padding:14px 14px 12px}
 .c-body{grid-template-columns:minmax(0,1fr);grid-template-areas:"why" "mini";gap:10px;align-items:start}
 .tiles{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
 .tile:nth-child(odd):last-child{grid-column:1/-1}
 .tile{padding:12px 12px 10px} .tile .v{font-size:22px}
 .tile .t-head{align-items:flex-start} .tile .l{white-space:normal;line-height:1.3}
 .stocks td.nm-cell{grid-area:nm;white-space:normal;min-width:0} .stocks td.chg{grid-area:chg;text-align:right} .stocks td.why{grid-area:why;margin-top:2px} .stocks td.mini{grid-area:mini;margin-top:8px}
 .stocks td.mini{width:auto} .stocks .mini-link{width:100%}
 .stocks .mini svg{width:100%;height:auto}
 .c-dates{font-size:11.5px;margin-top:6px}
 .chart-lg{display:none} .chart-sm{display:block}
 .sheet{left:0;right:0;top:auto;bottom:0;transform:none;width:100%;max-height:92vh;border-radius:6px 6px 0 0;padding:14px 16px calc(20px + env(safe-area-inset-bottom))}
 .sheet::before{content:"";display:block;width:40px;height:3px;background:var(--hair);margin:0 auto 12px}
 .s-side{padding:14px 14px 16px}
 .arc{grid-template-columns:1fr;gap:4px}
}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media print{
 body{font-size:13pt;line-height:1.45} .page{max-width:100%;padding:0}
 .controls,.mast .links,.detail,.foot .tags{display:none}
 .tbl,.tile,.card,.chart-card{page-break-inside:avoid} .sec h2{page-break-after:avoid}
}
"""

# ── KoPub돋움 자체 호스팅 (assets/fonts 에 파일이 있을 때만 @font-face 생성) ─────
# 파일명 규칙: KoPubDotum-Light / KoPubDotum-Medium / KoPubDotum-Bold (.woff2 | .woff | .ttf | .otf)
FONT_FILES = {"KoPubDotum-Light": "300", "KoPubDotum-Medium": "400 500", "KoPubDotum-Bold": "600 700"}
_FORMATS = (("woff2", "woff2"), ("woff", "woff"), ("ttf", "truetype"), ("otf", "opentype"))


def font_face_css(root: str, available) -> str:
    """존재하는 KoPub돋움 파일로 @font-face 규칙을 만든다. 없으면 빈 문자열(브라우저는 Noto Sans KR 로 폴백)."""
    avail = set(available or ())
    rules = []
    for stem, weight in FONT_FILES.items():
        srcs = [f"url('{root}assets/fonts/{stem}.{ext}') format('{fmt}')" for ext, fmt in _FORMATS if f"{stem}.{ext}" in avail]
        if srcs:
            rules.append(f"@font-face{{font-family:'KoPub Dotum';src:{','.join(srcs)};font-weight:{weight};font-style:normal;font-display:swap}}")
    return "".join(rules)
