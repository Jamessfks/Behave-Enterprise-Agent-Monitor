"""Agent Monitor: one stateless FastAPI app (local: `uv run uvicorn server:app`; also Vercel).

The browser holds each run and calls /api/check per step, so no session lives on the server.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from agent import live
from env.app import new_state
from env.company import default_context, merged, validate_context
from env.scenario import SOURCES, TRIGGER
from monitor.catalog import load_catalog
from monitor.core import calibration, check_step, checks, default_ranker, learned_rule
from monitor.events import EventError, load_run, validate_event
from monitor.unbox import (
    NAME_RE,
    PORTAL_CATALOGS,
    SLOTS,
    get_client,
    plan_push,
    read_csv,
    validate_rows,
)

app = FastAPI(title="Agent Monitor")

RUN_LABELS = {"careful_01": "Careful agent", "faulty": "Faulty agent"}


class CheckIn(BaseModel):
    history: list[dict[str, Any]]
    event: dict[str, Any]
    context: dict[str, Any] | None = None
    cusum: float = 0.0
    ranker: str | None = None


class LearnIn(BaseModel):
    event: dict[str, Any]
    failed: list[str]
    reason: str


class ContextIn(BaseModel):
    context: dict[str, Any]


class PreviewIn(BaseModel):
    catalog_id: str
    after: list[str] = []


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.get("/api/bootstrap")
def bootstrap() -> dict[str, Any]:
    cat = load_catalog()
    cal = calibration()
    gng_path = ROOT / "results" / "go_no_go.json"
    gng = json.loads(gng_path.read_text()) if gng_path.exists() else {}
    return {
        "catalog": {
            a.id: {"name": a.name, "app": a.app, "irreversible": a.irreversible, "role": a.role}
            for a in cat.values()
        },
        "runs": {k: load_run(ROOT / "runs" / f"{k}.jsonl") for k in RUN_LABELS},
        "run_labels": RUN_LABELS,
        "trigger": TRIGGER,
        "sources": {
            k: {"tab": s["tab"], "title": s["title"], "text": s["text"]} for k, s in SOURCES.items()
        },
        "context": default_context(),
        "rankers": {
            k: {
                "barrier": v["barrier"],
                "caught": v["caught"],
                "missed": v["missed"],
                "false_alarms": v["false_alarms"],
            }
            for k, v in cal["rankers"].items()
            if k in checks()
        },
        "default_ranker": default_ranker(),
        "go_no_go": {
            "careful_median_rank": gng.get("careful_median_rank"),
            "careful_top5_share": gng.get("careful_top5_share"),
            "catalog_size": gng.get("catalog_size"),
        },
        "live_available": live.available(),
        "behaviorgpt_live": bool(os.environ.get("UNBOXAI_API_KEY")),
    }


@app.post("/api/check")
def check(body: CheckIn) -> dict[str, Any]:
    try:
        validate_event({**body.event, "run_id": body.event.get("run_id", "x")})
    except EventError as e:
        raise HTTPException(422, f"bad event: {e}") from e
    ctx = merged(default_context(), body.context) if body.context else None
    return check_step(body.history, body.event, ctx, body.cusum, body.ranker)


@app.post("/api/rules/learn")
def learn(body: LearnIn) -> dict[str, Any]:
    if not body.reason.strip():
        raise HTTPException(422, "Allow needs a reason; it becomes a rule.")
    return learned_rule(body.event, body.failed, body.reason)


@app.post("/api/context/validate")
def context_validate(body: ContextIn) -> dict[str, Any]:
    ctx = merged(default_context(), body.context)
    return {"errors": validate_context(ctx), "context": ctx}


@app.get("/api/catalogs")
def catalogs() -> dict[str, Any]:
    """The account's catalogs on the Unbox portal, slots used, and which one the app uses."""
    current = os.environ.get("UNBOXAI_CATALOG_ID")
    rec_path = ROOT / "catalog" / "unbox.json"
    record = json.loads(rec_path.read_text()) if rec_path.exists() else None
    out: dict[str, Any] = {
        "portal": PORTAL_CATALOGS,
        "slots": SLOTS,
        "current": current or (record or {}).get("catalog_id"),
        "record": record,
    }
    if not os.environ.get("UNBOXAI_API_KEY"):
        return {**out, "available": False, "owned": []}
    mine = [x for x in get_client().list_catalogs() if x.owned]
    return {
        **out,
        "available": True,
        "owned": [
            {"catalog_id": x.catalog_id, "name": x.catalog_name, "status": x.status} for x in mine
        ],
    }


