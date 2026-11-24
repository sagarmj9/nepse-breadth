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
import json
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
HISTORY_PRICES = os.path.join(DATA, "history_prices.csv")      # older years, see import_history.py
HISTORY_TURNOVER = os.path.join(DATA, "history_turnover.csv")
STOCKS_FILE = os.path.join(DATA, "stocks.json")               # per-stock snapshot for the website lists
OUTPUT_START = "2020-01-01"

BACKFILL_START = date(2026, 1, 1)
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
    "New 52W highs",
    "New 52W lows",
    "52W net",
    "NEPSE close",
    "Stocks counted",
    "New 3M highs",
    "New 3M lows",
    "3M net",
    "New 6M highs",
    "New 6M lows",
    "6M net",
]

WARMUP_DAYS = 50
WINDOWS = (20, 60, 120, 250)  # 1 month, 3 months, 6 months, 52 weeks (market days)  # need 50 sessions of history before rows are reliable


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
    failed = []
    d = start
    while d <= today_np:
        # skip Saturday (NEPSE never trades); other closed days just return nothing
        if d.weekday() != 5:
            try:
                res = with_retry(nepse.getPriceVolumeHistory, d.isoformat())
            except Exception as e:
                # A single bad day must not stop the whole update; it is logged and skipped.
                print(f"{d}: could not download ({type(e).__name__}), skipped")
                failed.append(d.isoformat())
                d += timedelta(days=1)
                continue
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
    if failed:
        print(f"WARNING: {len(failed)} day(s) could not be downloaded: {', '.join(failed)}")
        if len(failed) > 5:
            raise SystemExit("Too many failed days - NEPSE may be blocking or down. Nothing saved is lost; try again later.")

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
    index = {r["date"]: r for r in read_csv(INDEX)}
    old_turnover = {r["date"]: num(r["turnover"]) for r in read_csv(HISTORY_TURNOVER)}

    # Older history (public dataset, equities only) + official NEPSE data (preferred where both exist)
    by_date = defaultdict(dict)
    history = read_csv(HISTORY_PRICES)
    allowed = universe | {r["symbol"] for r in history}
    for r in history + read_csv(PRICES):
        if r["symbol"] in allowed and num(r["close"]):
            by_date[r["date"]][r["symbol"]] = r
    dates = sorted(by_date)

    # Companies that no longer exist (merged/delisted) stop being counted after their last trade
    last_seen = {}
    for d in dates:
        for s in by_date[d]:
            last_seen[s] = d
    gone_after = defaultdict(list)
    for s, d in last_seen.items():
        if s not in universe:
            gone_after[d].append(s)

    closes = defaultdict(list)    # symbol -> carried-forward (adjusted) close per market day
    hilo = defaultdict(list)      # symbol -> [market day, adjusted high, adjusted low] on traded days
    first_day = {}
    last_close = {}
    out = []
    adjustments = 0
    last_highs = {w: set() for w in WINDOWS}
    last_lows = {w: set() for w in WINDOWS}
    traded_days = defaultdict(list)  # symbol -> market-day indexes it traded on
    for i, d in enumerate(dates):
        today = by_date[d]
        for s, r in today.items():
            # Bonus/right share adjustment: on the book-closure day NEPSE lowers the
            # "previous close". Scale this stock's older prices by the same factor so the
            # moving averages are not distorted (same as adjusted charts on SastoShare etc).
            pc = num(r["prev_close"])
            if s in last_close and pc and last_close[s] and abs(pc / last_close[s] - 1) > 0.01:
                f = pc / last_close[s]
                closes[s] = [x * f for x in closes[s]]
                for e in hilo[s]:
                    e[1] *= f
                    e[2] *= f
                adjustments += 1
            last_close[s] = num(r["close"])
            first_day.setdefault(s, i)
            traded_days[s].append(i)
        for s, c in last_close.items():
            closes[s].append(c)

        up = dn = 0
        nh = {w: 0 for w in WINDOWS}
        nl = {w: 0 for w in WINDOWS}
        for s, r in today.items():
            c, p = num(r["close"]), num(r["prev_close"])
            if p:
                ch = (c / p - 1) * 100
                up += ch >= 4.5
                dn += ch <= -4.5
            # New 1M / 3M / 6M / 52W highs and lows: today's intraday high (low) above (below)
            # every high (low) of the previous 20 / 60 / 120 / 250 market days, bonus-adjusted.
            # The stock must have been listed for the whole period.
            h, l = num(r["high"]) or c, num(r["low"]) or c
            hist = hilo[s]
            while hist and hist[0][0] <= i - 250:
                hist.pop(0)
            for w in WINDOWS:
                if first_day[s] <= i - (w - 1):
                    win = [e for e in hist if e[0] > i - w]
                    if win:
                        is_hi, is_lo = h > max(e[1] for e in win), l < min(e[2] for e in win)
                        nh[w] += is_hi
                        nl[w] += is_lo
                        if i == len(dates) - 1:
                            if is_hi:
                                last_highs[w].add(s)
                            if is_lo:
                                last_lows[w].add(s)
            hist.append([i, h, l])

        u5 = d5 = u20 = d20 = a20 = b20 = a50 = b50 = counted = 0
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
            if len(cl) >= 20:
                m = sum(cl[-20:]) / 20
                a20 += c > m
                b20 += c <= m
            if len(cl) >= 50:
                m = sum(cl[-50:]) / 50
                a50 += c > m
                b50 += c <= m

        for s in gone_after.get(d, []):
            last_close.pop(s, None)
            closes.pop(s, None)

        if i + 1 < WARMUP_DAYS or d < OUTPUT_START:
            continue
        ix = index.get(d, {})
        turnover = num(ix.get("turnover")) or old_turnover.get(d)
        out.append([
            d, up, dn, u5, d5, a20, b20, a50, b50,
            f"{turnover / 1e9:.3f}" if turnover else "",
            ix.get("change", ""),
            f"{a20 / (a20 + b20) * 100:.2f}%" if a20 + b20 else "",
            f"{a50 / (a50 + b50) * 100:.2f}%" if a50 + b50 else "",
            u20, d20, u20 - d20,
            nh[20], nl[20], nh[20] - nl[20],
            nh[250], nl[250], nh[250] - nl[250],
            ix.get("close", ""), counted,
            nh[60], nl[60], nh[60] - nl[60],
            nh[120], nl[120], nh[120] - nl[120],
        ])

    if dates:
        write_stocks(dates, by_date, universe, closes, hilo, first_day, traded_days, last_highs, last_lows)
    out.reverse()  # newest first, like the sheet
    write_csv(BREADTH, BREADTH_HEADER, out)
    print(f"breadth: {len(out)} rows, {out[-1][0] if out else '-'} .. {out[0][0] if out else '-'}, "
          f"{adjustments} bonus/right price adjustments applied")


