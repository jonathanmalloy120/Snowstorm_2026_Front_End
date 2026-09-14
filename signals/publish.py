"""Publish (or test) the attribute definitions against Signals.

  uv run python -m signals.publish --dry-run   # print what would be published
  uv run python -m signals.publish             # publish for real

Signals does NOT backdate: attributes are calculated only from the moment they
are published, so publish before generating any traffic you care about.
"""

import argparse
import sys

from snowplow_signals import Signals

from signals import config
from signals.definitions import ALL_GROUPS


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print definitions, publish nothing")
    args = ap.parse_args()

    for group in ALL_GROUPS:
        print(f"\n{group.name} v{group.version}  key={group.attribute_key.name}")
        for a in group.attributes:
            window = f"period={a.period}" if a.period else "lifetime"
            print(f"   {a.name:<22} {a.aggregation:<22} {window}")

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
    signals.publish(ALL_GROUPS)
    print(f"\npublished {len(ALL_GROUPS)} attribute groups")


if __name__ == "__main__":
    main()
