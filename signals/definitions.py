"""Snowplow Signals attribute definitions for Snowstorm 2026.

Two stream attribute groups:

  site_metrics    keyed on app_id      -- headline numbers + the article catalog
  article_metrics keyed on article_id  -- per-article metrics and metadata

Design rules held throughout (agreed in planning):
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
    PagePing,
    PageView,
    StreamAttributeGroup,
)

from signals import config

FIVE_MIN = timedelta(minutes=5)
ONE_HOUR = timedelta(hours=1)
SIX_HOURS = timedelta(hours=6)


def _article_prop(path: str) -> EntityProperty:
    """A field on the publisher's article entity."""
    return EntityProperty(
        vendor=config.ARTICLE_ENTITY_VENDOR,
        name=config.ARTICLE_ENTITY_NAME,
        major_version=config.ARTICLE_ENTITY_MAJOR_VERSION,
        path=path,
    )


def _interaction_event() -> Event:
    return Event(
        vendor=config.INTERACTION_EVENT_VENDOR,
        name=config.INTERACTION_EVENT_NAME,
        version=config.INTERACTION_EVENT_VERSION,
    )


def _interaction_type_prop() -> EntityProperty:
    """interaction_type lives on the interaction event's own entity payload."""
    return EntityProperty(
        vendor=config.INTERACTION_EVENT_VENDOR,
        name=config.INTERACTION_EVENT_NAME,
        major_version=1,
        path=config.INTERACTION_TYPE_PATH,
    )


def _interaction_counter(name: str, value: str, period: timedelta) -> Attribute:
    """Counter over interaction events filtered to one interaction_type."""
    return Attribute(
        name=name,
        type="int32",
        aggregation="counter",
        events=[_interaction_event()],
        criteria=Criteria(
            all=[Criterion(property=_interaction_type_prop(), operator="=", value=value)]
        ),
        period=period,
        default_value=0,
        description=f"{value} interactions in the trailing {period}.",
    )


# ---------------------------------------------------------------------------
# Attribute keys
# ---------------------------------------------------------------------------
# app_id is not one of the four built-in keys, so it is defined explicitly.
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
    description="Article identifier, read from the publisher's article entity.",
    ttl=timedelta(days=30),
)


# ---------------------------------------------------------------------------
# Group A -- site level, keyed on app_id
# ---------------------------------------------------------------------------
_site_attributes: list[Attribute] = [
    # The catalog. Signals caps unique_list at 100 values, evicting
    # least-recently-seen -- so this is "the 100 most recently read articles",
    # which is also the set the poller will fetch per-article metrics for.
    Attribute(
        name="article_ids",
        type="string_list",
        aggregation="unique_list",
        property=_article_prop("article_id"),
        events=[PageView()],
        description="Distinct article IDs seen on this site (max 100, LRU-evicted).",
    ),
]

for _label, _period in (("5m", FIVE_MIN), ("1h", ONE_HOUR), ("6h", SIX_HOURS)):
    _site_attributes += [
        Attribute(
            name=f"page_views_{_label}",
            type="int32",
            aggregation="counter",
            events=[PageView()],
            period=_period,
            default_value=0,
            description=f"Page views in the trailing {_label}.",
        ),
        Attribute(
            name=f"pings_{_label}",
            type="int32",
            aggregation="counter",
            events=[PagePing()],
            period=_period,
            default_value=0,
            description=f"Page pings in the trailing {_label}; engaged time is derived from this at read time.",
        ),
    ]

for _label, _period in (("1h", ONE_HOUR), ("6h", SIX_HOURS)):
    _site_attributes += [
        # HyperLogLog, ~1% error. Not summable across app_ids.
        Attribute(
            name=f"unique_visitors_{_label}",
            type="int32",
            aggregation="approx_count_distinct",
            property=AtomicProperty(name="domain_userid"),
            events=[PageView()],
            period=_period,
            default_value=0,
            description=f"Approximate distinct visitors in the trailing {_label} (HLL, ~1% error).",
        ),
        Attribute(
            name=f"country_counts_{_label}",
            type="dict",
            aggregation="category_count",
            property=AtomicProperty(name="geo_country"),
            events=[PageView()],
            period=_period,
            description=f"Page views by country in the trailing {_label} (top 100 countries).",
        ),
        Attribute(
            name=f"social_counts_{_label}",
            type="dict",
            aggregation="category_count",
            property=_interaction_type_prop(),
            events=[_interaction_event()],
            period=_period,
            description=f"Interaction counts by type in the trailing {_label}.",
        ),
    ]

site_metrics = StreamAttributeGroup(
    name="site_metrics",
    version=1,
    owner=config.OWNER,
    attribute_key=app_id_key,
    attributes=_site_attributes,
    description="Site-wide editorial metrics and the article catalog, keyed on app_id.",
)


# ---------------------------------------------------------------------------
# Group B -- article level, keyed on article_id
# ---------------------------------------------------------------------------
_article_attributes: list[Attribute] = [
    # Metadata carried on the article entity. last() keeps the most recent
    # value, so an edited headline follows through without a CMS integration.
    Attribute(
        name=field,
        type="string",
        aggregation="last",
        property=_article_prop(field),
        events=[PageView()],
        description=f"Most recent {field} seen for this article.",
    )
    for field in ("headline", "article_slug", "category", "author", "published_at")
]

for _label, _period in (("5m", FIVE_MIN), ("1h", ONE_HOUR)):
    _article_attributes += [
        Attribute(
            name=f"views_{_label}",
            type="int32",
            aggregation="counter",
            events=[PageView()],
            period=_period,
            default_value=0,
            description=f"Views of this article in the trailing {_label}.",
        ),
        Attribute(
            name=f"pings_{_label}",
            type="int32",
            aggregation="counter",
            events=[PagePing()],
            period=_period,
            default_value=0,
            description=f"Page pings on this article in the trailing {_label}.",
        ),
    ]

_article_attributes += [
    Attribute(
        name="unique_readers_1h",
        type="int32",
        aggregation="approx_count_distinct",
        property=AtomicProperty(name="domain_userid"),
        events=[PageView()],
        period=ONE_HOUR,
        default_value=0,
        description="Approximate distinct readers in the trailing hour (HLL, ~1% error).",
    ),
    Attribute(
        name="country_counts_1h",
        type="dict",
        aggregation="category_count",
        property=AtomicProperty(name="geo_country"),
        events=[PageView()],
        period=ONE_HOUR,
        description="Views of this article by country in the trailing hour.",
    ),
    _interaction_counter("shares_1h", config.INTERACTION_SHARE, ONE_HOUR),
    _interaction_counter("bookmarks_1h", config.INTERACTION_BOOKMARK, ONE_HOUR),
    _interaction_counter("likes_1h", config.INTERACTION_LIKE, ONE_HOUR),
    # Recomputed by Signals at read time -- a free "hot right now" signal.
    Attribute(
        name="time_since_last",
        type="double",
        aggregation="time_since_last",
        time_unit="s",
        events=[PageView(), PagePing()],
        description="Seconds since the last event on this article.",
    ),
]

article_metrics = StreamAttributeGroup(
    name="article_metrics",
    version=1,
    owner=config.OWNER,
    attribute_key=article_id_key,
    attributes=_article_attributes,
    description="Per-article editorial metrics and metadata, keyed on article_id.",
)


ALL_GROUPS = [site_metrics, article_metrics]
