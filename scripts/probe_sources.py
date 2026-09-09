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


if __name__ == "__main__":
    for label, url, headers, timeout in PROBES:
        status, body = fetch(url, headers, timeout)
        detail = naver_items(body) if label.startswith("naver list") and status == "200" else summarize(body)
        print(f"### {label}\n    {url}\n    {status} :: {detail}", flush=True)
