"""Agent Monitor server (ADR 0001). Local: `uv run uvicorn server:app --port 8780`.

One deploy, two apps:
- The ShiftPoint workspace (`workspace.main.create_app`): its own FastAPI app with its own world
  (Jmail /mail, Jdrive /drive, Habspot /crm, Calendario /calendar, quotes), mounted at "/" last.
  Every agent write passes its single gate, which runs the monitor in-process.
- The monitor: run APIs for the canvas (scenarios/runner.py, agent/live.py), Unbox catalog
  tools, and the canvas (`web/`) at /monitor/ ("/" redirects there).

State lives in a StateStore (workspace/state.py): process memory locally, Upstash Redis on Vercel.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from agent import live
from monitor.catalog import load_catalog
from monitor.unbox import (
    NAME_RE,
    PORTAL_CATALOGS,
    SLOTS,
    get_client,
    plan_push,
    read_csv,
    validate_rows,
)
from scenarios import runner
from workspace import events, session
from workspace.main import create_app
from workspace.state import MemoryStore, make_store

STATE = make_store()
DEFAULT_SCENARIO = "acme_after_call"
WORKSPACE = create_app(standalone=False, state=STATE)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if isinstance(STATE, MemoryStore):
        events.restore(None)  # seed the world in process memory
    yield


app = FastAPI(title="Agent Monitor", lifespan=lifespan)
session.install(app, STATE)  # state load/save + actor, around the monitor APIs and the workspace


class RunIn(BaseModel):
    scenario: str | None = None
    mistakes: bool = True
    instruction: str | None = None


class PreviewIn(BaseModel):
    catalog_id: str
    after: list[str] = []


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "state": STATE.name}


def _calibration() -> dict[str, Any]:
    path = ROOT / "monitor" / "calibration.json"
    return json.loads(path.read_text()) if path.exists() else {}


@app.get("/api/bootstrap")
def bootstrap() -> dict[str, Any]:
    sc = runner.load(DEFAULT_SCENARIO)
    cal = _calibration()
    gng_path = ROOT / "results" / "go_no_go.json"
    gng = json.loads(gng_path.read_text()) if gng_path.exists() else {}
    return {
        "company": {"name": "ShiftPoint", "persona": "Alex Chen"},
        "scenario": {
            "id": sc["id"],
            "title": sc["title"],
            "request": sc["request"],
            "account": sc["account"],
            "steps": {
                "careful": len(runner.steps_for(sc, False)),
                "mistakes": len(runner.steps_for(sc, True)),
            },
        },
        "apps": {"mail": "/mail", "drive": "/drive", "crm": "/crm/deals", "calendar": "/calendar"},
        "catalog": {
            a.id: {"name": a.name, "app": a.app, "irreversible": a.irreversible, "role": a.role}
            for a in load_catalog().values()
        },
        "rankers": {
            k: {key: v.get(key) for key in ("barrier", "caught", "missed", "false_alarms")}
            for k, v in (cal.get("rankers") or {}).items()
        },
        "default_ranker": cal.get("default", "workflow"),
        "go_no_go": {
            k: gng.get(k) for k in ("careful_median_rank", "careful_top5_share", "catalog_size")
        },
        "live_available": live.available(),
        "behaviorgpt_live": bool(os.environ.get("UNBOXAI_API_KEY")),
        "state": STATE.name,
    }


@app.post("/api/runs")
async def start_run(body: RunIn) -> dict[str, Any]:
    if body.instruction:
        if not live.available():
            raise HTTPException(400, "Live mode needs ANTHROPIC_API_KEY on the server.")
        return live.start(body.instruction)
    try:
        return runner.start(body.scenario or DEFAULT_SCENARIO, body.mistakes)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@app.post("/api/runs/current/next")
async def next_step() -> dict[str, Any]:
    if (events.RUN_STATE.get("live") or {}).get("active"):
        return await live.next_step(WORKSPACE)
    return await runner.next_step(WORKSPACE)


@app.get("/api/runs/current")
def current_run() -> dict[str, Any]:
    return runner.current()


@app.get("/")
def home() -> RedirectResponse:
    return RedirectResponse("/monitor/")


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


app.mount("/monitor", StaticFiles(directory=ROOT / "web", html=True), name="monitor")
# Declared last: the workspace app answers everything the monitor doesn't.
app.mount("/", WORKSPACE, name="workspace")
