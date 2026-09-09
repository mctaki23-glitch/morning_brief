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
--up:#C62828;--down:#043B72;--flat:#84888B;
--kr:'KoPub Dotum','KoPubDotum','KoPub Dotum Pro','KoPubDotum_Pro','Noto Sans KR','Spoqa Han Sans Neo','Apple SD Gothic Neo','Malgun Gothic',sans-serif;
--en:'Inter','Aptos','Segoe UI',system-ui,sans-serif}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--canvas);color:var(--body);font-family:var(--kr);font-size:17px;line-height:1.65;
-webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums;overflow-x:hidden}
a{color:var(--navy);text-decoration:none}
a:hover{color:var(--active)}
a:focus-visible,button:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid var(--orange);outline-offset:2px}
.num{font-family:var(--en);font-variant-numeric:tabular-nums}
.up{color:var(--up)} .down{color:var(--down)} .flat{color:var(--flat)}
.page{max-width:1200px;margin:0 auto;padding:28px 32px 64px}

/* 헤더 */
.mast{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;padding-bottom:16px;border-bottom:1px solid var(--hair2)}
.logo-slot{height:24px;margin-bottom:10px;display:flex;align-items:center}
.logo-slot:empty{display:none}
.logo-slot svg,.logo-slot img{height:24px;width:auto;display:block}
.brand .title{font-size:22px;font-weight:700;color:var(--ink);line-height:1.2;letter-spacing:-.3px}
.brand .title a{color:inherit}
.brand .sub{font-size:14px;color:var(--muted);margin-top:4px}
.when{text-align:right}
.when .date{font-family:var(--en);font-size:17px;font-weight:600;color:var(--ink)}
.when .date .wd{font-family:var(--kr);font-weight:500;color:var(--muted);margin-left:4px}
.when .links{font-size:14px;margin-top:2px}
.when .links a+a{margin-left:12px}

