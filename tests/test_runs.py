import json
from pathlib import Path

import pytest

from monitor.events import EventError, load_run, to_sdk, validate_event, validate_run

RUNS = Path(__file__).resolve().parent.parent / "runs"
RUN_FILES = sorted(RUNS.glob("*.jsonl"))


def test_runs_exist():
    assert len(RUN_FILES) >= 4


@pytest.mark.parametrize("path", RUN_FILES, ids=lambda p: p.stem)
def test_run_follows_schema(path):
    validate_run(load_run(path))


def test_mistake_markers_point_at_real_steps():
    marks = json.loads((RUNS / "mistakes.json").read_text())
    for run_id, step in marks.items():
        events = load_run(RUNS / f"{run_id}.jsonl")
        assert 0 < step < len(events)


def test_clean_runs_never_touch_the_duplicate_company():
    for path in RUN_FILES:
        if path.stem.startswith("golden"):
            assert all(e["details"]["entity"] != "Northwind Logistics" for e in load_run(path))


def test_send_is_marked_irreversible():
    for path in RUN_FILES:
        for e in load_run(path):
            if e["action_id"] in {"email.send_quote_reply", "crm.delete_record"}:
                assert e["details"]["irreversible"] is True


def _event(**over):
    ev = {
        "run_id": "r",
        "step": 0,
        "timestamp": "2026-11-08T15:00:00.000Z",
        "type": "view",
        "action_id": "inbox.open_lead_email",
        "query": None,
        "details": {"app": "Inbox", "entity": None, "irreversible": False},
    }
    ev.update(over)
    return ev


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "order"},
        {"action_id": None},
        {"type": "search", "query": None},
        {"timestamp": "2026-11-08 15:00"},
        {"details": {"app": "Slack", "entity": None, "irreversible": False}},
    ],
)
def test_rejects_bad_events(bad):
    with pytest.raises(EventError):
        validate_event(_event(**bad))


def test_to_sdk_never_sends_details():
    from behaviorgpt import Search, View

    assert isinstance(to_sdk(_event()), View)
    assert isinstance(to_sdk(_event(type="search", action_id=None, query="x")), Search)
