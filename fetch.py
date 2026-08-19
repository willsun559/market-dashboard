"""Fetch step: pull every source into the store, resiliently.

Run daily after the US close. Each pull is isolated in try/except so one dead
source (Yahoo rate-limit, a delisted ticker) can't abort the run or wipe the
store — thanks to upsert semantics, a failed or short pull simply adds nothing.

Sources:
  * FRED   (pandas_datareader) — official, needs FRED_API_KEY for higher limits
  * Yahoo  (yfinance)          — unofficial; flaky for some symbols, hence upsert
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import pandas as pd
import pandas_datareader.data as web
import yfinance as yf

import store

START = dt.datetime(2007, 1, 1)          # cross-asset history floor
START_MACRO = dt.datetime(1990, 1, 1)    # macro series go back further

# FRED series id -> store name (we keep the id as the name for traceability).
FRED_SERIES = {
    "BAMLC0A0CM": START,        # IG OAS
    "BAMLH0A0HYM2": START,      # HY OAS
    "T10Y2Y": START,            # 2s10s
    "DTWEXBGS": START,          # broad trade-weighted USD
    "GDPC1": START_MACRO,       # real GDP
    "INDPRO": START_MACRO,      # industrial production
    "PCNDGC96": START_MACRO,    # real nondurable PCE, quarterly
    "PCENDC96": START_MACRO,    # real nondurable PCE, monthly
}

# Yahoo tickers pulled with a generous window; upsert keeps prior history if a
# pull comes back short. VIX-family spot values are snapshotted so the dashboard
# can build its OWN constant-maturity history over time.
YF_TICKERS = [
    "HYG", "LQD", "SPY", "^VIX", "^MOVE", "DX-Y.NYB", "CL=F", "BZ=F",
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
    "^VIX9D", "^VIX3M", "^VIX6M", "^VIX1Y",
]
YF_PERIOD = "20y"


def fetch_fred() -> list[str]:
    log = []
    for sid, start in FRED_SERIES.items():
        try:
            s = web.DataReader(sid, "fred", start)[sid].dropna()
            n = store.upsert(sid, s)
            log.append(f"  FRED  {sid:12s} +{len(s):>5} pulled, {n:>6} stored")
        except Exception as e:                       # noqa: BLE001 - report and continue
            log.append(f"  FRED  {sid:12s} FAILED: {e!r}")
    return log


def fetch_yahoo() -> list[str]:
    log = []
    try:
        raw = yf.download(YF_TICKERS, period=YF_PERIOD, interval="1d",
                          auto_adjust=False, progress=False)["Close"]
    except Exception as e:                           # noqa: BLE001
        return [f"  YF    batch download FAILED: {e!r}"]

    if isinstance(raw, pd.Series):                   # single-ticker edge case
        raw = raw.to_frame(YF_TICKERS[0])

    for t in YF_TICKERS:
        try:
            s = raw[t].dropna() if t in raw.columns else pd.Series(dtype=float)
            n = store.upsert(t, s)
            flag = "" if len(s) > 1 else "  (spot only)"
            log.append(f"  YF    {t:10s} +{len(s):>5} pulled, {n:>6} stored{flag}")
        except Exception as e:                       # noqa: BLE001
            log.append(f"  YF    {t:10s} FAILED: {e!r}")
    return log


def main() -> int:
    if not os.environ.get("FRED_API_KEY"):
        print("Note: FRED_API_KEY not set — anonymous FRED access (lower limits).")
    print(f"Fetch run {dt.datetime.now():%Y-%m-%d %H:%M} — writing to {store.STORE_PATH}")

    log = fetch_fred() + fetch_yahoo()
    print("\n".join(log))

    failed = sum("FAILED" in line for line in log)
    print(f"\nDone. {len(log)} series, {failed} failed.")
    # Non-zero exit only if EVERYTHING failed (so a single flaky source is tolerated).
    return 1 if failed == len(log) else 0


if __name__ == "__main__":
    sys.exit(main())
