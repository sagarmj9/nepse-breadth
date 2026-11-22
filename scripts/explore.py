"""One-off exploration: inspect NEPSE lists, back-fill prices for a validation window,
and download Sagar's public sheet so definitions can be checked against his manual rows."""
import csv, json, os, sys, time, urllib.request
from collections import Counter
from datetime import date, timedelta
from nepse import Nepse

OUT = "explore_out"
os.makedirs(OUT, exist_ok=True)
n = Nepse()
n.setTLSVerification(False)

companies = n.getCompanyList()
securities = n.getSecurityList()
json.dump(companies, open(f"{OUT}/companies.json", "w"), ensure_ascii=False)
json.dump(securities, open(f"{OUT}/securities.json", "w"), ensure_ascii=False)
print("companies:", len(companies), "securities:", len(securities))
print("company sample:", json.dumps(companies[0], ensure_ascii=False))
print("security sample:", json.dumps(securities[0], ensure_ascii=False))
for key in ("sectorName", "instrumentType", "status"):
    print(key, Counter(c.get(key) for c in companies).most_common())

# NEPSE index history candidates
for url in ["/api/nots/index/history/58?size=500", "/api/nots/graph/index/58"]:
    try:
        r = n.requestGETAPI(url=url)
        print("INDEX", url, "->", json.dumps(r, ensure_ascii=False)[:600])
    except Exception as e:
        print("INDEX", url, "failed:", e)
try:
    g = n.getDailyNepseIndexGraph()
    print("DAILY GRAPH POST ->", json.dumps(g, ensure_ascii=False)[:600])
except Exception as e:
    print("daily graph failed", e)

# Sagar's sheet
try:
    url = "https://docs.google.com/spreadsheets/d/1Ois186HztaKjZMJoW7RXpOIjYmgB4PBWoP4ghWNdKiI/export?format=csv"
    urllib.request.urlretrieve(url, f"{OUT}/sheet.csv")
    print("sheet rows:", sum(1 for _ in open(f"{OUT}/sheet.csv")))
except Exception as e:
    print("sheet download failed", e)

# Back-fill all-stock prices for a validation window
start, end = date(2026, 4, 1), date(2026, 7, 3)
rows = []
d = start
while d <= end:
    try:
        r = n.getPriceVolumeHistory(d.isoformat())
        items = r.get("content", []) if isinstance(r, dict) else (r or [])
        rows.extend(items)
        print(d, len(items))
    except Exception as e:
        print(d, "ERR", e)
    d += timedelta(days=1)
json.dump(rows, open(f"{OUT}/prices_window.json", "w"), ensure_ascii=False)
print("total price rows", len(rows))
