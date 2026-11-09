"""Live mode with computer use: a Gemini agent clicks through the workspace in a real browser.

The agent (computer_use/gemini_agent.py, a separate process) sees screenshots of the ShiftPoint
apps and clicks and types like a person. Its browser sends `X-Actor: agent`, so every page it
opens is logged and scored and every save goes through the same write gate as the demo runs
(ADR 0005): a paused write shows the "waiting for approval" banner on the agent's screen and a
pause card on the canvas. The canvas follows the run with `POST /api/runs/current/next`, which
waits briefly for the agent's next logged step. Local only: it needs a browser on this machine.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from workspace import events, store

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / ".untracked"
MODEL = os.environ.get("COMPUTER_USE_MODEL", "gemini-3.5-flash-lite")
WAIT_S = 20.0  # how long one /next call waits for the agent's next step
PROC: dict[str, Any] = {"p": None}


def gemini_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key and os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                key = winreg.QueryValueEx(k, "GEMINI_API_KEY")[0]
        except OSError:
            key = None
    return key or None


def available() -> bool:
    """A Gemini key, and a machine with a browser (not a serverless deploy)."""
    return bool(gemini_key()) and not os.environ.get("VERCEL")


def running() -> bool:
    p = PROC["p"]
    return p is not None and p.poll() is None


def stop() -> None:
    p = PROC["p"]
    if p is not None and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    PROC["p"] = None


def start(instruction: str, base_url: str, model: str | None = None) -> dict[str, Any]:
    stop()
    store.reset()
    model = model or MODEL
    run = events.start_run(
        agent="computer_use", actor="agent", label=f"Live, computer use: {instruction[:60]}"
    )
    events.RUN_STATE["live"] = {
        "active": True,
        "mode": "computer_use",
        "model": model,
        "instruction": instruction,
        "cursor": len(events.EVENTS),
        "steps": [],
        "awaiting": None,
        "done": False,
        "summary": None,
    }
    events.RUN_STATE.pop("scenario", None)
    store.save()
    LOG_DIR.mkdir(exist_ok=True)
    log = open(LOG_DIR / f"computer_use_{run['id']}.log", "w", encoding="utf-8")  # noqa: SIM115
    env = {**os.environ, "GEMINI_API_KEY": gemini_key() or "", "PYTHONUNBUFFERED": "1"}
    env["PYTHONIOENCODING"] = "utf-8"
    PROC["p"] = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "computer_use.gemini_agent",
            "--base",
            base_url,
            "--model",
            model,
            "--run-id",
            run["id"],
            "--instruction",
            instruction,
        ],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return {
        "run": {**run, "scenario": None, "mistakes": None, "live": True, "computer_use": model},
        "steps_total": None,
    }


def finish(run_id: str, summary: str) -> dict[str, Any]:
    """Called by the agent process when it is done (or gives up)."""
    lv = events.RUN_STATE.get("live") or {}
    if lv.get("mode") != "computer_use" or events.RUN.get("id") != run_id:
        return {"ok": False}
    if lv.get("done"):  # already ended by the server (e.g. a person blocked a flagged step)
        return {"ok": True}
    lv.update(done=True, summary=summary or "Finished.")
    store.save()
    return {"ok": True}


def _approval_id(e: dict[str, Any]) -> str:
    return f"ap_{e['id']}"  # how events.commit() names a paused write's approval


def _bgpt_flagged(e: dict[str, Any]) -> bool:
    return "behaviorgpt" in ((e.get("monitor") or {}).get("failed") or [])


def status() -> dict[str, Any]:
    """What the agent process polls before each turn: is it halted on a step BehaviorGPT
    flagged (waiting for a person), or stopped?"""
    lv = events.RUN_STATE.get("live") or {}
    held = next(
        (
            e
            for e in reversed(events.EVENTS)
            if e.get("decision") == "pause"
            and _approval_id(e) in events.PENDING
            and _bgpt_flagged(e)
        ),
        None,
    )
    return {
        "run_id": events.RUN.get("id"),
        "halted": held is not None,
        "reason": ((held or {}).get("monitor") or {}).get("headline", ""),
        "stopped": bool(lv.get("done")) or lv.get("mode") != "computer_use",
    }


def _meaningful(e: dict[str, Any]) -> bool:
    from scenarios import runner

    return (
        e.get("by") == "agent"
        and e.get("app") not in runner.SKIP_APPS
        and e.get("action") not in runner.SIDE_ACTIONS
    )


def _view(e: dict[str, Any], index: int) -> dict[str, Any]:
    from monitor.core import label
    from scenarios import runner

    action = e.get("action", "")
    read = not e.get("irreversible") and action.split(".")[-1].startswith(
        ("open", "list", "search", "view")
    )
    link = runner._link(e) or runner._doc_link(e) or {}
    spec = {"label": label(e.get("catalog_action")) or action, "method": "GET" if read else "POST"}
    view = runner.step_view(e, spec, index, link.get("url", "") if read else "")
    if not read and link and e.get("decision") in ("allow", "flag"):
        view["changes"] = [link]
        view["page"] = link["url"]
    return view


async def next_step(_app: Any = None) -> dict[str, Any]:
    from scenarios import runner

    lv = events.RUN_STATE["live"]
    aw = lv.get("awaiting")
    if aw and aw["approval_id"] not in events.PENDING:  # a person decided (the canvas drew it)
        allowed = any(e.get("approval_id") == aw["approval_id"] for e in events.EVENTS)
        if aw.get("behaviorgpt") and not allowed:
            stop()  # blocking a step BehaviorGPT flagged ends the run
            lv.update(
                done=True,
                summary="Stopped by a person: they blocked a step BehaviorGPT flagged as unusual.",
            )
        lv["awaiting"] = None
    if lv.get("awaiting"):
        return {"done": False, "waiting": lv["awaiting"], "step": None, "changed": runner.changed()}
    deadline = time.monotonic() + WAIT_S
    while True:
        new = events.EVENTS[lv["cursor"] :]
        for i, e in enumerate(new):
            if not _meaningful(e):
                continue
            lv["cursor"] += i + 1
            view = _view(e, len(lv["steps"]))
            if e.get("decision") == "pause":
                lv["awaiting"] = {"approval_id": _approval_id(e), "behaviorgpt": _bgpt_flagged(e)}
                view["approval_id"] = _approval_id(e)
            lv["steps"].append(view)
            store.save()
            return {"done": False, "step": view, "changed": runner.changed()}
        lv["cursor"] += len(new)
        if lv["done"] or not running():
            if not lv["done"]:
                lv.update(done=True, summary=lv.get("summary") or "The agent stopped.")
            store.save()
            return {
                "done": True,
                "step": None,
                "changed": runner.changed(),
                "summary": lv["summary"],
            }
        if time.monotonic() > deadline:
            return {"done": False, "step": None, "working": True, "changed": runner.changed()}
        await asyncio.sleep(0.3)
