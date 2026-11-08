"""Generate catalog/actions.csv: one row per catalog_action the workspace can emit (ADR 0007).

    catalog_action = action + ":" + ":".join(ctx[key] for key in action_tags.json[action])

Ids are the actions the routers emit (string literals in workspace/routers/*.py) crossed with
the tag values they can produce. Values come from the workspace's own classifiers and constants
(workspace/events.py, the routers) and from the seed world (doc kinds and labels, folders,
contact statuses). Words (name, categories, role, phase, irreversible) come from
catalog/vocab.json. Clicks (ui.*), run markers (session.*, sentinel.*) and searches are not
catalog items: searches reach BehaviorGPT as Search(query) events.

    uv run python scripts/build_catalog.py              # write catalog/actions.csv
    uv run python scripts/build_catalog.py --check      # exit 1 if the CSV is out of date
    uv run python scripts/build_catalog.py --validate   # also run behaviorgpt.catalog_from_csv
                                                        # on a temp copy (nothing is uploaded)
"""

from __future__ import annotations

import argparse
import copy
import csv
import io
import itertools
import json
import re
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TAGS_FILE = ROOT / "catalog" / "action_tags.json"
VOCAB_FILE = ROOT / "catalog" / "vocab.json"
OUT_FILE = ROOT / "catalog" / "actions.csv"
SEED_FILE = ROOT / "world" / "seed" / "state.json"
ROUTERS = ROOT / "workspace" / "routers"

COLUMNS = [
    "id",
    "name",
    "brand",
    "categories",
    "event_type",
    "group",
    "irreversible",
    "role",
    "phase",
]
APPS = ("jmail", "jdrive", "habspot", "calendar", "quote")
NOT_ITEMS = ("ui.", "session.", "sentinel.")
ROLES = {"workflow", "benign", "wrong"}
PHASES = {"research", "act", "any"}
ID_RE = re.compile(
    r"^(jmail|jdrive|habspot|calendar|quote)\.[a-z]+(_[a-z]+)*(:[a-z0-9]+(_[a-z0-9]+)*)*$"
)
# Account-specific ids must never leak into the catalog: it is generic across accounts.
FORBIDDEN_IN_ID = ("acme", "co_", "dl_", "th_", "doc_")
ACTION_LITERAL = re.compile(r"[\"']((?:" + "|".join(APPS) + r")\.[a-z_]+)[\"']")
PLACEHOLDER = re.compile(r"\{([a-z_]+)(?:\.([a-z]+))?\}")


def _ordered(values: Iterable, order: Iterable = ()) -> list:
    """Unique values, those in `order` first (in that order), the rest as first seen."""
    seen = list(dict.fromkeys(v for v in values if v is not None))
    first = [v for v in order if v in seen]
    return first + [v for v in seen if v not in first]


def emitted_actions() -> list[str]:
    """Actions the workspace routers log, emit or commit (their string literals)."""
    found: list[str] = []
    for path in sorted(ROUTERS.glob("*.py")):
        found += ACTION_LITERAL.findall(path.read_text())
    return list(dict.fromkeys(found))


