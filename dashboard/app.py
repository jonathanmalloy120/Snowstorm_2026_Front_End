"""Flask dashboard for Snowstorm 2026.

Reads only from Postgres. Signals is the aggregation engine; this layer exists
because the Profiles Store holds current values with no history, and an
editorial team needs to see change over time.

    uv run flask --app dashboard.app run --debug --port 5000
"""

from __future__ import annotations

import time

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from dashboard import figures, queries
from poller.reader import SignalsReader
from signals import config
from signals.definitions import site_metrics

app = Flask(__name__)

WINDOW_CHOICES = [1, 6, 24]

# Metrics the live tile reads STRAIGHT FROM SIGNALS, bypassing Postgres.
# Everything else on the page is snapshot-derived; this is the one path that
# shows what Signals knows right now.
LIVE_ATTRS = ["article_views_5m", "page_views_5m", "unique_visitors_1h"]

# One reader for the process: ApiClient caches the JWT and refreshes it on
# expiry, so a per-request reader would re-authenticate on every poll (~700ms)
# instead of ~300ms. Not thread-safe for token refresh; the worst case is two
# concurrent requests both fetching a token, which is harmless.
_reader: SignalsReader | None = None


def _signals_reader() -> SignalsReader:
    global _reader
    if _reader is None:
        _reader = SignalsReader(
            api_url=config.SIGNALS_API_URL, api_key=config.SIGNALS_API_KEY,
            api_key_id=config.SIGNALS_API_KEY_ID, org_id=config.SIGNALS_ORG_ID,
        )
    return _reader


def _app_id() -> str:
    """Dashboard is configurable per app_id; default to the first configured."""
    requested = request.args.get("app_id")
    if requested and requested in config.APP_IDS:
        return requested
    return config.APP_IDS[0]


def _hours() -> int:
    try:
        h = int(request.args.get("hours", 6))
    except ValueError:
        return 6
    return h if h in WINDOW_CHOICES else 6


def _payload(conn, app_id: str, hours: int) -> dict:
    rows = queries.timeseries(conn, app_id, hours)
    return {
        "overview": queries.overview(conn, app_id),
        "coverage": queries.coverage(conn, app_id, hours),
        "articles": queries.top_articles(conn, app_id, limit=10),
        "figures": {
            "traffic": figures.traffic_over_time(rows),
            "engagement": figures.engagement_over_time(rows),
            "geo": figures.geo_choropleth(queries.countries(conn, app_id)),
            "category": figures.category_bar(queries.categories(conn, app_id)),
        },
    }


@app.template_filter("duration")
def duration(seconds: int | None) -> str:
    s = int(seconds or 0)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


@app.route("/")
def index():
    app_id, hours = _app_id(), _hours()
    with queries.connect() as conn:
        data = _payload(conn, app_id, hours)
        options = queries.article_options(conn, app_id)
    return render_template(
        "index.html", app_id=app_id, hours=hours, options=options,
        app_ids=config.APP_IDS, window_choices=WINDOW_CHOICES,
        poll_interval=config.POLL_INTERVAL_SECONDS,
        heartbeat=config.HEARTBEAT_DELAY_SECONDS,
        min_visit=config.MINIMUM_VISIT_LENGTH_SECONDS,
        **data,
    )


def _article_payload(conn, app_id: str, article_id: str, hours: int) -> dict:
    rows = queries.article_timeseries(conn, app_id, article_id, hours)
    detail = queries.article_detail(conn, app_id, article_id)
    return {
        "detail": detail,
        "coverage": queries.coverage(conn, app_id, hours),
        "figures": {
            "traffic": figures.article_traffic(rows),
            "engagement": figures.article_engagement(rows),
            "interactions": figures.article_interactions(rows),
            "geo": figures.article_geo(detail.get("country_counts_1h") or {}),
        },
    }


