"""Central configuration for Signals definitions and the snapshot poller.

Everything that couples us to another team's work lives here, so that a schema
change is a one-file edit.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Iglu coordinates -- confirmed against Console DEV on 2026-09-14.
#
#   iglu:com.snowplowanalytics/article/jsonschema/2-0-0             (entity)
#       title, author, article_id, category, published_at
#   iglu:com.snowplowanalytics/article_view/jsonschema/1-0-0        (event)
#       id, title, author
#   iglu:com.snowplowanalytics/article_interaction/jsonschema/1-0-0 (event)
#       interaction_type [like|bookmark|favorite|share], social_platform
#
# NOTE: only the ENTITY carries article_id. It must therefore be attached to
# page_view, page_ping and article_interaction (via addGlobalContexts) or the
# article_metrics group has no attribute key and populates with nothing.
# ---------------------------------------------------------------------------
ARTICLE_ENTITY_VENDOR = os.getenv("ARTICLE_ENTITY_VENDOR", "com.snowplowanalytics")
ARTICLE_ENTITY_NAME = os.getenv("ARTICLE_ENTITY_NAME", "article")
ARTICLE_ENTITY_MAJOR_VERSION = int(os.getenv("ARTICLE_ENTITY_MAJOR_VERSION", "2"))

# Purpose-built article view event: fires once per article, unlike page_view
# which also fires on the homepage and category pages.
ARTICLE_VIEW_EVENT_VENDOR = os.getenv("ARTICLE_VIEW_EVENT_VENDOR", "com.snowplowanalytics")
ARTICLE_VIEW_EVENT_NAME = os.getenv("ARTICLE_VIEW_EVENT_NAME", "article_view")
ARTICLE_VIEW_EVENT_VERSION = os.getenv("ARTICLE_VIEW_EVENT_VERSION", "1-0-0")

INTERACTION_EVENT_VENDOR = os.getenv("INTERACTION_EVENT_VENDOR", "com.snowplowanalytics")
INTERACTION_EVENT_NAME = os.getenv("INTERACTION_EVENT_NAME", "article_interaction")
INTERACTION_EVENT_VERSION = os.getenv("INTERACTION_EVENT_VERSION", "1-0-0")

INTERACTION_TYPE_PATH = os.getenv("INTERACTION_TYPE_PATH", "interaction_type")
INTERACTION_TYPES = [
    t.strip()
    for t in os.getenv("INTERACTION_TYPES", "like,bookmark,favorite,share").split(",")
    if t.strip()
]
SOCIAL_PLATFORM_PATH = os.getenv("SOCIAL_PLATFORM_PATH", "social_platform")
SHARE_INTERACTION = os.getenv("SHARE_INTERACTION", "share")

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
APP_IDS = [a.strip() for a in os.getenv("APP_IDS", "snowstorm-2026-publisher").split(",") if a.strip()]

POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
# Per-request identifier cap is undocumented; chunk conservatively.
ID_CHUNK_SIZE = int(os.getenv("ID_CHUNK_SIZE", "50"))

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://snowstorm:snowstorm@localhost:5433/snowstorm"
)

# Tracker activity-tracking config. Engaged seconds are derived at READ time as
#   (pings - 1) * HEARTBEAT_DELAY_SECONDS + MINIMUM_VISIT_LENGTH_SECONDS
#
# These MUST match enableActivityTracking() in the publisher's lib/snowplow.ts,
# currently { minimumVisitLength: 10, heartbeatDelay: 10 }. Note that the
# conventional Snowplow example "30/10" means minimumVisitLength=30 and
# heartbeatDelay=10 -- reading it as heartbeat-first overstates engaged time by
# 3x. The browser tracker has NO defaults for these: if either is missing or
# non-integer it silently disables activity tracking entirely.
HEARTBEAT_DELAY_SECONDS = int(os.getenv("HEARTBEAT_DELAY_SECONDS", "10"))
MINIMUM_VISIT_LENGTH_SECONDS = int(os.getenv("MINIMUM_VISIT_LENGTH_SECONDS", "10"))
