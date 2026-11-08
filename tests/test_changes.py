"""Per-step change tracking (workspace/changes.py, ADR 0012): what each write changed in the
apps, where to point at it, the next step ahead of time, and approved replays."""

import re

import pytest
from fastapi.testclient import TestClient

import server
from scenarios import runner

SCENARIO = "acme_after_call"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("UNBOXAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(server.app) as c:
        # Approval reasons become learned rules that survive resets; start and end clean.
        c.post("/api/rules/learned/clear", json={})
        yield c
        c.post("/api/rules/learned/clear", json={})


def matches(selector: str, html: str) -> bool:
    """A tiny CSS check for the selectors changes.py emits: [attr="v"] and #id."""
    m = re.fullmatch(r'\[([a-z-]+)="([^"]*)"\]', selector)
    if m:
        return f'{m.group(1)}="{m.group(2)}"' in html
    if selector.startswith("#"):
        return f'id="{selector[1:]}"' in html
    raise AssertionError(f"unexpected selector {selector!r}")


def run(c, mistakes, decide=None):
    """Play a run; return (start response, [(next response, html of the step's pages)])."""
    started = c.post("/api/runs", json={"scenario": SCENARIO, "mistakes": mistakes}).json()
    specs = runner.steps_for(runner.load(SCENARIO), mistakes)
    out = []
    while True:
        n = c.post("/api/runs/current/next").json()
        s = n.get("step")
        html = {}
        if s:
            before = specs[s["index"]].get("before_page", "")
            for url in {s["page"], before, *(ch["url"] for ch in s["changes"])} - {""}:
                html[url] = c.get(url).text
        out.append((n, html))
        if s and s["decision"] == "pause":
            action, reason = (decide or (lambda _s: ("approve", "ok")))(s)
            r = c.post(f"/api/approvals/{s['approval_id']}/{action}", json={"reason": reason})
            n["decided"] = r.json()
        if n.get("done"):
            return started, out


def by_label(out, prefix):
    return next(
        n["step"] for n, _ in out if n.get("step") and n["step"]["label"].startswith(prefix)
    )


def test_careful_run_records_what_each_write_changed(client):
    _, out = run(client, mistakes=False)

    ask = by_label(out, "Ask Alex")
    assert len(ask["changes"]) == 1
    ch = ask["changes"][0]
    assert (ch["app"], ch["kind"]) == ("Jmail", "sent")
    to = next(f["after"] for f in ch["fields"] if f["label"] == "To")
    assert "alex@shiftpoint.io" in to

    move = by_label(out, "Move the deal")
    [ch] = move["changes"]
    assert (ch["app"], ch["kind"]) == ("Habspot", "updated")
    assert {"label": "Stage", "before": "Discovery", "after": "Demo"} in ch["fields"]
    assert '[data-field="stage"]' in ch["focus"]

    quote = by_label(out, "Create a quote: 5 depots")
    assert [(c["app"], c["kind"]) for c in quote["changes"]] == [("Jdrive", "created")]

    draft = by_label(out, "Draft the recap")
    assert [(c["app"], c["kind"]) for c in draft["changes"]] == [("Jmail", "drafted")]

    book = by_label(out, "Book the intro call")
    assert [(c["app"], c["kind"]) for c in book["changes"]] == [("Calendario", "created")]

    reads = [n["step"] for n, _ in out if n.get("step") and n["step"]["kind"] != "write"]
    assert reads and all(s["changes"] == [] for s in reads)


def test_every_focus_selector_points_at_something_in_the_apps(client):
    _, out = run(client, mistakes=False)
    checked = 0
    for n, html in out:
        s = n.get("step")
        if not s:
            continue
        for ch in s["changes"]:
            assert ch["focus"], ch
            # Focus covers the pages the canvas shows around a write: the list the step opens
            # (e.g. a thread's row in Sent, a doc's row in the folder it shows before a quote
            # exists) and the object's own page (the message, the deal field). Every selector
            # must point at something, and the change's page and step's page each get one.
            shown = [ch["url"], s["page"]]
            for sel in ch["focus"]:
                assert any(matches(sel, h) for h in html.values()), (s["label"], sel)
            for url in filter(None, shown):
                assert any(matches(sel, html[url]) for sel in ch["focus"]), (
                    s["label"],
                    url,
                    ch["focus"],
                )
            checked += 1
    assert checked >= 8


def test_upcoming_names_the_next_step_before_it_runs(client):
    started, out = run(client, mistakes=False)
    assert started["upcoming"]["index"] == 0
    assert started["upcoming"]["page"] == "/drive/doc/doc_transcript_t1_acme_foods"
    for n, _ in out:
        if n.get("done"):
            assert n.get("upcoming") is None
        else:
            assert n["upcoming"]["index"] == n["step"]["index"] + 1
    quotes = [
        n["upcoming"]
        for n, _ in out
        if n.get("upcoming") and n["upcoming"]["label"].startswith("Create a quote")
    ]
    assert len(quotes) == 2
    assert all(u["page"] == "/drive?folder=fd_sales_offers" for u in quotes)
    assert all(u["app"] == "Jdrive" and u["kind"] == "write" for u in quotes)


def test_an_approved_pause_carries_the_replays_changes(client):
    _, out = run(client, mistakes=True)
    n = next(
        n
        for n, _ in out
        if n.get("step")
        and n["step"]["decision"] == "pause"
        and (n["step"]["catalog_action"] or "").startswith("habspot.stage")
    )
    paused = n["step"]
    assert paused["changes"] == []  # nothing applied while it waited
    [ch] = n["decided"]["changes"]
    assert {"label": "Stage", "before": "Discovery", "after": "Negotiation"} in ch["fields"]
    steps = client.get("/api/runs/current").json()["steps"]
    settled = next(s for s in steps if s["index"] == paused["index"])
    assert settled["resolution"]["decision"] == "allow"
    assert settled["changes"] == n["decided"]["changes"]


def test_a_blocked_pause_changes_nothing(client):
    _, out = run(client, mistakes=True, decide=lambda s: ("reject", "no"))
    paused = [n["step"] for n, _ in out if n.get("step") and n["step"]["decision"] == "pause"]
    assert paused
    steps = {s["index"]: s for s in client.get("/api/runs/current").json()["steps"]}
    for p in paused:
        assert steps[p["index"]]["resolution"]["decision"] == "block"
        assert steps[p["index"]]["changes"] == []


@pytest.mark.parametrize("mistakes", [False, True])
def test_look_for_strings_appear_on_their_pages(client, mistakes):
    _, out = run(client, mistakes=mistakes)
    specs = runner.steps_for(runner.load(SCENARIO), mistakes)
    seen = 0
    for n, html in out:
        s = n.get("step")
        if not s:
            continue
        assert s["look_for"] == (specs[s["index"]].get("look_for") or [])
        for text in s["look_for"]:
            assert text in html[s["page"]], (s["label"], text)
            seen += 1
    assert seen >= 10
