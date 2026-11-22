# NEPSE Market Breadth

A robot that updates NEPSE market breadth every trading day, using data from nepalstock.com.

- **`data/breadth.csv`**: the daily breadth table, newest first (same columns as the Google Sheet, plus extras).
- **`data/prices.csv`**: daily prices for every listed security (history).
- **`data/nepse_index.csv`**: NEPSE index close, change and turnover.
- **`data/universe.csv`**: the stocks counted (normal company shares only; no promoter shares, mutual funds or debentures).

It runs automatically at 15:45 and 17:45 Nepal time (GitHub Actions → *Daily NEPSE breadth update*).
To update by hand: **Actions → Daily NEPSE breadth update → Run workflow**.

For education and personal research only. Not investment advice.
