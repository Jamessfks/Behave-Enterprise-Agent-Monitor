"""API and live-agent tests. No network: Claude is faked; BehaviorGPT comes from the cache."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from agent import live
from env.app import new_state, to_event
from env.company import default_context


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("UNBOXAI_API_KEY", raising=False)
    return TestClient(server.app)


def test_bootstrap_works_without_keys(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    b = client.get("/api/bootstrap").json()
    assert {"careful_01", "faulty"} <= set(b["runs"])
    assert b["default_ranker"] in b["rankers"]
    assert b["live_available"] is False
    assert client.get("/").status_code == 200


def test_replay_over_the_api_pauses_three_times(client):
    run = client.get("/api/bootstrap").json()["runs"]["faulty"]
    cusum, pauses = 0.0, []
    for i, e in enumerate(run):
        r = client.post("/api/check", json={"history": run[:i], "event": e, "cusum": cusum}).json()
        if r["verdict"] == "pause":
            pauses.append(e["action_id"])
            cusum = 0.0
        else:
            cusum = r["checks"]["normal"]["cusum"]
    assert pauses == [
        "crm.set_stage_negotiation",
        "crm.set_close_date",
        "quotes.send_quote_to_client",
    ]


def test_check_rejects_bad_event(client):
    r = client.post("/api/check", json={"history": [], "event": {"type": "order"}})
    assert r.status_code == 422


def test_learn_requires_a_reason(client):
    ev = {"action_id": "crm.set_close_date", "details": {"entity": "Acme Industries"}}
    assert (
        client.post(
            "/api/rules/learn", json={"event": ev, "failed": ["facts"], "reason": " "}
        ).status_code
        == 422
    )
    rule = client.post(
        "/api/rules/learn", json={"event": ev, "failed": ["facts"], "reason": "Client confirmed"}
    ).json()
    assert rule["kind"] == "precedent" and rule["checks"] == ["facts"]


def test_catalog_upload_validates(client):
    good = "id,name,event_type,group\na.one,Do the first thing,product,product\n"
    r = client.post("/api/catalog/upload", files={"file": ("c.csv", good, "text/csv")}).json()
    assert r["rows"] == 1 and r["errors"] == []
    bad = "id,name\na,x\na,y\n"
    r = client.post("/api/catalog/upload", files={"file": ("c.csv", bad, "text/csv")}).json()
    assert "duplicate ids" in r["errors"] and any("event_type" in e for e in r["errors"])


def test_context_validate(client):
    r = client.post("/api/context/validate", json={"context": {"company": "Globex"}}).json()
    assert r["errors"] == [] and r["context"]["company"] == "Globex"


def test_tool_calls_map_to_catalog_events():
    st = new_state()
    ev = to_event(st, "quote", {"action": "set_discount", "discount_pct": 25}, "live", 0)
    assert ev["action_id"] == "quotes.apply_discount_over_15"
    ev = to_event(
        st, "crm_add_contact", {"account_id": "acc_acme_corp", "name": "Maria"}, "live", 1
    )
    assert ev["action_id"] == "crm.add_contact_wrong_account"
    assert ev["details"]["entity"] == "Acme Corp"
    assert to_event(st, "list_items", {"tab": "Mail"}, "live", 2) is None


class FakeClaude:
    """Returns scripted tool calls, one assistant turn per create()."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        blocks = self.turns.pop(0)
        return SimpleNamespace(
            content=[SimpleNamespace(model_dump=lambda exclude_none=True, b=b: b) for b in blocks]
        )


def tool(i, name, **inp):
    return {"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}


def test_live_agent_pauses_before_sending_and_block_is_respected():
    turns = [
        [
            tool(1, "open_item", item_id="msg_task"),
            tool(2, "open_item", item_id="email_acme"),
            tool(8, "open_item", item_id="call_acme"),
        ],
        [
            tool(3, "quote", action="create"),
            tool(4, "quote", action="set_seats", plan="Pro", seats=50),
        ],
        [
            tool(5, "quote", action="set_discount", discount_pct=25),
            tool(6, "quote", action="send_to_client"),
        ],
        [tool(7, "finish", summary="Done")],
    ]
    fake = FakeClaude(turns)
    p = {
        "instruction": "do it",
        "context": default_context(),
        "state": new_state(),
        "history": [],
        "messages": [],
    }
    for _ in range(3):
        p = live.step(p, client=fake)
        if p["pending"]:
            break
    assert p["pending"]["event"]["action_id"] == "quotes.send_quote_to_client"
    assert p["state"]["quote"]["status"] == "draft"  # checked before it ran: nothing sent
    p = live.step(
        {**p, "resolution": {"decision": "block", "reason": "needs approval"}}, client=fake
    )
    assert p["state"]["quote"]["status"] == "draft"
    assert p["done"] is True
    last_user = [m for m in p["messages"] if m["role"] == "user"][-1]["content"]
    assert any("Blocked by a supervisor" in r["content"] for r in last_user)
