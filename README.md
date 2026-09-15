# Snowstorm 2026 — Signals for Editorial Analytics

A live editorial dashboard — what people are reading right now, for how long,
and from where — built on **Snowplow Signals**.

```
publisher site ─▶ pipeline ─▶ Signals ─▶ poller (60s) ─▶ Postgres ─▶ dashboard
                              │                          │
                        "what's true now"            "what was true then"
```

Signals answers *what is true right now*, in milliseconds. What it cannot do is
tell you what was true an hour ago — it stores current values only. So a small
program (the **poller**) takes a snapshot of those values every 60 seconds and
files them in a database. That is what turns "right now" into a chart you can
look back through. Every number on the dashboard came from Signals.

The fake news site that generates the traffic lives in a separate repo:
[Snowstorm_2026_Publisher](https://github.com/jonathanmalloy120/Snowstorm_2026_Publisher).

---



# Getting it running

Seven steps, roughly 15 minutes. Do them in order — a few genuinely depend on
the ones before.

## Before you start

You'll need three things installed. Check each with the command shown; if you
get a version number back, you're fine.


| What                        | Check it's there                                                            | What it's for                                                                                                                        |
| --------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| **Docker**                  | `docker --version`                                                          | Runs the database, so you don't have to install one                                                                                  |
| **uv**                      | `uv --version`                                                              | Runs Python. This project needs Python 3.11, and `uv` fetches the right version itself so whatever is on your machine doesn't matter |
| **Snowplow Console access** | open [console.snowplowanalytics.com](https://console.snowplowanalytics.com) | Where the pipeline and Signals live                                                                                                  |


Missing `uv`? `curl -LsSf https://astral.sh/uv/install.sh | sh`.
Missing Docker? Install Docker Desktop.

---



## 1. Give the project its credentials

**What you're doing:** creating a private settings file so the project can talk
to Snowplow.

```bash
cp .env.example .env
```

Now open `.env` in any text editor and fill in four values from
**Console → Signals → Overview**:


| In the file          | What to paste                                                            |
| -------------------- | ------------------------------------------------------------------------ |
| `SIGNALS_API_URL`    | The Signals address, like `https://abc123.signals.snowplowanalytics.com` |
| `SIGNALS_API_KEY`    | Your Console API key                                                     |
| `SIGNALS_API_KEY_ID` | The ID shown next to that key                                            |
| `SIGNALS_ORG_ID`     | The long code in your Console web address                                |


**Why it matters:** `.env` is deliberately never committed to git, because it
holds a live key. `.env.example` is the blank template.

> ⚠️ **The** `SIGNALS_API_URL` **in the template is a placeholder, not a real
> address.** If you leave it, everything else will appear to work and then fail
> confusingly. Replace it.

**How to tell it worked:**

```bash
uv run python -c "from signals import config; print(config.SIGNALS_API_URL)"
```

You should see your real address, with no `<id>` in it.

---



## 2. Start the database

**What you're doing:** starting a Postgres database in a container.

```bash
docker compose up -d
```

**Why it matters:** this is where the 60-second snapshots are filed. Without
it the poller has nowhere to write and the dashboard has nothing to read.

It runs on port **5433** rather than the usual 5432, because 5432 is often
already taken by another project. The tables are created automatically the
first time it starts.

**How to tell it worked:**

```bash
docker ps --filter name=snowstorm-db
```

You want to see `Up … (healthy)`.

---



## 3. Install the Python dependencies

```bash
uv sync
```

**Why it matters:** downloads the Snowplow SDK, the database driver, Flask and
the charting library. Takes under a minute, and only needs doing once.

**How to tell it worked:** no error, and a `.venv` folder appears.

---



## 4. Switch on the Snowplow side

**What you're doing:** three settings in Console. None of them live in this
repo, and each one fails *quietly* if missed — you get an empty dashboard
rather than an error message, which is why they're worth checking up front.


| #   | In Console                                                     | Why it matters if missed                 |
| --- | -------------------------------------------------------------- | ---------------------------------------- |
| 1   | **Signals → Enable**                                           | Nothing aggregates at all                |
| 2   | **Pipelines → Enrichments → IP lookup (MaxMind)**, switched on | No country data, so the map stays blank. |


---



## 5. Publish the attribute definitions

**What you're doing:** telling Signals what to count — page views, reading
time, articles, countries, and so on.

Preview first, which changes nothing:

```bash
uv run python -m signals.publish --dry-run
```

Then do it for real:

```bash
uv run python -m signals.publish
```

**Why it matters, and why order matters:** Signals starts counting *from the
moment you publish* and **cannot go back and fill in the past**. Any traffic
before this point is lost forever. So publish before you invite people to click
around, not after.

**How to tell it worked:** it ends with a summary like

```
published: 2 keys, 2 groups, 2 services
```

Safe to run again. On a second run you'll see `unchanged: 2 groups (already published; bump version to change)` — that's normal, not a failure. Definitions
are frozen once live so that history stays consistent; changing one means
publishing a new version of it.

---



## 6. Start the poller

**What you're doing:** starting the background program that copies Signals'
current numbers into the database every 60 seconds.

```bash
nohup ./run_poller.sh >> poller.log 2>&1 &
```

**Why it matters:** this is the piece that creates history. Nothing else does.
While it isn't running, time passes unrecorded, and — because Signals can't
look backwards — those minutes can never be recovered.

That command looks odd for a reason: `nohup` and `&` let it keep running after
you close the terminal, and `run_poller.sh` wraps it in `caffeinate` so macOS
doesn't quietly suspend it while you're not looking.

**How to tell it worked:**

```bash
tail -f poller.log | grep -v httpx
```

Within a minute you should see a line like
`wrote 1 site row + 14 article rows`. Press `Ctrl-C` to stop watching — that
stops the *watching*, not the poller.

> 💡 **Leave the laptop plugged in and the lid open.** A sleeping Mac runs
> nothing at all, and every minute asleep is a hole in the charts that can't be
> filled in later.

---



## 7. Open the dashboard

```bash
uv run flask --app dashboard.app run --port 5000 --debug
```

Then open **[http://127.0.0.1:5000](http://127.0.0.1:5000)** in your browser.

**Why** `--debug`**:** it makes the page pick up edits to the design without
needing a restart. Leave it off and you'll wonder why your changes aren't
showing.

The page refreshes itself every 30 seconds, so you can leave it open.

---



## Is it actually working?

If something looks wrong, these three checks tell you *where* the problem is,
which is usually the hard part. Run them in order and stop at the first one
that looks wrong.

**Check 1 — is Signals counting anything?**

```bash
uv run python -c "
from poller.reader import SignalsReader
from signals import config
from signals.definitions import site_metrics
r = SignalsReader(config.SIGNALS_API_URL, config.SIGNALS_API_KEY,
                  config.SIGNALS_API_KEY_ID, config.SIGNALS_ORG_ID)
print(r.read_one(site_metrics.name, site_metrics.version,
                 [a.name for a in site_metrics.attributes],
                 site_metrics.attribute_key.name, config.APP_IDS[0]))"
```

Numbers coming back? Signals is fine — go to check 2. All zeros and `None`?
The problem is *upstream*: either nobody has browsed the site recently, or the
tracking/enrichment/schema setup in step 4 isn't right.

**Check 2 — is the poller writing?**

```bash
PGPASSWORD=snowstorm psql -h localhost -p 5433 -U snowstorm -d snowstorm -c \
  "SELECT count(*) ticks, (now()-max(snapshot_ts))::interval(0) AS stale FROM site_snapshots;"
```

`stale` should be under a minute. If it's hours, the poller stopped — restart
it (step 6).

**Check 3 — how complete is the history?**

```bash
PGPASSWORD=snowstorm psql -h localhost -p 5433 -U snowstorm -d snowstorm -c \
  "SELECT round(100.0*count(*)/360) || '%' AS coverage_6h
   FROM site_snapshots WHERE snapshot_ts > now() - interval '6 hours';"
```

Near 100% is healthy. A low number means the poller was stopped or the laptop
slept; the dashboard shows this figure in its header too, so sparse charts are
never mistaken for broken ones.

---



# Reading the dashboard

The page is split into three labelled zones, because they answer different
questions:

- **Right now** — current values straight from Signals, each over its own fixed
window. Not affected by the range control.
- **Over time** — the only panels the **1h / 6h / 24h** control changes. These
carry a blue rail and a blue `Last Nh` badge. This is the history that
Signals alone cannot give you.
- **Breakdowns** — where readers are, which sections, which articles. Fixed at
the trailing hour.

Two things worth knowing when reading any number:

- **Gaps in a line are real.** Where the poller wasn't running, the line breaks
rather than being drawn straight across. That's deliberate: a smooth line
through unmeasured time would be a fabrication.
- **Values are "in the last N minutes", not running totals.** "12" on the
traffic chart means twelve views in the preceding five minutes, not twelve
ever. Don't subtract one point from another.
- Visitor counts are **approximate** by design (±1%), which is what makes them
fast.

---



# How it works

**Schemas it depends on**


| Schema                                      | Version   | Fields                                                      |
| ------------------------------------------- | --------- | ----------------------------------------------------------- |
| `com.snowplowanalytics/article` (entity)    | **2-0-0** | `title`, `author`, `article_id`, `category`, `published_at` |
| `com.snowplowanalytics/article_view`        | 1-0-0     | `id`, `title`, `author`                                     |
| `com.snowplowanalytics/article_interaction` | 1-0-0     | `interaction_type`, `social_platform`                       |


**Only the entity carries** `article_id`, so it must be attached to
`page_view`, `page_ping` *and* `article_interaction` via `addGlobalContexts` in
the publisher. Without that, `article_metrics` has no attribute key and every
one of its attributes stays empty, with no error anywhere.



**The two attribute groups**

`site_metrics` (18 attributes), keyed on `app_id` — `article_ids` (the
catalog), page views, article views and pings at 5m/1h/6h, unique visitors,
country / category / social breakdowns, share-by-platform.

`article_metrics` (16 attributes), keyed on `article_id` — `title`,
`author`, `page_url`, `category`, `published_at` (all `last()`), views and
pings at 5m/1h, unique readers, country breakdown,
like/bookmark/favorite/share counters, `time_since_last`.



**How the poller finds articles without a CMS**

Signals has **no scan or list API** — you can only read keys you already know.
So `article_ids` on the site group *is* the enumeration: a `unique_list` of
every article ID seen. The poller reads it, then batch-reads per-article
metrics for exactly those IDs. No CMS integration anywhere, which was a goal of
the project.

`unique_list` is capped at **100 values**, evicting least-recently-seen, so the
catalog is really "the 100 most recently read articles".



**Services**

`editorial_site` (app_id) and `editorial_articles` (article_id). Two rather
than one because *a service can only reference groups sharing a single
attribute key*. Groups are referenced by versioned link, not by value, because
a published group is immutable.



**Where the code lives**


| Path                     | What                                                                        |
| ------------------------ | --------------------------------------------------------------------------- |
| `signals/config.py`      | Every cross-team coupling: Iglu coordinates, credentials, tracker constants |
| `signals/definitions.py` | The two attribute groups, two keys, two services                            |
| `signals/publish.py`     | Publishes to Signals; `--dry-run`, `--only`                                 |
| `poller/reader.py`       | Batch reader — the SDK reads one identifier at a time                       |
| `poller/run.py`          | The 60s snapshot loop; refuses to start on schema drift                     |
| `db/schema.sql`          | `site_snapshots` + `article_snapshots`                                      |
| `dashboard/queries.py`   | Read layer; derives engaged time                                            |
| `dashboard/figures.py`   | Plotly figures, built server-side                                           |
| `dashboard/app.py`       | Flask app + `/api/data` for the 30s auto-refresh                            |
| `run_poller.sh`          | Poller wrapped in `caffeinate`                                              |




---



# Rules the code depends on

- Rolling windows use `period=`**, never** `ttl=`. `ttl` is
expiry-on-inactivity whose timer resets on every event — it is not a window.
- Every stored value is a **trailing gauge** over its window, not a disjoint
bucket. **Never diff rows.**
- A **missing row** means the poller was not running. Charts break the line
there rather than interpolating across unmeasured time.
- A `NULL` **value inside a row** means the window was empty — i.e. **zero**,
not a failed poll. Signals returns `None` rather than `default_value` when a
rolling window contains no events at all.
- **No arithmetic is stored.** Engaged seconds are derived at read time as
`(pings - 1) * heartbeat + min_visit_length`, so retuning the tracker
reinterprets history instead of invalidating it. `HEARTBEAT_DELAY_SECONDS`
and `MINIMUM_VISIT_LENGTH_SECONDS` in `.env` **must** match
`enableActivityTracking()` in the publisher — nothing enforces this.
- Unique visitors/readers are **approximate** (HyperLogLog, ~1% error) and
**cannot be summed across app_ids**.



# Troubleshooting

Every entry below is a failure this project actually hit.


| Symptom                                                                       | Cause / fix                                                                                                                                                 |
| ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Bind for 0.0.0.0:5432 failed: port is already allocated`                     | Another Postgres container. We use **5433**; check `docker ps`.                                                                                             |
| `snowplow-signals requires Python >=3.11`                                     | Use `uv run …`, never system `python3`.                                                                                                                     |
| `pyenv: version '3.11' is not installed`                                      | Same — `pyenv` intercepts `python3`. Use `uv run`.                                                                                                          |
| `404 … Schema for event 'X' was not found or not in production`               | The data structure is on Dev only. Promote it to **Production** (step 4).                                                                                   |
| `422 Attribute key 'X' does not exist`                                        | Custom keys are **not** created implicitly by a group referencing them. Publish keys *with* the groups.                                                     |
| `422 Service can only reference attribute groups with the same attribute key` | One service per attribute key.                                                                                                                              |
| `400 Cannot update published attribute group`                                 | Groups are immutable once published. Bump `version`; don't unpublish.                                                                                       |
| Publishes fine, but every number stays empty                                  | Wrong Iglu vendor/name, wrong **major version**, or the entity isn't attached to the events being aggregated. None of these raise an error.                 |
| Map is blank                                                                  | IP lookup enrichment is off — it is not on by default (step 4).                                                                                             |
| Engaged time is always 0                                                      | No page pings. Check `enableActivityTracking` is called, and that `minimumVisitLength` isn't above typical dwell time.                                      |
| Engaged time looks 3× too big                                                 | `HEARTBEAT_DELAY_SECONDS` disagrees with the tracker. Snowplow's "30/10" convention means `minimumVisitLength=30, heartbeatDelay=10` — **min-visit first**. |
| Poller won't start, logs "schema/definition drift"                            | An attribute has no matching DB column, or vice versa. Update `db/schema.sql`. Deliberate — it prevents silent NULLs.                                       |
| Design edits don't show up                                                    | Flask is running without `--debug`, so templates are cached.                                                                                                |
| Coverage far below 100%                                                       | macOS suspended the poller. See Known gaps.                                                                                                                 |


---



# Known gaps

- **Poller coverage on a laptop.** `caffeinate` prevents App Nap and idle sleep
*on AC power only*. Unplugged or lid closed, macOS sleeps and polling stops;
Signals cannot backdate, so those minutes are gone. Overnight this produced
**11% coverage**. A `launchd` agent does not fix it either — it cannot run
during sleep, and macOS TCC blocks LaunchAgents from reading `~/Documents`
anyway (see `run_poller.sh`). The only gap-free option is running the poller
and Postgres off the laptop.
- **100-article ceiling** on the catalog, from `unique_list`.
- **No exact distinct count** — `approx_count_distinct` only.
- `category_count` **silently drops** all but the top 100 values.
- Article metrics are keyed on `article_id` alone, so they are **not scoped by**
`app_id`. Two app_ids serving the same article ID would merge upstream.

