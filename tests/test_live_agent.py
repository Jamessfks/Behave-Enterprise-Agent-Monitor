"""Live mode with a fake Claude: tools hit the real workspace routes through the gate."""

import asyncio
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from agent import live
from workspace import events


class FakeClaude:
    """Returns scripted tool calls, one assistant turn per create()."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        assert kw["model"] == live.MODEL and kw["tools"]
        blocks = self.turns.pop(0)
        return SimpleNamespace(
            content=[SimpleNamespace(model_dump=lambda exclude_none=True, b=b: b) for b in blocks]
        )


def tool(i, name, **inp):
    return {"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("UNBOXAI_API_KEY", raising=False)
    monkeypatch.setenv("MONITOR_MODE", "off")
    monkeypatch.setenv("APPROVE_EXTERNAL_SENDS", "1")
    with TestClient(server.app) as c:
        yield c


def test_every_tool_maps_to_a_real_route():
    def shape(p):  # parameter names may differ ({tid} vs {thread_id}); positions must match
        return re.sub(r"\{[^}]+\}", "{}", p)

    paths = {shape(p) for p in server.WORKSPACE.openapi()["paths"]}
    for name, (_method, path, *_rest) in live.TOOLS.items():
        if name == "finish":
            continue
        assert shape(path) in paths, f"{name}: {path} isn't a workspace route"


def test_live_agent_changes_the_workspace_and_waits_for_a_person(client):
    fake = FakeClaude(
        [
            [tool(1, "open_document", doc_id="doc_transcript_t1_acme_foods")],
            [tool(2, "set_deal_stage", deal_id="dl_acme_foods", stage="demo")],
            [
                tool(
                    3,
                    "create_quote",
                    deal_id="dl_acme_foods",
                    plan="core",
                    locations=5,
                    discount_pct=10,
                )
            ],
            [tool(4, "send_quote", doc_id="__QUOTE__", to="mark.keller@acmefoods.com")],
            [tool(5, "finish", summary="Quoted 5 depots at 10%.")],
        ]
    )
    live.start("Do the Acme follow-up")

    async def step():
        return await live.next_step(server.WORKSPACE, client=fake)

    out = asyncio.run(step())  # open transcript
    assert out["step"]["kind"] == "read"
    asyncio.run(step())  # stage -> demo
    assert events.EVENTS[-1]["catalog_action"].startswith("habspot.stage")
    out = asyncio.run(step())  # create quote
    quote_id = next(
        e["args"]["doc_id"]
        for e in reversed(events.EVENTS)
        if e["action"] == "habspot.quote_create"
    )
    fake.turns[0][0]["input"]["doc_id"] = quote_id
    out = asyncio.run(step())  # send quote -> external send pauses
    assert out["step"]["approval_id"]
    waiting = asyncio.run(step())
    assert waiting.get("waiting") and waiting["step"] is None
    r = client.post(
        f"/api/approvals/{out['step']['approval_id']}/reject", json={"reason": "not yet"}
    )
    assert r.status_code == 200
    done = asyncio.run(step())  # tool result says blocked, then finish
    assert done["done"] is True and "10%" in done["summary"]
    results = [
        block
        for m in events.RUN_STATE["live"]["messages"]
        if m["role"] == "user" and isinstance(m["content"], list)
        for block in m["content"]
    ]
    assert any("Blocked by a supervisor" in r["content"] for r in results)
    deal = client.get("/api/crm/deal/dl_acme_foods").json()
    assert deal.get("deal", deal)["stage"] == "demo"
