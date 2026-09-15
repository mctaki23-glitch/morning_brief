"""시세 소스 점검 스크립트 (GitHub 러너에서 실행해 어떤 소스가 응답하는지 확인).

python scripts/probe_sources.py  → 각 후보 URL 의 HTTP 상태, 응답 앞부분, JSON 키를 출력한다. 시세 파이프라인은 건드리지 않는다.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from morning_brief import prices as _p  # noqa: E402

END = date.today()
START = END - timedelta(days=100)
NAVER_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"


def fetch(url: str, headers: dict, timeout: int = 20) -> tuple[str, str]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return str(resp.status), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}", exc.read().decode("utf-8", errors="replace")[:300]
    except Exception as exc:  # noqa: BLE001
        return f"ERR {exc!r}", ""


def summarize(body: str) -> str:
    b = body.strip()
    if not b:
        return "(empty)"
    if b[0] in "[{":
        try:
            data = json.loads(b)
        except json.JSONDecodeError:
            return "JSON? " + b[:200].replace("\n", " ")
        if isinstance(data, list):
            first = data[0] if data else None
            keys = sorted(first.keys()) if isinstance(first, dict) else type(first).__name__
            return f"list[{len(data)}] first keys={keys} first={json.dumps(first, ensure_ascii=False)[:220]}"
        out = f"dict keys={sorted(data.keys())}"
        d = data.get("data")
        if isinstance(d, dict):
            out += f" data.keys={sorted(d.keys())}"
            tt = d.get("tradesTable")
            if isinstance(tt, dict):
                rows = tt.get("rows") or []
                out += f" rows={len(rows)} first={json.dumps(rows[0], ensure_ascii=False)[:200] if rows else None}"
        elif isinstance(d, list):
            out += f" data=list[{len(d)}] first={json.dumps(d[0], ensure_ascii=False)[:220] if d else None}"
        if isinstance(d, dict) and ("primaryData" in d or "summaryData" in d):
            out += " " + json.dumps({k: d[k] for k in d if k in ("primaryData", "secondaryData", "marketStatus", "lastTradeTimestamp")}, ensure_ascii=False)[:500]
            if isinstance(d.get("summaryData"), dict):
                out += " summary=" + json.dumps({k: v.get("value") if isinstance(v, dict) else v for k, v in d["summaryData"].items()}, ensure_ascii=False)[:700]
        if isinstance(d, dict) and "chart" in d:
            ch = d.get("chart") or []
            out += f" chart_points={len(ch)} first={json.dumps(ch[0], ensure_ascii=False)[:200] if ch else None} last={json.dumps(ch[-1], ensure_ascii=False)[:200] if ch else None} other_keys={sorted(k for k in d if k != 'chart')}"
        if "status" in data:
            out += f" status={json.dumps(data['status'], ensure_ascii=False)[:160]}"
        if "quotes" in data:
            qs = data["quotes"][:6] if isinstance(data["quotes"], list) else data["quotes"]
            out += " quotes=" + json.dumps([{k: q.get(k) for k in ("id", "symbol", "description", "exchange", "type", "flag")} for q in qs], ensure_ascii=False)[:900]
        return out
    return b[:260].replace("\n", " | ")


def nasdaq(symbol: str, assetclass: str) -> str:
    return (f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(symbol, safe='')}/historical?assetclass={assetclass}"
            f"&fromdate={START:%Y-%m-%d}&todate={END:%Y-%m-%d}&limit=9999")


NASDAQ_H = {"User-Agent": _p._UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
NAVER_H = {"User-Agent": NAVER_UA, "Accept": "application/json", "Referer": "https://m.stock.naver.com/"}
PLAIN_H = {"User-Agent": _p._UA, "Accept": "*/*"}

PROBES: list[tuple[str, str, dict, int]] = [
    ("treasury yield csv", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
     f"{END.year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={END.year}&page&_format=csv", PLAIN_H, 40),
    ("coingecko btc (control)", "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=3&interval=daily", PLAIN_H, 20),
]
# 네이버 시장지표: 카테고리 목록(코드 발견용) + 로이터 코드 추정치로 일봉 조회
NAVER_LISTS = ("metals", "energy", "agricultural", "exchange", "bond", "interest", "rates", "index")
for cat in NAVER_LISTS:
    PROBES.append((f"naver list {cat}", f"https://api.stock.naver.com/marketindex/{cat}", NAVER_H, 20))
for path in ("metals/GCcv1", "metals/SIcv1", "metals/HGcv1", "energy/CLcv1", "energy/LCOcv1", "energy/NGcv1",
             "agricultural/Wcv1", "agricultural/Ccv1", "agricultural/Scv1", "agricultural/KCcv1", "agricultural/CCcv1", "agricultural/SBcv1",
             "bond/US2YT=RR", "bond/US10YT=RR", "exchange/FX_USDKRW"):
    PROBES.append((f"naver prices {path} (60)", f"https://api.stock.naver.com/marketindex/{urllib.parse.quote(path, safe='/=')}/prices?page=1&pageSize=60", NAVER_H, 20))


def naver_items(body: str) -> str:
    """카테고리 목록 응답에서 (reutersCode, symbolCode, name, nameEng, unit, close) 만 뽑아 한 줄씩."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return body[:200]
    items = data if isinstance(data, list) else [x for k in ("majorList", "normalList") for x in (data.get(k) or [])] if isinstance(data, dict) else []
    lines = []
    for it in items:
        if isinstance(it, dict):
            lines.append("      - " + " | ".join(str(it.get(k)) for k in ("categoryType", "reutersCode", "symbolCode", "name", "nameEng", "unit", "closePrice")))
    return f"{len(items)} items\n" + "\n".join(lines)


