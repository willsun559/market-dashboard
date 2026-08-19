"""Build step: render the dashboard HTML from the store.

Pure read-and-render — no network. Reads the Parquet store, computes derived
signals, builds interactive Plotly figures, and writes one self-contained page
to site/index.html. Every panel degrades independently: if a series is missing
the panel shows a placeholder instead of blanking the page.
"""
from __future__ import annotations

import datetime as dt
import pathlib

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import store

SITE_DIR = pathlib.Path(__file__).resolve().parent / "site"
OUT_PATH = SITE_DIR / "index.html"
TODAY = pd.Timestamp.today().normalize()

# One shared visual language across every figure.
C = dict(blue="#1f77b4", red="#d62728", green="#2ca02c", purple="#9467bd",
         orange="#ff7f0e", brown="#8c564b", pink="#e377c2", cyan="#17becf",
         grey="#7f7f7f", black="#2b2b2b")
FONT = "#5f6b7a"   # slate — legible on both light and dark chrome


def style(fig: go.Figure, title: str, height: int = 320) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=FONT)),
        height=height, margin=dict(l=55, r=55, t=45, b=35),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=FONT, size=11),
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, font=dict(size=10)),
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(128,128,128,0.15)", zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(128,128,128,0.15)", zeroline=False)
    return fig


def div(fig: go.Figure) -> str:
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       config={"displayModeBar": False, "responsive": True})


def missing(title: str, msg: str = "no data in store yet") -> str:
    return f'<div class="chart"><div class="ph"><b>{title}</b><br><span>{msg}</span></div></div>'


def card(title: str, body: str) -> str:
    return f'<section class="card"><h2>{title}</h2>{body}</section>'


# ── derived-signal helpers ──────────────────────────────────────────────────
def yoy(s: pd.Series, periods: int) -> pd.Series:
    return s.pct_change(periods) * 100


def fmt_date(ts) -> str:
    return pd.Timestamp(ts).date().isoformat() if pd.notna(ts) else "—"


# ── figure builders (each returns an HTML fragment) ─────────────────────────
def fig_macro() -> str:
    gdp, ip, pce = store.get("GDPC1"), store.get("INDPRO"), store.get("PCENDC96")
    if gdp.empty or ip.empty:
        return missing("Year-over-year growth")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=gdp.index, y=yoy(gdp, 4), name="Real GDP (YoY)",
                             line=dict(color=C["blue"], width=2)))
    fig.add_trace(go.Scatter(x=ip.index, y=yoy(ip, 12), name="Industrial Prod. (YoY)",
                             line=dict(color=C["orange"], width=1.3)))
    if not pce.empty:
        fig.add_trace(go.Scatter(x=pce.index, y=yoy(pce, 12), name="Nondurable PCE (YoY)",
                                 line=dict(color=C["green"], width=1.3)))
    fig.add_hline(y=0, line=dict(color=FONT, width=1))
    return div(style(fig, "Output & consumption — YoY growth"))


def fig_curve2s10s() -> str:
    c = store.get("T10Y2Y")
    if c.empty:
        return missing("2s10s Treasury curve")
    bp = c * 100
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=bp.index, y=bp.values, name="10Y−2Y",
                             line=dict(color=C["cyan"], width=1.4),
                             fill="tozeroy", fillcolor="rgba(214,39,40,0.12)"))
    fig.add_hline(y=0, line=dict(color=FONT, width=1))
    return div(style(fig, "2s10s Treasury curve (10Y − 2Y, bp)"))


def fig_credit_spreads() -> str:
    ig, hy = store.get("BAMLC0A0CM"), store.get("BAMLH0A0HYM2")
    if ig.empty or hy.empty:
        return missing("Credit spreads")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=ig.index, y=ig * 100, name="IG OAS (bp)",
                             line=dict(color=C["blue"], width=1.3)), secondary_y=False)
    fig.add_trace(go.Scatter(x=hy.index, y=hy * 100, name="HY OAS (bp)",
                             line=dict(color=C["red"], width=1.3)), secondary_y=True)
    fig.update_yaxes(title_text="IG (bp)", secondary_y=False)
    fig.update_yaxes(title_text="HY (bp)", secondary_y=True)
    return div(style(fig, "Credit spreads — IG (left) & HY (right)"))


