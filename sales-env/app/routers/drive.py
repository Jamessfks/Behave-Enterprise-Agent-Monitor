"""Jdrive: Drive/Docs lookalike. Pages under /drive, JSON API under /api/drive."""
import copy
from typing import Any, List, Optional

import markdown as md
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import events, store
from ..web import body, ok, page

router = APIRouter()

PRICE = {"core": 1800, "pro": 2640}
ONBOARDING = 3000
PAYROLL = 2000
OFFER_FIELDS = ("account", "plan", "locations", "discount_pct", "onboarding", "payroll_addon", "valid_until", "notes")
SENS = ("public", "internal", "confidential", "outdated")


# ---------------------------------------------------------------- helpers

def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "on", "1", "yes")


def _num(v: Any, default: float = 0) -> float:
    try:
        f = float(str(v).strip().rstrip("%"))
        return int(f) if f == int(f) else f
    except Exception:
        return default


def folder_kind(fid: Optional[str]) -> str:
    p = store.folder_path(fid)
    if p.startswith("My Drive"):
        return "private"
    if p.startswith("Shared"):
        return "shared"
    return "team"


def _doc(doc_id: Optional[str]) -> dict:
    d = store.get("docs", doc_id)
    if not d:
        raise HTTPException(404, f"No such doc: {doc_id}")
    return d


def _folder(fid: Optional[str]) -> dict:
    f = store.get("folders", fid)
    if not f:
        raise HTTPException(404, f"No such folder: {fid}")
    return f


def offer_totals(o: Optional[dict]) -> Optional[dict]:
    if not o:
        return None
    plan = (o.get("plan") or "core").lower()
    per = PRICE.get(plan, PRICE["core"])
    locs = int(_num(o.get("locations"), 0))
    disc = _num(o.get("discount_pct"), 0)
    list_price = per * locs
    discount_amt = round(list_price * disc / 100.0, 2)
    subscription = list_price - discount_amt
    onboarding = ONBOARDING if o.get("onboarding") else 0
    payroll = PAYROLL if (o.get("payroll_addon") and plan == "core") else 0
    return {"per_location": per, "locations": locs, "list_price": list_price, "discount_pct": disc,
            "discount_amt": discount_amt, "subscription": subscription, "onboarding": onboarding,
            "payroll": payroll, "first_year_total": subscription + onboarding + payroll,
            "annual_recurring": subscription + payroll}


def account_options() -> List[str]:
    slugs = [c["id"][3:] for c in store.items("companies") if c.get("id", "").startswith("co_")]
    if not slugs:  # CRM data not loaded yet: fall back to accounts seen in docs
        slugs = sorted({d.get("account") for d in store.items("docs") if d.get("account")} |
                       {(d.get("offer") or {}).get("account") for d in store.items("docs")
                        if (d.get("offer") or {}).get("account")})
    return sorted(set(slugs))


def account_name(slug: Optional[str]) -> str:
    if not slug:
        return ""
    co = store.get("companies", f"co_{slug}")
    return co.get("name", slug) if co else slug.replace("_", " ").title()


def folder_tree() -> List[dict]:
    """Depth-first list of folders with depth for indentation."""
    fs = store.items("folders")
    out: List[dict] = []

    def walk(parent: Optional[str], depth: int):
        kids = sorted([f for f in fs if f.get("parent_id") == parent],
                      key=lambda f: (f["name"] != "My Drive", f["name"]))
        for f in kids:
            out.append({"f": f, "depth": depth})
            walk(f["id"], depth + 1)
    walk(None, 0)
    return out


def breadcrumb(fid: Optional[str]) -> List[dict]:
    out = []
    f = store.get("folders", fid)
    while f:
        out.append(f)
        f = store.get("folders", f.get("parent_id"))
    return list(reversed(out))


def summary(d: dict) -> dict:
    return dict({k: v for k, v in d.items() if k != "body"}, path=store.folder_path(d.get("folder_id")))


def search_docs(q: str, folder: Optional[str] = None) -> List[dict]:
    ql = (q or "").lower().strip()
    out = []
    for d in store.items("docs"):
        if folder and d.get("folder_id") != folder:
            continue
        if ql and ql not in d.get("name", "").lower() and ql not in (d.get("body") or "").lower():
            continue
        out.append(d)
    return sorted(out, key=lambda d: d.get("name", "").lower())


def render_md(text: str) -> str:
    return md.markdown(text or "", extensions=["tables", "fenced_code"])


def _sidebar_ctx(current_folder: Optional[str]) -> dict:
    return {"tree": folder_tree(), "current_folder": current_folder, "active_tab": "drive"}


# ---------------------------------------------------------------- pages

