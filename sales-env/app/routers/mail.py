"""Jmail: Gmail-like mailbox. Pages under /mail, JSON API under /api/mail."""
import re
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request

from .. import events, store, web

router = APIRouter()

SYSTEM_LABELS = [("INBOX", "Inbox"), ("STARRED", "Starred"), ("DRAFT", "Drafts"), ("SENT", "Sent"),
                 ("ARCHIVE", "Archive"), ("TRASH", "Trash")]
USER_LABELS = ["Prospects", "Customers", "Internal", "Follow-up", "Waiting on customer", "Newsletters"]
SENS_RANK = ["public", "internal", "outdated", "confidential"]
ME_PERSON = {"name": "Alex Chen", "email": store.MY_EMAIL}


# ---------------------------------------------------------------- helpers

def _is_me(email: str) -> bool:
    return (email or "").lower().strip() == store.MY_EMAIL


def _thread(tid: str) -> dict:
    t = store.get("threads", tid)
    if not t:
        raise HTTPException(404, "Thread not found")
    return t


def _last(t: dict) -> dict:
    return t["messages"][-1] if t.get("messages") else {"from": {"name": "", "email": ""}, "body": "", "ts": ""}


def _snippet(t: dict, n: int = 110) -> str:
    s = re.sub(r"\s+", " ", _last(t).get("body", "")).strip()
    return s[:n] + ("…" if len(s) > n else "")


def _senders(t: dict) -> str:
    names = []
    for m in t.get("messages", []):
        n = "me" if _is_me(m["from"]["email"]) else (m["from"].get("name") or m["from"]["email"])
        if n not in names:
            names.append(n)
    return ", ".join(names[-3:])


def _has_attach(t: dict) -> bool:
    return any(m.get("attachments") for m in t.get("messages", []))


def _in_label(t: dict, label: str) -> bool:
    labels = t.get("labels", [])
    if label == "STARRED":
        return bool(t.get("starred")) and "TRASH" not in labels
    if label == "ALL":
        return "TRASH" not in labels
    if label != "TRASH" and "TRASH" in labels:
        return False
    return label in labels


def _matches(t: dict, q: str) -> bool:
    q = q.lower().strip()
    if not q:
        return True
    hay = [t.get("subject", "")]
    for m in t.get("messages", []):
        hay += [m.get("body", ""), m["from"].get("name", ""), m["from"].get("email", "")]
        hay += [p.get("email", "") for p in m.get("to", []) + m.get("cc", [])]
        hay += [p.get("name", "") for p in m.get("to", []) + m.get("cc", [])]
    h = " ".join(hay).lower()
    return all(w in h for w in q.split())


def _list(label: str, q: str) -> List[dict]:
    # search spans all mail (except trash) like Gmail; otherwise filter by label
    ts = [t for t in store.items("threads") if (_in_label(t, "ALL") if q and label == "INBOX" else _in_label(t, label))]
    ts = [t for t in ts if _matches(t, q)]
    return sorted(ts, key=lambda t: _last(t).get("ts", ""), reverse=True)


def _summary(t: dict) -> dict:
    last = _last(t)
    return {"id": t["id"], "subject": t.get("subject", ""), "from": last["from"], "senders": _senders(t),
            "snippet": _snippet(t), "labels": t.get("labels", []), "unread": bool(t.get("unread")),
            "starred": bool(t.get("starred")), "last_ts": last.get("ts", ""),
            "messages": len(t.get("messages", [])), "has_attachments": _has_attach(t)}


def _counts() -> dict:
    out = {}
    for key, _ in SYSTEM_LABELS:
        out[key] = sum(1 for t in store.items("threads") if _in_label(t, key) and t.get("unread"))
    for lab in _user_labels():
        out[lab] = sum(1 for t in store.items("threads") if _in_label(t, lab) and t.get("unread"))
    return out


def _user_labels() -> List[str]:
    labs = list(USER_LABELS)
    sys = {k for k, _ in SYSTEM_LABELS}
    for t in store.items("threads"):
        for lab in t.get("labels", []):
            if lab not in sys and lab not in labs:
                labs.append(lab)
    return labs


