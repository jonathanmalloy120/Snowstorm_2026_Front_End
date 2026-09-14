"""Snowplow Signals attribute definitions for Snowstorm 2026.

Two stream attribute groups:

  site_metrics    keyed on app_id      -- headline numbers + the article catalog
  article_metrics keyed on article_id  -- per-article metrics and metadata

Schemas (Console DEV, 1-0-0):
  com.snowplowanalytics/article       2-0-0 entity: title, author, article_id,
                                            category, published_at
  com.snowplowanalytics/article_view  1-0-0 event:  id, title, author
  com.snowplowanalytics/article_interaction 1-0-0 event: interaction_type,
                                            social_platform

IMPORTANT: only the article ENTITY carries article_id, so it must be attached
to page_view, page_ping and article_interaction (addGlobalContexts) or the
article_metrics group has no key and every attribute stays empty.

Design rules held throughout:
  * Rolling windows use `period=`, NEVER `ttl=`. ttl is expiry-on-inactivity
    whose timer resets on every event -- it is not a window.
  * Every counter sets default_value=0 so a quiet window reads 0 rather than
    None. The poller can then treat None as "poll failed" and chart a gap.
  * No arithmetic here. Raw ping counts are stored; engaged seconds are derived
    at read time so that changing tracker config does not invalidate history.
"""

from datetime import timedelta

from snowplow_signals import (
    AtomicProperty,
    Attribute,
    AttributeKey,
    Criteria,
    Criterion,
    EntityProperty,
    Event,
    EventProperty,
    PagePing,
    PageView,
    StreamAttributeGroup,
)

from signals import config

FIVE_MIN = timedelta(minutes=5)
ONE_HOUR = timedelta(hours=1)
SIX_HOURS = timedelta(hours=6)


def _article_prop(path: str) -> EntityProperty:
    return EntityProperty(
        vendor=config.ARTICLE_ENTITY_VENDOR,
        name=config.ARTICLE_ENTITY_NAME,
        major_version=config.ARTICLE_ENTITY_MAJOR_VERSION,
        path=path,
    )


def _article_view_event() -> Event:
    return Event(
        vendor=config.ARTICLE_VIEW_EVENT_VENDOR,
        name=config.ARTICLE_VIEW_EVENT_NAME,
        version=config.ARTICLE_VIEW_EVENT_VERSION,
    )


def _interaction_event() -> Event:
    return Event(
        vendor=config.INTERACTION_EVENT_VENDOR,
        name=config.INTERACTION_EVENT_NAME,
        version=config.INTERACTION_EVENT_VERSION,
    )


def _interaction_prop(path: str) -> EventProperty:
    major = int(config.INTERACTION_EVENT_VERSION.split("-")[0])
    return EventProperty(
        vendor=config.INTERACTION_EVENT_VENDOR,
        name=config.INTERACTION_EVENT_NAME,
        major_version=major,
        path=path,
    )


def _interaction_counter(kind: str, period: timedelta) -> Attribute:
    """Counter over article_interaction filtered to one interaction_type."""
    return Attribute(
        name=f"{kind}s_{_label(period)}",
        type="int32",
        aggregation="counter",
        events=[_interaction_event()],
        criteria=Criteria(
            all=[
                Criterion(
                    property=_interaction_prop(config.INTERACTION_TYPE_PATH),
                    operator="=",
                    value=kind,
                )
            ]
        ),
        period=period,
        default_value=0,
        description=f"'{kind}' interactions in the trailing {_label(period)}.",
    )


def _label(period: timedelta) -> str:
    return {FIVE_MIN: "5m", ONE_HOUR: "1h", SIX_HOURS: "6h"}[period]


# ---------------------------------------------------------------------------
# Attribute keys
# ---------------------------------------------------------------------------
app_id_key = AttributeKey(
    name="snowstorm_app_id",
    property=AtomicProperty(name="app_id"),
    owner=config.OWNER,
    description="Publisher site identifier; the tenant key for the dashboard.",
    ttl=timedelta(days=30),
)

article_id_key = AttributeKey(
    name="snowstorm_article_id",
    property=_article_prop("article_id"),
    owner=config.OWNER,
    description="Article identifier, read from the article entity.",
    ttl=timedelta(days=30),
)


# ---------------------------------------------------------------------------
# Group A -- site level, keyed on app_id
# ---------------------------------------------------------------------------
_site: list[Attribute] = [
    # The catalog. Signals has no way to enumerate keys, so this list IS the
    # enumeration the poller uses to fetch per-article metrics. Capped at 100
    # values by Signals, evicting least-recently-seen.
    Attribute(
        name="article_ids",
        type="string_list",
        aggregation="unique_list",
        property=_article_prop("article_id"),
        events=[_article_view_event()],
        description="Distinct article IDs seen on this site (max 100, LRU-evicted).",
    ),
]

for _p in (FIVE_MIN, ONE_HOUR, SIX_HOURS):
    _l = _label(_p)
    _site += [
        Attribute(
            name=f"page_views_{_l}", type="int32", aggregation="counter",
            events=[PageView()], period=_p, default_value=0,
            description=f"Page views in the trailing {_l}.",
        ),
        Attribute(
            name=f"article_views_{_l}", type="int32", aggregation="counter",
            events=[_article_view_event()], period=_p, default_value=0,
            description=f"Article views in the trailing {_l}.",
        ),
        Attribute(
            name=f"pings_{_l}", type="int32", aggregation="counter",
            events=[PagePing()], period=_p, default_value=0,
            description=f"Page pings in the trailing {_l}; engaged time derives from this at read time.",
        ),
    ]