@app.post("/api/catalog/upload")
async def catalog_upload(
    file: Annotated[UploadFile, File()], embed: bool = False, name: str = "company_actions"
) -> dict[str, Any]:
    """Validate a company's action catalog CSV; with embed=true, upload it to the Unbox portal
    under `name` (same name refreshes that catalog; a new name takes a free slot)."""
    raw = (await file.read()).decode("utf-8-sig")
    if len(raw) > 2_000_000:
        raise HTTPException(413, "Catalog CSV is over 2 MB.")
    rows = read_csv(raw)
    errors = validate_rows(rows)
    if not NAME_RE.match(name):
        errors.append("catalog name: lowercase letters, digits, '_' or '-', 2-63 characters")
    summary: dict[str, Any] = {
        "rows": len(rows),
        "columns": sorted(rows[0]) if rows else [],
        "errors": errors,
        "sample": [{"id": r.get("id"), "name": r.get("name")} for r in rows[:5]],
        "name": name,
    }
    if errors or not embed:
        return summary
    if not os.environ.get("UNBOXAI_API_KEY"):
        raise HTTPException(400, "Embedding needs UNBOXAI_API_KEY on the server.")
    from behaviorgpt import catalog_from_csv

    client = get_client()
    mode, existing = plan_push(name, [x for x in client.list_catalogs() if x.owned])
    if mode == "full":
        raise HTTPException(
            409,
            f"Both catalog slots on your Unbox account are used and none is named {name!r}. "
            "Upload under an existing name to refresh it, or delete one on the portal.",
        )
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"{name}.csv"  # the file name becomes the catalog's name
        src.write_text(raw)
        try:
            parquet = catalog_from_csv(str(src))
            job = client.embed(parquet, wait=False)
        except Exception as e:
            raise HTTPException(400, f"BehaviorGPT refused the catalog: {e}") from e
    return {
        **summary,
        "job_id": job.job_id,
        "status": "embedding",
        "mode": mode,
        "replaces": existing,
    }


@app.get("/api/catalog/status")
def catalog_status(job_id: str) -> dict[str, Any]:
    st = get_client().job_status(job_id)
    return {
        "status": getattr(st, "status", None),
        "catalog_id": getattr(st, "catalog_id", None),
        "error": getattr(st, "error", None),
    }


@app.post("/api/catalog/preview")
def catalog_preview(body: PreviewIn) -> dict[str, Any]:
    """BehaviorGPT's top predicted next actions after `after`, on any embedded catalog."""
    from behaviorgpt import View

    if not os.environ.get("UNBOXAI_API_KEY"):
        raise HTTPException(400, "Preview needs UNBOXAI_API_KEY on the server.")
    res = get_client().complete(
        [View(a) for a in body.after], limit=8, catalog_id=body.catalog_id, register_event=False
    )
    return {"next": [{"id": i.id, "name": i.data.get("name"), "score": i.score} for i in res.items]}


@app.post("/api/agent/start")
def agent_start(body: dict[str, Any]) -> dict[str, Any]:
    if not live.available():
        raise HTTPException(400, "Live mode needs ANTHROPIC_API_KEY on the server.")
    ctx = merged(default_context(), body.get("context") or {})
    return {
        "instruction": body.get("instruction") or TRIGGER["text"],
        "context": ctx,
        "state": new_state(),
        "history": [],
        "messages": [],
        "queue": [],
        "results": [],
        "cusum": 0.0,
        "ranker": body.get("ranker"),
        "run_id": "live",
        "pending": None,
    }


@app.post("/api/agent/step")
def agent_step(body: dict[str, Any]) -> dict[str, Any]:
    if not live.available():
        raise HTTPException(400, "Live mode needs ANTHROPIC_API_KEY on the server.")
    return live.step(body)


# Declared last: API routes above take priority over the static files.
app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
