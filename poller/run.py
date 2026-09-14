"""Snapshot poller: Signals Profiles Store -> Postgres.

Every POLL_INTERVAL_SECONDS (default 60) this reads the current value of every
Signals attribute and writes one row per app_id and one row per catalogued
article, stamped with a single snapshot_ts for the whole tick.

Semantics that the dashboard relies on:
  * A value is a TRAILING GAUGE over its rolling window, not a bucket.
    Never diff consecutive rows.
  * Counters have default_value=0 in Signals, so a quiet window reads 0.
    NULL therefore means "this poll failed" and should render as a gap.
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

import psycopg

from poller.reader import SignalsReader, chunked
from signals import config
from signals.definitions import article_metrics, site_metrics

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("poller")

SITE_ATTRS = [a.name for a in site_metrics.attributes]
ARTICLE_ATTRS = [a.name for a in article_metrics.attributes]

# Attributes whose values are maps/lists and so land in jsonb columns.
JSON_ATTRS = {
    a.name
    for group in (site_metrics, article_metrics)
    for a in group.attributes
    if a.aggregation in ("category_count", "unique_list")
}

_running = True


def _stop(signum, _frame):
    global _running
    log.info("signal %s received; finishing current tick then stopping", signum)
    _running = False


# published_at arrives as an ISO date-time string from the entity; the column
# is timestamptz so that "newest articles" sorts correctly.
TIMESTAMP_ATTRS = {"published_at"}


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        log.warning("could not parse timestamp %r", value)
        return None


def _encode(attr: str, value: Any) -> Any:
    if value is None:
        return None
    if attr in JSON_ATTRS:
        return json.dumps(value)
    if attr in TIMESTAMP_ATTRS:
        return _parse_ts(value)
    return value


def verify_schema(conn: psycopg.Connection) -> None:
    """Fail fast if the DB columns and the Signals definitions have drifted."""
    problems = []
    for table, attrs, fixed in (
        ("site_snapshots", SITE_ATTRS, {"app_id", "snapshot_ts"}),
        (
            "article_snapshots",
            ARTICLE_ATTRS,
            {"article_id", "snapshot_ts", "app_id"},
        ),
    ):
        cols = {
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                (table,),
            ).fetchall()
        }
        if not cols:
            problems.append(f"{table}: table does not exist (run db/schema.sql)")
            continue
        missing = set(attrs) - cols
        extra = cols - set(attrs) - fixed
        if missing:
            problems.append(f"{table}: attributes with no column: {sorted(missing)}")
        if extra:
            problems.append(f"{table}: columns with no attribute: {sorted(extra)}")

    if problems:
        for p in problems:
            log.error(p)
        raise SystemExit("schema/definition drift; refusing to start")
    log.info("schema check passed: %d site + %d article attributes", len(SITE_ATTRS), len(ARTICLE_ATTRS))


def write_site_row(conn, app_id: str, ts: datetime, values: dict[str, Any]) -> None:
    cols = ["app_id", "snapshot_ts"] + SITE_ATTRS
    row = [app_id, ts] + [_encode(a, values.get(a)) for a in SITE_ATTRS]
    conn.execute(
        f"INSERT INTO site_snapshots ({', '.join(cols)}) "
        f"VALUES ({', '.join(['%s'] * len(cols))}) ON CONFLICT DO NOTHING",
        row,
    )


def write_article_rows(conn, app_id: str, ts: datetime, rows: dict[str, dict]) -> None:
    cols = ["article_id", "app_id", "snapshot_ts"] + ARTICLE_ATTRS
    payload = []
    for article_id, values in rows.items():
        record: list[Any] = [article_id, app_id, ts]
        for a in ARTICLE_ATTRS:
            record.append(_encode(a, values.get(a)))
        payload.append(record)
    if not payload:
        return
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO article_snapshots ({', '.join(cols)}) "
            f"VALUES ({', '.join(['%s'] * len(cols))}) ON CONFLICT DO NOTHING",
            payload,
        )


def tick(reader: SignalsReader, conn: psycopg.Connection) -> None:
    ts = datetime.now(timezone.utc)

    for app_id in config.APP_IDS:
        try:
            site = reader.read_one(
                site_metrics.name,
                site_metrics.version,
                SITE_ATTRS,
                site_metrics.attribute_key.name,
                app_id,
            )
        except Exception:
            log.exception("site read failed for app_id=%s; skipping tick", app_id)
            continue

        write_site_row(conn, app_id, ts, site)

        article_ids = site.get("article_ids") or []
        if not article_ids:
            log.info("app_id=%s: catalog empty; no article rows this tick", app_id)
            conn.commit()
            continue

        rows: dict[str, dict] = {}
        for batch in chunked(list(article_ids), config.ID_CHUNK_SIZE):
            try:
                rows.update(
                    reader.read_batch(
                        article_metrics.name,
                        article_metrics.version,
                        ARTICLE_ATTRS,
                        article_metrics.attribute_key.name,
                        batch,
                    )
                )
            except Exception:
                # NULL row == "poll failed", which the dashboard renders as a
                # gap. Better than omitting the articles entirely.
                log.exception("article batch failed (%d ids); writing NULL rows", len(batch))
                rows.update({i: {} for i in batch})

        write_article_rows(conn, app_id, ts, rows)
        conn.commit()
        log.info(
            "app_id=%s: wrote 1 site row + %d article rows at %s",
            app_id, len(rows), ts.isoformat(timespec="seconds"),
        )


def main() -> None:
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    missing = [
        n for n in ("SIGNALS_API_URL", "SIGNALS_API_KEY", "SIGNALS_API_KEY_ID", "SIGNALS_ORG_ID")
        if not getattr(config, n)
    ]
    if missing:
        sys.exit(f"missing required settings: {', '.join(missing)} (see .env.example)")

    reader = SignalsReader(
        api_url=config.SIGNALS_API_URL,
        api_key=config.SIGNALS_API_KEY,
        api_key_id=config.SIGNALS_API_KEY_ID,
        org_id=config.SIGNALS_ORG_ID,
    )

    with psycopg.connect(config.DATABASE_URL) as conn:
        verify_schema(conn)
        log.info(
            "polling %s every %ds -> %s",
            config.APP_IDS, config.POLL_INTERVAL_SECONDS, config.DATABASE_URL.rsplit("@", 1)[-1],
        )
        while _running:
            started = time.monotonic()
            try:
                tick(reader, conn)
            except Exception:
                log.exception("tick failed")
                conn.rollback()
            # Drift-free cadence: sleep the remainder, not a flat interval.
            elapsed = time.monotonic() - started
            if _running:
                time.sleep(max(0.0, config.POLL_INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    main()
