"""Build step: render the dashboard HTML from the store.

Pure read-and-render — no network. Reads the Parquet store, computes derived
signals, builds interactive Plotly figures, and writes one self-contained page
to site/index.html. Every panel degrades independently: if a series is missing
the panel shows a placeholder instead of blanking the page.

Aesthetic: Bloomberg-terminal — black canvas, thin white primary series with
magenta/green/yellow moving averages, dotted grid, right-hand price axis, and a
boxed legend that carries each series' latest value (so it never needs to
overlap the data). Times New Roman throughout; square corners everywhere.
"""
from __future__ import annotations

import calendar as _cal
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

# Bloomberg-style palette on black.
BB = dict(white="#ffffff", magenta="#ff2f92", green="#00c853", yellow="#ffd400",
          orange="#ff9500", cyan="#26c6da", red="#ff453a", blue="#4d9fff",
          purple="#b388ff", grey="#9e9e9e", amber="#ffb300")
INK = "#e8e8e8"          # default text
MUTE = "#8a8a8a"         # secondary text
GRID = "rgba(130,130,130,0.28)"
AXIS = "#5a5a5a"
SERIF = "Times New Roman, Times, serif"


# ── figure styling ──────────────────────────────────────────────────────────
def style(fig: go.Figure, title: str, height: int = 320, right_axis: bool = True) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left",
                   font=dict(size=15, color=INK, family=SERIF)),
        height=height, margin=dict(l=18, r=66, t=40, b=46),
        paper_bgcolor="#000000", plot_bgcolor="#000000",
        font=dict(color=INK, size=11, family=SERIF),
        legend=dict(x=0.012, y=0.98, xanchor="left", yanchor="top",
                    bgcolor="rgba(0,0,0,0.55)", bordercolor=AXIS, borderwidth=1,
                    font=dict(size=10, color=INK, family=SERIF)),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#0a0a0a", bordercolor=AXIS,
                        font=dict(family=SERIF, color=INK, size=11)),
    )
    axis_kw = dict(showgrid=True, gridcolor=GRID, griddash="dot", zeroline=False,
                   showline=True, linecolor=AXIS, ticks="outside", tickcolor=AXIS,
                   tickfont=dict(color=MUTE, size=10, family=SERIF))
    fig.update_xaxes(**axis_kw)
    fig.update_yaxes(**axis_kw)
    if right_axis:
        fig.update_yaxes(side="right")
    return fig


def div(fig: go.Figure) -> str:
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       config={"displayModeBar": False, "responsive": True})


def missing(title: str, msg: str = "no data in store yet") -> str:
    return f'<div class="chart"><div class="ph"><b>{title}</b><br><span>{msg}</span></div></div>'


def card(title: str, body: str) -> str:
    return f'<section class="card"><h2>{title}</h2>{body}</section>'


def nv(label: str, s: pd.Series, fmt: str = "{:.2f}") -> str:
    """Legend name carrying the series' latest value — the Bloomberg value box."""
    s = s.dropna()
    return f"{label}   {fmt.format(s.iloc[-1])}" if len(s) else label


def tag(fig: go.Figure, s: pd.Series, color: str, fmt: str = "{:.2f}") -> None:
    """A colored last-value chip pinned to the right axis (only the primary line,
    so chips never stack or overlap)."""
    s = s.dropna()
    if s.empty:
        return
    fig.add_annotation(x=s.index[-1], y=s.iloc[-1], text=fmt.format(s.iloc[-1]),
                       showarrow=False, xanchor="left", xshift=6, yanchor="middle",
                       font=dict(color="#000000", size=10, family=SERIF),
                       bgcolor=color, borderpad=2)


# ── derived-signal helpers ──────────────────────────────────────────────────
def yoy(s: pd.Series, periods: int) -> pd.Series:
    return s.pct_change(periods) * 100


def fmt_date(ts) -> str:
    return pd.Timestamp(ts).date().isoformat() if pd.notna(ts) else "—"


# ── figure builders ─────────────────────────────────────────────────────────
def fig_macro() -> str:
    gdp, ip, pce = store.get("GDPC1"), store.get("INDPRO"), store.get("PCENDC96")
    if gdp.empty or ip.empty:
        return missing("Year-over-year growth")
    g, i = yoy(gdp, 4), yoy(ip, 12)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=g.index, y=g.values, name=nv("Real GDP YoY", g),
                             line=dict(color=BB["white"], width=1.6)))
    fig.add_trace(go.Scatter(x=i.index, y=i.values, name=nv("Ind. Prod. YoY", i),
                             line=dict(color=BB["magenta"], width=1.2)))
    if not pce.empty:
        p = yoy(pce, 12)
        fig.add_trace(go.Scatter(x=p.index, y=p.values, name=nv("Nondur. PCE YoY", p),
                                 line=dict(color=BB["yellow"], width=1.2)))
    fig.add_hline(y=0, line=dict(color=AXIS, width=1))
    return div(style(fig, "Output & consumption — YoY growth (%)"))