def fig_quality() -> str:
    ig, hy = store.get("BAMLC0A0CM"), store.get("BAMLH0A0HYM2")
    if ig.empty or hy.empty:
        return missing("HY − IG quality spread")
    qs = (hy - ig).dropna() * 100
    fig = go.Figure(go.Scatter(x=qs.index, y=qs.values,
                               line=dict(color=C["purple"], width=1.3)))
    return div(style(fig, "HY − IG quality spread (bp)"))


def fig_hyg_lqd() -> str:
    f = store.frame(["HYG", "LQD"]).dropna()
    if f.empty:
        return missing("HYG / LQD ratio")
    ratio = (f["HYG"] / f["LQD"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ratio.index, y=ratio.values, name="HYG/LQD",
                             line=dict(color=C["green"], width=1.3)))
    fig.add_trace(go.Scatter(x=ratio.index, y=ratio.rolling(63).mean(), name="63-day avg",
                             line=dict(color=C["black"], width=1, dash="dash")))
    return div(style(fig, "HYG / LQD price ratio"))


def fig_hy_spy() -> str:
    hy, spy = store.get("BAMLH0A0HYM2"), store.get("SPY")
    if hy.empty or spy.empty:
        return missing("HY spread vs SPY")
    p = pd.DataFrame({"HY": hy * 100, "SPY": spy}).dropna()
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=p.index, y=p["SPY"], name="SPY",
                             line=dict(color=C["blue"], width=1.2)), secondary_y=False)
    fig.add_trace(go.Scatter(x=p.index, y=p["HY"], name="HY OAS (bp)",
                             line=dict(color=C["red"], width=1.2)), secondary_y=True)
    fig.update_yaxes(title_text="SPY", secondary_y=False)
    fig.update_yaxes(title_text="HY OAS (bp)", secondary_y=True)
    return div(style(fig, "SPY vs HY credit spread"))


def fig_vix_trend() -> str:
    vix = store.get("^VIX")
    if vix.empty:
        return missing("VIX level & trend")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=vix.index, y=vix.values, name="VIX",
                             line=dict(color=C["pink"], width=1)))
    fig.add_trace(go.Scatter(x=vix.index, y=vix.rolling(50).mean(), name="50-day MA",
                             line=dict(color=C["blue"], width=1.3)))
    fig.add_trace(go.Scatter(x=vix.index, y=vix.rolling(200).mean(), name="200-day MA",
                             line=dict(color=C["black"], width=1.3)))
    return div(style(fig, "VIX — level & trend"))


def fig_move_vix() -> str:
    f = store.frame(["^MOVE", "^VIX"]).dropna()
    if f.empty:
        return missing("MOVE vs VIX")
    win = f.iloc[-756:]
    norm = win / win.iloc[0] * 100
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=norm.index, y=norm["^MOVE"], name="MOVE",
                             line=dict(color=C["brown"], width=1.3)))
    fig.add_trace(go.Scatter(x=norm.index, y=norm["^VIX"], name="VIX",
                             line=dict(color=C["pink"], width=1.3)))
    return div(style(fig, "Bond vol (MOVE) vs equity vol (VIX) — indexed to 100"))


def fig_dollar() -> str:
    dxy, twi = store.get("DX-Y.NYB"), store.get("DTWEXBGS")
    if dxy.empty and twi.empty:
        return missing("US dollar")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if not dxy.empty:
        fig.add_trace(go.Scatter(x=dxy.index, y=dxy.values, name="DXY",
                                 line=dict(color=C["blue"], width=1.2)), secondary_y=False)
    if not twi.empty:
        fig.add_trace(go.Scatter(x=twi.index, y=twi.values, name="Broad TWI",
                                 line=dict(color=C["orange"], width=1)), secondary_y=True)
    fig.update_yaxes(title_text="DXY", secondary_y=False)
    fig.update_yaxes(title_text="Broad TWI", secondary_y=True)
    return div(style(fig, "US dollar — DXY & broad TWI"))


