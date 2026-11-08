"""Click-level UI events (the PDF's "page opened, field set, button clicked").

Layer 1 (this file, never gated):  ui.page_view, ui.click, ui.field_set
Layer 2 (events.commit/log_read):  meaning-level actions like jmail.forward, habspot.stage
Both land in the same run log; the UI layer is marked with app="ui".

Browser: app.js posts clicks and field changes to /api/ui (sendBeacon).
Server:  a middleware logs ui.page_view for every HTML page GET.
Scripts: POST /api/ui themselves (see scripts/scenarios/run.py) so practice runs match live runs.
"""
import re
from typing import Optional

from fastapi import APIRouter, Request

from .. import events

router = APIRouter()

ID_SEG = re.compile(r"^(th|doc|dl|ct|co|ev|fd|nt|tk|ac|m|u|ap|run|ev_cal)_")
MAX_VALUE = 300


def page_slug(path: str) -> str:
    """'/crm/deal/dl_acme_foods' -> 'crm.deal'; '/drive/doc/doc_x/edit' -> 'drive.doc.edit'."""
    parts = [p for p in path.split("?")[0].strip("/").split("/") if p]
    if parts and parts[0] == "api":
        parts = parts[1:]
    keep = [p for p in parts if not ID_SEG.match(p)]
    return ".".join(keep) or "home"


def slug(text: Optional[str]) -> str:
    t = re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return t[:40] or "unlabeled"


def log_ui(kind: str, page: str, target: Optional[str] = None, field: Optional[str] = None,
           value=None, url: str = "", extra: Optional[dict] = None):
    ctx = {"page": page}
    args = {"url": url}
    if target is not None:
        ctx["target"] = target
    if field is not None:
        ctx["field"] = field
    if value is not None:
        args["value"] = str(value)[:MAX_VALUE]
    if extra:
        args.update(extra)
    return events.emit("ui", f"ui.{kind}", None, None, ctx, args)


@router.post("/api/ui")
async def ui_event(request: Request):
    """{kind: click|field_set|page_view, path, label?, field?, value?, href?, form?}"""
    try:
        b = await request.json()
    except Exception:
        return {"ok": False}
    kind = b.get("kind")
    path = b.get("path") or "/"
    page = page_slug(path)
    if kind == "click":
        log_ui("click", page, target=slug(b.get("label")), url=path,
               extra={k: b[k] for k in ("label", "href", "form") if b.get(k)})
    elif kind == "field_set":
        log_ui("field_set", page, field=slug(b.get("field")), value=b.get("value"), url=path,
               extra={"form": b.get("form")} if b.get("form") else None)
    elif kind == "page_view":
        log_ui("page_view", page, url=path)
    return {"ok": True}


def install(app):
    @app.middleware("http")
    async def page_views(request: Request, call_next):
        response = await call_next(request)
        p = request.url.path
        if (request.method == "GET" and response.status_code == 200
                and not p.startswith(("/api/", "/static/")) and p != "/favicon.ico"
                and "text/html" in response.headers.get("content-type", "")):
            q = ("?" + request.url.query) if request.url.query else ""
            log_ui("page_view", page_slug(p), url=p + q)
        return response
