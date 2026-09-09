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
    ("nasdaq GC:CMX commodities", nasdaq("GC:CMX", "commodities"), NASDAQ_H, 20),
    ("nasdaq CL:NMX commodities", nasdaq("CL:NMX", "commodities"), NASDAQ_H, 20),
    ("nasdaq GC:CMX raw colon", nasdaq("GC:CMX", "commodities").replace("GC%3ACMX", "GC:CMX"), NASDAQ_H, 20),
    ("nasdaq BTC crypto", nasdaq("BTC", "cryptocurrency"), NASDAQ_H, 20),
    ("nasdaq AAPL stocks (control)", nasdaq("AAPL", "stocks"), NASDAQ_H, 20),
    ("fred DGS10 csv (40s)", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10", PLAIN_H, 40),
    ("fred DGS10 txt", "https://fred.stlouisfed.org/data/DGS10.txt", PLAIN_H, 40),
    ("treasury yield csv", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
     f"{END.year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={END.year}&page&_format=csv", PLAIN_H, 40),
    ("stooq gc.f", "https://stooq.com/q/d/l/?s=gc.f&i=d", PLAIN_H, 20),
    ("stooq 10yusy.b", "https://stooq.com/q/d/l/?s=10yusy.b&i=d", PLAIN_H, 20),
    ("stooq dx.f", "https://stooq.com/q/d/l/?s=dx.f&i=d", PLAIN_H, 20),
]
for path in ("exchange/FX_USDKRW", "oil/OIL_CL", "oil/OIL_BRT", "oil/OIL_DU", "metals/CMDT_GC", "metals/CMDT_SI", "metals/CMDT_CDY",
             "energy/OIL_NG", "oil/OIL_NG", "agricultural/CMDT_W", "agricultural/CMDT_C", "agricultural/CMDT_S",
             "bond/US10YT=RR", "bond/US10Y", "bond/KR10YT=RR", "exchange/FX_DXY"):
    PROBES.append((f"naver {path}", f"https://api.stock.naver.com/marketindex/{urllib.parse.quote(path, safe='/=')}/prices?page=1&pageSize=3", NAVER_H, 20))
for disc in ("https://api.stock.naver.com/marketindex/majors", "https://api.stock.naver.com/marketindex/oil",
             "https://api.stock.naver.com/marketindex/metals", "https://api.stock.naver.com/marketindex/bond",
             "https://api.stock.naver.com/marketindex/exchange", "https://api.stock.naver.com/marketindex/energy",
             "https://api.stock.naver.com/marketindex/agricultural", "https://api.stock.naver.com/marketindex/home/major"):
    PROBES.append((f"naver discovery {disc.rsplit('/', 1)[-1]}", disc, NAVER_H, 20))
INV_PAIRS = {"gold 8830": 8830, "wti 8849": 8849, "brent 8833": 8833, "natgas 8862": 8862, "silver 8836": 8836, "copper 8831": 8831,
             "us10y 23705": 23705, "us2y 23701": 23701, "dxy 8827": 8827, "usdkrw 650": 650, "wheat 8917": 8917,
             "soybean 8916": 8916, "corn 8918": 8918, "coffee 8832": 8832, "cocoa 8894": 8894, "sugar 8869": 8869, "btc 945629": 945629}
for label, pair in INV_PAIRS.items():
    PROBES.append((f"investing hist {label}", f"https://api.investing.com/api/financialdata/historical/{pair}?start-date={START:%Y-%m-%d}"
                   f"&end-date={END:%Y-%m-%d}&time-frame=Daily&add-missing-rows=false", _p._INV_HEADERS, 20))
for q in ("Gold Futures", "Crude Oil WTI", "US 10 Year", "US Dollar Index", "USD/KRW", "Natural Gas", "Wheat", "Cocoa"):
    PROBES.append((f"investing search {q}", f"https://api.investing.com/api/search/v2/search?q={urllib.parse.quote(q)}", _p._INV_HEADERS, 20))
PROBES.append(("coingecko btc (control)", "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=3&interval=daily", PLAIN_H, 20))

if __name__ == "__main__":
    for label, url, headers, timeout in PROBES:
        status, body = fetch(url, headers, timeout)
        print(f"### {label}\n    {url}\n    {status} :: {summarize(body)}", flush=True)
