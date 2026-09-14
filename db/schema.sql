-- Snowstorm 2026 — snapshot store for Snowplow Signals attributes.
--
-- Design notes (agreed in planning):
--   * Every row is a SNAPSHOT of a Signals attribute value at a point in time.
--     Signals holds only current values; this table is what gives us history.
--   * Attributes use rolling windows (`period=`), never `ttl=`. A value is
--     therefore a TRAILING GAUGE -- "views in the 5 minutes before snapshot_ts"
--     -- not a disjoint bucket. Never diff consecutive rows.
--   * snapshot_ts is stamped by the POLLER, not by Signals. Signals has no
--     notion of when a value was read.
--   * Counters are defined with default_value=0, so a quiet window returns 0.
--     NULL therefore means "the poll failed", and should render as a GAP.
--   * category_count / unique_list attributes are maps and lists, so they are
--     jsonb even though every other column is scalar.

CREATE TABLE IF NOT EXISTS site_snapshots (
    app_id                TEXT        NOT NULL,
    snapshot_ts           TIMESTAMPTZ NOT NULL,

    -- catalog: unique_list of article_id (capped at 100 by Signals,
    -- evicting least-recently-seen). Drives which articles we poll next tick.
    article_ids           JSONB,

    page_views_5m         NUMERIC,
    page_views_1h         NUMERIC,
    page_views_6h         NUMERIC,

    pings_5m              NUMERIC,
    pings_1h              NUMERIC,
    pings_6h              NUMERIC,

    -- HyperLogLog (~1% error). NOT summable across app_ids.
    unique_visitors_1h    NUMERIC,
    unique_visitors_6h    NUMERIC,

    country_counts_1h     JSONB,
    country_counts_6h     JSONB,
    social_counts_1h      JSONB,
    social_counts_6h      JSONB,

    PRIMARY KEY (app_id, snapshot_ts)
);

CREATE TABLE IF NOT EXISTS article_snapshots (
    article_id            TEXT        NOT NULL,
    snapshot_ts           TIMESTAMPTZ NOT NULL,

    -- Which site catalog this article was discovered through. NOTE: the Signals
    -- attribute group behind the metric columns is keyed on article_id ALONE,
    -- so these values are NOT scoped by app_id. If two app_ids ever serve the
    -- same article_id, their traffic merges upstream and this column records
    -- only the catalog we found it in.
    app_id                TEXT        NOT NULL,

    -- metadata, carried as last() on the article entity
    headline              TEXT,
    article_slug          TEXT,
    category              TEXT,
    author                TEXT,
    published_at          TIMESTAMPTZ,

    views_5m              NUMERIC,
    views_1h              NUMERIC,

    -- raw ping counts. Engaged seconds are computed at READ time as
    --   (pings - 1) * heartbeat_delay + minimum_visit_length
    -- so that changing tracker config does not invalidate stored history.
    pings_5m              NUMERIC,
    pings_1h              NUMERIC,

    unique_readers_1h     NUMERIC,
    country_counts_1h     JSONB,

    shares_1h             NUMERIC,
    bookmarks_1h          NUMERIC,
    likes_1h              NUMERIC,

    -- seconds since this article's last event; recomputed by Signals at read
    -- time. Useful as a "hot right now" signal.
    time_since_last       NUMERIC,

    PRIMARY KEY (article_id, snapshot_ts)
);

-- Charts are overwhelmingly "recent window, ordered by time".
CREATE INDEX IF NOT EXISTS site_snapshots_ts_idx
    ON site_snapshots (snapshot_ts DESC);
CREATE INDEX IF NOT EXISTS article_snapshots_ts_idx
    ON article_snapshots (snapshot_ts DESC);
CREATE INDEX IF NOT EXISTS article_snapshots_app_ts_idx
    ON article_snapshots (app_id, snapshot_ts DESC);