def fig_curve2s10s() -> str:
    c = store.get("T10Y2Y")
    if c.empty:
        return missing("2s10s Treasury curve")
    bp = c * 100
    fig = go.Figure(go.Scatter(x=bp.index, y=bp.values, name=nv("10Y−2Y (bp)", bp, "{:.0f}"),
                               line=dict(color=BB["white"], width=1.4)))
    fig.add_hline(y=0, line=dict(color=AXIS, width=1))
    tag(fig, bp, BB["white"], "{:.0f}")
    return div(style(fig, "2s10s Treasury curve (10Y − 2Y, bp)"))


def fig_credit_spreads() -> str:
    ig, hy = store.get("BAMLC0A0CM"), store.get("BAMLH0A0HYM2")
    if ig.empty or hy.empty:
        return missing("Credit spreads")
    igb, hyb = ig * 100, hy * 100
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=igb.index, y=igb.values, name=nv("IG OAS bp", igb, "{:.0f}"),
                             line=dict(color=BB["cyan"], width=1.2)), secondary_y=False)
    fig.add_trace(go.Scatter(x=hyb.index, y=hyb.values, name=nv("HY OAS bp", hyb, "{:.0f}"),
                             line=dict(color=BB["magenta"], width=1.2)), secondary_y=True)
    style(fig, "Credit spreads — IG (left) & HY (right)", right_axis=False)
    fig.update_yaxes(title_text="IG bp", secondary_y=False, showgrid=True,
                     gridcolor=GRID, griddash="dot", tickfont=dict(color=MUTE, family=SERIF))
    fig.update_yaxes(title_text="HY bp", secondary_y=True, showgrid=False,
                     tickfont=dict(color=MUTE, family=SERIF))
    return div(fig)


def fig_quality() -> str:
    ig, hy = store.get("BAMLC0A0CM"), store.get("BAMLH0A0HYM2")
    if ig.empty or hy.empty:
        return missing("HY − IG quality spread")
    qs = (hy - ig).dropna() * 100
    fig = go.Figure(go.Scatter(x=qs.index, y=qs.values, name=nv("HY−IG (bp)", qs, "{:.0f}"),
                               line=dict(color=BB["white"], width=1.3)))
    tag(fig, qs, BB["white"], "{:.0f}")
    return div(style(fig, "HY − IG quality spread (bp)"))


def fig_hyg_lqd() -> str:
    f = store.frame(["HYG", "LQD"]).dropna()
    if f.empty:
        return missing("HYG / LQD ratio")
    ratio = f["HYG"] / f["LQD"]
    avg = ratio.rolling(63).mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ratio.index, y=ratio.values, name=nv("HYG/LQD", ratio, "{:.3f}"),
                             line=dict(color=BB["white"], width=1.2)))
    fig.add_trace(go.Scatter(x=avg.index, y=avg.values, name=nv("63-day avg", avg, "{:.3f}"),
                             line=dict(color=BB["yellow"], width=1.1)))
    tag(fig, ratio, BB["white"], "{:.3f}")
    return div(style(fig, "HYG / LQD price ratio"))


def fig_hy_spy() -> str:
    hy, spy = store.get("BAMLH0A0HYM2"), store.get("SPY")
    if hy.empty or spy.empty:
        return missing("HY spread vs SPY")
    p = pd.DataFrame({"HY": hy * 100, "SPY": spy}).dropna()
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=p.index, y=p["SPY"], name=nv("SPY", p["SPY"]),
                             line=dict(color=BB["white"], width=1.2)), secondary_y=False)
    fig.add_trace(go.Scatter(x=p.index, y=p["HY"], name=nv("HY OAS bp", p["HY"], "{:.0f}"),
                             line=dict(color=BB["magenta"], width=1.2)), secondary_y=True)
    style(fig, "SPY vs HY credit spread", right_axis=False)
    fig.update_yaxes(title_text="SPY", secondary_y=False, showgrid=True, gridcolor=GRID,
                     griddash="dot", tickfont=dict(color=MUTE, family=SERIF))
    fig.update_yaxes(title_text="HY bp", secondary_y=True, showgrid=False,
                     tickfont=dict(color=MUTE, family=SERIF))
    return div(fig)