def _open_ctx(t: dict) -> dict:
    sender = None
    for m in reversed(t.get("messages", [])):
        if not _is_me(m["from"]["email"]):
            sender = m["from"]["email"]
            break
    cls = events.recipient_class(sender) if sender else "internal"
    return {"sender": cls, "source": "trusted_internal" if cls == "internal" else "untrusted_external"}


def _log_open(t: dict) -> None:
    events.log_read("jmail", "jmail.open_thread", "thread", t["id"], _open_ctx(t))
    if t.get("unread"):
        t["unread"] = False
        store.save()


def _log_search(q: str, label: str) -> None:
    events.emit("jmail", "jmail.search", "thread", "", {}, args={"q": q, "label": label})


def _doc_label(doc_id: str) -> dict:
    d = store.get("docs", doc_id)
    if not d:
        return {"id": doc_id, "name": doc_id, "path": "", "sensitivity": None, "missing": True}
    return {"id": doc_id, "name": d.get("name", doc_id), "path": store.folder_path(d.get("folder_id")),
            "sensitivity": d.get("sensitivity"), "missing": False}


def _person(s: str) -> dict:
    """'Name <a@b.com>' or 'a@b.com' -> {name, email}."""
    m = re.match(r"\s*(.*?)\s*<([^>]+)>\s*$", s)
    if m:
        name, email = m.group(1).strip('" '), m.group(2).strip()
    else:
        email, name = s.strip(), ""
    if not name:
        c = store.contact_by_email(email)
        u = store.user_by_email(email)
        if c:
            name = web.contact_name(c)
        elif u:
            name = u.get("name", "")
    return {"name": name or email, "email": email}


def _fmt_people(ps: list) -> str:
    return ", ".join(f"{p['name']} <{p['email']}>" if p.get("name") and p["name"] != p["email"] else p["email"] for p in ps)


def _quote(m: dict) -> str:
    head = f"On {web.fmt_dt(m.get('ts'), short=False)}, {m['from'].get('name','')} <{m['from']['email']}> wrote:"
    return "\n\n\n" + head + "\n" + "\n".join("> " + line for line in m.get("body", "").split("\n"))


def _fwd_block(m: dict) -> str:
    return ("\n\n\n---------- Forwarded message ---------\n"
            f"From: {m['from'].get('name','')} <{m['from']['email']}>\n"
            f"Date: {web.fmt_dt(m.get('ts'), short=False)}\n"
            f"Subject: {{subject}}\n"
            f"To: {_fmt_people(m.get('to', []))}\n"
            + (f"Cc: {_fmt_people(m.get('cc', []))}\n" if m.get("cc") else "")
            + "\n" + m.get("body", ""))


def _prefix(subject: str, p: str) -> str:
    s = subject or ""
    return s if s.lower().startswith(p.lower()) else f"{p} {s}"


def _all_docs() -> List[dict]:
    ds = [_doc_label(d["id"]) for d in store.items("docs")]
    return sorted(ds, key=lambda d: (d["path"], d["name"]))


# ---------------------------------------------------------------- pages

@router.get("/mail")
def mail_list(request: Request, label: str = "INBOX", q: str = ""):
    q = q.strip()
    if q:
        _log_search(q, label)
    ts = [_summary(t) for t in _list(label, q)]
    names = dict(SYSTEM_LABELS)
    return web.page(request, "mail/list.html", active_tab="mail", threads=ts, label=label, q=q,
                    label_name=names.get(label, label), counts=_counts(),
                    system_labels=SYSTEM_LABELS, user_labels=_user_labels())


