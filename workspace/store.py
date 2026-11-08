"""In-memory app state, persisted to state/state.json. Reset copies seed/state.json over it."""
import copy
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
SEED_FILE = ROOT / "world" / "seed" / "state.json"
STATE_FILE = ROOT / "state" / "state.json"

COLLECTIONS = ["users", "companies", "contacts", "deals", "activities", "threads", "folders", "docs", "calendar"]

# object type (as used in events) -> collection
TYPE_TO_COLL = {
    "user": "users", "company": "companies", "contact": "contacts", "deal": "deals",
    "activity": "activities", "note": "activities", "task": "activities",
    "thread": "threads", "folder": "folders", "doc": "docs", "event": "calendar",
}

DATA: Dict[str, Any] = {}

# In-world clock. Real event timestamps use wall time; displayed "today" is fixed.
NOW = "2026-11-09T09:00:00-07:00"
ME = "u_alex"
MY_EMAIL = "alex@shiftpoint.io"
SELLER_DOMAIN = "shiftpoint.io"
POLICY = {"max_discount_rep": 15, "max_discount_manager": 25,
          "large_amount_change_pct": 20, "large_close_date_change_days": 30}


def load() -> None:
    global DATA
    if not STATE_FILE.exists():
        reset()
        return
    DATA = json.loads(STATE_FILE.read_text())
    for c in COLLECTIONS:
        DATA.setdefault(c, [])


def save() -> None:
    STATE_FILE.parent.mkdir(exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(DATA, indent=1))
    tmp.replace(STATE_FILE)


def reset() -> None:
    if not SEED_FILE.exists():
        raise RuntimeError("seed/state.json missing - run: python scripts/build_seed.py")
    STATE_FILE.parent.mkdir(exist_ok=True)
    shutil.copy(SEED_FILE, STATE_FILE)
    load()


def items(coll: str) -> List[dict]:
    return DATA[coll]


def get(coll: str, id: Optional[str]) -> Optional[dict]:  # noqa: A002
    if not id:
        return None
    for o in DATA[coll]:
        if o.get("id") == id:
            return o
    return None


def find(coll: str, **kw) -> List[dict]:
    return [o for o in DATA[coll] if all(o.get(k) == v for k, v in kw.items())]


def first(coll: str, **kw) -> Optional[dict]:
    r = find(coll, **kw)
    return r[0] if r else None


def add(coll: str, obj: dict) -> dict:
    DATA[coll].append(obj)
    return obj


def remove(coll: str, id: str) -> Optional[dict]:  # noqa: A002
    o = get(coll, id)
    if o:
        DATA[coll].remove(o)
    return o


def replace(coll: str, obj: dict) -> None:
    """Put obj back (used by undo). Adds it if it was deleted."""
    for i, o in enumerate(DATA[coll]):
        if o.get("id") == obj["id"]:
            DATA[coll][i] = obj
            return
    DATA[coll].append(obj)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


def snapshot(obj_type: str, obj_id: Optional[str]) -> Optional[dict]:
    coll = TYPE_TO_COLL.get(obj_type)
    if not coll or not obj_id:
        return None
    o = get(coll, obj_id)
    return copy.deepcopy(o) if o else None


# ---- lookups used by context derivation and templates ----

def domain_of(email: str) -> str:
    return email.split("@")[-1].lower().strip() if "@" in email else ""


def contact_by_email(email: str) -> Optional[dict]:
    e = email.lower().strip()
    for c in DATA["contacts"]:
        if c.get("email", "").lower() == e:
            return c
    return None


def company_by_domain(domain: str) -> Optional[dict]:
    for c in DATA["companies"]:
        if c.get("domain", "").lower() == domain:
            return c
    return None


def user_by_email(email: str) -> Optional[dict]:
    e = email.lower().strip()
    for u in DATA["users"]:
        if u.get("email", "").lower() == e:
            return u
    return None


def folder_path(folder_id: Optional[str]) -> str:
    parts = []
    f = get("folders", folder_id)
    while f:
        parts.append(f["name"])
        f = get("folders", f.get("parent_id"))
    return "/".join(reversed(parts))


_BOOT = __import__("time").time()


def now_iso() -> str:
    """In-world time: Mon 9 Nov 2026 09:00 plus real seconds since the server started.
    Use this for timestamps shown in the apps (new messages, notes, docs)."""
    from datetime import datetime, timedelta
    t = datetime.fromisoformat(NOW) + timedelta(seconds=__import__("time").time() - _BOOT)
    return t.isoformat(timespec="seconds")
