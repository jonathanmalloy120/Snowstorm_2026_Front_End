"""Read layer for the editorial dashboard.

Semantics this module encodes -- worth reading before changing anything:

  * Every stored value is a TRAILING GAUGE over its rolling window ("views in
    the 5 minutes before snapshot_ts"), not a disjoint bucket. Never diff
    consecutive rows.

  * A MISSING ROW means the poller did not run (sleep, crash, restart). Those
    are real gaps in history and are rendered as breaks in the line.

  * A NULL VALUE inside a row means the window was empty -- i.e. zero. Signals
    returns None rather than default_value when a rolling window contains no
    events at all, so NULL and 0 both mean "nothing happened", and NULL must
    not be drawn as a gap.

  * Engaged seconds are DERIVED here, never stored:
        (pings - 1) * heartbeat_delay + minimum_visit_length
    so retuning the tracker reinterprets history instead of invalidating it.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from signals import config


def connect() -> psycopg.Connection:
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row)


def engaged_seconds(pings: Any) -> int:
    """Derive engaged time from a raw ping count. 0 pings -> 0 seconds."""
    if not pings:
        return 0
    return int((int(pings) - 1) * config.HEARTBEAT_DELAY_SECONDS
               + config.MINIMUM_VISIT_LENGTH_SECONDS)


def _num(v: Any) -> int:
    """NULL inside a stored row means 'empty window', which is zero."""
    return int(v) if v is not None else 0


def overview(conn: psycopg.Connection, app_id: str) -> dict[str, Any]:
    """Headline tiles, from the most recent snapshot."""
    row = conn.execute(
        """
        SELECT snapshot_ts, page_views_1h, article_views_1h, pings_1h,
               unique_visitors_1h, page_views_6h, article_views_6h,
               social_counts_1h
        FROM site_snapshots
        WHERE app_id = %s
        ORDER BY snapshot_ts DESC
        LIMIT 1
        """,
        (app_id,),
    ).fetchone()
    if not row:
        return {}

    social = row["social_counts_1h"] or {}
    return {
        "snapshot_ts": row["snapshot_ts"],
        "unique_visitors_1h": _num(row["unique_visitors_1h"]),
        "article_views_1h": _num(row["article_views_1h"]),
        "article_views_6h": _num(row["article_views_6h"]),
        "page_views_1h": _num(row["page_views_1h"]),
        "engaged_seconds_1h": engaged_seconds(row["pings_1h"]),
        "social_total_1h": sum(int(v) for v in social.values()),
        "social_breakdown_1h": social,
    }


def timeseries(conn: psycopg.Connection, app_id: str, hours: int = 6) -> list[dict]:
    """Trailing-gauge series for the time-travel chart.

    Rows are returned as stored. Missing minutes are simply absent, which is
    what produces the visible gaps -- they are real and should not be filled.
    """
    rows = conn.execute(
        """
        SELECT snapshot_ts, page_views_5m, article_views_5m, pings_5m,
               unique_visitors_1h
        FROM site_snapshots
        WHERE app_id = %s AND snapshot_ts > now() - make_interval(hours => %s)
        ORDER BY snapshot_ts
        """,
        (app_id, hours),
    ).fetchall()
    for r in rows:
        r["engaged_seconds_5m"] = engaged_seconds(r["pings_5m"])
        r["page_views_5m"] = _num(r["page_views_5m"])
        r["article_views_5m"] = _num(r["article_views_5m"])
        r["pings_5m"] = _num(r["pings_5m"])
    return rows


def top_articles(conn: psycopg.Connection, app_id: str, limit: int = 10) -> list[dict]:
    """Latest snapshot per article, ranked by views in the trailing hour."""
    rows = conn.execute(
        """
        SELECT article_id, title, author, category, page_url,
               views_1h, views_5m, pings_1h, unique_readers_1h,
               likes_1h, bookmarks_1h, favorites_1h, shares_1h,
               time_since_last, published_at
        FROM article_snapshots
        WHERE app_id = %s
          AND snapshot_ts = (
              SELECT max(snapshot_ts) FROM article_snapshots WHERE app_id = %s
          )
        ORDER BY views_1h DESC NULLS LAST, title
        LIMIT %s
        """,
        (app_id, app_id, limit),
    ).fetchall()
    for r in rows:
        r["engaged_seconds_1h"] = engaged_seconds(r["pings_1h"])
        for k in ("views_1h", "views_5m", "unique_readers_1h",
                  "likes_1h", "bookmarks_1h", "favorites_1h", "shares_1h"):
            r[k] = _num(r[k])
        r["interactions_1h"] = (r["likes_1h"] + r["bookmarks_1h"]
                                + r["favorites_1h"] + r["shares_1h"])
    return rows


def _latest_map(conn: psycopg.Connection, app_id: str, column: str) -> dict[str, int]:
    """Most recent non-null value of a jsonb category_count column."""
    row = conn.execute(
        f"""
        SELECT {column} AS m
        FROM site_snapshots
        WHERE app_id = %s AND {column} IS NOT NULL
        ORDER BY snapshot_ts DESC
        LIMIT 1
        """,
        (app_id,),
    ).fetchone()
    return {k: int(v) for k, v in (row["m"] or {}).items()} if row else {}


def countries(conn, app_id: str) -> dict[str, int]:
    return _latest_map(conn, app_id, "country_counts_1h")


def categories(conn, app_id: str) -> dict[str, int]:
    return _latest_map(conn, app_id, "category_counts_1h")


def share_platforms(conn, app_id: str) -> dict[str, int]:
    return _latest_map(conn, app_id, "share_platforms_1h")


def coverage(conn: psycopg.Connection, app_id: str, hours: int = 6) -> dict[str, Any]:
    """How much of the window the poller actually sampled.

    Shown in the UI because sparse history is a property of the data, not a
    rendering artefact -- a reader should be able to tell the difference.
    """
    row = conn.execute(
        """
        SELECT count(*) AS ticks,
               max(snapshot_ts) AS last_tick,
               EXTRACT(EPOCH FROM (now() - max(snapshot_ts))) AS stale_seconds
        FROM site_snapshots
        WHERE app_id = %s AND snapshot_ts > now() - make_interval(hours => %s)
        """,
        (app_id, hours),
    ).fetchone()
    expected = hours * 3600 / max(config.POLL_INTERVAL_SECONDS, 1)
    ticks = row["ticks"] or 0
    return {
        "ticks": ticks,
        "expected": int(expected),
        "pct": round(100.0 * ticks / expected) if expected else 0,
        "last_tick": row["last_tick"],
        "stale_seconds": int(row["stale_seconds"] or 0) if row["last_tick"] else None,
    }