@router.get("/mail/thread/{tid}")
def mail_thread(request: Request, tid: str, label: str = "INBOX"):
    t = _thread(tid)
    _log_open(t)
    msgs = []
    for m in t.get("messages", []):
        msgs.append({**m, "atts": [_doc_label(a) for a in m.get("attachments", [])],
                     "to_s": _fmt_people(m.get("to", [])), "cc_s": _fmt_people(m.get("cc", []))})
    return web.page(request, "mail/thread.html", active_tab="mail", t=t, msgs=msgs, label=label,
                    counts=_counts(), system_labels=SYSTEM_LABELS, user_labels=_user_labels())


@router.get("/mail/compose")
def mail_compose(request: Request, mode: str = "new", thread: str = "", to: str = "", subject: str = "",
                 attach: str = ""):
    if mode not in ("new", "reply", "reply_all", "forward", "draft"):
        mode = "new"
    f = {"to": to, "cc": "", "subject": subject, "body": "", "attachments": web.as_list(attach), "thread_id": "",
         "draft_id": ""}
    t = store.get("threads", thread) if thread else None
    if t and mode == "draft":
        dm = t["messages"][-1]
        f.update({"to": ", ".join(p["email"] for p in dm.get("to", [])), "cc": ", ".join(p["email"] for p in dm.get("cc", [])),
                  "subject": t.get("subject", ""), "body": dm.get("body", ""), "attachments": dm.get("attachments", []),
                  "draft_id": t["id"], "thread_id": dm.get("reply_to_thread") or ""})
        mode = dm.get("draft_mode") or "new"
        return web.page(request, "mail/compose.html", active_tab="mail", mode=mode, f=f, t=None, docs=_all_docs(),
                        counts=_counts(), system_labels=SYSTEM_LABELS, user_labels=_user_labels(), label="")
    if t and mode != "new" and t.get("messages"):
        f["thread_id"] = t["id"]
        last = _last(t)
        # message to reply to: latest one not from me (fallback: latest)
        src = next((m for m in reversed(t["messages"]) if not _is_me(m["from"]["email"])), last)
        if mode in ("reply", "reply_all"):
            f["subject"] = _prefix(t.get("subject", ""), "Re:")
            if _is_me(src["from"]["email"]):
                tos = [p["email"] for p in src.get("to", [])]
            else:
                tos = [src["from"]["email"]]
            ccs: List[str] = []
            if mode == "reply_all":
                for p in src.get("to", []) + src.get("cc", []):
                    e = p["email"]
                    if not _is_me(e) and e not in tos and e not in ccs:
                        ccs.append(e)
            f["to"] = to or ", ".join(tos)
            f["cc"] = ", ".join(ccs)
            f["body"] = _quote(last)
        else:
            f["subject"] = _prefix(t.get("subject", ""), "Fwd:")
            f["body"] = _fwd_block(last).replace("{subject}", t.get("subject", ""))
            atts = []
            for m in t["messages"]:
                for a in m.get("attachments", []):
                    if a not in atts:
                        atts.append(a)
            f["attachments"] = atts + [a for a in f["attachments"] if a not in atts]
    return web.page(request, "mail/compose.html", active_tab="mail", mode=mode, f=f, t=t, docs=_all_docs(),
                    counts=_counts(), system_labels=SYSTEM_LABELS, user_labels=_user_labels(), label="")


# ---------------------------------------------------------------- JSON reads

@router.get("/api/mail/threads")
def api_threads(label: str = "INBOX", q: str = ""):
    q = q.strip()
    if q:
        _log_search(q, label)
    return {"threads": [_summary(t) for t in _list(label or "INBOX", q)]}


@router.get("/api/mail/thread/{tid}")
def api_thread(tid: str):
    t = _thread(tid)
    _log_open(t)
    out = dict(t)
    out["messages"] = [{**m, "attachment_docs": [_doc_label(a) for a in m.get("attachments", [])]}
                       for m in t.get("messages", [])]
    return {"thread": out}


@router.get("/api/mail/labels")
def api_labels():
    return {"system": [k for k, _ in SYSTEM_LABELS], "user": _user_labels(), "unread": _counts()}


# ---------------------------------------------------------------- writes

