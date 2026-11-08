import json
from pathlib import Path

import pytest

from monitor.events import EventError, load_run, to_sdk, validate_event, validate_run

RUNS = Path(__file__).resolve().parent.parent / "runs"
RUN_FILES = sorted(RUNS.glob("*.jsonl"))


def test_runs_exist():
    names = {p.stem for p in RUN_FILES}
    assert "faulty" in names
    assert sum(n.startswith("careful_") for n in names) >= 5


@pytest.mark.parametrize("path", RUN_FILES, ids=lambda p: p.stem)
def test_run_follows_schema(path):
    validate_run(load_run(path))


def test_expectations_name_real_actions():
    exp = json.loads((RUNS / "expectations.json").read_text())
    faulty = {e["action_id"] for e in load_run(RUNS / "faulty.jsonl")}
    for x in exp["faulty"]:
        assert x["action_id"] in faulty
        assert set(x["caught_by"]) <= {"normal", "facts", "rules"}


def test_careful_runs_never_touch_the_lookalike_account():
    for path in RUNS.glob("careful_*.jsonl"):
        for e in load_run(path):
            assert not (e["action_id"] or "").endswith("acme_corp") or e["type"] == "search"


def _event(**over):
    ev = {
        "run_id": "r",
        "step": 0,
        "timestamp": "2026-11-09T09:00:00.000Z",
        "type": "view",
        "action_id": "mail.open_task_message",
        "query": None,
        "details": {"app": "Mail", "entity": None, "irreversible": False},
    }
    ev.update(over)
    return ev


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "order"},
        {"action_id": None},
        {"type": "search", "query": None},
        {"timestamp": "2026-11-09 09:00"},
        {"details": {"app": "Slack", "entity": None, "irreversible": False}},
        {"details": {"app": "CRM", "entity": None, "irreversible": False, "values": [1]}},
    ],
)
def test_rejects_bad_events(bad):
    with pytest.raises(EventError):
        validate_event(_event(**bad))


def test_to_sdk_never_sends_details():
    from behaviorgpt import Search, View

    assert isinstance(to_sdk(_event()), View)
    assert isinstance(to_sdk(_event(type="search", action_id=None, query="x")), Search)
