"""Persistent time-series store for the market dashboard.

Everything lives in one long-format Parquet file: (date, series, value). Writes
*upsert* — new points are merged in and duplicates on (series, date) keep the
latest fetch. This is the robustness property that makes the daily job safe:
a bad pull (e.g. Yahoo returning only a spot value) can never delete history
that was already stored, it can only add to it.
"""
from __future__ import annotations

import pathlib

import pandas as pd

STORE_DIR = pathlib.Path(__file__).resolve().parent / "data"
STORE_PATH = STORE_DIR / "timeseries.parquet"


def load() -> pd.DataFrame:
    """Return the whole store as a tidy frame [date, series, value] (empty if none)."""
    if STORE_PATH.exists():
        return pd.read_parquet(STORE_PATH)
    return pd.DataFrame(columns=["date", "series", "value"])


def upsert(series_name: str, s: pd.Series) -> int:
    """Merge one series into the store. Returns the number of rows now held for it."""
    s = s.dropna()
    if s.empty:
        return 0
    incoming = pd.DataFrame({
        "date": pd.to_datetime(s.index),
        "series": series_name,
        "value": s.values.astype(float),
    })

    existing = load()
    combined = pd.concat([existing, incoming], ignore_index=True)
    # Last write wins for a given (series, date).
    combined = (combined
                .drop_duplicates(subset=["series", "date"], keep="last")
                .sort_values(["series", "date"])
                .reset_index(drop=True))

    STORE_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(STORE_PATH, index=False)
    return int((combined["series"] == series_name).sum())


def get(series_name: str) -> pd.Series:
    """One series as a date-indexed float Series (empty if absent)."""
    df = load()
    sub = df[df["series"] == series_name]
    if sub.empty:
        return pd.Series(dtype=float, name=series_name)
    return (sub.set_index("date")["value"]
            .sort_index()
            .rename(series_name))


def frame(series_names: list[str]) -> pd.DataFrame:
    """Several series as columns of one frame (outer-joined on date)."""
    cols = {name: get(name) for name in series_names}
    return pd.DataFrame(cols)


def as_of() -> pd.Series:
    """Latest stored date per series — drives the freshness stamps."""
    df = load()
    if df.empty:
        return pd.Series(dtype="datetime64[ns]")
    return df.groupby("series")["date"].max()
