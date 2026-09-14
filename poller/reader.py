"""Batch reader for the Signals Profiles Store.

The Python SDK's get_group_attributes() accepts a single identifier and its
response formatter keeps only `value[0]`, discarding the rest of the batch.
The wire protocol, however, accepts a LIST of identifiers and answers
columnar: {attribute_name: [value_for_id_1, value_for_id_2, ...]}.

So we build the same request model the SDK uses and post it through the SDK's
ApiClient -- which gives us JWT fetch and expiry-refresh for free -- then do our
own row assembly instead of the lossy one.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Iterator

from snowplow_signals.api_client import ApiClient
from snowplow_signals.models import (
    AttributeKeyIdentifiers,
    GetAttributeGroupAttributesRequest,
)

log = logging.getLogger(__name__)


def chunked(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class SignalsReader:
    def __init__(self, api_url: str, api_key: str, api_key_id: str, org_id: str):
        self._api = ApiClient(
            api_url=api_url, api_key=api_key, api_key_id=api_key_id, org_id=org_id
        )

    def read_batch(
        self,
        group_name: str,
        group_version: int,
        attribute_names: Iterable[str],
        attribute_key: str,
        identifiers: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Read many identifiers in one request.

        Returns {identifier: {attribute_name: value}}. Identifiers the store
        knows nothing about still get an entry, with all values None.
        """
        attribute_names = list(attribute_names)
        if not identifiers:
            return {}

        qualified = [f"{group_name}_v{group_version}:{a}" for a in attribute_names]
        request = GetAttributeGroupAttributesRequest(
            attributes=qualified,
            attribute_keys=AttributeKeyIdentifiers(root={attribute_key: identifiers}),
        )
        raw = self._api.make_request(
            method="POST",
            endpoint="get-online-attributes",
            data=request.model_dump(mode="json", exclude_none=True),
        )

        data: dict[str, list[Any]] = raw.get("data", raw) or {}
        result: dict[str, dict[str, Any]] = {i: {} for i in identifiers}

        for attr in attribute_names:
            # Response keys may be bare or fully qualified depending on the
            # full_attribute_names flag; accept either.
            column = data.get(attr)
            if column is None:
                column = data.get(f"{group_name}_v{group_version}:{attr}")
            if column is None:
                for ident in identifiers:
                    result[ident][attr] = None
                continue

            # ASSUMPTION (verify on first live run): the columnar response is
            # ordered to match the identifiers we sent. A length mismatch is the
            # signal that this is wrong, so we refuse to guess rather than
            # silently attributing one article's numbers to another.
            if len(column) != len(identifiers):
                log.error(
                    "Length mismatch for %s: sent %d identifiers, got %d values. "
                    "Refusing to align by index.",
                    attr,
                    len(identifiers),
                    len(column),
                )
                for ident in identifiers:
                    result[ident][attr] = None
                continue

            for ident, value in zip(identifiers, column):
                result[ident][attr] = value

        return result

    def read_one(
        self,
        group_name: str,
        group_version: int,
        attribute_names: Iterable[str],
        attribute_key: str,
        identifier: str,
    ) -> dict[str, Any]:
        return self.read_batch(
            group_name, group_version, attribute_names, attribute_key, [identifier]
        ).get(identifier, {})
