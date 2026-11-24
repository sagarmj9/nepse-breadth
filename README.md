# NEPSE Market Breadth

A robot that updates NEPSE market breadth every trading day, using data from nepalstock.com.

- **`data/breadth.csv`**: the daily breadth table, newest first (same columns as the Google Sheet, plus extras).
- **`data/prices.csv`**: daily prices for every listed security (history).
- **`data/nepse_index.csv`**: NEPSE index close, change and turnover.
- **`data/history_prices.csv`**: older daily prices (2019–2025) for normal company shares, imported once from the public dataset [Aabishkar2/nepse-data](https://github.com/Aabishkar2/nepse-data) with `scripts/import_history.py` (NEPSE's own site only keeps about one year).
- **`data/stocks.json`**: per-stock snapshot for the latest day (returns, new highs, RS rating) used by the website lists.
- **`data/universe.csv`**: the stocks counted (normal company shares only; no promoter shares, mutual funds or debentures).

It runs automatically at 15:45 and 17:45 Nepal time (GitHub Actions → *Daily NEPSE breadth update*).
To update by hand: **Actions → Daily NEPSE breadth update → Run workflow**.

Note: before 2026 the counts include fewer stocks (about 150 in 2020, 240 in 2024) because some merged/delisted companies are missing from the old data; compare old years using the % columns. NEPSE index change/close are only available from Nov 2025.

For education and personal research only. Not investment advice.
