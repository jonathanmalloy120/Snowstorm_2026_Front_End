# Snowstorm 2026 — Signals for Editorial Analytics

A near-real-time editorial dashboard powered by **Snowplow Signals** as the
aggregation engine.

```
publisher site ─▶ pipeline ─▶ Signals ─▶ poller (60s) ─▶ Postgres ─▶ Flask dashboard
                              │                          │
                        current values              history
```

Signals answers *what is true now*, in milliseconds, with no stream
infrastructure to run. What it cannot do is tell you what was true an hour ago:
the Profiles Store holds current values only. The poller snapshots those values
on a fixed cadence, and Postgres is what turns them into history. That split is
the whole point of the project — the dashboard reads history from Postgres, and
every number in it originated in Signals.

The publisher site lives in a separate repo:
[Snowstorm_2026_Publisher](https://github.com/jonathanmalloy120/Snowstorm_2026_Publisher).

---

## Prerequisites

| | |
|---|---|
| **Docker** | runs Postgres |
| **[uv](https://docs.astral.sh/uv/)** | manages Python; the SDK needs **3.11+**, and `.python-version` pins it so your system Python doesn't matter |
| **Snowplow Console access** | to the org that owns the pipeline |
| `psql` *(optional)* | for querying the DB by hand |

---

## Setup

### 1. Credentials

```bash
cp .env.example .env
```

From **Console → Signals → Overview**, fill in:

| Variable | Where |
|---|---|
| `SIGNALS_API_URL` | Signals → Overview. Looks like `https://<id>.signals.snowplowanalytics.com` — **the placeholder in `.env.example` is not a real URL** |
| `SIGNALS_API_KEY` / `SIGNALS_API_KEY_ID` | Console API key |
| `SIGNALS_ORG_ID` | the UUID in the Console URL |

`APP_IDS` must match `NEXT_PUBLIC_SNOWPLOW_APP_ID` in the publisher repo.

`HEARTBEAT_DELAY_SECONDS` and `MINIMUM_VISIT_LENGTH_SECONDS` must match
`enableActivityTracking()` in the publisher's `lib/snowplow.ts` — currently
`{ minimumVisitLength: 10, heartbeatDelay: 10 }`. Engaged time is derived from
them, so a mismatch silently scales every engagement number. Nothing enforces
this; it is convention only.

### 2. Database

```bash
docker compose up -d        # Postgres 16 on localhost:5433
```

Port **5433**, not 5432, because 5432 is commonly taken by another project's
container. `db/schema.sql` is applied automatically on first boot of an empty
volume; to re-apply by hand:

```bash
PGPASSWORD=snowstorm psql -h localhost -p 5433 -U snowstorm -d snowstorm -f db/schema.sql
```

### 3. Python

```bash
uv sync
```

### 4. Prerequisites in Console (once per pipeline)

These are **not** in this repo, and each one fails silently or cryptically if
missed:

1. **Signals enabled** — Console → Signals → Enable.
2. **IP lookup (MaxMind) enrichment on** — it is *not* in the default
   enrichment set. Without it there is no `geo_country` and the map is empty.
   Select the **City** database if you ever want lat/lon.
3. **Data structures deployed to PROD.** Signals binds only to schemas in
   production — DEV is not enough. Promotion is dev → prod; `publish prod`
   does not validate and requires the structure to exist on dev first.

### 5. Publish the Signals definitions

```bash
uv run python -m signals.publish --dry-run   # print what would be published
uv run python -m signals.publish             # for real
```

> **Signals does not backdate.** Attributes calculate from the moment they are
> published. Publish *before* generating traffic you care about, or it is lost.

---

## Running

### Poller

```bash
nohup ./run_poller.sh >> poller.log 2>&1 &
```

`run_poller.sh` wraps the poller in `caffeinate -is` so macOS does not nap or
idle-sleep it. Check on it with:

```bash
tail -f poller.log | grep -v httpx
```

**A sleeping Mac runs nothing.** `caffeinate -s` only holds on AC power; an
unplugged or lid-closed laptop produces gaps that cannot be recovered. See
[Known gaps](#known-gaps).

### Dashboard

```bash
uv run flask --app dashboard.app run --port 5000 --debug
```

Then open <http://127.0.0.1:5000>. Use `--debug` while developing or Jinja
caches templates and your edits will not appear.

---

## Verifying it works

Work outwards from Signals, so a failure is unambiguous about where it is.

```bash
# 1. Is Signals aggregating? (reads the site group directly)
uv run python -c "
from poller.reader import SignalsReader
from signals import config
from signals.definitions import site_metrics
r = SignalsReader(config.SIGNALS_API_URL, config.SIGNALS_API_KEY,
                  config.SIGNALS_API_KEY_ID, config.SIGNALS_ORG_ID)
print(r.read_one(site_metrics.name, site_metrics.version,
                 [a.name for a in site_metrics.attributes],
                 site_metrics.attribute_key.name, config.APP_IDS[0]))"

# 2. Is the poller writing?
PGPASSWORD=snowstorm psql -h localhost -p 5433 -U snowstorm -d snowstorm -c \
  "SELECT count(*) ticks, max(snapshot_ts) last_tick,
          (now()-max(snapshot_ts))::interval(0) AS stale FROM site_snapshots;"

# 3. What coverage are we actually getting?
PGPASSWORD=snowstorm psql -h localhost -p 5433 -U snowstorm -d snowstorm -c \
  "SELECT count(*) AS ticks, round(100.0*count(*)/360) || '%' AS coverage_6h
   FROM site_snapshots WHERE snapshot_ts > now() - interval '6 hours';"
```

If step 1 returns values but step 2 is stale, the poller is down. If step 1 is
all `None`/0, the problem is upstream — tracking, enrichment, or schemas.

---

## Layout

| Path | What |
|---|---|
| `signals/config.py` | Every cross-team coupling: Iglu coordinates, credentials, tracker constants |
| `signals/definitions.py` | The two attribute groups, two keys, two services |
| `signals/publish.py` | Publishes to Signals; `--dry-run`, `--only` |
| `poller/reader.py` | Batch reader — the SDK reads one identifier at a time |
| `poller/run.py` | The 60s snapshot loop; refuses to start on schema drift |
| `db/schema.sql` | `site_snapshots` + `article_snapshots` |
| `dashboard/queries.py` | Read layer; derives engaged time |
| `dashboard/figures.py` | Plotly figures, built server-side |
| `dashboard/app.py` | Flask app + `/api/data` for the 30s auto-refresh |
| `run_poller.sh` | Poller wrapped in `caffeinate` |

---

## How it fits together

### Schemas it binds to

| Schema | Version | Fields |
|---|---|---|
| `com.snowplowanalytics/article` (entity) | **2-0-0** | `title`, `author`, `article_id`, `category`, `published_at` |
| `com.snowplowanalytics/article_view` | 1-0-0 | `id`, `title`, `author` |
| `com.snowplowanalytics/article_interaction` | 1-0-0 | `interaction_type`, `social_platform` |

**Only the entity carries `article_id`**, so it must be attached to
`page_view`, `page_ping` *and* `article_interaction` via `addGlobalContexts`.
Without that, `article_metrics` has no attribute key and every one of its
attributes stays empty, with no error anywhere.

### Attribute groups

**`site_metrics`** (18 attributes), keyed on `app_id` — `article_ids` (the
catalog), page views, article views and pings at 5m/1h/6h, unique visitors,
country / category / social breakdowns, share-by-platform.

**`article_metrics`** (16 attributes), keyed on `article_id` — `title`,
`author`, `page_url`, `category`, `published_at` (all `last()`), views and
pings at 5m/1h, unique readers, country breakdown, like/bookmark/favorite/share
counters, `time_since_last`.

### How enumeration works

Signals has **no scan or list API** — you can only read keys you already know.
So `article_ids` on the site group *is* the enumeration: a `unique_list` of
every article ID seen. The poller reads it, then batch-reads per-article
metrics for exactly those IDs. No CMS integration anywhere, which was a goal.

`unique_list` is capped at **100 values**, evicting least-recently-seen, so the
catalog is really "the 100 most recently read articles".

### Services

`editorial_site` (app_id) and `editorial_articles` (article_id). Two rather
than one because *a service can only reference groups sharing a single
attribute key*. Groups are referenced by versioned link, not by value, because
a published group is immutable.

---

## Rules the code depends on

* Rolling windows use **`period=`, never `ttl=`**. `ttl` is
  expiry-on-inactivity whose timer resets on every event — it is not a window.
* Every stored value is a **trailing gauge** over its window ("views in the 5
  minutes before `snapshot_ts`"), not a disjoint bucket. **Never diff rows.**
* A **missing row** means the poller was not running. Charts break the line
  there rather than interpolating across unmeasured time.
* A **`NULL` value inside a row** means the window was empty — i.e. **zero**,
  not a failed poll. Signals returns `None` rather than `default_value` when a
  rolling window contains no events at all.
* **No arithmetic is stored.** Engaged seconds are derived at read time as
  `(pings - 1) * heartbeat + min_visit_length`, so retuning the tracker
  reinterprets history instead of invalidating it.
* Unique visitors/readers are **approximate** — HyperLogLog, ~1% error — and
  **cannot be summed across app_ids**.

### Changing a published definition

A published attribute group **cannot be edited**; the API returns `Cannot
update published attribute group`. **Bump the group's `version`** and publish
that.

Do **not** unpublish to get around it — that resets aggregation, and since
Signals does not backdate, the accumulated history is unrecoverable. Use
`--only {keys,groups,services}` to publish one kind of object without touching
live groups.

---

## Troubleshooting

Every entry below is a failure this project actually hit.

| Symptom | Cause / fix |
|---|---|
| `Bind for 0.0.0.0:5432 failed: port is already allocated` | Another Postgres container. We use **5433**; check `docker ps`. |
| `snowplow-signals requires Python >=3.11` | Use `uv run …`, never system `python3`. `.python-version` pins 3.11. |
| `python3` fails with a `pyenv: version '3.11' is not installed` error | Same — `pyenv` intercepts `python3`. Use `uv run`. |
| `404 … Schema for event 'X' was not found or not in production` | The data structure is on DEV only. Promote it to **PROD**. |
| `422 Attribute key 'X' does not exist` | Custom keys are **not** created implicitly by a group referencing them. Publish keys *with* the groups (`ALL_OBJECTS`). |
| `422 Service can only reference attribute groups with the same attribute key` | One service per attribute key. |
| `400 Cannot update published attribute group` | Groups are immutable once published. Bump `version`; don't unpublish. |
| Attributes publish fine but stay empty | Wrong Iglu vendor/name, wrong **major version**, or the entity isn't attached to the events being aggregated. None of these raise an error. |
| Map is empty | IP lookup enrichment is off — it is not on by default. |
| Engaged time is always 0 | No page pings. Check `enableActivityTracking` is called *and* that `minimumVisitLength` hasn't been raised above typical dwell time. |
| Engaged time looks 3× too big | `HEARTBEAT_DELAY_SECONDS` disagrees with the tracker. Note Snowplow's "30/10" convention is `minimumVisitLength=30, heartbeatDelay=10` — **min-visit first**. |
| Poller refuses to start, logs "schema/definition drift" | An attribute has no matching DB column, or vice versa. Update `db/schema.sql`. This is deliberate — it prevents silent NULLs. |
| Template edits don't show | Flask is running without `--debug`, so Jinja caches templates. |
| Poller coverage far below 100% | macOS suspended it. See [Known gaps](#known-gaps). |

---

## Known gaps

* **Poller coverage on a laptop.** `caffeinate` prevents App Nap and idle sleep
  *on AC power only*. Unplugged or lid closed, macOS sleeps and polling stops;
  Signals cannot backdate, so those minutes are gone. Overnight this produced
  **11% coverage**. A `launchd` agent does not fix it either (it cannot run
  during sleep, and macOS TCC blocks LaunchAgents from reading `~/Documents`
  anyway — see `run_poller.sh`). The only gap-free option is running the poller
  and Postgres off the laptop.
* **100-article ceiling** on the catalog, from `unique_list`.
* **No exact distinct count** — `approx_count_distinct` only.
* **`category_count` silently drops** all but the top 100 values.
* Article metrics are keyed on `article_id` alone, so they are **not scoped by
  `app_id`**. Two app_ids serving the same article ID would merge upstream.