@app.route("/article/")
@app.route("/article/<article_id>")
def article(article_id: str | None = None):
    app_id, hours = _app_id(), _hours()
    with queries.connect() as conn:
        options = queries.article_options(conn, app_id)
        if not options:
            return render_template("article.html", app_id=app_id, hours=hours,
                                   app_ids=config.APP_IDS,
                                   window_choices=WINDOW_CHOICES,
                                   options=[], detail={}, coverage={},
                                   figures={}, article_id=None,
                                   poll_interval=config.POLL_INTERVAL_SECONDS,
                                   heartbeat=config.HEARTBEAT_DELAY_SECONDS,
                                   min_visit=config.MINIMUM_VISIT_LENGTH_SECONDS)
        # No article chosen: fall through to the busiest one rather than an
        # empty page, so the link is useful from a bookmark.
        if article_id is None:
            return redirect(url_for("article", article_id=options[0]["article_id"],
                                    hours=hours, app_id=app_id))
        if article_id not in {o["article_id"] for o in options}:
            abort(404, "No snapshots for that article")

        data = _article_payload(conn, app_id, article_id, hours)

    return render_template("article.html", app_id=app_id, hours=hours,
                           app_ids=config.APP_IDS, window_choices=WINDOW_CHOICES,
                           options=options, article_id=article_id,
                           poll_interval=config.POLL_INTERVAL_SECONDS,
                           heartbeat=config.HEARTBEAT_DELAY_SECONDS,
                           min_visit=config.MINIMUM_VISIT_LENGTH_SECONDS,
                           **data)


@app.route("/api/article/<article_id>")
def api_article(article_id: str):
    app_id, hours = _app_id(), _hours()
    with queries.connect() as conn:
        data = _article_payload(conn, app_id, article_id, hours)
    d = data["detail"]
    if not d:
        abort(404)
    return jsonify({
        "detail": {**d,
                   "snapshot_ts": d["snapshot_ts"].isoformat() if d.get("snapshot_ts") else None,
                   "published_at": d["published_at"].isoformat() if d.get("published_at") else None,
                   "first_seen": d["first_seen"].isoformat() if d.get("first_seen") else None,
                   "time_since_last": float(d["time_since_last"]) if d.get("time_since_last") is not None else None},
        "coverage": {**data["coverage"],
                     "last_tick": data["coverage"]["last_tick"].isoformat()
                     if data["coverage"].get("last_tick") else None},
        "figures": data["figures"],
        "engaged_label": duration(d.get("engaged_seconds_1h", 0)),
        "peak_engaged_label": duration(d.get("peak_engaged_1h", 0)),
        "interactions_label": d.get("interactions_label", ""),
    })


@app.route("/api/live")
def api_live():
    """Current values read directly from Signals, with no snapshot in between.

    Measured end-to-end latency from a page view on the publisher to a changed
    value here is ~6s, which is the pipeline and cannot be polled away. The
    page polls this every 5s; faster gains nothing.
    """
    app_id = _app_id()
    started = time.monotonic()
    try:
        values = _signals_reader().read_one(
            site_metrics.name, site_metrics.version, LIVE_ATTRS,
            site_metrics.attribute_key.name, app_id,
        )
    except Exception:
        app.logger.exception("live Signals read failed")
        # Degrade to nulls rather than breaking the page: this is one tile, and
        # the rest of the dashboard does not depend on Signals being reachable.
        return jsonify({"ok": False, "values": {k: None for k in LIVE_ATTRS}}), 200

    return jsonify({
        "ok": True,
        "values": {k: (int(values[k]) if values.get(k) is not None else 0) for k in LIVE_ATTRS},
        "read_ms": round((time.monotonic() - started) * 1000),
    })


@app.route("/api/data")
def api_data():
    """Polled by the page so it refreshes without a reload."""
    app_id, hours = _app_id(), _hours()
    with queries.connect() as conn:
        data = _payload(conn, app_id, hours)
    ov = data["overview"]
    return jsonify({
        "overview": {**ov, "snapshot_ts": ov.get("snapshot_ts").isoformat()
                     if ov.get("snapshot_ts") else None},
        "coverage": {**data["coverage"],
                     "last_tick": data["coverage"]["last_tick"].isoformat()
                     if data["coverage"].get("last_tick") else None},
        "articles": [
            {**a,
             "published_at": a["published_at"].isoformat() if a.get("published_at") else None,
             "time_since_last": float(a["time_since_last"]) if a.get("time_since_last") is not None else None,
             "engaged_label": duration(a["engaged_seconds_1h"])}
            for a in data["articles"]
        ],
        "figures": data["figures"],
        "engaged_label": duration(ov.get("engaged_seconds_1h", 0)),
        "social_label": ov.get("social_label", ""),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
