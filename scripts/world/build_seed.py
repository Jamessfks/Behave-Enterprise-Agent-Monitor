"""Build seed/state.json from the human-editable content in world/.

  world/habspot/crm.json        -> users, companies, contacts, deals, activities
  world/inbox/threads.json      -> threads
  world/drive/*.md              -> docs (front matter + markdown body)
  world/transcripts/T*.md       -> docs (kind=transcript)
  folders are derived from each doc's `folder:` path

Usage: .venv/bin/python scripts/build_seed.py   (then POST /api/admin/reset)
Missing inputs are skipped with a warning so partial content still builds.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORLD = ROOT / "world"
OUT = ROOT / "world" / "seed" / "state.json"

BOOL = {"true": True, "false": False}


def parse_md(path: Path) -> dict:
    text = path.read_text()
    meta, body = {}, text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            if ":" in line and not line.strip().startswith("#"):
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return {"meta": meta, "body": body.strip() + "\n"}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def folder_id(path: str) -> str:
    return "fd_" + slug(path)


def ensure_folders(path: str, folders: dict) -> str:
    parts = [p.strip() for p in path.split("/") if p.strip()]
    parent = None
    for i in range(len(parts)):
        p = "/".join(parts[: i + 1])
        fid = folder_id(p)
        if fid not in folders:
            folders[fid] = {"id": fid, "name": parts[i], "parent_id": parent, "path": p}
        parent = fid
    return parent


def to_int(v, default=0):
    try:
        return int(float(v))
    except Exception:
        return default


def doc_from_md(path: Path, folders: dict) -> dict:
    p = parse_md(path)
    m = p["meta"]
    name = m.get("name") or path.stem
    folder = m.get("folder") or ("Sales/Call Transcripts" if m.get("kind") == "transcript" else "My Drive")
    shared = []
    for item in [s.strip() for s in m.get("shared_with", "").split(",") if s.strip()]:
        email, _, role = item.partition(":")
        shared.append({"email": email.strip(), "role": (role or "viewer").strip()})
    doc = {
        "id": m.get("id") or f"doc_{slug(name)}",
        "name": name,
        "folder_id": ensure_folders(folder, folders),
        "sensitivity": m.get("sensitivity", "internal"),
        "kind": m.get("kind", "doc"),
        "owner": m.get("owner", "u_alex"),
        "updated_at": m.get("updated_at", "2026-11-01T09:00:00-07:00"),
        "shared_with": shared,
        "body": p["body"],
        "account": m.get("account") or m.get("offer_account") or None,
        "deal": m.get("deal") or None,
        "call_date": m.get("call_date") or None,
        "duration_min": to_int(m.get("duration_min"), None) if m.get("duration_min") else None,
        "participants": [s.strip() for s in m.get("participants", "").split(",") if s.strip()],
        "offer": None,
        "copied_from": None,
    }
    if doc["kind"] == "offer":
        doc["offer"] = {
            "account": m.get("offer_account") or None,
            "plan": m.get("offer_plan", "core"),
            "locations": to_int(m.get("offer_locations")),
            "discount_pct": to_int(m.get("offer_discount_pct")),
            "onboarding": BOOL.get(m.get("offer_onboarding", "false").lower(), False),
            "payroll_addon": BOOL.get(m.get("offer_payroll_addon", "false").lower(), False),
            "valid_until": m.get("offer_valid_until") or None,
            "notes": "",
        }
    return doc


def main() -> int:
    state = {"users": [], "companies": [], "contacts": [], "deals": [], "activities": [],
             "threads": [], "folders": [], "docs": [], "calendar": []}
    crm = WORLD / "habspot" / "crm.json"
    if crm.exists():
        data = json.loads(crm.read_text())
        for k in ("users", "companies", "contacts", "deals", "activities"):
            state[k] = data.get(k, [])
    else:
        print("WARN: world/habspot/crm.json missing", file=sys.stderr)

    inbox = WORLD / "inbox" / "threads.json"
    if inbox.exists():
        state["threads"] = json.loads(inbox.read_text())
    else:
        print("WARN: world/inbox/threads.json missing", file=sys.stderr)

    cal = WORLD / "calendar" / "events.json"
    if cal.exists():
        state["calendar"] = json.loads(cal.read_text())
    else:
        print("WARN: world/calendar/events.json missing", file=sys.stderr)

    folders: dict = {}
    # always-present roots, so the tree looks right even before content exists
    for root in ("My Drive/Alex – Private", "Sales/Pricing", "Sales/Templates", "Sales/Call Transcripts",
                 "Sales/Offers", "Sales/Contracts", "Sales/Playbook", "Marketing", "Finance", "Shared/Team"):
        ensure_folders(root, folders)
    docs = []
    for f in sorted((WORLD / "drive").glob("*.md")):
        if f.name.lower() != "readme.md":
            docs.append(doc_from_md(f, folders))
    for f in sorted((WORLD / "transcripts").glob("T*.md")):
        d = doc_from_md(f, folders)
        d["kind"] = "transcript"
        docs.append(d)
    state["docs"] = docs
    state["folders"] = list(folders.values())

    # light referential checks
    doc_ids = {d["id"] for d in docs}
    for t in state["threads"]:
        for msg in t.get("messages", []):
            for a in msg.get("attachments", []):
                if a not in doc_ids:
                    print(f"WARN: thread {t['id']} attaches unknown doc {a}", file=sys.stderr)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(state, indent=1))
    print("seed built:", {k: len(v) for k, v in state.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
