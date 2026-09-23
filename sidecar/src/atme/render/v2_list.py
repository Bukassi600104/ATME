"""Shared fail-closed support rules for authored one-line list disclosure."""

from __future__ import annotations

from atme.store.contracts_v2 import TextObject

_LINE_BREAKS = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")


class UnsupportedOrderedList(ValueError):
    """An authored list cannot be disclosed as complete ordered items."""


def validate_ordered_list(obj: TextObject) -> None:
    if obj.object_type != "list" or not obj.items:
        raise UnsupportedOrderedList(f"v2 object {obj.object_id} needs an authored ordered-child list")
    if any(not value.strip() or any(char in _LINE_BREAKS for char in value)
           for value in (obj.text, *obj.items)):
        raise UnsupportedOrderedList(
            f"v2 list {obj.object_id} requires nonblank, one-line heading and items"
        )