@router.post("/api/mail/send")
async def api_send(request: Request):
    b = await web.body(request)
    mode = b.get("mode") or "new"
    if mode not in ("new", "reply", "reply_all", "forward"):
        raise HTTPException(400, "mode must be new|reply|reply_all|forward")
    to = [_person(x) for x in web.as_list(b.get("to"))]
    cc = [_person(x) for x in web.as_list(b.get("cc"))]
    if not to and not cc:
        raise HTTPException(400, "Add at least one recipient in To")
    subject = (b.get("subject") or "").strip() or "(no subject)"
    text = b.get("body") or ""
    atts = [a for a in web.as_list(b.get("attachments")) if a]
    atts = list(dict.fromkeys(atts))
    for a in atts:
        if not store.get("docs", a):
            raise HTTPException(400, f"Unknown attachment doc id: {a}")
    tid = b.get("thread_id") or ""
    t = store.get("threads", tid) if tid else None
    if mode != "new" and tid and not t:
        raise HTTPException(404, "Thread not found")

    emails = [p["email"] for p in to + cc]
    rcls = events.recipients_class(emails)

    worst_sens, worst_disc = None, None
    for a in atts:
        d = store.get("docs", a)
        sens = d.get("sensitivity") or "internal"
        events.emit("jmail", "jmail.attach", "doc", a, {"sensitivity": sens, "recipient": rcls})
        if sens in SENS_RANK and (worst_sens is None or SENS_RANK.index(sens) > SENS_RANK.index(worst_sens)):
            worst_sens = sens
        if d.get("kind") == "offer" and d.get("offer"):
            pct = d["offer"].get("discount_pct") or 0
            dc = events.discount_class(float(pct))
            events.emit("quote", "quote.discount", "doc", a, {"discount": dc})
            if worst_disc is None or dc == "over_limit":
                worst_disc = dc

    action = {"new": "jmail.send", "reply": "jmail.reply", "reply_all": "jmail.reply",
              "forward": "jmail.forward"}[mode]
    ctx = {"recipient": rcls}
    if worst_sens:
        ctx["attachment"] = worst_sens
    if worst_disc:
        ctx["discount"] = worst_disc

    msg = {"id": store.new_id("m"), "from": dict(ME_PERSON), "to": to, "cc": cc, "ts": store.now_iso(),
           "body": text, "attachments": atts}
    new_tid = tid if (t and mode != "new") else store.new_id("th")

    draft_id = b.get("draft_id") or ""

    def apply():
        if draft_id:
            store.remove("threads", draft_id)
        th = store.get("threads", new_tid)
        if th:
            th["messages"].append(msg)
            if "SENT" not in th["labels"]:
                th["labels"].append("SENT")
            if "TRASH" in th["labels"]:
                th["labels"].remove("TRASH")
        else:
            th = store.add("threads", {"id": new_tid, "subject": subject, "labels": ["SENT"], "unread": False,
                                       "starred": False, "messages": [msg]})
        return {"thread_id": th["id"], "message_id": msg["id"]}

    args = {"mode": mode, "to": [p["email"] for p in to], "cc": [p["email"] for p in cc], "subject": subject,
            "attachments": atts, "body_chars": len(text)}
    res = events.commit("jmail", action, "thread", tid or None, args, ctx, apply=apply, irreversible=True)
    return web.ok(res, redirect=f"/mail/thread/{new_tid}", thread_id=new_tid)