def fig_vix_trend() -> str:
    vix = store.get("^VIX")
    if vix.empty:
        return missing("VIX level & trend")
    ma50, ma100, ma200 = vix.rolling(50).mean(), vix.rolling(100).mean(), vix.rolling(200).mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=vix.index, y=vix.values, name=nv("VIX", vix),
                             line=dict(color=BB["white"], width=1.0)))
    fig.add_trace(go.Scatter(x=ma50.index, y=ma50.values, name=nv("SMAVG (50)", ma50),
                             line=dict(color=BB["magenta"], width=1.2)))
    fig.add_trace(go.Scatter(x=ma100.index, y=ma100.values, name=nv("SMAVG (100)", ma100),
                             line=dict(color=BB["green"], width=1.2)))
    fig.add_trace(go.Scatter(x=ma200.index, y=ma200.values, name=nv("SMAVG (200)", ma200),
                             line=dict(color=BB["yellow"], width=1.2)))
    tag(fig, vix, BB["white"])
    return div(style(fig, "VIX — level & trend"))


def fig_move_vix() -> str:
    f = store.frame(["^MOVE", "^VIX"]).dropna()
    if f.empty:
        return missing("MOVE vs VIX")
    win = f.iloc[-756:]
    norm = win / win.iloc[0] * 100
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=norm.index, y=norm["^MOVE"], name=nv("MOVE", norm["^MOVE"], "{:.0f}"),
                             line=dict(color=BB["amber"], width=1.3)))
    fig.add_trace(go.Scatter(x=norm.index, y=norm["^VIX"], name=nv("VIX", norm["^VIX"], "{:.0f}"),
                             line=dict(color=BB["white"], width=1.3)))
    return div(style(fig, "Bond vol (MOVE) vs equity vol (VIX) — indexed to 100"))


def fig_dollar() -> str:
    dxy, twi = store.get("DX-Y.NYB"), store.get("DTWEXBGS")
    if dxy.empty and twi.empty:
        return missing("US dollar")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if not dxy.empty:
        fig.add_trace(go.Scatter(x=dxy.index, y=dxy.values, name=nv("DXY", dxy, "{:.1f}"),
                                 line=dict(color=BB["white"], width=1.2)), secondary_y=False)
    if not twi.empty:
        fig.add_trace(go.Scatter(x=twi.index, y=twi.values, name=nv("Broad TWI", twi, "{:.1f}"),
                                 line=dict(color=BB["amber"], width=1.1)), secondary_y=True)
    style(fig, "US dollar — DXY & broad TWI", right_axis=False)
    fig.update_yaxes(title_text="DXY", secondary_y=False, showgrid=True, gridcolor=GRID,
                     griddash="dot", tickfont=dict(color=MUTE, family=SERIF))
    fig.update_yaxes(title_text="TWI", secondary_y=True, showgrid=False,
                     tickfont=dict(color=MUTE, family=SERIF))
    return div(fig)


def fig_crude() -> str:
    wti, brent = store.get("CL=F"), store.get("BZ=F")
    if wti.empty:
        return missing("Crude oil")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=wti.index, y=wti.values, name=nv("WTI", wti, "{:.1f}"),
                             line=dict(color=BB["white"], width=1.1)))
    if not brent.empty:
        fig.add_trace(go.Scatter(x=brent.index, y=brent.values, name=nv("Brent", brent, "{:.1f}"),
                                 line=dict(color=BB["amber"], width=1.1)))
    tag(fig, wti, BB["white"], "{:.1f}")
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
    disp = rets.std(axis=1).rolling(w).mean() * 100
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=corr.index, y=corr.values, name=nv("avg pairwise corr", corr, "{:.2f}"),
                             line=dict(color=BB["white"], width=1.2)), secondary_y=False)
    fig.add_trace(go.Scatter(x=disp.index, y=disp.values, name=nv("dispersion %", disp),
                             line=dict(color=BB["amber"], width=1.1)), secondary_y=True)
    style(fig, "Mega-cap realized correlation & dispersion", height=340, right_axis=False)
    fig.update_yaxes(title_text="corr", secondary_y=False, showgrid=True, gridcolor=GRID,
                     griddash="dot", tickfont=dict(color=MUTE, family=SERIF))
    fig.update_yaxes(title_text="disp %", secondary_y=True, showgrid=False,
                     tickfont=dict(color=MUTE, family=SERIF))
    return div(fig)


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