def fig_crude() -> str:
    wti, brent = store.get("CL=F"), store.get("BZ=F")
    if wti.empty:
        return missing("Crude oil")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=wti.index, y=wti.values, name="WTI",
                             line=dict(color=C["black"], width=1.1)))
    if not brent.empty:
        fig.add_trace(go.Scatter(x=brent.index, y=brent.values, name="Brent",
                                 line=dict(color=C["brown"], width=1)))
    return div(style(fig, "Crude oil — WTI & Brent ($/bbl)"))


def fig_megacap() -> str:
    mega = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
    px = store.frame(mega).dropna()
    if len(px) < 30:
        return missing("Mega-cap correlation & dispersion")
    rets = px.pct_change().dropna()
    n, w = len(mega), 21
    idx = rets.index[w - 1:]
    corr = pd.Series(
        [(rets.iloc[i - w:i].corr().values.sum() - n) / (n * (n - 1))
         for i in range(w, len(rets) + 1)], index=idx)
    disp = (rets.std(axis=1).rolling(w).mean() * 100)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=corr.index, y=corr.values, name="avg pairwise corr",
                             line=dict(color=C["red"], width=1.2)), secondary_y=False)
    fig.add_trace(go.Scatter(x=disp.index, y=disp.values, name="dispersion (%)",
                             line=dict(color=C["grey"], width=1)), secondary_y=True)
    fig.update_yaxes(title_text="correlation", secondary_y=False)
    fig.update_yaxes(title_text="dispersion (%)", secondary_y=True)
    return div(style(fig, "Mega-cap realized correlation & dispersion"))


def fig_vix_curve() -> str:
    """Self-built VIX term structure from daily spot snapshots stored over time."""
    tenors = {"^VIX9D": 9, "^VIX": 30, "^VIX3M": 93, "^VIX6M": 186, "^VIX1Y": 365}
    latest = {}
    for t, d in tenors.items():
        s = store.get(t)
        if not s.empty:
            latest[d] = (s.index[-1], s.iloc[-1])
    if len(latest) < 2:
        return missing("VIX term structure",
                       "self-built from daily snapshots — needs ≥2 tenors stored")
    xs = sorted(latest)
    ys = [latest[d][1] for d in xs]
    labels = {9: "9D", 30: "VIX", 93: "3M", 186: "6M", 365: "1Y"}
    fig = go.Figure(go.Scatter(x=xs, y=ys, mode="lines+markers+text",
                               text=[f"{labels[d]}<br>{v:.2f}" for d, v in zip(xs, ys)],
                               textposition="top center",
                               line=dict(color=C["blue"], width=2)))
    fig.update_xaxes(title_text="Horizon (calendar days)")
    fig.update_yaxes(title_text="Implied vol")
    return div(style(fig, "VIX term structure — latest snapshot (self-built)"))


