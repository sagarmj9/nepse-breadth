"""
NEPSE market breadth robot.

Every run:
  1. Downloads any missing trading days of all-stock prices from nepalstock.com
     (first run back-fills from BACKFILL_START).
  2. Downloads NEPSE index history (close, change, turnover).
  3. Recalculates the breadth table and writes data/breadth.csv (newest first).

Universe = normal company shares only: instrumentType "Equity", active, not Mutual Fund.
Promoter shares, mutual funds and debentures are excluded.
"""
import csv
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
PRICES = os.path.join(DATA, "prices.csv")
INDEX = os.path.join(DATA, "nepse_index.csv")
UNIVERSE = os.path.join(DATA, "universe.csv")
BREADTH = os.path.join(DATA, "breadth.csv")

BACKFILL_START = date(2025, 9, 1)
NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))

PRICE_FIELDS = ["date", "symbol", "open", "high", "low", "close", "prev_close",
                "volume", "turnover", "high52", "low52"]
INDEX_FIELDS = ["date", "close", "change", "pct_change", "turnover", "volume"]

BREADTH_HEADER = [
    "Date",
    "Number of Stocks up 4.5%+ Today",
    "Number of stocks down 4.5%+ Today",
    "Number of stocks up 20%+ in 5 days",
    "Number of stocks down 20%+ in 5 days",
    "Number of Stocks above 20 DMA (Early Signal)",
    "Number of Stocks below 20 DMA (Early Signal)",
    "Number of Stocks above 50 DMA",
    "Number of Stocks below 50 DMA",
    "VOLUME (Turnover, Rs Arba)",
    "NEPSE",
    "% Above 20DMA",
    "% Above 50DMA",
    # extras (for the website later)
    "Up 25%+ in 20 days",
    "Down 25%+ in 20 days",
    "Monthly thrust (net)",
    "New 1M highs",
    "New 1M lows",
    "1M net",
    "NEPSE close",
    "Stocks counted",
]

WARMUP_DAYS = 50  # need 50 sessions of history before rows are reliable


# ----------------------------------------------------------------------------- io
def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for r in rows:
            w.writerow([r.get(k, "") for k in fields] if isinstance(r, dict) else r)
    os.replace(tmp, path)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# -------------------------------------------------------------------------- fetch
def with_retry(fn, *args, tries=4):
    for i in range(tries):
        try:
            return fn(*args)
        except Exception as e:  # network hiccups / token refresh
            if i == tries - 1:
                raise
            print(f"  retry {i + 1} after error: {e}")
            time.sleep(3 * (i + 1))


def fetch(nepse):
    # Universe
    companies = with_retry(nepse.getCompanyList)
    universe = sorted(
        (c["symbol"], c["sectorName"], c["companyName"])
        for c in companies
        if c.get("instrumentType") == "Equity"
        and c.get("status") == "A"
        and c.get("sectorName") != "Mutual Fund"
    )
    write_csv(UNIVERSE, ["symbol", "sector", "name"],
              [{"symbol": s, "sector": sec, "name": n} for s, sec, n in universe])
    print(f"universe: {len(universe)} stocks")

    # Prices: fetch days after the last stored date
    existing = read_csv(PRICES)
    have_dates = {r["date"] for r in existing}
    last = max(have_dates) if have_dates else None
    start = (date.fromisoformat(last) + timedelta(days=1)) if last else BACKFILL_START
    today_np = datetime.now(NEPAL_TZ).date()
    new_rows = []
    d = start
    while d <= today_np:
        # skip Saturday (NEPSE never trades); other closed days just return nothing
        if d.weekday() != 5:
            res = with_retry(nepse.getPriceVolumeHistory, d.isoformat())
            items = res.get("content", []) if isinstance(res, dict) else (res or [])
            for r in items:
                new_rows.append({
                    "date": r["businessDate"], "symbol": r["symbol"],
                    "open": r.get("openPrice"), "high": r.get("highPrice"),
                    "low": r.get("lowPrice"), "close": r.get("closePrice"),
                    "prev_close": r.get("previousDayClosePrice"),
                    "volume": r.get("totalTradedQuantity"),
                    "turnover": r.get("totalTradedValue"),
                    "high52": r.get("fiftyTwoWeekHigh"), "low52": r.get("fiftyTwoWeekLow"),
                })
            if items:
                print(f"{d}: {len(items)} securities")
        d += timedelta(days=1)

    # Don't store today's prices until the market has closed for the day
    if new_rows:
        status = with_retry(nepse.getMarketStatus)
        if status.get("isOpen") == "OPEN":
            todays = today_np.isoformat()
            new_rows = [r for r in new_rows if r["date"] != todays]
            print("market still open: today's prices skipped")

    new_rows = [r for r in new_rows if r["date"] not in have_dates]
    all_rows = existing + new_rows
    all_rows.sort(key=lambda r: (r["date"], r["symbol"]))
    write_csv(PRICES, PRICE_FIELDS, all_rows)
    print(f"prices: {len(new_rows)} new rows, {len(all_rows)} total")

    # NEPSE index history (id 58)
    idx = with_retry(nepse.requestGETAPI, "/api/nots/index/history/58?size=500")
    idx_items = idx.get("content", []) if isinstance(idx, dict) else idx
    old_idx = {r["date"]: r for r in read_csv(INDEX)}
    for r in idx_items:
        old_idx[r["businessDate"]] = {
            "date": r["businessDate"], "close": r.get("closingIndex"),
            "change": r.get("absChange"), "pct_change": r.get("percentageChange"),
            "turnover": r.get("turnoverValue"), "volume": r.get("turnoverVolume"),
        }
    write_csv(INDEX, INDEX_FIELDS, sorted(old_idx.values(), key=lambda r: r["date"]))


