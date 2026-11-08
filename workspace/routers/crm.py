"""Habspot: a small HubSpot-like CRM (deals, contacts, companies, notes, tasks).

Every read is logged via events.log_read, every write goes through events.commit.
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import events, store
from ..web import body, contact_name, ok, page

router = APIRouter()

STAGE_LABELS = {
    "new": "New", "discovery": "Discovery", "demo": "Demo", "proposal": "Proposal",
    "negotiation": "Negotiation", "closed_won": "Closed Won", "closed_lost": "Closed Lost",
}
CONTACT_STATUSES = ["active", "interested", "unsubscribed", "do_not_contact"]
STATUS_LABELS = {"active": "Active", "interested": "Interested", "unsubscribed": "Unsubscribed",
                 "do_not_contact": "Do not contact"}


# ---------------------------------------------------------------- helpers

def _deal(deal_id: str) -> dict:
    d = store.get("deals", deal_id)
    if not d:
        raise HTTPException(404, "Deal not found")
    return d


def _contact(contact_id: str) -> dict:
    c = store.get("contacts", contact_id)
    if not c:
        raise HTTPException(404, "Contact not found")
    return c


def _company(company_id: str) -> dict:
    c = store.get("companies", company_id)
    if not c:
        raise HTTPException(404, "Company not found")
    return c


def _timeline(deal_id: Optional[str] = None, contact_id: Optional[str] = None,
              company_id: Optional[str] = None) -> List[dict]:
    out = []
    for a in store.items("activities"):
        if deal_id and a.get("deal_id") == deal_id:
            out.append(a)
        elif contact_id and contact_id in (a.get("contact_ids") or []):
            out.append(a)
        elif company_id and a.get("company_id") == company_id:
            out.append(a)
    return sorted(out, key=lambda a: a.get("ts") or "", reverse=True)


def _matches(q: str, *vals) -> bool:
    q = q.lower().strip()
    return any(q in str(v or "").lower() for v in vals)


def _search(q: str) -> dict:
    if not q.strip():
        return {"contacts": [], "companies": [], "deals": []}
    contacts = [c for c in store.items("contacts")
                if _matches(q, contact_name(c), c.get("email"), c.get("title"))]
    companies = [c for c in store.items("companies") if _matches(q, c.get("name"), c.get("domain"))]
    deals = [d for d in store.items("deals") if _matches(q, d.get("name"))]
    return {"contacts": contacts, "companies": companies, "deals": deals}


def _contacts_filtered(q: str = "", email: str = "") -> List[dict]:
    rows = store.items("contacts")
    if email:
        rows = [c for c in rows if c.get("email", "").lower() == email.lower().strip()]
    if q:
        rows = [c for c in rows if _matches(q, contact_name(c), c.get("email"), c.get("title"),
                                            (store.get("companies", c.get("company_id")) or {}).get("name"))]
    return rows


def _num(v):
    if v is None or v == "":
        return None
    try:
        f = float(str(v).replace(",", "").replace("$", ""))
        return int(f) if f == int(f) else f
    except Exception:
        raise HTTPException(400, f"Invalid number: {v}")


def _ctx(**kw):
    kw.setdefault("STAGES", events.STAGES)
    kw.setdefault("STAGE_LABELS", STAGE_LABELS)
    kw.setdefault("STATUS_LABELS", STATUS_LABELS)
    kw.setdefault("CONTACT_STATUSES", CONTACT_STATUSES)
    kw.setdefault("active_tab", "crm")
    return kw


# ---------------------------------------------------------------- pages

@router.get("/crm")
def crm_root():
    return RedirectResponse("/crm/deals")


@router.get("/crm/deals")
def deals_page(request: Request, view: str = "board"):
    events.log_read("habspot", "habspot.list_deals", None, None, args={"view": view})
    deals = store.items("deals")
    cols = {s: [d for d in deals if d.get("stage") == s] for s in events.STAGES}
    return page(request, "crm/deals.html", **_ctx(view=view, deals=deals, cols=cols, totals={s: sum((d.get("amount") or 0) for d in v) for s, v in cols.items()}, section="deals"))


@router.get("/crm/deal/{deal_id}")
def deal_page(request: Request, deal_id: str):
    d = _deal(deal_id)
    events.log_read("habspot", "habspot.open_deal", "deal", deal_id)
    return page(request, "crm/deal.html", **_ctx(
        d=d, company=store.get("companies", d.get("company_id")),
        contacts=[c for c in (store.get("contacts", i) for i in d.get("contact_ids") or []) if c],
        acts=_timeline(deal_id=deal_id), section="deals",
        contract=store.get("docs", d.get("contract_doc_id"))))


@router.get("/crm/contacts")
def contacts_page(request: Request, q: str = ""):
    if q:
        events.log_read("habspot", "habspot.search", None, None, args={"q": q})
    return page(request, "crm/contacts.html", **_ctx(rows=_contacts_filtered(q), q=q, section="contacts"))


@router.get("/crm/contact/{contact_id}")
def contact_page(request: Request, contact_id: str):
    c = _contact(contact_id)
    events.log_read("habspot", "habspot.open_contact", "contact", contact_id, ctx={"status": c.get("status")})
    deals = [d for d in store.items("deals") if contact_id in (d.get("contact_ids") or [])]
    return page(request, "crm/contact.html", **_ctx(
        c=c, company=store.get("companies", c.get("company_id")), deals=deals,
        acts=_timeline(contact_id=contact_id), section="contacts"))


@router.get("/crm/companies")
def companies_page(request: Request, q: str = ""):
    rows = [c for c in store.items("companies") if not q or _matches(q, c.get("name"), c.get("domain"))]
    return page(request, "crm/companies.html", **_ctx(rows=rows, q=q, section="companies"))


@router.get("/crm/company/{company_id}")
def company_page(request: Request, company_id: str):
    co = _company(company_id)
    events.log_read("habspot", "habspot.open_company", "company", company_id)
    return page(request, "crm/company.html", **_ctx(
        co=co, contacts=store.find("contacts", company_id=company_id),
        deals=store.find("deals", company_id=company_id),
        acts=_timeline(company_id=company_id), section="companies"))


@router.get("/crm/search")
def search_page(request: Request, q: str = ""):
    events.log_read("habspot", "habspot.search", None, None, args={"q": q})
    return page(request, "crm/search.html", **_ctx(q=q, res=_search(q), section=""))


# ---------------------------------------------------------------- JSON reads

@router.get("/api/crm/deals")
def api_deals(stage: str = "", company_id: str = ""):
    events.log_read("habspot", "habspot.list_deals", None, None)
    rows = store.items("deals")
    if stage:
        rows = [d for d in rows if d.get("stage") == stage]
    if company_id:
        rows = [d for d in rows if d.get("company_id") == company_id]
    return {"deals": rows}


@router.get("/api/crm/deal/{deal_id}")
def api_deal(deal_id: str):
    d = _deal(deal_id)
    events.log_read("habspot", "habspot.open_deal", "deal", deal_id)
    return {"deal": d, "activities": _timeline(deal_id=deal_id)}


@router.get("/api/crm/contacts")
def api_contacts(q: str = "", email: str = ""):
    return {"contacts": _contacts_filtered(q, email)}


@router.get("/api/crm/contact/{contact_id}")
def api_contact(contact_id: str):
    c = _contact(contact_id)
    events.log_read("habspot", "habspot.open_contact", "contact", contact_id, ctx={"status": c.get("status")})
    return {"contact": c, "activities": _timeline(contact_id=contact_id)}


@router.get("/api/crm/companies")
def api_companies():
    return {"companies": store.items("companies")}


@router.get("/api/crm/company/{company_id}")
def api_company(company_id: str):
    co = _company(company_id)
    events.log_read("habspot", "habspot.open_company", "company", company_id)
    return {"company": co, "contacts": store.find("contacts", company_id=company_id),
            "deals": store.find("deals", company_id=company_id), "activities": _timeline(company_id=company_id)}


@router.get("/api/crm/search")
def api_search(q: str = ""):
    events.log_read("habspot", "habspot.search", None, None, args={"q": q})
    return _search(q)


# ---------------------------------------------------------------- writes

@router.post("/api/crm/deal/{deal_id}/stage")
async def api_stage(request: Request, deal_id: str):
    b = await body(request)
    d = _deal(deal_id)
    new = b.get("stage")
    if new not in events.STAGES:
        raise HTTPException(400, f"Unknown stage: {new}")
    old = d.get("stage")

    def apply():
        d["stage"] = new
        return {"stage": new}

    res = events.commit("habspot", "habspot.stage", "deal", deal_id, {"from": old, "stage": new},
                        {"crm_change": events.stage_change(old, new, d)}, apply)
    return ok(res, redirect=f"/crm/deal/{deal_id}")


@router.post("/api/crm/deal/{deal_id}/update")
async def api_deal_update(request: Request, deal_id: str):
    b = await body(request)
    d = _deal(deal_id)
    res = None
    if "amount" in b and b["amount"] not in (None, ""):
        new = _num(b["amount"])
        old = d.get("amount")
        if new != old:
            def apply_amount(new=new):
                d["amount"] = new
                return {"amount": new}
            res = events.commit("habspot", "habspot.amount", "deal", deal_id, {"from": old, "amount": new},
                                {"crm_change": events.amount_change(old or 0, new)}, apply_amount)
    if b.get("close_date"):
        new = str(b["close_date"])[:10]
        old = d.get("close_date") or ""
        if new != old[:10]:
            def apply_close(new=new):
                d["close_date"] = new
                return {"close_date": new}
            res = events.commit("habspot", "habspot.close_date", "deal", deal_id, {"from": old, "close_date": new},
                                {"crm_change": events.close_date_change(old, new)}, apply_close)
    ch = {}
    if "next_step" in b and (b["next_step"] or "") != (d.get("next_step") or ""):
        ch["next_step"] = b["next_step"] or ""
    if "next_step_date" in b and b["next_step_date"] and b["next_step_date"] != (d.get("next_step_date") or ""):
        ch["next_step_date"] = b["next_step_date"]
    if ch:
        def apply_ns(ch=ch):
            d.update(ch)
            return ch
        res = events.commit("habspot", "habspot.next_step", "deal", deal_id, dict(ch), {}, apply_ns)
    return ok(res, redirect=f"/crm/deal/{deal_id}", changed=res is not None)


@router.post("/api/crm/note")
async def api_note(request: Request):
    b = await body(request)
    text = (b.get("body") or "").strip()
    if not text:
        raise HTTPException(400, "Note body is empty")
    deal_id, contact_id, company_id = b.get("deal_id") or None, b.get("contact_id") or None, b.get("company_id") or None
    if deal_id:
        d = _deal(deal_id)
        obj_type, obj_id = "deal", deal_id
        company_id = company_id or d.get("company_id")
        contact_ids = list(d.get("contact_ids") or [])
        redirect = f"/crm/deal/{deal_id}"
    elif contact_id:
        c = _contact(contact_id)
        obj_type, obj_id = "contact", contact_id
        company_id = company_id or c.get("company_id")
        contact_ids = [contact_id]
        redirect = f"/crm/contact/{contact_id}"
    elif company_id:
        _company(company_id)
        obj_type, obj_id, contact_ids = "company", company_id, []
        redirect = f"/crm/company/{company_id}"
    else:
        raise HTTPException(400, "deal_id, contact_id or company_id required")
    nid = store.new_id("nt")

    def apply():
        return store.add("activities", {
            "id": nid, "type": "note", "deal_id": deal_id, "company_id": company_id,
            "contact_ids": contact_ids, "author": store.ME, "ts": store.now_iso(),
            "title": "Note", "body": text, "due": None, "done": None})

    res = events.commit("habspot", "habspot.note", obj_type, obj_id, {"body": text, "note_id": nid},
                        {"crm_change": "note_append"}, apply)
    return ok(res, redirect=redirect, note_id=nid)


@router.post("/api/crm/note/{note_id}/edit")
async def api_note_edit(request: Request, note_id: str):
    b = await body(request)
    n = store.get("activities", note_id)
    if not n:
        raise HTTPException(404, "Note not found")
    text = (b.get("body") or "").strip()
    old = n.get("body")

    def apply():
        n["body"] = text
        n["edited_at"] = store.now_iso()
        return {"body": text}

    res = events.commit("habspot", "habspot.note", "activity", note_id, {"from": old, "body": text, "deal_id": n.get("deal_id")},
                        {"crm_change": "note_overwrite"}, apply)
    redirect = f"/crm/deal/{n['deal_id']}" if n.get("deal_id") else (
        f"/crm/contact/{n['contact_ids'][0]}" if n.get("contact_ids") else f"/crm/company/{n.get('company_id')}")
    return ok(res, redirect=redirect)


@router.post("/api/crm/contact/{contact_id}/status")
async def api_contact_status(request: Request, contact_id: str):
    b = await body(request)
    c = _contact(contact_id)
    new = b.get("status")
    if new not in CONTACT_STATUSES:
        raise HTTPException(400, f"Unknown status: {new}")
    old = c.get("status")

    def apply():
        c["status"] = new
        return {"status": new}

    res = events.commit("habspot", "habspot.contact_status", "contact", contact_id, {"from": old, "status": new},
                        {"status": new}, apply)
    return ok(res, redirect=f"/crm/contact/{contact_id}")


CONTACT_FIELDS = ("first_name", "last_name", "email", "phone", "title", "role", "about", "company_id")


@router.post("/api/crm/contact/{contact_id}/update")
async def api_contact_update(request: Request, contact_id: str):
    b = await body(request)
    c = _contact(contact_id)
    ch = {k: b[k] for k in CONTACT_FIELDS if k in b and b[k] is not None and b[k] != c.get(k)}
    if not ch:
        return ok(None, redirect=f"/crm/contact/{contact_id}", changed=False)

    def apply():
        c.update(ch)
        return ch

    res = events.commit("habspot", "habspot.contact_update", "contact", contact_id, dict(ch), {}, apply)
    return ok(res, redirect=f"/crm/contact/{contact_id}", changed=True)


@router.post("/api/crm/contact/create")
async def api_contact_create(request: Request):
    b = await body(request)
    if not b.get("email"):
        raise HTTPException(400, "email required")
    cid = store.new_id("ct")
    obj = {"id": cid, "first_name": b.get("first_name", ""), "last_name": b.get("last_name", ""),
           "email": b["email"].strip(), "phone": b.get("phone", ""), "title": b.get("title", ""),
           "company_id": b.get("company_id") or None, "status": "active", "role": b.get("role", ""),
           "owner": store.ME, "created_at": store.now_iso(), "last_contacted_at": None, "about": b.get("about", "")}

    def apply():
        return store.add("contacts", obj)

    res = events.commit("habspot", "habspot.contact_create", "contact", cid,
                        {k: obj[k] for k in ("first_name", "last_name", "email", "title", "company_id")},
                        {"scope": events.scope_tag("contact", obj)}, apply)
    return ok(res, redirect=f"/crm/contact/{cid}", contact_id=cid)


@router.post("/api/crm/task")
async def api_task(request: Request):
    b = await body(request)
    title = (b.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Task title required")
    deal_id, contact_id = b.get("deal_id") or None, b.get("contact_id") or None
    company_id = b.get("company_id") or None
    contact_ids: List[str] = []
    if deal_id:
        d = _deal(deal_id)
        obj_type, obj_id = "deal", deal_id
        company_id = company_id or d.get("company_id")
        contact_ids = list(d.get("contact_ids") or [])
        redirect = f"/crm/deal/{deal_id}"
    elif contact_id:
        c = _contact(contact_id)
        obj_type, obj_id = "contact", contact_id
        company_id = company_id or c.get("company_id")
        contact_ids = [contact_id]
        redirect = f"/crm/contact/{contact_id}"
    elif company_id:
        obj_type, obj_id = "company", company_id
        redirect = f"/crm/company/{company_id}"
    else:
        obj_type, obj_id, redirect = None, None, "/crm/deals"
    tid = store.new_id("tk")

    def apply():
        return store.add("activities", {
            "id": tid, "type": "task", "deal_id": deal_id, "company_id": company_id,
            "contact_ids": contact_ids, "author": store.ME, "ts": store.now_iso(),
            "title": title, "body": b.get("body", ""), "due": b.get("due") or None, "done": False})

    res = events.commit("habspot", "habspot.task_create", obj_type, obj_id,
                        {"title": title, "due": b.get("due"), "task_id": tid}, {}, apply)
    return ok(res, redirect=redirect, task_id=tid)


@router.post("/api/crm/task/{task_id}/complete")
async def api_task_complete(request: Request, task_id: str):
    t = store.get("activities", task_id)
    if not t or t.get("type") != "task":
        raise HTTPException(404, "Task not found")

    def apply():
        t["done"] = True
        return {"done": True}

    res = events.commit("habspot", "habspot.task_complete", "activity", task_id, {"title": t.get("title")}, {}, apply)
    redirect = f"/crm/deal/{t['deal_id']}" if t.get("deal_id") else (
        f"/crm/contact/{t['contact_ids'][0]}" if t.get("contact_ids") else "/crm/deals")
    return ok(res, redirect=redirect)