# ── KPI tiles ───────────────────────────────────────────────────────────────
def tiles() -> str:
    out = []

    def tile(label, value, sub, ts):
        out.append(
            f'<div class="tile"><div class="tl">{label}</div>'
            f'<div class="tv">{value}</div><div class="ts">{sub}</div>'
            f'<div class="td">as of {fmt_date(ts)}</div></div>')

    vix = store.get("^VIX")
    if not vix.empty:
        lvl = vix.iloc[-1]
        w5 = vix.iloc[-252 * 5:]
        pct = (w5 < lvl).mean() * 100
        tile("VIX", f"{lvl:.2f}", f"{pct:.0f}th %ile (5y)", vix.index[-1])

    hy = store.get("BAMLH0A0HYM2")
    if not hy.empty:
        bp = hy.iloc[-1] * 100
        chg = bp - hy.iloc[-22] * 100 if len(hy) > 22 else float("nan")
        tile("HY OAS", f"{bp:.0f} bp", f"{chg:+.0f} bp / 1m", hy.index[-1])

    ig = store.get("BAMLC0A0CM")
    if not ig.empty:
        tile("IG OAS", f"{ig.iloc[-1] * 100:.0f} bp", "invest-grade", ig.index[-1])

    c = store.get("T10Y2Y")
    if not c.empty:
        v = c.iloc[-1] * 100
        tile("2s10s", f"{v:+.0f} bp", "inverted" if v < 0 else "positive", c.index[-1])

    dxy = store.get("DX-Y.NYB")
    if not dxy.empty:
        tile("DXY", f"{dxy.iloc[-1]:.1f}", "US dollar", dxy.index[-1])

    wti = store.get("CL=F")
    if not wti.empty:
        tile("WTI", f"${wti.iloc[-1]:.1f}", "crude / bbl", wti.index[-1])

    return '<div class="tiles">' + "".join(out) + "</div>" if out else ""


# ── calendar (computed flow events + hand-kept macro list) ──────────────────
MACRO_EVENTS = [
    ("2026-09-16", "FOMC decision (Sep) — SEP/dots"), ("2026-10-28", "FOMC decision (Oct)"),
    ("2026-12-09", "FOMC decision (Dec) — SEP/dots"), ("2026-09-10", "CPI (Aug)"),
    ("2026-10-13", "CPI (Sep)"), ("2026-11-13", "CPI (Oct)"), ("2026-09-25", "PCE (Aug)"),
    ("2026-10-30", "PCE (Sep)"), ("2026-09-05", "NFP (Aug)"), ("2026-10-03", "NFP (Sep)"),
    ("2026-11-07", "NFP (Oct)"),
]


def _third_friday(y, m):
    d = dt.date(y, m, 1)
    return pd.Timestamp(d + dt.timedelta(days=(4 - d.weekday()) % 7) + dt.timedelta(weeks=2))


def _last_bday(y, m):
    d = pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)
    while d.weekday() >= 5:
        d -= pd.Timedelta("1D")
    return d


def calendar_table() -> str:
    rows = [(pd.to_datetime(d), e, "macro") for d, e in MACRO_EVENTS]
    cur = TODAY.replace(day=1)
    for _ in range(4):
        y, m = cur.year, cur.month
        quad = m in (3, 6, 9, 12)
        rows.append((_third_friday(y, m), f"{'quad witching' if quad else 'monthly OpEx'}", "flow"))
        rows.append((_last_bday(y, m), f"{'quarter' if quad else 'month'}-end rebalance", "flow"))
        cur += pd.offsets.MonthBegin(1)
    df = (pd.DataFrame(rows, columns=["date", "event", "type"])
          .loc[lambda d: (d["date"] >= TODAY) & (d["date"] <= TODAY + pd.Timedelta(days=60))]
          .sort_values("date"))
    if df.empty:
        return '<div class="ph"><span>no events in the next 60 days</span></div>'
    body = "".join(
        f'<tr><td>{fmt_date(r.date)}</td><td>{(r.date - TODAY).days}d</td>'
        f'<td><span class="badge {r.type}">{r.type}</span></td><td>{r.event}</td></tr>'
        for r in df.itertuples())
    return ('<table class="cal"><thead><tr><th>Date</th><th>In</th>'
            f'<th>Type</th><th>Event</th></tr></thead><tbody>{body}</tbody></table>')


def freshness_row() -> str:
    ao = store.as_of()
    if ao.empty:
        return ""
    stalest = ao.min()
    age = (TODAY - pd.Timestamp(stalest).normalize()).days
    return (f'<span class="fresh">stalest series: {fmt_date(stalest)} '
            f'({age}d old) · {len(ao)} series tracked</span>')


