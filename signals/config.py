"""Central configuration for Signals definitions and the snapshot poller.

Everything that depends on work owned by other people lives here, so that when
the publisher's Iglu schemas land, this is the ONLY file that needs editing.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Iglu coordinates -- OWNED BY THE PUBLISHER REPO, NOT YET PUBLISHED.
#
# These are placeholders inferred from types/analytics.ts in the publisher repo
# (ArticleContext: article_id, article_slug, headline, category, author, tags,
# published_at). Confirm against the real data structures before publishing --
# a wrong vendor/name silently yields attributes that never populate.
# ---------------------------------------------------------------------------
ARTICLE_ENTITY_VENDOR = os.getenv("ARTICLE_ENTITY_VENDOR", "com.snowstorm")
ARTICLE_ENTITY_NAME = os.getenv("ARTICLE_ENTITY_NAME", "article")
ARTICLE_ENTITY_MAJOR_VERSION = int(os.getenv("ARTICLE_ENTITY_MAJOR_VERSION", "1"))

INTERACTION_EVENT_VENDOR = os.getenv("INTERACTION_EVENT_VENDOR", "com.snowstorm")
INTERACTION_EVENT_NAME = os.getenv("INTERACTION_EVENT_NAME", "content_interaction")
INTERACTION_EVENT_VERSION = os.getenv("INTERACTION_EVENT_VERSION", "1-0-0")

# Field on the interaction event that distinguishes share/bookmark/like.
INTERACTION_TYPE_PATH = os.getenv("INTERACTION_TYPE_PATH", "interaction_type")
INTERACTION_SHARE = os.getenv("INTERACTION_SHARE", "share")
INTERACTION_BOOKMARK = os.getenv("INTERACTION_BOOKMARK", "bookmark")
INTERACTION_LIKE = os.getenv("INTERACTION_LIKE", "like")

OWNER = os.getenv("SIGNALS_OWNER", "jon.malloy@snowplowanalytics.com")

# ---------------------------------------------------------------------------
# Signals connection (Console > Signals > Overview)
# ---------------------------------------------------------------------------
SIGNALS_API_URL = os.getenv("SIGNALS_API_URL", "")
SIGNALS_API_KEY = os.getenv("SIGNALS_API_KEY", "")
SIGNALS_API_KEY_ID = os.getenv("SIGNALS_API_KEY_ID", "")
SIGNALS_ORG_ID = os.getenv("SIGNALS_ORG_ID", "")

# ---------------------------------------------------------------------------
# Poller
# ---------------------------------------------------------------------------
# app_ids whose catalogs we poll. Group A is keyed on app_id.
APP_IDS = [a.strip() for a in os.getenv("APP_IDS", "snowstorm-2026-publisher").split(",") if a.strip()]

POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
# Per-request identifier cap is undocumented; chunk conservatively.
ID_CHUNK_SIZE = int(os.getenv("ID_CHUNK_SIZE", "50"))

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://snowstorm:snowstorm@localhost:5433/snowstorm"
)

# Tracker activity-tracking config. Engaged seconds are derived at READ time as
#   (pings - 1) * HEARTBEAT_DELAY_SECONDS + MINIMUM_VISIT_LENGTH_SECONDS
# These MUST match enableActivityTracking() in the publisher repo.
HEARTBEAT_DELAY_SECONDS = int(os.getenv("HEARTBEAT_DELAY_SECONDS", "30"))
MINIMUM_VISIT_LENGTH_SECONDS = int(os.getenv("MINIMUM_VISIT_LENGTH_SECONDS", "10"))
