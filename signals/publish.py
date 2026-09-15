"""Publish (or test) the attribute definitions against Signals.

  uv run python -m signals.publish --dry-run   # print what would be published
  uv run python -m signals.publish             # publish for real

Signals does NOT backdate: attributes are calculated only from the moment they
are published, so publish before generating any traffic you care about.
"""

import argparse
import sys

from snowplow_signals import AttributeKey, Service, Signals
from snowplow_signals.api_client import SignalsAPIError

from signals import config
from signals.definitions import ALL_GROUPS, ALL_KEYS, ALL_OBJECTS, ALL_SERVICES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print definitions, publish nothing")
    ap.add_argument(
        "--only", choices=["all", "keys", "groups", "services"], default="all",
        help="publish a subset. Published groups are IMMUTABLE, so re-sending "
             "them fails with 'Cannot update published attribute group' -- use "
             "--only services to add or change a service without touching them. "
             "To change a published group's attributes, bump its version.",
    )
    args = ap.parse_args()

    for key in ALL_KEYS:
        print(f"attribute key: {key.name}")

    for group in ALL_GROUPS:
        print(f"\n{group.name} v{group.version}  key={group.attribute_key.name}")
        for a in group.attributes:
            window = f"period={a.period}" if a.period else "lifetime"
            print(f"   {a.name:<22} {a.aggregation:<22} {window}")

    for svc in ALL_SERVICES:
        names = ", ".join(g.name for g in (svc.attribute_groups or []))
        print(f"\nservice: {svc.name}  groups=[{names}]")

    if args.dry_run:
        print("\n[dry run] nothing published")
        return

    missing = [
        n for n in ("SIGNALS_API_URL", "SIGNALS_API_KEY", "SIGNALS_API_KEY_ID", "SIGNALS_ORG_ID")
        if not getattr(config, n)
    ]
    if missing:
        sys.exit(f"missing required settings: {', '.join(missing)} (see .env.example)")

    signals = Signals(
        api_url=config.SIGNALS_API_URL,
        api_key=config.SIGNALS_API_KEY,
        api_key_id=config.SIGNALS_API_KEY_ID,
        org_id=config.SIGNALS_ORG_ID,
    )
    targets = {
        "all": ALL_OBJECTS,
        "keys": ALL_KEYS,
        "groups": ALL_GROUPS,
        "services": ALL_SERVICES,
    }[args.only]
    # Published attribute groups are immutable, so re-running this is expected
    # to hit "already exists" / "Cannot update published attribute group" for
    # anything unchanged. That is not an error: publish object by object and
    # report those as unchanged, so the command is safe to re-run. To actually
    # change a live group, bump its version -- see README.
    IMMUTABLE = ("already exists", "Cannot update published")

    done: list[str] = []
    unchanged: list[str] = []
    for obj in targets:
        kind = ("key" if isinstance(obj, AttributeKey)
                else "service" if isinstance(obj, Service) else "group")
        label = f"{kind} {obj.name}"
        try:
            signals.publish([obj])
            done.append(label)
        except SignalsAPIError as e:
            if e.status_code == 400 and any(m in str(e) for m in IMMUTABLE):
                unchanged.append(label)
            else:
                raise

    def _summary(items: list[str]) -> str:
        counts: dict[str, int] = {}
        for i in items:
            counts[i.split()[0]] = counts.get(i.split()[0], 0) + 1
        return ", ".join(f"{n} {k}{'s' if n > 1 else ''}"
                         for k, n in counts.items()) or "nothing"

    print()
    print(f"published: {_summary(done)}")
    if unchanged:
        print(f"unchanged: {_summary(unchanged)} (already published; bump version to change)")


if __name__ == "__main__":
    main()