@router.get("/drive")
def drive_home(request: Request, folder: Optional[str] = None, q: Optional[str] = None):
    if q is not None and q.strip():
        q = q.strip()
        events.emit("jdrive", "jdrive.search", None, None, {}, args={"q": q})
        docs = search_docs(q)
        return page(request, "drive/folder.html", folder=None, crumbs=[], subfolders=[], docs=docs, q=q,
                    **_sidebar_ctx(None))
    fid = folder or "fd_sales"
    f = store.get("folders", fid)
    if not f:
        return RedirectResponse("/drive?folder=fd_sales")
    events.log_read("jdrive", "jdrive.open_folder", "folder", fid, {})
    subs = sorted([x for x in store.items("folders") if x.get("parent_id") == fid], key=lambda x: x["name"])
    docs = sorted([d for d in store.items("docs") if d.get("folder_id") == fid], key=lambda d: d["name"].lower())
    return page(request, "drive/folder.html", folder=f, crumbs=breadcrumb(fid), subfolders=subs, docs=docs, q="",
                **_sidebar_ctx(fid))


@router.get("/drive/doc/{doc_id}")
def doc_page(request: Request, doc_id: str):
    d = _doc(doc_id)
    events.log_read("jdrive", "jdrive.open", "doc", doc_id, {"sensitivity": d.get("sensitivity"), "kind": d.get("kind")})
    return page(request, "drive/doc.html", doc=d, html=render_md(d.get("body")), crumbs=breadcrumb(d.get("folder_id")),
                totals=offer_totals(d.get("offer")), account_name=account_name,
                participants=d.get("participants") or [], **_sidebar_ctx(d.get("folder_id")))


@router.get("/drive/doc/{doc_id}/edit")
def edit_page(request: Request, doc_id: str):
    d = _doc(doc_id)
    return page(request, "drive/edit.html", doc=d, crumbs=breadcrumb(d.get("folder_id")),
                accounts=account_options(), account_name=account_name, totals=offer_totals(d.get("offer")),
                **_sidebar_ctx(d.get("folder_id")))


# ---------------------------------------------------------------- JSON reads

@router.get("/api/drive/folders")
def api_folders():
    return {"folders": [dict(f, path=store.folder_path(f["id"])) for f in store.items("folders")]}


@router.get("/api/drive/docs")
def api_docs(folder: Optional[str] = None, q: Optional[str] = None):
    if q:
        events.emit("jdrive", "jdrive.search", None, None, {}, args={"q": q})
    elif folder:
        events.log_read("jdrive", "jdrive.open_folder", "folder", folder, {})
    return {"docs": [summary(d) for d in search_docs(q or "", folder)]}


@router.get("/api/drive/doc/{doc_id}")
def api_doc(doc_id: str):
    d = _doc(doc_id)
    events.log_read("jdrive", "jdrive.open", "doc", doc_id, {"sensitivity": d.get("sensitivity"), "kind": d.get("kind")})
    return {"doc": dict(d, path=store.folder_path(d.get("folder_id"))), "offer_totals": offer_totals(d.get("offer"))}


# ---------------------------------------------------------------- writes

@router.post("/api/drive/create")
async def api_create(request: Request):
    b = await body(request)
    fid = b.get("folder_id") or "fd_my_drive"
    _folder(fid)
    name = (b.get("name") or "").strip() or "Untitled document"
    new_id = store.new_id("doc")
    doc = {"id": new_id, "name": name, "folder_id": fid, "sensitivity": "internal", "kind": "doc",
           "owner": store.ME, "updated_at": store.now_iso(), "shared_with": [], "body": b.get("body") or "",
           "account": None, "deal": None, "offer": None, "copied_from": None}
    res = events.commit("jdrive", "jdrive.create", "doc", new_id, {"folder_id": fid, "name": name},
                        {"folder_kind": folder_kind(fid)}, apply=lambda: store.add("docs", doc) and new_id)
    return ok(res, redirect=f"/drive/doc/{new_id}/edit", doc_id=new_id)


@router.post("/api/drive/copy")
async def api_copy(request: Request):
    b = await body(request)
    src = _doc(b.get("doc_id"))
    fid = b.get("folder_id") or src.get("folder_id")
    _folder(fid)
    name = (b.get("name") or "").strip() or f"Copy of {src['name']}"
    new_id = store.new_id("doc")

    def apply():
        d = copy.deepcopy(src)
        d.update({"id": new_id, "name": name, "folder_id": fid, "owner": store.ME, "updated_at": store.now_iso(),
                  "shared_with": [], "copied_from": src["id"]})
        store.add("docs", d)
        return new_id
    res = events.commit("jdrive", "jdrive.copy", "doc", src["id"],
                        {"doc_id": src["id"], "new_doc_id": new_id, "name": name, "folder_id": fid},
                        {"sensitivity": src.get("sensitivity"), "folder_kind": folder_kind(fid)}, apply=apply)
    return ok(res, redirect=f"/drive/doc/{new_id}", doc_id=new_id)