def calendar_html() -> str:
    """A real month-grid calendar for the next ~60 days, events dropped onto their
    day cells. No event-type classification."""
    window_end = TODAY + pd.Timedelta(days=60)

    events: dict[dt.date, list[str]] = {}

    def add(d, text):
        d = pd.Timestamp(d)
        if TODAY <= d <= window_end:
            events.setdefault(d.date(), []).append(text)

    # Months to display: this month through the month containing TODAY+60.
    months = []
    cur = TODAY.replace(day=1)
    while cur <= window_end:
        months.append((cur.year, cur.month))
        cur += pd.offsets.MonthBegin(1)

    for d, text in MACRO_EVENTS:
        add(pd.to_datetime(d), text)
    for y, m in months:
        quad = m in (3, 6, 9, 12)
        add(_third_friday(y, m), "Quad witching" if quad else "Monthly OpEx")
        add(_last_bday(y, m), "Quarter-end rebalance" if quad else "Month-end rebalance")

    grid = _cal.Calendar(firstweekday=6)                 # Sunday-first (US)
    dow = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    today = TODAY.date()

    out = []
    for y, m in months:
        cells = "".join(f'<div class="dow">{d}</div>' for d in dow)
        for week in grid.monthdatescalendar(y, m):
            for day in week:
                cls = "cal-cell"
                if day.month != m:
                    cls += " other"
                if day == today:
                    cls += " today"
                evs = "".join(f'<div class="cal-ev">{t}</div>' for t in events.get(day, []))
                cells += f'<div class="{cls}"><div class="dnum">{day.day}</div>{evs}</div>'
        out.append(f'<div class="cal-month"><h3>{_cal.month_name[m]} {y}</h3>'
                   f'<div class="cal-grid">{cells}</div></div>')
    return "".join(out)


def freshness_row() -> str:
    ao = store.as_of()
    if ao.empty:
        return ""
    stalest = ao.min()
    age = (TODAY - pd.Timestamp(stalest).normalize()).days
    return (f'stalest series {fmt_date(stalest)} ({age}d old) · {len(ao)} series tracked')


TEMPLATE = """<meta charset="utf-8">
<title>Cross-Asset Market Monitor</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
* {{ box-sizing:border-box; border-radius:0 !important; }}
body {{ margin:0; background:#000000; color:#e8e8e8;
       font-family:"Times New Roman", Times, serif; }}
header {{ padding:20px 26px 14px; border-bottom:1px solid #333; }}
h1 {{ margin:0; font-size:22px; font-weight:700; letter-spacing:.2px; }}
.sub {{ color:#8a8a8a; font-size:13px; margin-top:4px; }}
main {{ max-width:1280px; margin:0 auto; padding:18px 18px 60px; }}
.grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:14px; }}
.card {{ background:#000000; border:1px solid #333; padding:6px 12px 10px; overflow:hidden; }}
.card.wide {{ grid-column:1 / -1; }}
.card h2 {{ font-size:13px; color:#8a8a8a; font-weight:700; margin:10px 4px 2px;
           text-transform:uppercase; letter-spacing:.6px; }}
.ph {{ display:flex; flex-direction:column; align-items:center; justify-content:center;
      height:300px; color:#8a8a8a; text-align:center; gap:6px; }}
.ph span {{ font-size:12px; }}
.cal-month {{ margin-bottom:16px; }}
.cal-month h3 {{ font-size:15px; color:#e8e8e8; font-weight:700; margin:8px 2px 6px; }}
.cal-grid {{ display:grid; grid-template-columns:repeat(7,1fr);
            border-top:1px solid #333; border-left:1px solid #333; }}
.dow {{ text-align:center; font-size:11px; color:#8a8a8a; text-transform:uppercase;
       letter-spacing:.5px; padding:6px 0; background:#0a0a0a;
       border-right:1px solid #333; border-bottom:1px solid #333; }}
.cal-cell {{ min-height:90px; padding:4px 6px;
            border-right:1px solid #333; border-bottom:1px solid #333; }}
.cal-cell .dnum {{ font-size:12px; color:#9e9e9e; }}
.cal-cell.other .dnum {{ color:#3a3a3a; }}
.cal-cell.today {{ background:#151515; }}
.cal-cell.today .dnum {{ color:#ffffff; font-weight:700; }}
.cal-ev {{ font-size:11px; color:#e8e8e8; margin-top:3px; line-height:1.25;
          border-left:2px solid #ffb300; padding-left:5px; }}
@media (max-width:820px) {{ .grid {{ grid-template-columns:1fr; }} }}
</style>
<header>
  <h1>Cross-Asset Market Monitor</h1>
  <div class="sub">Macro · rates · credit · volatility · FX &amp; commodities · equity internals</div>
  <div class="sub">{fresh}</div>
</header>
<main>
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
             f'<div class="card">{fig_move_vix()}</div></div>'),
        card("4 · FX & Commodities", f'<div class="grid"><div class="card">{fig_dollar()}</div>'
             f'<div class="card">{fig_crude()}</div></div>'),
        card("5 · Equity Internals",
             f'<div class="grid"><div class="card wide">{fig_megacap()}</div></div>'),
        card("6 · Event & Flow Calendar (next 60 days)", calendar_html()),
    ]
    html = TEMPLATE.format(fresh=freshness_row(), sections="\n".join(sections))
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    return OUT_PATH


if __name__ == "__main__":
    p = build()
    print(f"wrote {p}  ({p.stat().st_size / 1024:.0f} KB)")