for _p in (ONE_HOUR, SIX_HOURS):
    _l = _label(_p)
    _site += [
        # HyperLogLog, ~1% error. NOT summable across app_ids.
        Attribute(
            name=f"unique_visitors_{_l}", type="int32", aggregation="approx_count_distinct",
            property=AtomicProperty(name="domain_userid"), events=[PageView()],
            period=_p, default_value=0,
            description=f"Approximate distinct visitors in the trailing {_l} (HLL, ~1% error).",
        ),
        Attribute(
            name=f"country_counts_{_l}", type="dict", aggregation="category_count",
            property=AtomicProperty(name="geo_country"), events=[PageView()], period=_p,
            description=f"Page views by country in the trailing {_l} (top 100).",
        ),
        Attribute(
            name=f"social_counts_{_l}", type="dict", aggregation="category_count",
            property=_interaction_prop(config.INTERACTION_TYPE_PATH),
            events=[_interaction_event()], period=_p,
            description=f"Interactions by type in the trailing {_l}.",
        ),
    ]

_site += [
    Attribute(
        name="category_counts_1h", type="dict", aggregation="category_count",
        property=_article_prop("category"), events=[_article_view_event()],
        period=ONE_HOUR,
        description="Article views by category (section) in the trailing hour.",
    ),
    Attribute(
        name="share_platforms_1h", type="dict", aggregation="category_count",
        property=_interaction_prop(config.SOCIAL_PLATFORM_PATH),
        events=[_interaction_event()],
        criteria=Criteria(all=[
            Criterion(property=_interaction_prop(config.INTERACTION_TYPE_PATH),
                      operator="=", value=config.SHARE_INTERACTION)
        ]),
        period=ONE_HOUR,
        description="Shares by social platform in the trailing hour.",
    ),
]

site_metrics = StreamAttributeGroup(
    name="site_metrics", version=1, owner=config.OWNER,
    attribute_key=app_id_key, attributes=_site,
    description="Site-wide editorial metrics and the article catalog, keyed on app_id.",
)


# ---------------------------------------------------------------------------
# Group B -- article level, keyed on article_id
# ---------------------------------------------------------------------------
# The entity carries only title and author. The article's URL is recovered from
# the page_url atomic field, which is better than a slug anyway -- it is the
# real link the dashboard needs for "top posts with links".
_article: list[Attribute] = [
    Attribute(
        name="title", type="string", aggregation="last",
        property=_article_prop("title"), events=[_article_view_event()],
        description="Most recent title seen for this article.",
    ),
    Attribute(
        name="author", type="string", aggregation="last",
        property=_article_prop("author"), events=[_article_view_event()],
        description="Most recent author seen for this article.",
    ),
    Attribute(
        name="page_url", type="string", aggregation="last",
        property=AtomicProperty(name="page_url"), events=[_article_view_event()],
        description="Most recent URL this article was served at.",
    ),
    Attribute(
        name="category", type="string", aggregation="last",
        property=_article_prop("category"), events=[_article_view_event()],
        description="Most recent category (section) seen for this article.",
    ),
    Attribute(
        name="published_at", type="string", aggregation="last",
        property=_article_prop("published_at"), events=[_article_view_event()],
        description="Publication timestamp (date-time) carried on the entity.",
    ),
]

for _p in (FIVE_MIN, ONE_HOUR):
    _l = _label(_p)
    _article += [
        Attribute(
            name=f"views_{_l}", type="int32", aggregation="counter",
            events=[_article_view_event()], period=_p, default_value=0,
            description=f"Views of this article in the trailing {_l}.",
        ),
        Attribute(
            name=f"pings_{_l}", type="int32", aggregation="counter",
            events=[PagePing()], period=_p, default_value=0,
            description=f"Page pings on this article in the trailing {_l}.",
        ),
    ]

_article += [
    Attribute(
        name="unique_readers_1h", type="int32", aggregation="approx_count_distinct",
        property=AtomicProperty(name="domain_userid"), events=[_article_view_event()],
        period=ONE_HOUR, default_value=0,
        description="Approximate distinct readers in the trailing hour (HLL, ~1% error).",
    ),
    Attribute(
        name="country_counts_1h", type="dict", aggregation="category_count",
        property=AtomicProperty(name="geo_country"), events=[_article_view_event()],
        period=ONE_HOUR,
        description="Views of this article by country in the trailing hour.",
    ),
]

# like / bookmark / favorite / share, per the interaction_type enum.
_article += [_interaction_counter(kind, ONE_HOUR) for kind in config.INTERACTION_TYPES]

_article += [
    Attribute(
        name="time_since_last", type="double", aggregation="time_since_last",
        time_unit="s", events=[_article_view_event(), PagePing()],
        description="Seconds since the last event on this article.",
    ),
]

article_metrics = StreamAttributeGroup(
    name="article_metrics", version=1, owner=config.OWNER,
    attribute_key=article_id_key, attributes=_article,
    description="Per-article editorial metrics and metadata, keyed on article_id.",
)


ALL_GROUPS = [site_metrics, article_metrics]
ALL_KEYS = [app_id_key, article_id_key]

# Custom attribute keys must exist before the groups that reference them.
# RegistryClient.create_or_update() publishes keys first, but only for the
# objects it is handed -- so keys must be in this list, not just the groups.
ALL_OBJECTS = ALL_KEYS + ALL_GROUPS
