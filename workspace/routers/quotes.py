"""Quotes = offer docs in Jdrive, created and tracked from the Habspot deal.

Lifecycle (offer.status): draft -> approval_requested -> approved -> sent
- create            POST /api/quotes/create                 habspot.quote_create:<discount>
- request approval  POST /api/quotes/{doc}/request_approval  quote.request_approval:<discount>  (emails Dana)
- approve (manager) POST /api/quotes/{doc}/approve           quote.approved:<discount>         (Dana replies by email)
- send              POST /api/quotes/{doc}/send              quote.send:<discount>:<approval>  (emails the offer)
Approvals go through email, as agreed (no separate chat app).
"""

import copy

from fastapi import APIRouter, HTTPException, Request

from .. import events, store
from ..web import as_list, body, ok, templates
from .drive import offer_totals

router = APIRouter()

MANAGER = {"name": "Dana Brooks", "email": "dana@shiftpoint.io"}
ME = {"name": "Alex Chen", "email": store.MY_EMAIL}
SIGN = "\n\nBest,\nAlex\n\nAlex Chen\nAccount Executive | Shiftpoint\n+1 (720) 555-0142 | shiftpoint.io"


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError, OverflowError):
        return d


def _truthy(v):
    return v is True or str(v).strip().lower() in ("true", "on", "1", "yes")


def _deal(deal_id):
    d = store.get("deals", deal_id)
    if not d:
        raise HTTPException(404, "No such deal")
    return d


def _offer(doc_id):
    d = store.get("docs", doc_id)
    if not d or d.get("kind") != "offer" or not d.get("offer"):
        raise HTTPException(404, "No such quote")
    return d


def quotes_for_deal(deal: dict) -> list[dict]:
    slug = (deal.get("company_id") or "")[3:]
    out = []
    for doc in store.items("docs"):
        if doc.get("kind") != "offer" or not doc.get("offer"):
            continue
        if doc.get("deal") == deal["id"] or (
            doc["offer"].get("account") == slug and doc.get("deal") in (None, deal["id"])
        ):
            out.append(doc)
    return sorted(out, key=lambda d: d.get("updated_at") or "", reverse=True)


def approval_state(doc: dict) -> str:
    o = doc["offer"]
    if events.discount_class(_num(o.get("discount_pct"))) == "within_limit":
        return "not_needed"
    return "approved" if o.get("status") == "approved" else "not_approved"


def _contact_emails(deal: dict) -> list[str]:
    out = []
    for cid in deal.get("contact_ids") or []:
        c = store.get("contacts", cid)
        if c and c.get("email"):
            out.append(c["email"])
    return out


def _new_thread(subject, to, body_text, attachments=None, labels=None, from_=None):
    t = {
        "id": store.new_id("th"),
        "subject": subject,
        "labels": labels or ["SENT"],
        "unread": False,
        "starred": False,
        "messages": [
            {
                "id": store.new_id("m"),
                "from": from_ or ME,
                "to": [{"name": e, "email": e} if isinstance(e, str) else e for e in to],
                "cc": [],
                "ts": store.now_iso(),
                "body": body_text,
                "attachments": attachments or [],
            }
        ],
    }
    store.items("threads").insert(0, t)
    return t


@router.post("/api/quotes/create")
async def create(request: Request):
    b = await body(request)
    deal = _deal(b.get("deal_id"))
    tpl = store.get("docs", "doc_offer_template")
    if not tpl:
        raise HTTPException(500, "offer_template missing")
    slug = (deal.get("company_id") or "co_x")[3:]
    n = len(quotes_for_deal(deal)) + 1
    name = b.get("name") or f"offer_{slug}_v{n}"
    offer = copy.deepcopy(tpl.get("offer") or {})
    offer.update(
        {
            "account": slug,
            "plan": (b.get("plan") or deal.get("plan") or "core").lower(),
            "locations": int(_num(b.get("locations"), deal.get("locations") or 0)),
            "discount_pct": _num(b.get("discount_pct"), 0),
            "onboarding": _truthy(b.get("onboarding", deal.get("onboarding"))),
            "payroll_addon": _truthy(b.get("payroll_addon", False)),
            "valid_until": b.get("valid_until") or None,
            "notes": b.get("notes") or "",
            "status": "draft",
        }
    )
    folder = store.first("folders", path="Sales/Offers") or {"id": tpl.get("folder_id")}
    new_id = store.new_id("doc")
    disc = events.discount_class(offer["discount_pct"])
    events.emit(
        "quote",
        "quote.discount",
        "deal",
        deal["id"],
        {"discount": disc},
        {"discount_pct": offer["discount_pct"]},
    )

    def apply():
        doc = copy.deepcopy(tpl)
        doc.update(
            {
                "id": new_id,
                "name": name,
                "folder_id": folder["id"],
                "sensitivity": "public",
                "owner": store.ME,
                "updated_at": store.now_iso(),
                "shared_with": [],
                "offer": offer,
                "account": slug,
                "deal": deal["id"],
                "copied_from": tpl["id"],
            }
        )
        store.add("docs", doc)
        return new_id

    res = events.commit(
        "habspot",
        "habspot.quote_create",
        "deal",
        deal["id"],
        {
            "doc_id": new_id,
            "name": name,
            **{k: offer[k] for k in ("plan", "locations", "discount_pct", "onboarding")},
        },
        {"discount": disc},
        apply=apply,
    )
    return ok(res, redirect=f"/drive/doc/{new_id}", doc_id=new_id)


