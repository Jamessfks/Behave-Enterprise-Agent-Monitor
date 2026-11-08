"""The Sentinel action catalog (catalog/actions.csv).

The CSV holds the BehaviorGPT columns plus our own: `irreversible`, `role` (workflow | benign |
wrong) and `phase` (gather | act | any). `catalog_from_csv` drops the extra columns, so they never
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

ID_RE = re.compile(r"^(inbox|docs|transcripts|crm|email)\.[a-z]+(_[a-z]+)*$")
APP_OF_PREFIX = {
    "inbox": "Inbox",
    "docs": "Docs",
    "transcripts": "Transcripts",
    "crm": "CRM",
    "email": "Email",
}
ROLES = {"workflow", "benign", "wrong"}
PHASES = {"gather", "act", "any"}


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
