"""Catalogs on the Unbox portal: validation, naming and the 2-slot rule, shared by
scripts/catalog_sync.py and the server's upload endpoint."""

from __future__ import annotations

import csv
import io
import re

PORTAL_CATALOGS = "https://portal.unboxai.com/catalogs/"
SLOTS = 2
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
REQUIRED = ("id", "name", "event_type", "group")


def validate_rows(rows: list[dict]) -> list[str]:
    """Problems that would make a portal catalog unusable, before anything is sent."""
    if not rows:
        return ["the CSV has no rows"]
    errors = [f"missing column {c!r}" for c in REQUIRED if c not in rows[0]]
    ids = [r.get("id", "") for r in rows]
    if len(set(ids)) != len(ids):
        errors.append("duplicate ids")
    if any(not r.get("id") or not r.get("name") for r in rows):
        errors.append("every row needs an id and a name")
    if len(rows) > 100_000:
        errors.append("over 100,000 rows")
    return errors


def read_csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def plan_push(name: str, owned: list) -> tuple[str, str | None]:
    """('refresh', catalog_id) | ('new', None) | ('full', None) for uploading under `name`.

    The file name is the catalog's name: the same name refreshes that catalog and keeps its id,
    a new name takes a free slot, and with both slots used a new name is refused upstream.
    """
    for x in owned:
        if x.catalog_name == name:
            return "refresh", x.catalog_id
    return ("new", None) if len(owned) < SLOTS else ("full", None)
