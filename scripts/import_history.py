"""
One-time import of older daily prices (before NEPSE's own 1-year window) from the public
dataset https://github.com/Aabishkar2/nepse-data (one CSV per company).

Usage:
    python scripts/import_history.py <path-to-nepse-data-clone> <companies.json>

companies.json = NEPSE company list (Nepse().getCompanyList()), which also lists delisted
companies, so merged/delisted equities that are in the dataset are included too.

Writes:
    data/history_prices.csv    equities only, same columns as data/prices.csv
    data/history_turnover.csv  estimated daily turnover (sum over every security in the dataset)
"""
import csv
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
START = "2019-01-01"

PRICE_FIELDS = ["date", "symbol", "open", "high", "low", "close", "prev_close",
                "volume", "turnover", "high52", "low52"]


def main(dataset, companies_path):
    companies = json.load(open(companies_path, encoding="utf-8"))
    equities = {
        c["symbol"] for c in companies
        if c.get("instrumentType") == "Equity" and c.get("sectorName") != "Mutual Fund"
    }
    # Delisted/merged companies that NEPSE's list no longer contains, but which were normal shares
    equities |= {"LBL", "NIB", "PLI", "PLIC", "RHPC", "SLI", "SLICL"}

    # Official NEPSE prices start here; history fills everything before it
    official_dates = sorted({r["date"] for r in csv.DictReader(open(os.path.join(DATA, "prices.csv")))})
    cutoff = official_dates[0]
    print("official data starts", cutoff)

    folder = os.path.join(dataset, "data", "company-wise")
    rows, turnover = [], defaultdict(float)
    used = 0
    for f in sorted(os.listdir(folder)):
        sym = f[:-4]
        is_equity = sym in equities
        took = False
        for r in csv.DictReader(open(os.path.join(folder, f), encoding="utf-8")):
            d = r["published_date"]
            if d < START or d >= cutoff:
                continue
            try:
                amount = float(r["traded_amount"])
                if not math.isnan(amount):
                    turnover[d] += amount
            except ValueError:
                pass
            if not is_equity:
                continue
            close = float(r["close"])
            prev = ""
            try:
                pc = float(r["per_change"])
                if not math.isnan(pc) and pc > -100:
                    prev = round(close / (1 + pc / 100), 2)  # NEPSE's (bonus-adjusted) previous close
            except ValueError:
                pass
            rows.append({
                "date": d, "symbol": sym, "open": r["open"], "high": r["high"], "low": r["low"],
                "close": r["close"], "prev_close": prev, "volume": r["traded_quantity"],
                "turnover": r["traded_amount"], "high52": "", "low52": "",
            })
            took = True
        used += took

    rows.sort(key=lambda r: (r["date"], r["symbol"]))
    with open(os.path.join(DATA, "history_prices.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PRICE_FIELDS)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(DATA, "history_turnover.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "turnover"])
        for d in sorted(turnover):
            w.writerow([d, round(turnover[d], 2)])
    print(f"history: {len(rows)} rows from {used} equities, {len(turnover)} days ({START} .. before {cutoff})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
