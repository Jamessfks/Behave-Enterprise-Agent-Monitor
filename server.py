"""Agent Monitor: one stateless FastAPI app (local: `uv run uvicorn server:app`; also Vercel).

The browser holds each run and calls /api/check per step, so no session lives on the server.
"""

from __future__ import annotations

import csv
import io
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


REQUIRED = ["id", "name", "event_type", "group"]


@app.post("/api/catalog/upload")
async def catalog_upload(
    file: Annotated[UploadFile, File()], embed: bool = False
) -> dict[str, Any]:
    """Validate a company's action catalog CSV; with embed=true, upload it to BehaviorGPT."""
    raw = (await file.read()).decode("utf-8-sig")
    if len(raw) > 2_000_000:
        raise HTTPException(413, "Catalog CSV is over 2 MB.")
    rows = list(csv.DictReader(io.StringIO(raw)))
    cols = set(rows[0]) if rows else set()
    errors = [f"missing column {c!r}" for c in REQUIRED if c not in cols]
    ids = [r.get("id", "") for r in rows]
    if len(set(ids)) != len(ids):
        errors.append("duplicate ids")
    if any(not r.get("id") or not r.get("name") for r in rows):
        errors.append("every row needs an id and a name")
    summary = {
        "rows": len(rows),
        "columns": sorted(cols),
        "errors": errors,
        "sample": [{"id": r.get("id"), "name": r.get("name")} for r in rows[:5]],
    }
    if errors or not embed:
        return summary
    if not os.environ.get("UNBOXAI_API_KEY"):
        raise HTTPException(400, "Embedding needs UNBOXAI_API_KEY on the server.")
    from behaviorgpt import UnboxAIClient, catalog_from_csv

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "company_actions.csv"
        src.write_text(raw)
        try:
            parquet = catalog_from_csv(str(src))
            job = UnboxAIClient(market="us").embed(parquet, wait=False)
        except Exception as e:
            raise HTTPException(400, f"BehaviorGPT refused the catalog: {e}") from e
    return {**summary, "job_id": job.job_id, "status": "embedding"}


@app.get("/api/catalog/status")
def catalog_status(job_id: str) -> dict[str, Any]:
    from behaviorgpt import UnboxAIClient

    st = UnboxAIClient(market="us").job_status(job_id)
    return {
        "status": getattr(st, "status", None),
        "catalog_id": getattr(st, "catalog_id", None),
        "error": getattr(st, "error", None),
    }


@app.post("/api/catalog/preview")
def catalog_preview(body: PreviewIn) -> dict[str, Any]:
    """BehaviorGPT's top predicted next actions after `after`, on any embedded catalog."""
    from behaviorgpt import UnboxAIClient, View

    if not os.environ.get("UNBOXAI_API_KEY"):
        raise HTTPException(400, "Preview needs UNBOXAI_API_KEY on the server.")
    res = UnboxAIClient(market="us").complete(
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