# ── 지수 시세 후보 (다우 · 나스닥 · S&P500 · 러셀2000 · 필라델피아 반도체 · 코스피 · 코스닥) ──
for code in (".DJI", ".IXIC", ".INX", ".SPX", ".RUT", ".SOX", "KOSPI", "KOSDAQ"):
    PROBES.append((f"naver index {code}", f"https://api.stock.naver.com/index/{urllib.parse.quote(code)}/price?page=1&pageSize=3", NAVER_H, 20))
PROBES.append(("naver index basic .DJI", "https://api.stock.naver.com/index/.DJI/basic", NAVER_H, 20))
for sym in ("SPX", "COMP", "INDU", "RUT", "SOX", "DJIA", "NDX"):
    PROBES.append((f"nasdaq index {sym}", nasdaq(sym, "index"), NASDAQ_H, 20))
for sym in ("KOSPI", "KOSDAQ"):
    PROBES.append((f"naver siseJson {sym}", f"https://api.finance.naver.com/siseJson.naver?symbol={sym}&requestType=1&startTime={START:%Y%m%d}&endTime={END:%Y%m%d}&timeframe=day",
                   {"User-Agent": _p._UA, "Accept": "*/*", "Referer": "https://finance.naver.com/"}, 20))
for path in ("worldstock/index/.DJI/price", "index/.DJI/prices"):
    PROBES.append((f"naver alt {path}", f"https://api.stock.naver.com/{path}?page=1&pageSize=3", NAVER_H, 20))


# ── 마감 직후 최신 봉 보충 후보 (Nasdaq historical 은 종가를 수 시간 뒤에 반영) ──
for sym in ("OKLO.N", "OKLO", "OKLO.O", "ORCL.N", "DELL.N", "ABBV.N", "MU.O", "HXSCL", "HXSCL.O", "HXSCL.N", "SKHY", "SKHY.O", "SKHY.N"):
    PROBES.append((f"naver world {sym}", f"https://api.stock.naver.com/stock/{urllib.parse.quote(sym)}/price?pageSize=3&page=1", NAVER_H, 20))
for sym in ("OKLO", "MU", "HXSCL", "SKHY"):
    PROBES.append((f"nasdaq info {sym}", f"https://api.nasdaq.com/api/quote/{sym}/info?assetclass=stocks", NASDAQ_H, 20))
    PROBES.append((f"nasdaq summary {sym}", f"https://api.nasdaq.com/api/quote/{sym}/summary?assetclass=stocks", NASDAQ_H, 20))
    PROBES.append((f"nasdaq historical {sym} (last rows)", nasdaq(sym, "stocks"), NASDAQ_H, 20))


