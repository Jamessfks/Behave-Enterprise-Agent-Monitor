"""The merged app end to end: the workspace (its own FastAPI app) mounted in the monitor server,
scripted runs executing against it, approvals replaying the original request, no disk writes."""

import builtins
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from workspace import events, store
from workspace.state import decode, encode


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("UNBOXAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(server.app) as c:
        yield c


def play(c, mistakes, decide=lambda step: ("approve", "ok")):
    c.post("/api/runs", json={"scenario": "acme_after_call", "mistakes": mistakes})
    steps = []
    while True:
        n = c.post("/api/runs/current/next").json()
        if n.get("step"):
            steps.append(n["step"])
            if n["step"]["decision"] == "pause":
                action, reason = decide(n["step"])
                c.post(f"/api/approvals/{n['step']['approval_id']}/{action}", json={"reason": reason})
        if n.get("done"):
            return steps, n["changed"]


def deal(c):
    d = c.get("/api/crm/deal/dl_acme_foods").json()
    return d.get("deal", d)


def test_routes_compose_two_apps(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/monitor/"
    assert client.get("/monitor/").status_code == 200
    for page in ("/mail", "/drive", "/crm/deals", "/calendar", "/events"):
        assert client.get(page).status_code == 200, page


def test_workspace_runs_on_its_own():
    from workspace.main import app as standalone

    with TestClient(standalone) as c:
        assert c.get("/", follow_redirects=False).headers["location"] == "/mail"
        assert c.get("/api/crm/deal/dl_acme_foods").status_code == 200


def test_careful_run_changes_the_apps_and_never_pauses(client):
    steps, changed = play(client, mistakes=False)
    assert [s["decision"] for s in steps if s["decision"] in ("pause", "block")] == []
    d = deal(client)
    assert d["stage"] == "demo"
    assert d.get("close_date") == "2026-12-18"  # untouched
    urls = {x["url"] for x in changed}
    assert "/crm/deal/dl_acme_foods" in urls and "/mail?label=DRAFT" in urls
    drafts = client.get("/api/mail/threads", params={"label": "DRAFT"}).json()
    assert any("Recap" in (t.get("subject") or "") for t in drafts.get("threads", drafts))


def test_blocking_every_pause_leaves_the_deal_as_seeded(client):
    seed = dict(deal(client))
    steps, _ = play(client, mistakes=True, decide=lambda s: ("reject", "not without approval"))
    paused = [s for s in steps if s["decision"] == "pause"]
    d = deal(client)
    for s in paused:
        if s["catalog_action"].startswith("habspot.stage"):
            assert d["stage"] == seed["stage"]
        if s["catalog_action"].startswith("habspot.close_date"):
            assert d.get("close_date") == seed.get("close_date")
        if s["catalog_action"].startswith("habspot.amount"):
            assert d.get("amount") == seed.get("amount")
    sent = client.get("/api/mail/threads", params={"label": "SENT"}).json()
    if any(s["catalog_action"].startswith("quote.send") for s in paused):
        assert not any("Your Shiftpoint quote" in (t.get("subject") or "") for t in sent.get("threads", sent))


def test_approval_replays_the_original_request(client, monkeypatch):
    monkeypatch.setenv("MONITOR_MODE", "off")
    monkeypatch.setenv("APPROVE_EXTERNAL_SENDS", "1")
    steps, _ = play(client, mistakes=True, decide=lambda s: ("approve", "Dana approved by phone"))
    send = next(s for s in steps if (s["catalog_action"] or "").startswith("quote.send"))
    assert send["decision"] == "pause"
    sent = client.get("/api/mail/threads", params={"label": "SENT"}).json()
    assert any("Your Shiftpoint quote" in (t.get("subject") or "") for t in sent.get("threads", sent))
    assert events.LEARNED and events.LEARNED[-1]["reason"] == "Dana approved by phone"


def test_snapshot_round_trip_is_compact_and_lossless(client):
    play(client, mistakes=False)
    snap = events.snapshot()
    blob = encode(snap)
    assert decode(blob) == snap
    assert len(blob) < 400_000  # well under Upstash's per-request limit


def test_no_disk_writes_during_a_run(client, monkeypatch):
    real_open = builtins.open

    def guarded(file, mode="r", *a, **k):
        if any(m in mode for m in "wax+") and not str(file).startswith(("/dev/", "/private/var", "/tmp")):
            raise AssertionError(f"disk write to {file}")
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", guarded)
    monkeypatch.setattr(Path, "write_text", lambda *a, **k: (_ for _ in ()).throw(AssertionError("write_text")))
    monkeypatch.setattr(io, "open", guarded)
    play(client, mistakes=True, decide=lambda s: ("reject", ""))
    assert store.CHANGED["v"] in (True, False)


def test_people_browsing_dont_change_the_run(client):
    client.post("/api/runs", json={"scenario": "acme_after_call", "mistakes": False})
    n = len(events.EVENTS)
    client.get("/drive/doc/doc_transcript_t1_acme_foods")
    client.get("/api/crm/deal/dl_acme_foods")
    assert len(events.EVENTS) == n