@router.post("/api/mail/draft")
async def api_draft(request: Request):
    """Save (or update) a draft. Reversible; nothing leaves the mailbox."""
    b = await web.body(request)
    to = [_person(x) for x in web.as_list(b.get("to"))]
    cc = [_person(x) for x in web.as_list(b.get("cc"))]
    atts = list(dict.fromkeys(a for a in web.as_list(b.get("attachments")) if a and store.get("docs", a)))
    draft_id = b.get("draft_id") or store.new_id("th")
    existing = store.get("threads", draft_id)
    msg = {"id": store.new_id("m"), "from": dict(ME_PERSON), "to": to, "cc": cc, "ts": store.now_iso(),
           "body": b.get("body") or "", "attachments": atts, "draft": True,
           "draft_mode": b.get("mode") or "new", "reply_to_thread": b.get("thread_id") or None}
    emails = [p["email"] for p in to + cc]

    def apply():
        th = store.get("threads", draft_id)
        if th:
            th["messages"] = [msg]
            th["subject"] = (b.get("subject") or "").strip() or "(no subject)"
        else:
            store.items("threads").insert(0, {"id": draft_id, "subject": (b.get("subject") or "").strip() or "(no subject)",
                                              "labels": ["DRAFT"], "unread": False, "starred": False, "messages": [msg]})
        return draft_id

    res = events.commit("jmail", "jmail.draft_save", "thread", draft_id if existing else None,
                        {"to": emails, "subject": b.get("subject"), "attachments": atts, "body_chars": len(b.get("body") or "")},
                        {"recipient": events.recipients_class(emails) if emails else None}, apply=apply)
    return web.ok(res, redirect=f"/mail?label=DRAFT", draft_id=draft_id)


async def _simple(request: Request, action: str, mutate, ctx_fn=None, redirect_list: bool = True):
    b = await web.body(request)
    t = _thread(b.get("thread_id") or "")
    ctx = ctx_fn(b) if ctx_fn else {}
    args = {k: v for k, v in b.items() if k != "thread_id"}

    def apply():
        th = store.get("threads", t["id"])
        mutate(th, b)
        return {"thread_id": th["id"], "labels": th["labels"]}

    res = events.commit("jmail", action, "thread", t["id"], args, ctx, apply=apply, irreversible=False)
    back = b.get("back") or "/mail?label=INBOX"
    if not back.startswith("/mail"):
        back = "/mail"
    return web.ok(res, redirect=back if redirect_list else f"/mail/thread/{t['id']}", thread_id=t["id"])


def _norm_label(lab: str) -> str:
    lab = (lab or "").strip()
    for k, _ in SYSTEM_LABELS:
        if lab.upper() == k:
            return k
    return lab


@router.post("/api/mail/label")
async def api_label(request: Request):
    b = await web.body(request)
    lab = _norm_label(b.get("label", ""))
    if not lab:
        raise HTTPException(400, "label required")
    op = b.get("op") or "add"
    if op not in ("add", "remove"):
        raise HTTPException(400, "op must be add|remove")

    def mutate(th, _b):
        if lab == "STARRED":
            th["starred"] = op == "add"
        elif op == "add" and lab not in th["labels"]:
            th["labels"].append(lab)
        elif op == "remove" and lab in th["labels"]:
            th["labels"].remove(lab)

    t = _thread(b.get("thread_id") or "")
    args = {"label": lab, "op": op}

    def apply():
        th = store.get("threads", t["id"])
        mutate(th, b)
        return {"thread_id": th["id"], "labels": th["labels"]}

    res = events.commit("jmail", "jmail.label", "thread", t["id"], args, {"label": lab}, apply=apply)
    return web.ok(res, redirect=f"/mail/thread/{t['id']}", thread_id=t["id"])


def _archive(th, _b):
    if "INBOX" in th["labels"]:
        th["labels"].remove("INBOX")
    if "TRASH" in th["labels"]:
        th["labels"].remove("TRASH")
    if "ARCHIVE" not in th["labels"]:
        th["labels"].append("ARCHIVE")


def _delete(th, _b):
    if "INBOX" in th["labels"]:
        th["labels"].remove("INBOX")
    if "TRASH" not in th["labels"]:
        th["labels"].append("TRASH")


def _unread(th, _b):
    th["unread"] = True


@router.post("/api/mail/archive")
async def api_archive(request: Request):
    return await _simple(request, "jmail.archive", _archive)


@router.post("/api/mail/delete")
async def api_delete(request: Request):
    return await _simple(request, "jmail.delete", _delete)


@router.post("/api/mail/mark_unread")
async def api_mark_unread(request: Request):
    return await _simple(request, "jmail.mark_unread", _unread)