def workspace_values() -> SimpleNamespace:
    """Every tag value the workspace can produce, from its own code and the seed world."""
    from workspace import events, store
    from workspace.routers import crm, drive, quotes

    seed = json.loads(SEED_FILE.read_text())
    store.load(copy.deepcopy(seed))  # drive.folder_kind reads folder paths from the store
    docs = seed["docs"]
    sens = _ordered((d.get("sensitivity") for d in docs), drive.SENS)
    kinds = _ordered(d.get("kind") for d in docs)
    stages = events.STAGES
    signed = ({"contract_signed": False}, {"contract_signed": True})
    over = float(store.POLICY["max_discount_rep"]) + 1
    return SimpleNamespace(
        recipient=list(events.RECIPIENT_RANK),
        sender=list(events.RECIPIENT_RANK),
        sensitivity=sens,
        kind=kinds,
        discount=_ordered(events.discount_class(p) for p in (0.0, over)),
        status=_ordered([*crm.CONTACT_STATUSES, *(c.get("status") for c in seed["contacts"])]),
        folder_kind=_ordered(
            (drive.folder_kind(f["id"]) for f in seed["folders"]), ("private", "team", "shared")
        ),
        crm_change={
            "habspot.stage": _ordered(
                events.stage_change(o, n, s)
                for o, n, s in itertools.product(stages, stages, signed)
            ),
            "habspot.amount": _ordered(
                events.amount_change(o, n) for o, n in ((100, 101), (100, 1000), (0, 1))
            ),
            "habspot.close_date": _ordered(
                events.close_date_change(o, n)
                for o, n in (("2026-01-01", "2026-01-05"), ("2026-01-01", "2026-06-01"))
            ),
        },
        # Multi-tag ids: only the combinations that can occur.
        joint={
            # a doc's (kind, label) pairs as they exist in the world
            ("kind", "sensitivity"): sorted(
                _ordered((d.get("kind"), d.get("sensitivity")) for d in docs),
                key=lambda p: (kinds.index(p[0]), sens.index(p[1])),
            ),
            # approval only applies over the rep's limit (quotes.approval_state)
            ("discount", "approval"): _ordered(
                (
                    events.discount_class(p),
                    quotes.approval_state({"offer": {"discount_pct": p, "status": st}}),
                )
                for p in (0.0, over)
                for st in ("draft", "approval_requested", "approved", "sent")
            ),
        },
    )


def _values(action: str, key: str, spec: dict, ws: SimpleNamespace) -> list[str]:
    if key in spec.get("values", {}):
        return list(spec["values"][key])
    if key == "crm_change" and action in ws.crm_change:
        return ws.crm_change[action]
    v = getattr(ws, key, None)
    if not isinstance(v, list):
        raise SystemExit(
            f"{action}: no value source for tag {key!r}; list them under "
            f"actions.{action}.values in {VOCAB_FILE.name}"
        )
    return v


def combos(action: str, keys: list[str], spec: dict, ws: SimpleNamespace) -> list[dict]:
    """The {tag: value} sets `action` can carry, in key order; {} is the bare id."""
    if tuple(keys) in ws.joint:
        tuples = ws.joint[tuple(keys)]
    else:
        tuples = itertools.product(*(_values(action, k, spec, ws) for k in keys))
    out = [tuple(zip(keys, t, strict=True)) for t in tuples]
    for opt in spec.get("optional", []):  # the workspace may leave this tag out of ctx
        out = _ordered([tuple(kv for kv in c if kv[0] != opt) for c in out] + out)
    return [dict(c) for c in out]


def _render(template: str, tags: dict[str, str], phrases: dict, aid: str) -> str:
    def sub(m: re.Match) -> str:
        key, variant = m.group(1), m.group(2)
        table = phrases.get(f"{key}.{variant}" if variant else key, {})
        if key not in tags or tags[key] not in table:
            raise SystemExit(f"{aid}: no phrase for {m.group(0)} = {tags.get(key)!r}")
        return table[tags[key]]

    return PLACEHOLDER.sub(sub, template)