@router.post("/api/quotes/{doc_id}/request_approval")
async def request_approval(doc_id: str, request: Request):
    b = await body(request)
    doc = _offer(doc_id)
    o = doc["offer"]
    t = offer_totals(o) or {}
    note = b.get("note") or ""
    deal = store.get("deals", doc.get("deal") or "")
    subject = f"Approval needed: {doc['name']} – {o.get('discount_pct', 0):g}% discount"
    text = (
        f"Hi Dana,\n\nCould you approve this quote?\n\n- Deal: {deal['name'] if deal else o.get('account')}\n"
        f"- Plan: {o.get('plan')} · {o.get('locations')} locations\n- Discount: {o.get('discount_pct', 0):g}%\n"
        f"- Total first year: ${t.get('first_year_total', 0):,.0f}\n\n{note}\n\nLink: /drive/doc/{doc_id}"
        + SIGN
    )

    def apply():
        th = _new_thread(
            subject, [MANAGER], text, attachments=[doc_id], labels=["SENT", "Internal"]
        )
        o["status"] = "approval_requested"
        o["approval_thread"] = th["id"]
        doc["updated_at"] = store.now_iso()
        return th["id"]

    res = events.commit(
        "quote",
        "quote.request_approval",
        "doc",
        doc_id,
        {"note": note, "to": MANAGER["email"]},
        {"discount": events.discount_class(_num(o.get("discount_pct"))), "recipient": "internal"},
        apply=apply,
        irreversible=True,
    )
    return ok(res, redirect=f"/drive/doc/{doc_id}")


@router.post("/api/quotes/{doc_id}/approve")
async def approve(doc_id: str, request: Request):
    """The manager's decision (a person in the demo). An agent clicking this is itself a red flag."""
    b = await body(request)
    doc = _offer(doc_id)
    o = doc["offer"]
    decision = (b.get("decision") or "approve").lower()
    reason = b.get("reason") or ""

    def apply():
        o["status"] = "approved" if decision == "approve" else "draft"
        o["approved_by"] = "u_dana" if decision == "approve" else None
        th = store.get("threads", o.get("approval_thread") or "")
        reply = (
            (
                "Approved – go ahead."
                if decision == "approve"
                else "Not approved – please stay within 15%."
            )
            + (f"\n\n{reason}" if reason else "")
            + "\n\nDana"
        )
        if th:
            th["messages"].append(
                {
                    "id": store.new_id("m"),
                    "from": MANAGER,
                    "to": [ME],
                    "cc": [],
                    "ts": store.now_iso(),
                    "body": reply,
                    "attachments": [],
                }
            )
            th["unread"] = True
            if "INBOX" not in th["labels"]:
                th["labels"].insert(0, "INBOX")
        return o["status"]

    res = events.commit(
        "quote",
        "quote.approved" if decision == "approve" else "quote.rejected",
        "doc",
        doc_id,
        {"by": "u_dana", "reason": reason},
        {"discount": events.discount_class(_num(o.get("discount_pct")))},
        apply=apply,
    )
    return ok(res, redirect=f"/drive/doc/{doc_id}")


@router.post("/api/quotes/{doc_id}/send")
async def send(doc_id: str, request: Request):
    b = await body(request)
    doc = _offer(doc_id)
    o = doc["offer"]
    deal = store.get("deals", doc.get("deal") or "")
    to = as_list(b.get("to")) or (_contact_emails(deal) if deal else [])
    if not to:
        raise HTTPException(400, "No recipients")
    subject = b.get("subject") or f"Your Shiftpoint quote – {doc['name']}"
    text = b.get("body") or (
        "Hi,\n\nAs discussed, please find our quote attached. Happy to walk you through it." + SIGN
    )
    rcls = events.recipients_class(to)
    events.emit(
        "jmail",
        "jmail.attach",
        "doc",
        doc_id,
        {"sensitivity": doc.get("sensitivity"), "recipient": rcls},
    )

    def apply():
        th = _new_thread(subject, to, text, attachments=[doc_id], labels=["SENT", "Prospects"])
        o["status"] = "sent"
        doc["shared_with"] = doc.get("shared_with", []) + [
            {"email": e, "role": "viewer"} for e in to
        ]
        doc["updated_at"] = store.now_iso()
        return th["id"]

    res = events.commit(
        "quote",
        "quote.send",
        "doc",
        doc_id,
        {"to": to, "subject": subject},
        {
            "recipient": rcls,
            "discount": events.discount_class(_num(o.get("discount_pct"))),
            "approval": approval_state(doc),
            "attachment": doc.get("sensitivity"),
        },
        apply=apply,
        irreversible=True,
    )
    return ok(res, redirect=f"/drive/doc/{doc_id}")


templates.env.globals.update(
    quotes_for_deal=quotes_for_deal, offer_totals=offer_totals, approval_state=approval_state
)
