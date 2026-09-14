# Snowstorm 2026 — Signals for Editorial Analytics

Signals is the aggregation engine. Postgres only records **history**, which is
the one thing the Profiles Store structurally cannot provide.

```
publisher site -> pipeline -> Signals -> poller (60s) -> Postgres -> dashboard
```

## Layout

| Path | What |
|---|---|
| `signals/definitions.py` | The two attribute groups |
| `signals/config.py` | All cross-team coupling: Iglu coordinates, credentials, poller settings |
| `signals/publish.py` | Publish definitions to Signals |
| `poller/reader.py` | Batch reader (the SDK only reads one identifier at a time) |
| `poller/run.py` | The 60s snapshot loop |
| `db/schema.sql` | `site_snapshots` + `article_snapshots` |

## Attribute groups

**`site_metrics`**, keyed on `app_id` — `article_ids` (the catalog), page views,
pings, unique visitors, country and social breakdowns at 5m/1h/6h.

**`article_metrics`**, keyed on `article_id` — metadata (`last()`), views, pings,
unique readers, country breakdown, shares/bookmarks/likes, `time_since_last`.

Signals has no way to enumerate keys, so `article_ids` on the site group *is*
the enumeration: the poller reads it, then batch-reads per-article metrics for
exactly those IDs. No CMS integration anywhere.

## Services

`editorial_site` (app_id) and `editorial_articles` (article_id). Two rather
than one because a service can only reference groups sharing a single attribute
key. Groups are referenced by versioned link, since a published group is
immutable.

## Changing a published definition

A published attribute group cannot be edited -- the API returns
`Cannot update published attribute group`. **Bump the group's `version`** and
publish that; do not unpublish, which would reset aggregation (Signals does not
backdate, so accumulated history is unrecoverable). `--only {keys,groups,services}`
scopes a publish so services can change without touching live groups.

## Rules the code depends on

* Rolling windows use `period=`, **never `ttl=`** — ttl is expiry-on-inactivity
  whose timer resets on every event, not a window.
* Every value is a **trailing gauge**, not a bucket. **Never diff rows.**
* Counters set `default_value=0`, so a quiet window reads 0 and `NULL` means the
  poll failed — render it as a gap.
* No arithmetic is stored. Engaged seconds are derived at read time as
  `(pings - 1) * heartbeat + min_visit_length`, so retuning the tracker does not
  invalidate accumulated history.
* Signals does **not backdate**. Publish definitions before generating traffic.

## Running

```bash
cp .env.example .env      # fill in Signals credentials
docker compose up -d      # Postgres on :5433 (5432 is often taken)
uv sync

uv run python -m signals.publish --dry-run
uv run python -m signals.publish
uv run python -m poller.run
```

## Known gaps

* Iglu coordinates are confirmed against Console DEV 1-0-0. The schemas are on
  publisher's `types/analytics.ts`. Confirm them before publishing — a wrong
  vendor yields attributes that populate with nothing and report no error.
* The publisher does not yet call `enableActivityTracking` (no page pings, so no
  engaged time) or `addGlobalContexts` (no article entity, so `article_metrics`
  has no key). Both are required for anything article-level to work.
* `reader.py` assumes the columnar batch response is ordered to match the
  identifiers sent. Verify on the first live run; a length mismatch is logged and
  the batch is nulled rather than misaligned.
