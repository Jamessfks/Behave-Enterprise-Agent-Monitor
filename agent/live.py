"""Live mode: a Claude agent works in the ShiftPoint workspace on any typed request.

Its tools are the workspace's own JSON routes, called in-process as the agent (workspace/
dispatch.py), so every tool call passes the same gate as the scripted runs and changes the same
apps. The canvas steps it one tool call at a time (`POST /api/runs/current/next`). A paused tool
call waits for a person's Allow/Block; the decision goes back to Claude as the tool result.
State lives in `events.RUN_STATE["live"]` (part of the workspace snapshot), so each request is
short and works on Vercel. At most one Claude call per request.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from fastapi import FastAPI

from workspace import dispatch, events, store

MODEL = "claude-opus-5-5"
MAX_TURNS = 40
PATH_PARAM = re.compile(r"\{([a-z_]+)\}")

# name -> (method, path, description, input properties, required)
TOOLS: dict[str, tuple[str, str, str, dict[str, Any], list[str]]] = {
    "list_inbox": ("GET", "/api/mail/threads", "List email threads (optionally by label or search text).",
                   {"label": {"type": "string"}, "q": {"type": "string"}}, []),
    "open_email_thread": ("GET", "/api/mail/thread/{thread_id}", "Open an email thread.",
                          {"thread_id": {"type": "string"}}, ["thread_id"]),
    "send_email": ("POST", "/api/mail/send", "Send an email (mode new|reply|reply_all|forward).",
                   {"mode": {"type": "string"}, "to": {"type": "string"}, "cc": {"type": "string"},
                    "subject": {"type": "string"}, "body": {"type": "string"}, "thread_id": {"type": "string"},
                    "attachments": {"type": "array", "items": {"type": "string"}}}, ["to", "subject", "body"]),
    "save_email_draft": ("POST", "/api/mail/draft", "Save an email as a draft without sending it.",
                         {"mode": {"type": "string"}, "to": {"type": "string"}, "cc": {"type": "string"},
                          "subject": {"type": "string"}, "body": {"type": "string"},
                          "attachments": {"type": "array", "items": {"type": "string"}}}, ["to", "subject", "body"]),
    "search_drive": ("GET", "/api/drive/docs", "Search documents in Jdrive.", {"q": {"type": "string"}}, []),
    "open_document": ("GET", "/api/drive/doc/{doc_id}", "Open a Jdrive document (transcripts, RFPs, policies).",
                      {"doc_id": {"type": "string"}}, ["doc_id"]),
    "search_crm": ("GET", "/api/crm/search", "Search Habspot companies, contacts and deals.",
                   {"q": {"type": "string"}}, ["q"]),
    "open_company": ("GET", "/api/crm/company/{company_id}", "Open a Habspot company.",
                     {"company_id": {"type": "string"}}, ["company_id"]),
    "open_deal": ("GET", "/api/crm/deal/{deal_id}", "Open a Habspot deal.", {"deal_id": {"type": "string"}}, ["deal_id"]),
    "add_deal_note": ("POST", "/api/crm/note", "Append a note to a deal.",
                      {"deal_id": {"type": "string"}, "body": {"type": "string"}}, ["deal_id", "body"]),
    "update_deal": ("POST", "/api/crm/deal/{deal_id}/update", "Update deal fields (amount, close_date, next_step, next_step_date).",
                    {"deal_id": {"type": "string"}, "amount": {"type": "number"}, "close_date": {"type": "string"},
                     "next_step": {"type": "string"}, "next_step_date": {"type": "string"}}, ["deal_id"]),
    "set_deal_stage": ("POST", "/api/crm/deal/{deal_id}/stage", "Move a deal to a stage.",
                       {"deal_id": {"type": "string"}, "stage": {"type": "string"}}, ["deal_id", "stage"]),
    "create_quote": ("POST", "/api/quotes/create", "Create a quote (offer doc) for a deal.",
                     {"deal_id": {"type": "string"}, "plan": {"type": "string"}, "locations": {"type": "integer"},
                      "discount_pct": {"type": "number"}, "onboarding": {"type": "string"}}, ["deal_id", "plan", "locations"]),
    "request_quote_approval": ("POST", "/api/quotes/{doc_id}/request_approval", "Ask the sales manager to approve a quote's discount.",
                               {"doc_id": {"type": "string"}, "note": {"type": "string"}}, ["doc_id"]),
    "send_quote": ("POST", "/api/quotes/{doc_id}/send", "Send a quote to the client.",
                   {"doc_id": {"type": "string"}, "to": {"type": "string"}, "subject": {"type": "string"},
                    "body": {"type": "string"}}, ["doc_id", "to"]),
    "create_calendar_event": ("POST", "/api/calendar/create", "Book a meeting.",
                              {"title": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
                               "attendees": {"type": "string"}, "deal": {"type": "string"}}, ["title", "start", "end"]),
    "finish": ("", "", "Call when the task is done, with a one-paragraph summary for the person.",
               {"summary": {"type": "string"}}, ["summary"]),
}


def tool_specs() -> list[dict[str, Any]]:
    return [
        {"name": n, "description": d, "input_schema": {"type": "object", "properties": props, "required": req}}
        for n, (_m, _p, d, props, req) in TOOLS.items()
    ]


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def system_prompt(instruction: str) -> str:
    written = json.loads((store.ROOT / "world" / "rules" / "written_rules.json").read_text())
    rules = written.get("rules", written) if isinstance(written, dict) else written
    policies = "\n".join(f"- {r.get('text') or r.get('rule') or r.get('id')}" for r in rules)
    return (
        "You are Alex Chen's assistant at ShiftPoint (shift-scheduling software sold per location). "
        "Work only through your tools, in Jmail, Jdrive, Habspot and Calendario.\n\n"
        f"Written policies:\n{policies}\n\n"
        "Read the relevant sources before acting and use only facts you found. When sources "
        "disagree, ask Alex (alex@shiftpoint.io) instead of choosing. A person supervises every "
        "step and may pause or block it; if a step is blocked, don't retry it, continue another "
        f"way. Call `finish` when done.\n\nTask:\n{instruction}"
    )


def start(instruction: str) -> dict[str, Any]:
    store.reset()
    run = events.start_run(agent="live", actor="agent", label=f"Live: {instruction[:60]}")
    events.RUN_STATE["live"] = {"active": True, "instruction": instruction, "messages": [], "queue": [],
                                "results": [], "awaiting": None, "done": False, "summary": None, "steps": []}
    events.RUN_STATE.pop("scenario", None)
    store.save()
    return {"run": {**run, "scenario": None, "mistakes": None, "live": True}, "steps_total": None}


def _client():
    import anthropic

    return anthropic.Anthropic()


def _route(name: str, args: dict[str, Any]) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    method, path, *_ = TOOLS[name]
    params = PATH_PARAM.findall(path)
    filled = PATH_PARAM.sub(lambda m: str(args.get(m.group(1), "")), path)
    rest = {k: v for k, v in args.items() if k not in params}
    return method, filled, (rest if method == "POST" else {}), (rest if method == "GET" else {})


async def next_step(app: FastAPI, client: Any = None) -> dict[str, Any]:
    from scenarios import runner

    lv = events.RUN_STATE["live"]
    if lv.get("awaiting") and lv["awaiting"]["approval_id"] not in events.PENDING:
        aw = lv["awaiting"]
        replayed = next((e for e in reversed(events.EVENTS) if e.get("approval_id") == aw["approval_id"]), None)
        text = "Approved by a person and done." if replayed else (
            "Blocked by a supervisor. Don't retry this step; continue another way.")
        lv["results"].append({"type": "tool_result", "tool_use_id": aw["tool_use_id"], "content": text})
        lv["awaiting"] = None
    if lv.get("awaiting"):
        return {"done": False, "waiting": lv["awaiting"], "step": None, "changed": runner.changed()}
    if lv["done"]:
        return {"done": True, "step": None, "changed": runner.changed(), "summary": lv["summary"]}

    if not lv["queue"]:
        if lv["results"]:
            lv["messages"].append({"role": "user", "content": lv["results"]})
            lv["results"] = []
        if not lv["messages"]:
            lv["messages"].append({"role": "user", "content": "Start the task now."})
        if sum(m["role"] == "assistant" for m in lv["messages"]) >= MAX_TURNS:
            lv.update(done=True, summary="Stopped: turn limit reached.")
            store.save()
            return {"done": True, "step": None, "changed": runner.changed(), "summary": lv["summary"]}
        resp = (client or _client()).messages.create(
            model=MODEL, max_tokens=2048, system=system_prompt(lv["instruction"]),
            tools=tool_specs(), messages=lv["messages"],
        )
        content = [b.model_dump(exclude_none=True) for b in resp.content]
        lv["messages"].append({"role": "assistant", "content": content})
        lv["queue"] = [b for b in content if b.get("type") == "tool_use"]
        if not lv["queue"]:
            text = next((b.get("text") for b in content if b.get("type") == "text"), "Finished.")
            lv.update(done=True, summary=text)
            store.save()
            return {"done": True, "step": None, "changed": runner.changed(), "summary": text}

    block = lv["queue"].pop(0)
    name, args = block["name"], block.get("input") or {}
    if name == "finish" or name not in TOOLS:
        lv["results"].append({"type": "tool_result", "tool_use_id": block["id"], "content": "Done."})
        lv.update(done=True, summary=args.get("summary", ""))
        store.save()
        return {"done": True, "step": None, "changed": runner.changed(), "summary": lv["summary"]}

    method, path, body, query = _route(name, args)
    before = len(events.EVENTS)
    status, out = await dispatch.call(app, method, path, body, query)
    ev = runner._step_event(events.EVENTS[before:])
    spec = {"label": f"{name.replace('_', ' ').capitalize()}", "method": method}
    view = runner.step_view(ev, spec, len(lv["steps"]), path.replace("/api", "", 1) if method == "GET" else "")
    if status == 202:
        approval_id = (out.get("detail") or {}).get("approval_id")
        lv["awaiting"] = {"approval_id": approval_id, "tool_use_id": block["id"]}
        view["approval_id"] = approval_id
    else:
        text = json.dumps(out)[:4000] if status < 300 else f"Error {status}: {json.dumps(out)[:1000]}"
        lv["results"].append({"type": "tool_result", "tool_use_id": block["id"], "content": text})
    lv["steps"].append(view)
    store.save()
    return {"done": False, "step": view, "changed": runner.changed()}
