"""Plotly figure construction.

Charts are built server-side and serialised to JSON, so all logic stays in
Python and the page only needs plotly.js to render.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import plotly.graph_objects as go
import pycountry

from signals import config

# Editorial palette: one accent, one muted support, neutral everything else.
# Counts are discrete and sparse. Lines are drawn LINEAR, never splined:
# smoothing would invent intermediate values the snapshots never recorded, and
# can overshoot below zero — the same class of fabrication that gap-breaking
# exists to avoid.
#
# For the same reason these series carry no area fill. Plotly's fill="tozeroy"
# spans a None even when connectgaps=False, so a filled series draws a solid
# wedge straight across hours the poller never sampled — exactly the lie the
# broken line is there to prevent.
ACCENT = "#2f6fed"
SUPPORT = "#e8833a"
MUTED = "#8a94a6"
GRID = "rgba(140,150,170,0.18)"

_BASE = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
              size=12, color="#5b6472"),
    margin=dict(l=48, r=16, t=16, b=40),
    hovermode="x unified",
    showlegend=True,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=11)),
)


def _layout(**overrides):
    """Base layout with per-figure overrides merged in (not duplicated)."""
    return {**_BASE, **overrides}


def _break_gaps(rows: list[dict], value_key: str) -> tuple[list, list]:
    """Insert None where the poller missed ticks, so lines break at real gaps.

    A missing row means the poller was not running. Connecting across that
    would draw a straight line through hours of unmeasured time and imply data
    we do not have.
    """
    limit = timedelta(seconds=config.POLL_INTERVAL_SECONDS * 2.5)
    xs: list[Any] = []
    ys: list[Any] = []
    prev = None
    for r in rows:
        ts = r["snapshot_ts"]
        if prev is not None and ts - prev > limit:
            xs.append(prev + limit / 2)
            ys.append(None)
        xs.append(ts)
        ys.append(r[value_key])
        prev = ts
    return xs, ys


def _empty(message: str) -> str:
    fig = go.Figure()
    fig.update_layout(**_layout(height=280, showlegend=False,
                      xaxis=dict(visible=False), yaxis=dict(visible=False),
                      annotations=[dict(text=message, showarrow=False,
                                        font=dict(size=13, color=MUTED))]))
    return fig.to_json()


def traffic_over_time(rows: list[dict]) -> str:
    """The chart that justifies the whole Postgres layer."""
    if not rows:
        return _empty("No snapshots in this window yet")

    fig = go.Figure()
    for key, name, colour in (
        ("article_views_5m", "Article views", ACCENT),
        ("page_views_5m", "All page views", MUTED),
    ):
        xs, ys = _break_gaps(rows, key)
        fig.add_trace(go.Scatter(
            x=xs, y=ys, name=name, mode="lines",
            line=dict(color=colour, width=2.2 if colour == ACCENT else 1.4,
                      shape="linear"),
            connectgaps=False,
            hovertemplate="%{y} in trailing 5 min<extra>" + name + "</extra>",
        ))
    fig.update_layout(**_layout(height=300,
                      xaxis=dict(showgrid=False, showline=True, linecolor=GRID),
                      yaxis=dict(title="views (trailing 5 min)", gridcolor=GRID,
                                 zeroline=False, rangemode="tozero")))
    return fig.to_json()


def engagement_over_time(rows: list[dict]) -> str:
    if not rows:
        return _empty("No snapshots in this window yet")
    xs, ys = _break_gaps(rows, "engaged_seconds_5m")
    fig = go.Figure(go.Scatter(
        x=xs, y=ys, mode="lines", name="Engaged time",
        line=dict(color=SUPPORT, width=2.2, shape="linear"),
        connectgaps=False,
        hovertemplate="%{y}s engaged in trailing 5 min<extra></extra>",
    ))
    fig.update_layout(**_layout(height=240, showlegend=False,
                      xaxis=dict(showgrid=False, showline=True, linecolor=GRID),
                      yaxis=dict(title="engaged seconds", gridcolor=GRID,
                                 zeroline=False, rangemode="tozero")))
    return fig.to_json()


def _iso3(code: str) -> str | None:
    """Snowplow's geo_country is ISO-2; plotly choropleths want ISO-3."""
    try:
        c = pycountry.countries.get(alpha_2=code.upper())
        return c.alpha_3 if c else None
    except (LookupError, AttributeError):
        return None


