"""The monitor's acceptance tests (docs/prompts/build-mvp.md, "Done means")."""

import json
from pathlib import Path

import pytest

from env.company import default_context, validate_context
from monitor.core import check_step, learned_rule
from monitor.events import load_run
from monitor.facts import check_facts
from monitor.rankers import WorkflowRanker
from monitor.rules import check_rules
from monitor.scoring import predict

RUNS = Path(__file__).resolve().parent.parent / "runs"
PRICING = {"Pro": 45, "Enterprise": 65}


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    """Everything here must work with no API keys (replay mode)."""
    monkeypatch.delenv("UNBOXAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def play(run, ctx=None, decide=None):
    """Replay a run through the monitor; returns [(step, result)] for every pause."""
    ctx = ctx or default_context()
    cusum, pauses = 0.0, []
    for i, e in enumerate(run):
        r = check_step(run[:i], e, ctx, cusum)
        if r["verdict"] == "pause":
            pauses.append((i, r))
            if decide:
                decide(ctx, e, r)
            cusum = 0.0
        else:
            cusum = r["checks"]["normal"]["cusum"]
    return pauses


def test_careful_runs_never_pause():
    for path in sorted(RUNS.glob("careful_*.jsonl")):
        assert play(load_run(path)) == [], path.stem


def test_faulty_run_pauses_exactly_at_the_planted_mistakes():
    run = load_run(RUNS / "faulty.jsonl")
    exp = json.loads((RUNS / "expectations.json").read_text())["faulty"]
    pauses = play(run)
    assert [run[i]["action_id"] for i, _ in pauses] == [x["action_id"] for x in exp]
    for (_, r), x in zip(pauses, exp, strict=True):
        assert set(x["caught_by"]) <= set(r["failed"]), (x, r["failed"])
        assert r["headline"] and r["reasons"]


def test_send_quote_pause_quotes_marco():
    run = load_run(RUNS / "faulty.jsonl")
    _, r = play(run)[-1]
    assert any(v["author"] == "Marco" for v in r["checks"]["rules"]["violations"])
    assert any(x.startswith("Marco would stop here") for x in r["reasons"])


def test_allow_with_reason_becomes_a_rule_that_fires_later():
    ctx = default_context()
    run = load_run(RUNS / "faulty.jsonl")
    i, first = play(run)[1]  # the invented close date
    ctx["learned_rules"].append(learned_rule(run[i], first["failed"], "Client confirmed Dec 31"))
    again = check_step(run[: i + 1], run[i], ctx)
    assert again["verdict"] == "allowed_by_rule"
    assert again["precedent"] == "Client confirmed Dec 31"


def test_fact_check_quotes_the_source_span():
    run = load_run(RUNS / "careful_01.jsonl")
    i = next(k for k, e in enumerate(run) if e["action_id"] == "crm.log_call_notes")
    v = check_facts(run[:i], run[i], PRICING)
    assert v.ok
    budget = next(c for c in v.checked if c["field"] == "budget")
    assert "$60,000" in budget["evidence"][0]["span"]


def test_fact_check_flags_value_contradicting_the_call():
    run = load_run(RUNS / "faulty.jsonl")
    i = next(k for k, e in enumerate(run) if e["action_id"] == "quotes.set_seats")
    ev = json.loads(json.dumps(run[i]))
    ev["details"]["values"]["seats"] = 200
    v = check_facts(run[:i], ev, PRICING)
    assert not v.ok and "contradicts the call transcript (50)" in v.reasons[0]
    ok = check_facts(run[:i], run[i], PRICING)  # 50 matches the call: passes with a warning
    assert ok.ok and ok.warnings


def test_derived_amount_must_match_the_quote():
    run = load_run(RUNS / "careful_01.jsonl")
    i = next(k for k, e in enumerate(run) if e["action_id"] == "crm.set_deal_amount")
    assert check_facts(run[:i], run[i], PRICING).ok
    bad = json.loads(json.dumps(run[i]))
    bad["details"]["values"]["amount"] = 30000
    assert not check_facts(run[:i], bad, PRICING).ok


def test_stage_skip_rule():
    ctx = default_context()
    ev = {
        "type": "view",
        "action_id": "crm.set_stage_negotiation",
        "details": {"values": {"stage": "Negotiation"}, "entity": "Acme Industries"},
    }
    assert not check_rules([], ev, ctx).ok
    ev2 = {
        **ev,
        "action_id": "crm.set_stage_qualification",
        "details": {"values": {"stage": "Qualification"}},
    }
    prior = [{"type": "view", "action_id": "crm.log_call_notes", "details": {}}]
    assert check_rules(prior, ev2, ctx).ok


def test_workflow_ranker_charges_a_skip_once():
    runs = [load_run(p) for p in sorted(RUNS.glob("careful_*.jsonl"))]
    wf = WorkflowRanker(runs)
    faulty = load_run(RUNS / "faulty.jsonl")
    i = next(
        k for k, e in enumerate(faulty) if e["action_id"] == "crm.open_account_acme_industries"
    )
    j = i + 1
    assert wf.missing(faulty[:i], faulty[i]["action_id"])  # skipped the rep: charged here
    assert wf.rank(faulty[:j])[faulty[j]["action_id"]] > -1  # not charged again


def test_softmax_is_a_distribution():
    pred = predict({"a": 2.0, "b": 1.0, "c": 0.0}, "a", 1.0, 0.0)
    assert pred.rank == 1 and 0 < pred.logp < 1e-9 or pred.rank == 1
    assert abs(sum(p for _, p in pred.top) - 1.0) < 1e-9


def test_context_validation():
    assert validate_context(default_context()) == []
    bad = default_context()
    bad["unwritten_rules"].append({"text": "x", "kind": "nonsense"})
    assert validate_context(bad)


def test_an_empty_cache_is_used_not_swapped_for_the_committed_one(tmp_path):
    """Regression: RankingCache has __len__, so `cache or default` dropped an empty cache."""
    from monitor.rankers import BehaviorGPTRanker, RankingCache

    fresh = RankingCache(tmp_path / "fresh.json")
    assert BehaviorGPTRanker(catalog_id="cat_x", cache=fresh).cache is fresh


def test_default_verdicts_do_not_depend_on_behaviorgpt(monkeypatch):
    """BehaviorGPT is evidence, not a decider: with it down, the default pauses are the same."""
    from behaviorgpt import UnboxAIError

    from monitor.rankers import BehaviorGPTRanker

    run = load_run(RUNS / "faulty.jsonl")
    with_bgpt = [(i, r["failed"]) for i, r in play(run)]

    def down(self, history):
        raise UnboxAIError("BehaviorGPT unavailable", status_code=503)

    monkeypatch.setattr(BehaviorGPTRanker, "rank", down)
    monkeypatch.setattr(BehaviorGPTRanker, "cached", lambda self, history: True)
    without = play(run)
    assert [(i, r["failed"]) for i, r in without] == with_bgpt
    assert all(r["checks"]["normal"]["behaviorgpt"]["rank"] is None for _, r in without)
