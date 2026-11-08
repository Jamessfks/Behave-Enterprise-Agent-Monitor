"""Keep the action catalog on the Unbox portal (portal.unboxai.com/catalogs) in sync.

Catalogs embedded with your API key are the portal's catalogs: there's no separate portal
upload. Each key holds 2 catalogs, and the parquet's file name is the catalog's name, so pushing
the same name refreshes that catalog (same catalog_id) while a new name takes a free slot.

    uv run python scripts/catalog_sync.py status
    uv run python scripts/catalog_sync.py push [--csv catalog/actions.csv] [--name actions] [--keywords]
    uv run python scripts/catalog_sync.py keywords
    uv run python scripts/catalog_sync.py smoke

`push` writes catalog/unbox.json (which catalog the app uses, committed) and UNBOXAI_CATALOG_ID
in .env. It sends only the catalog (fictional workplace actions), never personal data.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from monitor.unbox import (
    NAME_RE,
    PORTAL_CATALOGS,
    SLOTS,
    get_client,
    plan_push,
    read_csv,
    validate_rows,
)

RECORD = ROOT / "catalog" / "unbox.json"
PORTAL = PORTAL_CATALOGS


def client():
    load_dotenv(ROOT / ".env")
    if not os.environ.get("UNBOXAI_API_KEY"):
        sys.exit("UNBOXAI_API_KEY is not set: add it to .env (never commit it).")
    return get_client()


def owned(c) -> list:
    return [x for x in c.list_catalogs() if x.owned]


def set_env(key: str, value: str) -> None:
    env = ROOT / ".env"
    lines = env.read_text().splitlines() if env.exists() else []
    lines = [ln for ln in lines if not ln.startswith(f"{key}=")] + [f"{key}={value}"]
    env.write_text("\n".join(lines) + "\n")


def validate_csv(path: Path) -> list[str]:
    return validate_rows(read_csv(path.read_text(encoding="utf-8-sig")))


def cmd_status(_args) -> None:
    c = client()
    mine = owned(c)
    current = os.environ.get("UNBOXAI_CATALOG_ID")
    print(f"Your catalogs on the Unbox portal ({len(mine)} of {SLOTS} slots): {PORTAL}")
    for x in mine:
        mark = "  <- used by the app" if x.catalog_id == current else ""
        print(f"  {x.catalog_name:<28} {x.catalog_id}  {x.status}{mark}")
    if RECORD.exists():
        print(f"catalog/unbox.json: {json.loads(RECORD.read_text())}")


def cmd_push(args) -> None:
    src = Path(args.csv)
    if not NAME_RE.match(args.name):
        sys.exit("Catalog names: lowercase letters, digits, '_' or '-', 2-63 characters.")
    errors = validate_csv(src)
    if errors:
        sys.exit("Fix the CSV first: " + "; ".join(errors))
    c = client()
    mode, _ = plan_push(args.name, owned(c))
    if mode == "full":
        sys.exit(
            f"Both catalog slots are in use and none is named {args.name!r}. Push under an "
            "existing name to refresh it, or delete one on the portal first."
        )
    from behaviorgpt import catalog_from_csv

    work = ROOT / ".untracked"
    work.mkdir(exist_ok=True)
    named = work / f"{args.name}.csv"  # the parquet's file name becomes the catalog's name
    shutil.copyfile(src, named)
    parquet = catalog_from_csv(str(named))
    print(f"{'Refreshing' if mode == 'refresh' else 'Creating'} catalog {args.name!r} ...")
    timeout = 3600.0 if args.keywords else 1800.0
    job = c.embed(parquet, keywords=args.keywords, wait=True, timeout=timeout)
    rows = sum(1 for _ in csv.DictReader(src.open(encoding="utf-8-sig")))
    record = {
        "catalog_id": job.catalog_id,
        "catalog_name": args.name,
        "source": str(src.relative_to(ROOT)) if src.is_relative_to(ROOT) else src.name,
        "rows": rows,
        "keywords": bool(args.keywords),
        "embedded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "portal": PORTAL,
    }
    RECORD.write_text(json.dumps(record, indent=2) + "\n")
    set_env("UNBOXAI_CATALOG_ID", job.catalog_id)
    print(f"Done: {job.catalog_id}. See it at {PORTAL}")


def cmd_keywords(_args) -> None:
    c = client()
    cid = os.environ.get("UNBOXAI_CATALOG_ID") or sys.exit("UNBOXAI_CATALOG_ID is not set.")
    c.add_keywords(cid, wait=True)
    if RECORD.exists():
        rec = json.loads(RECORD.read_text())
        rec["keywords"] = True
        RECORD.write_text(json.dumps(rec, indent=2) + "\n")
    print(f"Keywords generated for {cid}.")


def cmd_smoke(_args) -> None:
    from behaviorgpt import View

    c = client()
    cid = os.environ.get("UNBOXAI_CATALOG_ID")
    res = c.complete(
        [View("jdrive.open:transcript:internal")], limit=5, catalog_id=cid, register_event=False
    )
    print("After reading a call transcript, BehaviorGPT expects:")
    for item in res.items:
        print(f"  {item.data.get('name')}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p = sub.add_parser("push")
    p.add_argument("--csv", default=str(ROOT / "catalog" / "actions.csv"))
    p.add_argument("--name", default="actions")
    p.add_argument("--keywords", action="store_true", help="also generate keywords")
    p.set_defaults(fn=cmd_push)
    sub.add_parser("keywords").set_defaults(fn=cmd_keywords)
    sub.add_parser("smoke").set_defaults(fn=cmd_smoke)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
