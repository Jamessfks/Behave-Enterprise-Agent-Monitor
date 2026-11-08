"""The company context the monitor checks against, loaded from `world/` (ADR 0002, 0008).

- `world/company/context.json`: seller domain, prices, discount limits, stages, location nouns,
  which actions are drafts/sends, fact-check settings, step-model settings, agent-role rules.
- `world/rules/written_rules.json`: documented policies (the bible's section 6).
- `world/rules/unwritten_rules.json`: a senior rep's rules of thumb (the author comes from the file).

Every rule carries a machine-readable `spec` (monitor/rules.py). Nothing here is written in Python,
so a new policy or account is a data change.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
WORLD = ROOT / "world"
CONTEXT_PATH = WORLD / "company" / "context.json"
RULE_FILES = {
    "written": WORLD / "rules" / "written_rules.json",
    "unwritten": WORLD / "rules" / "unwritten_rules.json",
}


@cache
def company_context() -> dict[str, Any]:
    return json.loads(CONTEXT_PATH.read_text())


def _rule(raw: dict[str, Any], group: str) -> dict[str, Any]:
    specs = raw.get("spec") or {"kind": "advisory"}
    return {
        "id": raw["id"],
        "group": group,
        # Unwritten rules are shown in their author's own words.
        "text": raw.get("quote") or raw.get("rule") or "",
        "rule": raw.get("rule") or "",
        "author": raw.get("author"),
        "source": raw.get("source_doc"),
        "specs": specs if isinstance(specs, list) else [specs],
    }


@cache
def company_rules() -> tuple[dict[str, Any], ...]:
    """Written, unwritten and agent-role rules, each as {id, group, text, author, source, specs}."""
    out = []
    for group, path in RULE_FILES.items():
        out += [_rule(r, group) for r in json.loads(path.read_text())["rules"]]
    out += [_rule(r, "agent") for r in company_context().get("agent_rules") or []]
    return tuple(out)


def price(plan: str | None) -> float | None:
    return company_context()["pricing"]["per_location_year"].get((plan or "").lower())


def user_name(data: dict[str, Any] | None, user_id: str | None) -> str | None:
    """A person's display name from the workspace's users (u_dana -> Dana Brooks)."""
    for u in (data or {}).get("users") or []:
        if u.get("id") == user_id or u.get("email") == user_id:
            return u.get("name")
    return user_id