/* 섹션 */
.sec{margin-top:40px}
.rule{height:1px;background:var(--orange);margin-bottom:14px}
.sec h2{font-size:24px;line-height:1.3;font-weight:700;color:var(--ink);margin:0 0 12px;letter-spacing:-.3px}
.sec h2 .n{font-family:var(--en);font-weight:500;color:var(--muted);font-size:17px;margin-left:6px}
.sec-head{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.sec-head h2{margin:0}
.lead{font-size:19px;line-height:1.7;margin:0;max-width:68ch;color:var(--body)}
.lead+.lead{margin-top:12px}
.lead.headline{font-size:21px;font-weight:700;color:var(--ink);line-height:1.45;letter-spacing:-.3px}
.empty{color:var(--muted);font-size:15px;margin:0}

/* 지수 보드 */
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.tile{border:1px solid var(--hair);padding:12px 14px;background:var(--canvas);min-width:0}
.tile .l{font-size:13px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tile .v{font-family:var(--en);font-size:26px;font-weight:700;color:var(--navy);line-height:1.1;margin:4px 0 2px}
.tile .v:empty{display:none}
.tile .c{font-family:var(--en);font-size:15px;font-weight:600}

/* 컨트롤 (세그먼트) */
.controls{display:flex;gap:8px;flex-wrap:wrap}
.seg{display:inline-flex;border:1px solid var(--hair);border-radius:2px;overflow:hidden;background:var(--canvas)}
.seg button{appearance:none;border:0;background:var(--canvas);color:var(--muted);font:inherit;font-size:13.5px;padding:6px 12px;cursor:pointer;line-height:1.3}
.seg button+button{border-left:1px solid var(--hair)}
.seg button:hover{background:var(--s2);color:var(--ink)}
.seg button[aria-pressed="true"]{background:var(--orange);color:#FFFFFF;font-weight:600}

/* 종목 테이블 */
.tbl{border:1px solid var(--hair);overflow-x:auto;background:var(--canvas)}
table{border-collapse:collapse;width:100%;font-size:15px;line-height:1.5}
thead th{background:var(--soft);color:var(--ink);font-weight:700;text-align:left;padding:9px 12px;border-bottom:1px solid var(--hair);white-space:nowrap;font-size:14px}
tbody td{padding:10px 12px;border-bottom:1px solid var(--hair2);vertical-align:middle}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:var(--s2)}
th.r,td.r{text-align:right}
.stocks tr[hidden]{display:none}
.stocks .nm{font-weight:700;color:var(--ink)}
.stocks .nm a{color:inherit}
.stocks .nm a:hover{color:var(--active)}
.stocks .tk{font-family:var(--en);font-size:12px;color:var(--muted);margin-left:6px}
.stocks td.nm-cell{white-space:nowrap}
.stocks .mk{font-size:11px;color:var(--muted);border:1px solid var(--hair);padding:0 5px;margin-left:6px;vertical-align:1px}
.stocks .chg{font-family:var(--en);font-weight:700;white-space:nowrap}
.stocks .why{color:var(--muted);font-size:14px}
.stocks .mini svg{display:block}
.stocks .more{white-space:nowrap;font-size:13px}
.badge-warn{display:inline-block;font-size:11px;color:var(--muted);border:1px solid var(--hair);padding:0 5px;margin-left:6px;vertical-align:1px}

/* 관전 포인트 · 원문 */
.outlook p{font-size:17px;line-height:1.7;margin:0 0 10px;max-width:72ch}
details.raw{margin-top:18px;border:1px solid var(--hair2);padding:10px 14px;background:var(--s2)}
details.raw summary{cursor:pointer;font-size:14px;color:var(--navy);font-weight:600}
details.raw pre{white-space:pre-wrap;font-family:inherit;font-size:14px;line-height:1.6;color:var(--body);margin:10px 0 0}

/* 브리핑 전문 */
.fulltext .empty{margin:0 0 6px}
.msg{border-top:1px solid var(--hair2);padding:16px 0 18px}
.msg:last-child{padding-bottom:4px}
.msg-h{display:flex;gap:14px;align-items:baseline;font-size:13.5px;color:var(--muted);margin-bottom:8px}
.msg-h .num{font-family:var(--en)}
.msg-b{font-size:16px;line-height:1.75;color:var(--body);white-space:pre-wrap;overflow-wrap:anywhere;max-width:76ch}

/* 푸터 */
.foot{margin-top:48px;border-top:1px solid var(--hair2);padding-top:14px;font-size:13.5px;line-height:1.6;color:var(--muted)}
.foot p{margin:0 0 8px}
.tags{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}
.tag{display:inline-block;font-size:12px;color:var(--muted);border:1px solid var(--hair);padding:1px 8px;border-radius:2px;background:var(--canvas);white-space:nowrap}
.tag.ok{color:var(--navy);border-color:var(--navy)}
.tag.warn{color:var(--active);border-color:var(--active)}

/* 종목 서머리 (오버레이 시트, :target 기반 — JS 없이 동작) */
.detail{position:fixed;inset:0;z-index:50;display:none}
.detail:target{display:block}
.detail .scrim{position:absolute;inset:0;background:rgba(26,26,26,.55)}
.sheet{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(760px,calc(100vw - 32px));max-height:calc(100vh - 48px);
overflow:auto;background:var(--canvas);border:1px solid var(--hair);border-radius:4px;padding:22px 24px 24px}
.sheet .close{position:absolute;top:10px;right:10px;width:40px;height:40px;display:grid;place-items:center;color:var(--muted);font-size:22px;line-height:1;border:1px solid transparent;border-radius:2px}
.sheet .close:hover{color:var(--ink);border-color:var(--hair)}
.s-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;padding-right:48px}
.s-head h2{font-size:22px;font-weight:700;color:var(--ink);margin:0;letter-spacing:-.3px}
.s-head .tk{font-family:var(--en);font-size:13px;color:var(--muted)}
.s-head .mk{font-size:11px;border:1px solid var(--hair);padding:0 6px;color:var(--muted)}
.price{font-family:var(--en);font-size:24px;font-weight:700;color:var(--ink);margin:6px 0 14px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.price small{font-size:14px;font-weight:500;color:var(--muted)}
.price .chg{font-weight:700}
.s-rule{height:1px;background:var(--orange);margin:14px 0 10px}
.s-h{font-size:16px;font-weight:700;color:var(--ink);margin:0 0 8px}
.chart-card{background:var(--s2);border:1px solid var(--hair2);padding:8px}
.chart-card svg{display:block;width:100%;height:auto}
.chart-sm{display:none}
.chart-note{font-size:13px;color:var(--muted);margin:8px 0 0}
.reason{font-size:16px;line-height:1.65;margin:0;color:var(--body)}
.quote{margin:10px 0 0;padding:8px 14px;border-left:2px solid var(--soft);background:var(--s2);font-size:14.5px;line-height:1.6;color:var(--body)}
.quote .src{display:block;margin-top:6px;font-size:13px}
details.data{margin-top:10px}
details.data summary{cursor:pointer;font-size:13px;color:var(--navy);font-weight:600}
table.ohlcv{font-size:12.5px;margin-top:8px;font-family:var(--en)}
table.ohlcv th,table.ohlcv td{padding:4px 8px;text-align:right}
table.ohlcv th:first-child,table.ohlcv td:first-child{text-align:left}
.s-dis{font-size:12.5px;color:var(--muted2);margin:14px 0 0}
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
@media(max-width:768px){
 .page{padding:20px 20px 56px}
 .mast{flex-direction:column;align-items:flex-start;gap:6px}
 .when{text-align:left}
 .sec{margin-top:32px} .sec h2{font-size:21px} .lead{font-size:17px}
 .tile .v{font-size:22px}
}
@media(max-width:640px){
 .stocks thead{display:none}
 .stocks tbody tr{display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"nm chg" "why why" "mini mini";gap:2px 10px;padding:12px 14px;border-bottom:1px solid var(--hair2)}
 .stocks tbody tr[hidden]{display:none}
 .stocks tbody td{display:block;padding:0;border:0}
 .stocks tbody tr:hover td{background:transparent}
 .stocks tbody tr:hover{background:var(--s2)}
 .stocks td.nm-cell{grid-area:nm} .stocks td.chg{grid-area:chg;text-align:right} .stocks td.why{grid-area:why} .stocks td.mini{grid-area:mini;margin-top:6px}
 .stocks td.more{display:none}
 .stocks .mini svg{width:100%;height:36px}
 .chart-lg{display:none} .chart-sm{display:block}
 .sheet{left:0;right:0;top:auto;bottom:0;transform:none;width:100%;max-height:92vh;border-radius:4px 4px 0 0;padding:16px 16px calc(20px + env(safe-area-inset-bottom))}
 .sheet::before{content:"";display:block;width:40px;height:3px;background:var(--hair);margin:0 auto 12px}
 .arc{grid-template-columns:1fr;gap:4px}
}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media print{
 body{font-size:13pt;line-height:1.45} .page{max-width:100%;padding:0}
 .controls,.when .links,.detail,.foot .tags{display:none}
 .tbl,.tile,.chart-card{page-break-inside:avoid} .sec h2{page-break-after:avoid}
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