TEMPLATE = """<meta charset="utf-8">
<title>Cross-Asset Market Monitor</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
:root {{ --bg:#f6f7f9; --card:#ffffff; --ink:#1f2733; --muted:#5f6b7a;
        --line:#e6e9ee; --accent:#1f77b4; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#0f1216; --card:#171b21; --ink:#e6e9ee; --muted:#9aa5b1;
           --line:#252b33; --accent:#5aa9e6; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
       font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
header {{ padding:22px 28px 14px; border-bottom:1px solid var(--line); }}
h1 {{ margin:0; font-size:20px; letter-spacing:-.2px; }}
.sub {{ color:var(--muted); font-size:13px; margin-top:4px; }}
.fresh {{ color:var(--muted); font-size:12px; }}
main {{ max-width:1240px; margin:0 auto; padding:20px 20px 60px; }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
         gap:12px; margin-bottom:22px; }}
.tile {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
        padding:14px 16px; }}
.tl {{ font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:.4px; }}
.tv {{ font-size:26px; font-weight:650; margin:2px 0; }}
.ts {{ font-size:12px; color:var(--ink); }}
.td {{ font-size:11px; color:var(--muted); margin-top:4px; }}
.grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:16px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
        padding:8px 14px 12px; overflow:hidden; }}
.card.wide {{ grid-column:1 / -1; }}
.card h2 {{ font-size:13px; color:var(--muted); font-weight:600; margin:10px 4px 2px;
           text-transform:uppercase; letter-spacing:.4px; }}
.ph {{ display:flex; flex-direction:column; align-items:center; justify-content:center;
      height:300px; color:var(--muted); text-align:center; gap:6px; }}
.ph span {{ font-size:12px; }}
table.cal {{ width:100%; border-collapse:collapse; font-size:13px; }}
table.cal th {{ text-align:left; color:var(--muted); font-weight:600; padding:6px 8px;
               border-bottom:1px solid var(--line); font-size:11px; text-transform:uppercase; }}
table.cal td {{ padding:6px 8px; border-bottom:1px solid var(--line); }}
.badge {{ font-size:11px; padding:1px 7px; border-radius:20px; }}
.badge.macro {{ background:rgba(31,119,180,.15); color:var(--accent); }}
.badge.flow {{ background:rgba(127,127,127,.18); color:var(--muted); }}
@media (max-width:820px) {{ .grid {{ grid-template-columns:1fr; }} }}
</style>
<header>
  <h1>Cross-Asset Market Monitor</h1>
  <div class="sub">Macro · rates · credit · volatility · FX &amp; commodities · equity internals</div>
  <div class="sub">Built {built} · {fresh}</div>
</header>
<main>
  {tiles}
  {sections}
</main>
"""


def build() -> pathlib.Path:
    sections = [
        card("1 · Macro / Growth", f'<div class="grid"><div class="card">{fig_macro()}</div>'
             f'<div class="card">{fig_curve2s10s()}</div></div>'),
        card("2 · Credit", f'<div class="grid"><div class="card">{fig_credit_spreads()}</div>'
             f'<div class="card">{fig_quality()}</div><div class="card">{fig_hyg_lqd()}</div>'
             f'<div class="card">{fig_hy_spy()}</div></div>'),
        card("3 · Volatility", f'<div class="grid"><div class="card">{fig_vix_trend()}</div>'
             f'<div class="card">{fig_move_vix()}</div><div class="card">{fig_vix_curve()}</div></div>'),
        card("4 · FX & Commodities", f'<div class="grid"><div class="card">{fig_dollar()}</div>'
             f'<div class="card">{fig_crude()}</div></div>'),
        card("5 · Equity Internals",
             f'<div class="grid"><div class="card wide">{fig_megacap()}</div></div>'),
        card("6 · Event & Flow Calendar (next 60 days)", calendar_table()),
    ]
    html = TEMPLATE.format(
        built=f"{dt.datetime.now():%Y-%m-%d %H:%M}", fresh=freshness_row(),
        tiles=tiles(), sections="\n".join(sections))
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    return OUT_PATH


if __name__ == "__main__":
    p = build()
    print(f"wrote {p}  ({p.stat().st_size / 1024:.0f} KB)")