@router.post("/api/drive/edit")
async def api_edit(request: Request):
    b = await body(request)
    d = _doc(b.get("doc_id"))
    sens = d.get("sensitivity")
    is_offer = d.get("kind") == "offer" and any(k in b for k in OFFER_FIELDS)
    args = {k: b[k] for k in ("name",) + OFFER_FIELDS if k in b}
    if "body" in b:
        args["body_len"] = len(b.get("body") or "")

    new_offer = None
    if is_offer:
        new_offer = copy.deepcopy(d.get("offer") or {})
        if "account" in b:
            new_offer["account"] = (b.get("account") or "").strip() or None
        if "plan" in b:
            new_offer["plan"] = (b.get("plan") or "core").lower()
        if "locations" in b:
            new_offer["locations"] = int(_num(b.get("locations"), 0))
        if "discount_pct" in b:
            new_offer["discount_pct"] = _num(b.get("discount_pct"), 0)
        for k in ("onboarding", "payroll_addon"):
            if k in b:
                new_offer[k] = _truthy(b.get(k))
        if "valid_until" in b:
            new_offer["valid_until"] = b.get("valid_until") or None
        if "notes" in b:
            new_offer["notes"] = b.get("notes") or ""
        for k in OFFER_FIELDS:
            new_offer.setdefault(k, None)

    def apply():
        if "name" in b and (b.get("name") or "").strip():
            d["name"] = b["name"].strip()
        if "body" in b:
            d["body"] = b.get("body") or ""
        if new_offer is not None:
            d["offer"] = new_offer
            if new_offer.get("account"):
                d["account"] = new_offer["account"]
                d["sensitivity"] = "public"  # customer-facing offer
        d["updated_at"] = store.now_iso()
        return d["id"]

    if is_offer:
        res = events.commit("jdrive", "quote.save", "doc", d["id"], args,
                            {"discount": events.discount_class(new_offer.get("discount_pct") or 0), "sensitivity": sens},
                            apply=apply)
    else:
        res = events.commit("jdrive", "jdrive.edit", "doc", d["id"], args, {"sensitivity": sens}, apply=apply)
    return ok(res, redirect=f"/drive/doc/{d['id']}", doc_id=d["id"])


@router.post("/api/drive/rename")
async def api_rename(request: Request):
    b = await body(request)
    d = _doc(b.get("doc_id"))
    name = (b.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Name required")

    def apply():
        d["name"] = name
        d["updated_at"] = store.now_iso()
    res = events.commit("jdrive", "jdrive.rename", "doc", d["id"], {"name": name}, {}, apply=apply)
    return ok(res, redirect=f"/drive/doc/{d['id']}")


@router.post("/api/drive/move")
async def api_move(request: Request):
    b = await body(request)
    d = _doc(b.get("doc_id"))
    fid = b.get("folder_id")
    _folder(fid)

    def apply():
        d["folder_id"] = fid
        d["updated_at"] = store.now_iso()
    res = events.commit("jdrive", "jdrive.move", "doc", d["id"], {"folder_id": fid},
                        {"folder_kind": folder_kind(fid), "sensitivity": d.get("sensitivity")}, apply=apply)
    return ok(res, redirect=f"/drive/doc/{d['id']}")


@router.post("/api/drive/share")
async def api_share(request: Request):
    b = await body(request)
    d = _doc(b.get("doc_id"))
    email = (b.get("email") or "").strip().lower()
    role = (b.get("role") or "viewer").lower()
    if "@" not in email:
        raise HTTPException(400, "Valid email required")
    if role not in ("viewer", "editor"):
        role = "viewer"

    def apply():
        sw = [s for s in d.setdefault("shared_with", []) if s.get("email") != email]
        sw.append({"email": email, "role": role})
        d["shared_with"] = sw
    res = events.commit("jdrive", "jdrive.share", "doc", d["id"], {"email": email, "role": role},
                        {"recipient": events.recipient_class(email), "sensitivity": d.get("sensitivity")},
                        apply=apply, irreversible=True)
    return ok(res, redirect=f"/drive/doc/{d['id']}")


@router.post("/api/drive/unshare")
async def api_unshare(request: Request):
    b = await body(request)
    d = _doc(b.get("doc_id"))
    email = (b.get("email") or "").strip().lower()

    def apply():
        d["shared_with"] = [s for s in d.get("shared_with", []) if s.get("email") != email]
    res = events.commit("jdrive", "jdrive.unshare", "doc", d["id"], {"email": email}, {}, apply=apply)
    return ok(res, redirect=f"/drive/doc/{d['id']}")


@router.post("/api/drive/delete")
async def api_delete(request: Request):
    b = await body(request)
    d = _doc(b.get("doc_id"))
    fid = d.get("folder_id")
    res = events.commit("jdrive", "jdrive.delete", "doc", d["id"], {"name": d.get("name")},
                        {"sensitivity": d.get("sensitivity")}, apply=lambda: store.remove("docs", d["id"]) and d["id"])
    return ok(res, redirect=f"/drive?folder={fid}")
