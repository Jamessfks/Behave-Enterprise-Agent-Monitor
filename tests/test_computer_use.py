"""Live mode by computer use (ADR 0013), with no browser and no Gemini: the agent process is
faked, and "its" clicks are requests that carry X-Actor: agent, as its browser's do."""

import pytest
from fastapi.testclient import TestClient

import server
from agent import computer_use


class FakeProc:
    def __init__(self, *args, **kwargs):
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("UNBOXAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setattr(computer_use.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(computer_use, "WAIT_S", 0.5)
    monkeypatch.setattr(computer_use, "LOG_DIR", tmp_path)
    with TestClient(server.app) as c:
        yield c
    computer_use.stop()


def test_bootstrap_offers_computer_use_live(client):
    b = client.get("/api/bootstrap").json()
    assert b["live_available"] and b["live_agent"] == "computer_use"


def test_agent_clicks_become_checked_steps_and_finish_ends_the_run(client):
    run = client.post("/api/runs", json={"instruction": "Do the Acme follow-up"}).json()["run"]
    assert run["live"] and run["computer_use"]

    # Nothing yet: the canvas is told the agent is still working.
    n = client.post("/api/runs/current/next").json()
    assert n["step"] is None and n["working"] and not n["done"]

    # The agent's browser opens the inbox and a thread (agent requests are logged and scored).
    client.get("/mail", headers={"X-Actor": "agent"})
    thread = client.get("/api/mail/threads").json()
    tid = (thread.get("threads") or thread)[0]["id"]
    client.get(f"/mail/thread/{tid}", headers={"X-Actor": "agent"})
    steps = []
    for _ in range(3):
        n = client.post("/api/runs/current/next").json()
        if n["step"]:
            steps.append(n["step"])
    assert steps, "agent page views should show up as steps"
    assert all("check" in s and s["decision"] in ("allow", "flag") for s in steps)

    # A person browsing the apps (no X-Actor) never adds steps.
    client.get("/drive")
    assert client.post("/api/runs/current/next").json()["step"] is None

    client.post("/api/runs/current/finish", json={"run_id": run["id"], "summary": "All done."})
    n = client.post("/api/runs/current/next").json()
    assert n["done"] and n["summary"] == "All done."


def test_a_new_run_stops_the_agent(client):
    client.post("/api/runs", json={"instruction": "First"})
    proc = computer_use.PROC["p"]
    client.post("/api/runs", json={"scenario": "acme_after_call", "mistakes": False})
    assert not proc.alive and computer_use.PROC["p"] is None


def test_the_demo_task_never_uses_the_live_ranker(client, monkeypatch):
    """Demo runs keep the cold ranker, the team catalog and the committed cache (ADR 0013)."""
    from monitor import core

    def boom():
        raise AssertionError("the demo task must not use Live mode's BehaviorGPT")

    monkeypatch.setattr(core, "bgpt_live", boom)
    client.post("/api/runs", json={"scenario": "acme_after_call", "mistakes": True})
    for _ in range(200):
        n = client.post("/api/runs/current/next").json()
        if n.get("step") and n["step"]["decision"] == "pause":
            client.post(f"/api/approvals/{n['step']['approval_id']}/reject", json={"reason": ""})
        if n.get("done"):
            break
    assert n["done"]


def _flag_every_live_step(monkeypatch, rank):
    """Pretend BehaviorGPT ranks every live step #rank of 139 (no network)."""
    from monitor import core

    real = core.behaviorgpt_evidence

    def fake(history, event, live=False):
        if not live:
            return real(history, event, live)
        return {"rank": rank, "of": 139, "top": [{"action_id": "x", "name": "Open the deal"}]}

    monkeypatch.setattr(core, "behaviorgpt_evidence", fake)


def _agent_note(client):
    return client.post(
        "/api/crm/note",
        json={"deal_id": "dl_acme_foods", "body": "Call recap"},
        headers={"X-Actor": "agent"},
    )


def test_behaviorgpt_holds_an_unusual_live_change_and_block_stops_the_agent(client, monkeypatch):
    _flag_every_live_step(monkeypatch, rank=99)
    client.post("/api/runs", json={"instruction": "Do the Acme follow-up"})
    proc = computer_use.PROC["p"]
    assert _agent_note(client).status_code == 202  # held: nothing written yet

    status = client.get("/api/runs/current/agent").json()
    assert status["halted"] and "BehaviorGPT" in status["reason"]
    step = next(
        n["step"]
        for n in (client.post("/api/runs/current/next").json() for _ in range(5))
        if n.get("step") and n["step"]["decision"] == "pause"
    )
    assert "behaviorgpt" in step["check"]["failed"]

    client.post(f"/api/approvals/{step['approval_id']}/reject", json={"reason": ""})
    n = client.post("/api/runs/current/next").json()
    assert n["done"] and "blocked" in n["summary"]
    assert not proc.alive and client.get("/api/runs/current/agent").json()["stopped"]


def test_allowing_a_flagged_change_lets_the_agent_continue(client, monkeypatch):
    _flag_every_live_step(monkeypatch, rank=99)
    client.post("/api/runs", json={"instruction": "Do the Acme follow-up"})
    assert _agent_note(client).status_code == 202
    approval = next(
        n["step"]["approval_id"]
        for n in (client.post("/api/runs/current/next").json() for _ in range(5))
        if n.get("step") and n["step"]["decision"] == "pause"
    )
    client.post(f"/api/approvals/{approval}/approve", json={"reason": "Alex asked for it"})
    status = client.get("/api/runs/current/agent").json()
    assert not status["halted"] and not status["stopped"]


def test_an_expected_live_change_is_not_held(client, monkeypatch):
    _flag_every_live_step(monkeypatch, rank=2)
    client.post("/api/runs", json={"instruction": "Do the Acme follow-up"})
    assert _agent_note(client).status_code == 200