RETURN_DAYS = (5, 10, 20, 30, 60, 90, 125, 180, 250)


def write_stocks(dates, by_date, universe, closes, hilo, first_day, traded_days, last_highs, last_lows):
    """Snapshot of every current stock on the latest market day, for the website's stock lists."""
    names = {r["symbol"]: (r["name"], r["sector"]) for r in read_csv(UNIVERSE)}
    i = len(dates) - 1
    today = by_date[dates[-1]]
    stocks = []
    for s in sorted(universe):
        cl = closes.get(s)
        if not cl:
            continue
        c = cl[-1]
        ret = {}
        for n in RETURN_DAYS:
            if len(cl) > n and cl[-1 - n]:
                ret[str(n)] = round((c / cl[-1 - n] - 1) * 100, 2)
        hist = [e for e in hilo.get(s, []) if e[0] > i - 250]
        high52 = max((e[1] for e in hist), default=None)
        r = today.get(s)
        chg = None
        if r and num(r["prev_close"]):
            chg = round((num(r["close"]) / num(r["prev_close"]) - 1) * 100, 2)
        recent = sum(1 for d in traded_days.get(s, []) if d > i - 60)
        stocks.append({
            "s": s, "n": names.get(s, ("", ""))[0], "sec": names.get(s, ("", ""))[1],
            "c": round(c, 2), "chg": chg, "ret": ret,
            "fromHigh": round((c / high52 - 1) * 100, 2) if high52 else None,
            "hi": [w for w in WINDOWS if s in last_highs[w]],
            "lo": [w for w in WINDOWS if s in last_lows[w]],
            "a20": len(cl) >= 20 and c > sum(cl[-20:]) / 20,
            "a50": len(cl) >= 50 and c > sum(cl[-50:]) / 50,
            "days": i - first_day.get(s, i) + 1, "traded60": recent,
        })
    # RS rating 1-99: weighted 12-month performance, latest 3 months counting double,
    # ranked against every stock listed for a full year that traded on 20+ of the last 60 days
    def perf(st):
        r = st["ret"]
        if "250" not in r or st["traded60"] < 20:
            return None
        q1 = (1 + r["60"] / 100)
        q2 = (1 + r["125"] / 100) / q1
        q3 = (1 + r["180"] / 100) / (1 + r["125"] / 100)
        q4 = (1 + r["250"] / 100) / (1 + r["180"] / 100)
        return 2 * q1 + q2 + q3 + q4
    rated = sorted((perf(st), st["s"]) for st in stocks if perf(st) is not None)
    rank = {sym: k for k, (_, sym) in enumerate(rated)}
    for st in stocks:
        st["rs"] = max(1, min(99, int(rank[st["s"]] / (len(rated) - 1) * 98) + 1)) if st["s"] in rank and len(rated) > 1 else None
    with open(STOCKS_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": dates[-1], "stocks": stocks}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"stocks: {len(stocks)} written, {len(rated)} with RS rating")


if __name__ == "__main__":
    if "--compute-only" not in sys.argv:
        from nepse import Nepse
        n = Nepse()
        n.setTLSVerification(False)  # NEPSE's SSL certificate issue (library guidance)
        fetch(n)
    compute()