def build_rows(ws: SimpleNamespace | None = None) -> list[dict[str, str]]:
    tags_map = {k: v for k, v in json.loads(TAGS_FILE.read_text()).items() if not k.startswith("_")}
    vocab = json.loads(VOCAB_FILE.read_text())
    ws = ws or workspace_values()
    emitted = [
        a for a in emitted_actions() if not a.startswith(NOT_ITEMS) and not a.endswith(".search")
    ]
    order = list(tags_map) + [a for a in emitted if a not in tags_map]
    actions = sorted(
        (a for a in order if a in emitted), key=lambda a: APPS.index(a.split(".")[0])
    )  # stable: keeps tag-file order

    rows: list[dict[str, str]] = []
    for action in actions:
        spec = vocab["actions"].get(action)
        if spec is None:
            raise SystemExit(
                f"{action} is emitted by the workspace but has no entry in {VOCAB_FILE.name}"
            )
        key = tags_map.get(action)
        keys = [] if not key else ([key] if isinstance(key, str) else list(key))
        for tags in combos(action, keys, spec, ws):
            suffix = ":".join(tags.values())
            aid = action + (":" + suffix if suffix else "")
            name = spec.get("names", {}).get(suffix) or (
                _render(spec["name"], tags, vocab["phrases"], aid) if "name" in spec else None
            )
            if not name:
                raise SystemExit(f"{aid}: no name (add names[{suffix!r}] in {VOCAB_FILE.name})")
            risky = any(v in vocab["risky"].get(k, []) for k, v in tags.items())
            role = spec.get("roles", {}).get(suffix) or (
                spec["risky_role"] if risky and spec.get("risky_role") else spec["role"]
            )
            rows.append(
                {
                    "id": aid,
                    "name": name,
                    "brand": vocab["apps"][action.split(".")[0]],
                    "categories": spec["categories"],
                    "event_type": "product",
                    "group": "product",
                    "irreversible": "true" if spec.get("irreversible") else "false",
                    "role": role,
                    "phase": spec["phase"],
                }
            )
    _check(rows, vocab, actions)
    return rows


def _check(rows: list[dict[str, str]], vocab: dict, actions: list[str]) -> None:
    ids = [r["id"] for r in rows]
    names = [r["name"] for r in rows]
    problems = []
    problems += [f"duplicate id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    problems += [f"duplicate name {n!r}" for n in sorted({n for n in names if names.count(n) > 1})]
    for r in rows:
        if not ID_RE.match(r["id"]):
            problems.append(f"malformed id {r['id']}")
        if any(s in r["id"] for s in FORBIDDEN_IN_ID):
            problems.append(f"account-specific id {r['id']}")
        if len(r["name"].split()) < 4 or not r["name"][0].isupper():
            problems.append(f"name is not a sentence: {r['id']} -> {r['name']!r}")
        if r["role"] not in ROLES or r["phase"] not in PHASES:
            problems.append(f"bad role/phase on {r['id']}")
    if problems:
        raise SystemExit("catalog problems:\n  " + "\n  ".join(problems))
    stale = sorted(set(vocab["actions"]) - set(actions))
    if stale:
        print(
            f"note: vocab entries for actions the workspace no longer emits: {stale}",
            file=sys.stderr,
        )


def to_csv(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def validate(text: str) -> int:
    """Run the SDK's own converter and schema check on a temp copy; returns the row count."""
    import pyarrow.parquet as pq
    from behaviorgpt import catalog_from_csv

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "actions.csv"
        src.write_text(text)
        out = catalog_from_csv(src, Path(tmp) / "actions.parquet")
        return pq.read_metadata(out).num_rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the CSV is out of date")
    ap.add_argument("--validate", action="store_true", help="run behaviorgpt.catalog_from_csv")
    args = ap.parse_args()

    rows = build_rows()
    text = to_csv(rows)
    per_app = {app: sum(r["id"].startswith(app + ".") for r in rows) for app in APPS}
    roles = {role: sum(r["role"] == role for r in rows) for role in sorted(ROLES)}
    print(f"{len(rows)} actions  {per_app}  {roles}")
    if args.validate:
        print(f"catalog_from_csv: ok, {validate(text)} rows")
    if args.check:
        current = OUT_FILE.read_text() if OUT_FILE.exists() else ""
        if current != text:
            print(
                f"{OUT_FILE.relative_to(ROOT)} is out of date: run scripts/build_catalog.py",
                file=sys.stderr,
            )
            return 1
        print(f"{OUT_FILE.relative_to(ROOT)} is up to date")
        return 0
    OUT_FILE.write_text(text)
    print(f"wrote {OUT_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
