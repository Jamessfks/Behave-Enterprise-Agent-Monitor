"""The Sentinel action catalog (catalog/actions.csv).

The CSV holds the BehaviorGPT columns plus our own: `irreversible`, `role` (workflow | benign |
wrong) and `phase` (research | act | any). `catalog_from_csv` drops the extra columns, so they never
reach Unbox.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_CSV = ROOT / "catalog" / "actions.csv"

ID_RE = re.compile(r"^(mail|files|calls|crm|quotes|chat|calendar)\.[a-z]+(_[a-z0-9]+)*$")
APP_OF_PREFIX = {
    "mail": "Mail",
    "files": "Files",
    "calls": "Calls",
    "crm": "CRM",
    "quotes": "Quotes",
    "chat": "Chat",
    "calendar": "Calendar",
}
ROLES = {"workflow", "benign", "wrong"}
PHASES = {"research", "act", "any"}


@dataclass(frozen=True)
class Action:
    id: str
    name: str
    app: str
    categories: str
    irreversible: bool
    role: str
    phase: str


@cache
def load_catalog(path: Path = CATALOG_CSV) -> dict[str, Action]:
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    out: dict[str, Action] = {}
    for row in rows:
        a = Action(
            id=row["id"],
            name=row["name"],
            app=row["brand"],
            categories=row["categories"],
            irreversible=row["irreversible"] == "true",
            role=row["role"],
            phase=row["phase"],
        )
        if a.id in out:
            raise ValueError(f"duplicate action id {a.id}")
        out[a.id] = a
    return out
