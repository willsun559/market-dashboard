# Cross-Asset Market Monitor — daily dashboard

A static, self-updating market dashboard. A scheduled job fetches data into a
persistent store, renders an interactive HTML page, and publishes it — no server
to keep running.

```
fetch.py   →  data/timeseries.parquet  →  build.py  →  site/index.html
(pull)         (append-only store)          (render)      (publish)
```

## Pipeline

| File | Role |
|------|------|
| `store.py` | Parquet store, long-format `(date, series, value)`. Writes **upsert** — a bad or short pull can only add points, never delete stored history. |
| `fetch.py` | Pulls FRED (official) + Yahoo (`yfinance`) into the store. Each source is isolated; one failure doesn't abort the run. |
| `build.py` | Reads the store, computes derived signals, renders `site/index.html` (Plotly). Pure, no network. Panels degrade independently. |

## Run locally

```bash
cd dashboard
pip install -r requirements.txt
export FRED_API_KEY="your-key"      # optional; raises FRED rate limits
python fetch.py                     # populate/refresh the store
python build.py                     # write site/index.html
open site/index.html
```

## Daily automation (GitHub Actions + Pages)

`.github/workflows/daily.yml` runs weekdays after the US close: fetch → build →
commit the refreshed store → deploy `site/` to GitHub Pages.

One-time setup:
1. Push this repo to GitHub.
2. **Settings → Secrets and variables → Actions** → add `FRED_API_KEY`.
3. **Settings → Pages** → Source: *GitHub Actions*.
4. **Settings → Actions → General** → Workflow permissions: *Read and write*.

Trigger the first run from the **Actions** tab (**Run workflow**).

## Notes & known limits

- **The store is the durability layer.** Committing `data/timeseries.parquet` each
  run is what lets the dashboard survive Yahoo's flakiness and slowly rebuild the
  VIX term structure from daily spot snapshots.
- **Yahoo (`yfinance`) is unofficial** and occasionally returns only a spot value
  for some symbols (notably the VIX curve tenors). Upsert tolerates this. For
  higher reliability, migrate price pulls to an official source (Stooq/Tiingo/
  Polygon) and pull the VIX family from CBOE's published CSVs.
- **Macro calendar dates in `build.py` are hand-maintained** for 2026 — verify
  against official sources and extend as needed. The flow events (OpEx, quad
  witching, month/quarter-end) are computed and need no upkeep.
- **Rotate the FRED key** that was hardcoded in the original notebooks.