# ── OTC 예탁증서(SK하이닉스 ADR = HXSCL) 시세 소스 후보 — Nasdaq·네이버 해외주식은 09-15 재처리에서 조용히 실패(rCode 400 / 409) ──
PLAIN_UA = {"User-Agent": _p._UA, "Accept": "*/*"}
PROBES.append(("nasdaq chart HXSCL 5d", f"https://api.nasdaq.com/api/quote/HXSCL/chart?assetclass=stocks&fromdate={END - timedelta(days=5):%Y-%m-%d}&todate={END:%Y-%m-%d}", NASDAQ_H, 20))
for sym in ("HXSCL.PK", "HXSCL.K", "HXSCL.US"):
    PROBES.append((f"naver world {sym}", f"https://api.stock.naver.com/stock/{urllib.parse.quote(sym)}/price?pageSize=3&page=1", NAVER_H, 20))
PROBES.append(("naver m search HXSCL", "https://m.stock.naver.com/api/search/all?query=HXSCL", NAVER_H, 20))
PROBES.append(("naver m search 하이닉스 ADR", "https://m.stock.naver.com/api/search/all?query=" + urllib.parse.quote("SK하이닉스 ADR"), NAVER_H, 20))
PROBES.append(("stooq hxscl.us csv", "https://stooq.com/q/d/l/?s=hxscl.us&i=d", PLAIN_UA, 20))
PROBES.append(("cnbc quote HXSCL", "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=HXSCL&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1", PLAIN_UA, 20))
PROBES.append(("cnbc bars HXSCL 1M", "https://ts-api.cnbc.com/harmony/app/bars/1M/1D/adjusted/HXSCL.json", PLAIN_UA, 20))
PROBES.append(("otcmarkets inside HXSCL", "https://backend.otcmarkets.com/otcapi/stock/trade/inside/HXSCL?symbol=HXSCL", {"User-Agent": _p._UA, "Accept": "application/json", "Referer": "https://www.otcmarkets.com/", "Origin": "https://www.otcmarkets.com"}, 20))
PROBES.append(("marketwatch csv HXSCL", f"https://www.marketwatch.com/investing/stock/hxscl/downloaddatapartial?startdate={END - timedelta(days=40):%m/%d/%Y}%2000:00:00&enddate={END:%m/%d/%Y}%2000:00:00&daterange=d30&frequency=p1d&csvdownload=true&downloadpartial=false&newdates=false", PLAIN_UA, 20))
PROBES.append(("google finance HXSCL", "https://www.google.com/finance/quote/HXSCL:OTCMKTS", PLAIN_UA, 20))


# ── HXSCL 2차 후보: CNBC 시세 JSON 전체 덤프 · CNBC 시계열 경로 변형 · 서버 렌더링 히스토리 페이지(FT · stockanalysis) · Yahoo 재시도 ──
PROBES.append(("dump cnbc quote HXSCL", "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=HXSCL&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1", PLAIN_UA, 20))
for path in ("bars/1D/1M/adjusted/HXSCL.json", "bars/1M/1D/adjusted/HXSCL-US.json", "bars/3M/1D/adjusted/HXSCL.json", "bars/1Y/1D/adjusted/HXSCL.json",
             "charts/1M.json?symbol=HXSCL", "bars/1M/1D/adjusted/AAPL.json"):
    PROBES.append((f"cnbc ts {path}", f"https://ts-api.cnbc.com/harmony/app/{path}", PLAIN_UA, 20))
PROBES.append(("html ft tearsheet HXSCL:PKC", "https://markets.ft.com/data/equities/tearsheet/historical?s=HXSCL:PKC", PLAIN_UA, 25))
PROBES.append(("html stockanalysis HXSCL history", "https://stockanalysis.com/quote/otc/HXSCL/history/", PLAIN_UA, 25))
PROBES.append(("yahoo chart HXSCL", "https://query2.finance.yahoo.com/v8/finance/chart/HXSCL?range=3mo&interval=1d", PLAIN_UA, 20))
PROBES.append(("yahoo spark HXSCL", "https://query1.finance.yahoo.com/v7/finance/spark?symbols=HXSCL&range=3mo&interval=1d", PLAIN_UA, 20))


PROBES.append(("dump cnbc ts charts HXSCL", "https://ts-api.cnbc.com/harmony/app/charts/1M.json?symbol=HXSCL", PLAIN_UA, 20))
PROBES.append(("dump cnbc ts charts AAPL", "https://ts-api.cnbc.com/harmony/app/charts/1M.json?symbol=AAPL", PLAIN_UA, 20))
PROBES.append(("dump cnbc quote HXSCL.PK", "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=HXSCL.PK&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json", PLAIN_UA, 20))