# ------------------------------------------------------------------------ compute
def compute():
    universe = {r["symbol"] for r in read_csv(UNIVERSE)}
    prices = [r for r in read_csv(PRICES) if r["symbol"] in universe]
    index = {r["date"]: r for r in read_csv(INDEX)}

    by_date = defaultdict(dict)
    for r in prices:
        if num(r["close"]):
            by_date[r["date"]][r["symbol"]] = r
    dates = sorted(by_date)

    closes = defaultdict(list)  # symbol -> carried-forward close per market day
    last_close = {}
    out = []
    for i, d in enumerate(dates):
        today = by_date[d]
        for s, r in today.items():
            last_close[s] = num(r["close"])
        for s, c in last_close.items():
            closes[s].append(c)

        up = dn = 0
        for s, r in today.items():
            c, p = num(r["close"]), num(r["prev_close"])
            if p:
                ch = (c / p - 1) * 100
                up += ch >= 4.5
                dn += ch <= -4.5

        u5 = d5 = u20 = d20 = a20 = b20 = a50 = b50 = hi1m = lo1m = counted = 0
        for s, cl in closes.items():
            c = cl[-1]
            counted += 1
            if len(cl) >= 6:
                x = (c / cl[-6] - 1) * 100
                u5 += x >= 20
                d5 += x <= -20
            if len(cl) >= 21:
                x = (c / cl[-21] - 1) * 100
                u20 += x >= 25
                d20 += x <= -25
                prev20 = cl[-21:-1]
                hi1m += c > max(prev20)
                lo1m += c < min(prev20)
            if len(cl) >= 20:
                m = sum(cl[-20:]) / 20
                a20 += c > m
                b20 += c <= m
            if len(cl) >= 50:
                m = sum(cl[-50:]) / 50
                a50 += c > m
                b50 += c <= m

        if i + 1 < WARMUP_DAYS:
            continue
        ix = index.get(d, {})
        turnover = num(ix.get("turnover"))
        out.append([
            d, up, dn, u5, d5, a20, b20, a50, b50,
            f"{turnover / 1e9:.3f}" if turnover else "",
            ix.get("change", ""),
            f"{a20 / (a20 + b20) * 100:.2f}%" if a20 + b20 else "",
            f"{a50 / (a50 + b50) * 100:.2f}%" if a50 + b50 else "",
            u20, d20, u20 - d20, hi1m, lo1m, hi1m - lo1m,
            ix.get("close", ""), counted,
        ])

    out.reverse()  # newest first, like the sheet
    write_csv(BREADTH, BREADTH_HEADER, out)
    print(f"breadth: {len(out)} rows, latest {out[0][0] if out else '-'}")


if __name__ == "__main__":
    if "--compute-only" not in sys.argv:
        from nepse import Nepse
        n = Nepse()
        n.setTLSVerification(False)  # NEPSE's SSL certificate issue (library guidance)
        fetch(n)
    compute()
