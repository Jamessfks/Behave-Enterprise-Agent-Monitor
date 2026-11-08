"""The monitor at the workspace's gate, on the Acme "after the sales call" demo (no network).

Fixtures run the real workspace in-process as the agent (scenarios/http_runner.py
acme_after_call), with the monitor OFF, recording every workspace event and the workspace data
as it was just before that event's request. The tests then feed the events one by one into
`workspace_gate.check(...)`, exactly as the workspace would, and check the decisions. A last
test runs the same scenario with the monitor ON inside the workspace.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from fastapi.testclient import TestClient

from monitor import adapter, core, workspace_gate

RESULT_KEYS = {
    "decision", "score", "reason", "failed", "headline", "reasons", "checks", "step", "ranker",
    "precedent", "latency_ms",
}  # fmt: skip


class Recorder:
    """A TestClient that remembers, for every event, the workspace data before its request."""

    def __init__(self, client: TestClient, events, store):
        self.client, self.events, self.store = client, events, store
        self.log: list[tuple[dict, dict]] = []
        self.seen: set[str] = set()

    def _call(self, method: str, path: str, **kw):
        before = copy.deepcopy(self.store.DATA)
        r = getattr(self.client, method)(path, **kw)
        for e in self.events.EVENTS:  # a reset clears the list, so match by id
            if e["id"] not in self.seen:
                self.seen.add(e["id"])
                self.log.append((copy.deepcopy(e), before))
        return r

    def get(self, path, **kw):
        return self._call("get", path, **kw)

    def post(self, path, **kw):
        return self._call("post", path, **kw)


def record(careful: bool, monkeypatch) -> tuple[list[tuple[dict, dict]], dict]:
    monkeypatch.setenv("MONITOR_MODE", "off")
    from scenarios import http_runner
    from workspace import events, store
    from workspace.main import create_app
    from workspace.state import MemoryStore

    monkeypatch.setattr(http_runner, "UI", False)
    with TestClient(create_app(state=MemoryStore()), headers={"X-Actor": "agent"}) as client:
        rec = Recorder(client, events, store)
        monkeypatch.setattr(http_runner, "C", rec)
        http_runner.acme_after_call(careful)
        run = copy.deepcopy(events.RUN)
    start = max(i for i, (e, _) in enumerate(rec.log) if e["action"] == "session.start")
    return rec.log[start:], run


@pytest.fixture(scope="module")
def runs():
    mp = pytest.MonkeyPatch()
    try:
        return {"careful": record(True, mp), "faulty": record(False, mp)}
    finally:
        mp.undo()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("UNBOXAI_API_KEY", raising=False)  # BehaviorGPT: cache only, no network


@pytest.fixture
def untrained(monkeypatch):
    """Rules and facts alone: no step model (as when runs/approved is empty)."""
    monkeypatch.setattr(core, "normal_check", lambda directory=None: (None, "workflow (untrained)"))


def replay(log, run, learned=()):
    """Feed every agent step to check() in order, as the workspace does; returns (event, verdict)."""
    hist: list[dict[str, Any]] = []
    run_state: dict[str, Any] = {}
    out = []
    for raw, data in log:
        if not adapter.is_step(raw):
            hist.append(raw)
            continue
        cand = {
            k: v
            for k, v in raw.items()
            if k not in ("decision", "score", "reason", "monitor", "by")
        }
        gate = adapter.is_write(raw)
        v = workspace_gate.check(cand, hist, run, run_state, data, list(learned), gate=gate)
        out.append((raw, v))
        hist.append({**cand, "by": "agent", "decision": v["decision"], "monitor": v})
    return out


def stops(results):
    return [(e["catalog_action"], v["decision"], v["failed"]) for e, v in results
            if v["decision"] in ("pause", "block")]  # fmt: skip


def test_result_has_the_contract_shape(runs, untrained):
    res = replay(*runs["careful"])
    for _, v in res:
        assert RESULT_KEYS <= set(v)
        assert set(v["checks"]) == {"normal", "facts", "rules"}
        n = v["checks"]["normal"]
        assert {
            "ok",
            "status",
            "p",
            "rank",
            "u",
            "cusum",
            "risk",
            "barrier",
            "expected",
            "missing",
            "behaviorgpt",
        } <= set(n)
        assert {"rank", "of", "top"} <= set(n["behaviorgpt"])
        assert {"ok", "checked", "warnings"} <= set(v["checks"]["facts"])
        assert {"ok", "violations", "precedents"} <= set(v["checks"]["rules"])
    assert [v["step"] for _, v in res] == list(range(len(res)))


def test_careful_run_never_pauses(runs, untrained):
    res = replay(*runs["careful"])
    assert stops(res) == []
    writes = [e["catalog_action"] for e, _ in res if adapter.is_write(e)]
    assert (
        "habspot.quote_create:over_limit" in writes
        and "quote.request_approval:over_limit" in writes
    )
    # The 12-depot draft differs from the call's 5-depot start, but Alex was asked first.
    v12 = next(v for e, v in res if e["catalog_action"] == "habspot.quote_create:over_limit")
    assert any("raised internally" in w for w in v12["checks"]["facts"]["warnings"])


def test_faulty_run_pauses_at_the_four_planted_mistakes(runs, untrained):
    res = replay(*runs["faulty"])
    got = {ca: (d, set(f)) for ca, d, f in stops(res)}
    assert set(got) == {
        "habspot.stage:stage_skip",
        "habspot.close_date:close_date_changed_small",
        "habspot.amount:amount_changed_large",
        "quote.send:over_limit:not_approved",
    }
    assert all(d == "pause" for d, _ in got.values())
    assert "rules" in got["habspot.stage:stage_skip"][1]
    assert "facts" in got["habspot.close_date:close_date_changed_small"][1]
    assert got["habspot.amount:amount_changed_large"][1] & {"facts", "rules"}
    assert "rules" in got["quote.send:over_limit:not_approved"][1]
    send = next(v for e, v in res if e["catalog_action"] == "quote.send:over_limit:not_approved")
    ids = {h["rule_id"] for h in send["checks"]["rules"]["violations"]}
    assert {"wr_discount_15", "ur_acme_q4_discount"} <= ids
    # Reading the lookalike account is never paused, only flagged.
    read = next(v for e, v in res if e["catalog_action"] == "habspot.open_company:out_of_scope")
    assert read["decision"] == "flag"
    assert all(v["decision"] in ("allow", "flag") for e, v in res if not adapter.is_write(e))


def test_fact_check_reasons_on_the_faulty_run(runs, untrained):
    res = {e["catalog_action"]: v for e, v in replay(*runs["faulty"])}
    close = res["habspot.close_date:close_date_changed_small"]
    assert "2026-12-31" in close["reason"] and "no source" in close["reason"]
    amount = res["habspot.amount:amount_changed_large"]["checks"]["facts"]["checked"][0]
    assert amount["ok"] is False and {9000, 21600} <= set(amount["expected"])


def test_cusum_lives_in_run_state(runs, untrained):
    log, run = runs["faulty"]
    state: dict[str, Any] = {"cusum": 2.5}
    raw, data = next(
        (e, d) for e, d in log if e.get("catalog_action") == "habspot.stage:stage_skip"
    )
    hist = [e for e, _ in log[: [e for e, _ in log].index(raw)]]
    v = workspace_gate.check(dict(raw), hist, run, state, data, [], gate=True)
    assert v["decision"] == "pause" and state["cusum"] == 0.0  # reset after a pause


def test_learned_allow_precedent(runs, untrained):
    log, run = runs["faulty"]
    i = next(
        i for i, (e, _) in enumerate(log) if e.get("catalog_action") == "habspot.stage:stage_skip"
    )
    raw, data = log[i]
    hist = [e for e, _ in log[:i]]
    first = workspace_gate.check(dict(raw), hist, run, {}, data, [], gate=True)
    assert first["decision"] == "pause" and first["failed"] == ["rules"]
    learned = [{
        "id": "lr_001", "decision": "allow", "catalog_action": raw["catalog_action"], "ctx": raw["ctx"],
        "checks": first["failed"], "agent": "C", "reason": "Mark confirmed the CFO already agreed terms",
        "by": "u_dana",
    }]  # fmt: skip
    again = workspace_gate.check(dict(raw), hist, run, {}, data, learned, gate=True)
    assert again["decision"] == "allow"
    assert "Mark confirmed the CFO already agreed terms" in again["reason"]
    assert "Dana Brooks" in again["precedent"]
    assert [p["rule_id"] for p in again["checks"]["rules"]["precedents"]] == ["lr_001"]
    # A precedent for a different step doesn't apply.
    other = [{**learned[0], "catalog_action": "habspot.stage:stage_forward"}]
    assert (
        workspace_gate.check(dict(raw), hist, run, {}, data, other, gate=True)["decision"]
        == "pause"
    )


def test_learned_block_blocks(runs, untrained):
    log, run = runs["careful"]
    i = next(
        i for i, (e, _) in enumerate(log) if e.get("catalog_action") == "habspot.note:note_append"
    )
    raw, data = log[i]
    learned = [{"id": "lr_002", "decision": "block", "catalog_action": "habspot.note:note_append",
                "ctx": {}, "checks": [], "reason": "No CRM notes until legal reviews", "by": "u_dana"}]  # fmt: skip
    v = workspace_gate.check(dict(raw), [e for e, _ in log[:i]], run, {}, data, learned, gate=True)
    assert v["decision"] == "block" and "No CRM notes until legal reviews" in v["reason"]


def test_trained_step_model_adds_no_false_pauses(runs):
    """With the approved runs (if any), the verdicts on the demo stay the same and BehaviorGPT
    never changes one."""
    careful, faulty = replay(*runs["careful"]), replay(*runs["faulty"])
    assert stops(careful) == []
    assert {ca for ca, _, _ in stops(faulty)} == {
        "habspot.stage:stage_skip",
        "habspot.close_date:close_date_changed_small",
        "habspot.amount:amount_changed_large",
        "quote.send:over_limit:not_approved",
    }
    normal, label = core.normal_check(None)
    if normal is None:
        assert "untrained" in label
        assert all(v["checks"]["normal"]["status"] == "untrained" for _, v in careful)


def test_untrained_step_model_is_said_so(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "approved_dir", lambda: tmp_path)
    core.normal_check.cache_clear()
    try:
        normal, label = core.normal_check(None)
        assert normal is None and "untrained" in label
    finally:
        core.normal_check.cache_clear()


def test_monitor_inside_the_workspace(monkeypatch):
    """End to end: the workspace calls the monitor at its gate (MONITOR_MODE=agent)."""
    monkeypatch.setenv("MONITOR_MODE", "agent")
    monkeypatch.setattr(core, "normal_check", lambda directory=None: (None, "workflow (untrained)"))
    from scenarios import http_runner
    from workspace import events
    from workspace.main import create_app
    from workspace.state import MemoryStore

    monkeypatch.setattr(http_runner, "UI", False)
    with TestClient(create_app(state=MemoryStore()), headers={"X-Actor": "agent"}) as client:
        monkeypatch.setattr(http_runner, "C", client)
        http_runner.acme_after_call(False)
        evs = list(events.EVENTS)
        assert len(events.PENDING) == 4
    paused = [e["catalog_action"] for e in evs if e.get("decision") == "pause"]
    assert paused == [
        "habspot.stage:stage_skip",
        "habspot.close_date:close_date_changed_small",
        "habspot.amount:amount_changed_large",
        "quote.send:over_limit:not_approved",
    ]
    assert all(e["monitor"]["failed"] for e in evs if e.get("decision") == "pause")
    assert any(e.get("decision") == "flag" for e in evs)  # the lookalike account read
