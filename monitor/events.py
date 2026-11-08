"""The shared event format (docs/event-schema.md): validation and conversion to SDK events."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

APPS = {"Mail", "Files", "Calls", "CRM", "Quotes", "Chat", "Calendar"}
TYPES = {"search", "view"}


class EventError(ValueError):
    pass


def validate_event(ev: dict[str, Any]) -> None:
    """Raise EventError if `ev` does not follow docs/event-schema.md."""
    for key in ("run_id", "step", "timestamp", "type", "action_id", "query", "details"):
        if key not in ev:
            raise EventError(f"missing field {key!r}")
    if not isinstance(ev["run_id"], str) or not ev["run_id"]:
        raise EventError("run_id must be a non-empty string")
    if not isinstance(ev["step"], int) or ev["step"] < 0:
        raise EventError("step must be a non-negative int")
    ts = ev["timestamp"]
    if not isinstance(ts, str) or not ts.endswith("Z"):
        raise EventError("timestamp must be ISO-8601 UTC ending in Z")
    try:
        datetime.fromisoformat(ts)
    except ValueError as e:
        raise EventError(f"bad timestamp {ts!r}") from e
    if ev["type"] not in TYPES:
        raise EventError(f"type must be one of {sorted(TYPES)}")
    if ev["type"] == "view":
        if not ev["action_id"] or ev["query"] is not None:
            raise EventError("view needs action_id and a null query")
    else:
        if ev["action_id"] is not None or not ev["query"]:
            raise EventError("search needs query and a null action_id")
    d = ev["details"]
    if not isinstance(d, dict):
        raise EventError("details must be an object")
    if d.get("app") not in APPS:
        raise EventError(f"details.app must be one of {sorted(APPS)}")
    if not isinstance(d.get("irreversible"), bool):
        raise EventError("details.irreversible must be a bool")
    if "entity" not in d:
        raise EventError("details.entity is required (may be null)")
    if "values" in d and not (
        isinstance(d["values"], dict) and all(isinstance(k, str) for k in d["values"])
    ):
        raise EventError("details.values must be an object of field -> value")
    if "source" in d and d["source"] is not None and not isinstance(d["source"], str):
        raise EventError("details.source must be a source id string or null")


def validate_run(events: list[dict[str, Any]]) -> None:
    if not events:
        raise EventError("empty run")
    run_ids = {e["run_id"] for e in events}
    if len(run_ids) != 1:
        raise EventError(f"mixed run_ids: {sorted(run_ids)}")
    for i, ev in enumerate(events):
        validate_event(ev)
        if ev["step"] != i:
            raise EventError(f"step {ev['step']} at position {i}: steps must be 0..n-1")


def load_run(path: str | Path) -> list[dict[str, Any]]:
    lines = Path(path).read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def to_sdk(ev: dict[str, Any]):
    """One schema event as a BehaviorGPT SDK event. `details` is never sent."""
    from behaviorgpt import Search, View

    return Search(ev["query"]) if ev["type"] == "search" else View(ev["action_id"])