for sym in ("OKLO", "MU"):
    PROBES.append((f"nasdaq chart {sym} 1d", f"https://api.nasdaq.com/api/quote/{sym}/chart?assetclass=stocks&fromdate={END - timedelta(days=1):%Y-%m-%d}&todate={END:%Y-%m-%d}", NASDAQ_H, 20))
    PROBES.append((f"nasdaq chart {sym} default", f"https://api.nasdaq.com/api/quote/{sym}/chart?assetclass=stocks", NASDAQ_H, 20))


def live_topup_checks() -> None:
    """실제 보충 함수를 러너에서 실행해 코드 경로를 검증한다. historical 마지막 봉이 through-5일이라고 가정하고 그 이후 봉을 받아본다
    (OKLO·ORCL: 네이버에 없는 NYSE 종목, IWM: 러셀2000 프록시 ETF)."""
    through = (END - timedelta(days=1)).isoformat()
    last = (END - timedelta(days=5)).isoformat()
    for sym, assetclass in (("OKLO", "stocks"), ("ORCL", "stocks"), ("IWM", "etf")):
        try:
            bars = _p.nasdaq_topup(sym, last, through, assetclass)
            print(f"### live nasdaq_topup {sym}/{assetclass} last={last} through={through}\n    "
                  f"{[(b.date, b.open, b.high, b.low, b.close, b.volume) for b in bars]}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"### live nasdaq_topup {sym}/{assetclass}\n    ERR {exc!r}", flush=True)
        try:
            print(f"### live nasdaq_latest_bar {sym}/{assetclass}\n    {_p.nasdaq_latest_bar(sym, through, assetclass)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"### live nasdaq_latest_bar {sym}/{assetclass}\n    ERR {exc!r}", flush=True)


def ft_probe() -> None:
    """FT 마켓 데이터: 티어시트 HTML 에서 내부 xid 를 찾고 get-historical-prices 로 일별 시세 표(HTML 행)를 받아본다 — OTC ADR 커버리지 확인."""
    import re as _re
    for sym in ("HXSCL:PKC", "HXSCL:OTC", "OKLO:NYQ"):
        status, body = fetch(f"https://markets.ft.com/data/equities/tearsheet/summary?s={urllib.parse.quote(sym)}", PLAIN_UA, 25)
        xids = sorted(set(_re.findall(r'"xid"\s*:\s*"?(\d+)', body)))
        price = _re.findall(r'mod-ui-data-list__value"[^>]*>([^<]{1,20})<', body)[:3]
        asof = _re.findall(r'Data delayed[^<]{0,80}|as of [^<]{0,60}', body)[:2]
        print(f"### ft summary {sym}\n    {status} len={len(body)} xids={xids[:5]} price={price} asof={asof}", flush=True)
        for xid in xids[:2]:
            url = (f"https://markets.ft.com/data/equities/ajax/get-historical-prices?startDate={END - timedelta(days=35):%Y/%m/%d}"
                   f"&endDate={END:%Y/%m/%d}&symbol={xid}")
            st2, b2 = fetch(url, {**PLAIN_UA, "X-Requested-With": "XMLHttpRequest", "Referer": f"https://markets.ft.com/data/equities/tearsheet/historical?s={sym}"}, 25)
            rows = _re.findall(r"<tr>(.*?)</tr>", b2.replace("\\/", "/"), _re.S)
            print(f"### ft historical xid={xid}\n    {url}\n    {st2} len={len(b2)} rows={len(rows)} first={rows[0][:400] if rows else b2[:300]!r}", flush=True)


if __name__ == "__main__":
    for label, url, headers, timeout in PROBES:
        status, body = fetch(url, headers, timeout)
        if label.startswith("dump "):
            detail = body[:2500].replace("\n", " ")
        elif label.startswith("html "):
            import re as _re
            dates = _re.findall(r"(?:Sep|Aug) \d{1,2}, 2026|2026-0[89]-\d{2}", body)[:6]
            detail = f"len={len(body)} table={'<table' in body} dates={dates} sample={body[:160]!r}"
        else:
            detail = naver_items(body) if label.startswith("naver list") and status == "200" else summarize(body)
        print(f"### {label}\n    {url}\n    {status} :: {detail}", flush=True)
    live_topup_checks()
    ft_probe()