def geo_choropleth(counts: dict[str, int]) -> str:
    if not counts:
        return _empty("No geo data yet — check the IP lookup enrichment")
    pairs = [(_iso3(k), k, v) for k, v in counts.items()]
    pairs = [p for p in pairs if p[0]]
    if not pairs:
        return _empty("No resolvable country codes yet")

    iso3, iso2, vals = zip(*pairs)
    names = []
    for code in iso2:
        c = pycountry.countries.get(alpha_2=code.upper())
        names.append(c.name if c else code)

    fig = go.Figure(go.Choropleth(
        locations=list(iso3), z=list(vals), text=names, locationmode="ISO-3",
        colorscale=[[0, "rgba(47,111,237,0.15)"], [1, ACCENT]],
        showscale=False, marker_line_color="rgba(255,255,255,0.6)",
        marker_line_width=0.5,
        hovertemplate="%{text}: %{z} views<extra></extra>",
    ))
    fig.update_layout(**_layout(margin=dict(l=0, r=0, t=0, b=0), height=320,
                      showlegend=False,
                      geo=dict(showframe=False, showcoastlines=False,
                               projection_type="natural earth",
                               bgcolor="rgba(0,0,0,0)",
                               landcolor="rgba(140,150,170,0.10)",
                               showland=True, showcountries=True,
                               countrycolor="rgba(255,255,255,0.5)")))
    return fig.to_json()


def category_bar(counts: dict[str, int]) -> str:
    if not counts:
        return _empty("No category data yet")
    items = sorted(counts.items(), key=lambda kv: kv[1])
    labels = [k.title() for k, _ in items]
    vals = [v for _, v in items]
    fig = go.Figure(go.Bar(
        x=vals, y=labels, orientation="h", marker_color=ACCENT,
        hovertemplate="%{y}: %{x} views<extra></extra>",
    ))
    fig.update_layout(**_layout(height=max(200, 40 * len(items) + 60),
                      showlegend=False,
                      xaxis=dict(title="views (trailing hour)", gridcolor=GRID, zeroline=False),
                      yaxis=dict(showgrid=False)))
    return fig.to_json()


# ---------------------------------------------------------------------------
# Single-article figures
# ---------------------------------------------------------------------------

INTERACTION_SERIES = (
    ("likes_1h", "Likes", ACCENT),
    ("bookmarks_1h", "Bookmarks", SUPPORT),
    ("favorites_1h", "Favourites", "#9b59d0"),
    ("shares_1h", "Shares", "#1f9d5c"),
)


def article_traffic(rows: list[dict]) -> str:
    """Views and readers for one article over the window."""
    if not rows:
        return _empty("No snapshots for this article in this window")
    fig = go.Figure()
    for key, name, colour, fill in (
        ("views_5m", "Views (trailing 5 min)", ACCENT, True),
        ("unique_readers_1h", "Readers (trailing hour)", MUTED, False),
    ):
        xs, ys = _break_gaps(rows, key)
        fig.add_trace(go.Scatter(
            x=xs, y=ys, name=name, mode="lines", connectgaps=False,
            line=dict(color=colour, width=2.2 if fill else 1.4,
                      shape="linear"),
            hovertemplate="%{y}<extra>" + name + "</extra>",
        ))
    fig.update_layout(**_layout(height=280,
                      xaxis=dict(showgrid=False, showline=True, linecolor=GRID),
                      yaxis=dict(gridcolor=GRID, zeroline=False, rangemode="tozero")))
    return fig.to_json()


def article_engagement(rows: list[dict]) -> str:
    if not rows:
        return _empty("No snapshots for this article in this window")
    xs, ys = _break_gaps(rows, "engaged_seconds_5m")
    fig = go.Figure(go.Scatter(
        x=xs, y=ys, mode="lines", connectgaps=False,
        line=dict(color=SUPPORT, width=2.2, shape="linear"),
        hovertemplate="%{y}s engaged in trailing 5 min<extra></extra>",
    ))
    fig.update_layout(**_layout(height=240, showlegend=False,
                      xaxis=dict(showgrid=False, showline=True, linecolor=GRID),
                      yaxis=dict(title="engaged seconds", gridcolor=GRID,
                                 zeroline=False, rangemode="tozero")))
    return fig.to_json()


def article_interactions(rows: list[dict]) -> str:
    """Stacked interaction counts. Omits series that are flat zero, so a quiet
    article doesn't show four meaningless legend entries."""
    if not rows:
        return _empty("No snapshots for this article in this window")
    active = [(k, n, c) for k, n, c in INTERACTION_SERIES if any(r[k] for r in rows)]
    if not active:
        return _empty("No likes, bookmarks, favourites or shares yet")

    fig = go.Figure()
    for key, name, colour in active:
        xs, ys = _break_gaps(rows, key)
        fig.add_trace(go.Scatter(
            x=xs, y=ys, name=name, mode="lines", connectgaps=False,
            stackgroup="one", line=dict(color=colour, width=0.8),
            hovertemplate="%{y}<extra>" + name + "</extra>",
        ))
    fig.update_layout(**_layout(height=240,
                      xaxis=dict(showgrid=False, showline=True, linecolor=GRID),
                      yaxis=dict(title="interactions (trailing hour)",
                                 gridcolor=GRID, zeroline=False, rangemode="tozero")))
    return fig.to_json()


def article_geo(counts: dict[str, int]) -> str:
    if not counts:
        return _empty("No geo data for this article yet")
    return geo_choropleth(counts)
