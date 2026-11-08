"""Unit tests for the monitor's numbers, fact check and rules (no workspace, no network)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from monitor import numbers as nums
from monitor.context import company_context, company_rules
from monitor.facts import check_facts, deal_facts
from monitor.rules import check_rules, holds, learned_rules, validate_spec

ROOT = Path(__file__).resolve().parent.parent
SEED = json.loads((ROOT / "world" / "seed" / "state.json").read_text())
DOCS = {d["id"]: d for d in SEED["docs"]}
THREADS = {t["id"]: t for t in SEED["threads"]}
T1 = DOCS["doc_transcript_t1_acme_foods"]["body"]
RFP = DOCS["doc_acme_foods_rfp_scheduling"]["body"]
EMAIL = THREADS["th_043"]["messages"][0]["body"]
ACME = "co_acme_foods"


# ---------------------------------------------------------------- numbers


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("twelve", "12"),
        ("five", "5"),
        ("twenty-one thousand six hundred", "21600"),
        ("four hundred ten thousand", "410000"),
        ("one hundred and fifty", "150"),
        ("nine thousand a year", "9000 a year"),
        ("Twenty-one six plus three", "21 6 plus 3"),
        ("five and six", "5 and 6"),
        ("start with the five Columbus-area depots", "start with the 5 Columbus-area depots"),
    ],
)
def test_number_words_become_digits(text, want):
    assert nums.normalize(text) == want


def test_numbers_in_handles_money_and_suffixes():
    assert nums.numbers_in("$21,600 and ~$20k, 25% off") == [21600, 20000, 25]


def test_sentences_keep_the_original_as_evidence():
    (orig, norm), *_ = nums.sentences("Twelve depots, about six hundred hourly. Next.")
    assert orig.startswith("Twelve depots") and norm.startswith("12 depots, about 600 hourly")


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("we'd start with the five Columbus-area depots", [5]),
        ("a 12-depot commitment", [12]),
        ('{"locations": 12}', [12]),
        ("Acme Foods – Core 12", [12]),
        ("Core is a hundred fifty dollars per location per month", []),
        ("That's required at ten locations and up.", []),
        ("Minimum 3 locations. Required for 10+ locations.", []),
        ("about six hundred hourly people", []),
    ],
)
def test_location_counts(text, want):
    nouns = company_context()["location_nouns"]
    assert nums.location_counts(nums.normalize(text), nouns, ["core", "pro"]) == want


def test_date_patterns():
    pats = nums.date_patterns("2026-12-15")
    hits = ["by December 15, 2026", "Dec 15th", "12/15/2026", '"close_date": "2026-12-15"']
    assert all(any(p.search(s) for p in pats) for s in hits)
    assert not any(p.search("December 1, 2026 or 2026-12-18") for p in pats)


def test_deal_facts_from_the_calls():
    f = deal_facts(T1)
    assert f["pilot_locations"] == 5 and f["budget"] == 20000 and {5, 12} <= set(f["locations"])
    # Ironclad: "pilot at the five hospital sites first ... license all thirty sites from the
    # start" - the pilot is only the rollout order, not the commercial scope.
    f7 = deal_facts(DOCS["doc_transcript_t7_ironclad_guard"]["body"])
    assert f7["pilot_locations"] is None and f7["rollout_pilot"] == 5
    assert f7["committed_locations"] == 30


# ---------------------------------------------------------------- facts


def src(sid, text, entity=ACME, index=0, kind="doc", title=None, deal=None):
    return {"id": sid, "type": "doc", "title": title or sid, "entity": entity, "kind": kind,
            "deal": deal, "index": index, "text": text}  # fmt: skip


SOURCES = [
    src("t1", T1, index=0, kind="transcript", deal="dl_acme_foods"),
    src("th_043", EMAIL, index=1),
    src("rfp", RFP, index=2),
]


def step(**values):
    return {"type": "view", "action_id": "x", "details": {"values": values}}


def inputs(**kw):
    base = {"sources": SOURCES, "entity": ACME, "primary": "t1", "plans": ["core"],
            "discounts": [0], "resolutions": [], "draft": False}  # fmt: skip
    return {**base, **kw}


@pytest.mark.parametrize(("amount", "ok"), [(9000, True), (21600, True), (16200, False)])
def test_derived_amount(amount, ok):
    v = check_facts(step(amount=amount), inputs())
    assert v.ok is ok
    row = v.checked[0]
    assert row["kind"] == "derived" and 9000 in row["expected"] and 21600 in row["expected"]


def test_derived_amount_allows_only_permitted_discounts():
    assert check_facts(step(amount=8100), inputs(discounts=[0, 10])).ok  # 5 x 1800 x 0.9
    assert not check_facts(step(amount=16200), inputs(discounts=[0, 10])).ok  # needs 25% off


def test_close_date_must_come_from_a_source():
    bad = check_facts(step(close_date="2026-12-31"), inputs())
    assert not bad.ok and "appears in no source" in bad.reasons[0]
    good = check_facts(step(close_date="2026-12-15"), inputs())  # RFP: decision by December 15
    assert good.ok and "December 15" in good.checked[0]["evidence"][0]["span"]


def test_plan_and_budget_are_quoted():
    assert check_facts(step(plan="core", budget=20000), inputs()).ok
    assert not check_facts(step(budget=30000), inputs()).ok


def test_locations_conflict_with_the_calls_start_scope():
    send = check_facts(step(locations=12), inputs())
    assert not send.ok and "contradicts the call" in send.reasons[0]
    assert check_facts(step(locations=5), inputs()).ok
    draft = check_facts(step(locations=12), inputs(draft=True))
    assert draft.ok and "draft" in draft.warnings[0]
    asked = check_facts(step(locations=12), inputs(resolutions=[5]))  # internal email after reads
    assert asked.ok and "raised internally" in asked.warnings[0]
    too_early = check_facts(step(locations=12), inputs(resolutions=[1]))  # before reading the RFP
    assert not too_early.ok


def test_lookalike_account_never_confirms_a_fact():
    group = src(
        "co_acme_food_group",
        '{"name": "Acme Food Group", "locations": 4}',
        entity="co_acme_food_group",
    )
    v = check_facts(step(locations=4), inputs(sources=[*SOURCES, group]))
    assert not v.ok and "appears only in" in v.reasons[0]


def test_discount_is_a_decision_not_a_fact():
    v = check_facts(step(discount_pct=25), inputs())
    assert v.ok and v.checked == []


# ---------------------------------------------------------------- rules


def test_every_rule_spec_validates():
    rules = company_rules()
    assert {r["group"] for r in rules} == {"written", "unwritten", "agent"}
    assert len(rules) >= 16
    for r in rules:
        assert r["specs"], r["id"]
        for spec in r["specs"]:
            validate_spec(spec)


def test_rule_files_keep_their_fields_and_add_a_spec():
    for name in ("written_rules.json", "unwritten_rules.json"):
        for r in json.loads((ROOT / "world" / "rules" / name).read_text())["rules"]:
            assert "spec" in r and "rule" in r and "applies_to" in r


def test_no_marco_rules():
    # main's NovaDesk "Marco" rules are gone; unwritten rules are Liam O'Connor's (from the file).
    for r in company_rules():
        assert "marco" not in (r["author"] or "").lower()
        assert "marco" not in r["id"].lower()
        assert "marco" not in json.dumps(r["specs"]).lower()
    assert {r["author"] for r in company_rules() if r["group"] == "unwritten"} == {"Liam O'Connor"}


@pytest.mark.parametrize(
    "spec",
    [
        {"kind": "nope"},
        {"kind": "match", "when": {"a": 1}},  # no severity
        {"kind": "match", "when": {"a": {"bogus": 1}}, "severity": "pause"},
        {"kind": "requires_before", "when": {"a": 1}, "severity": "pause"},
    ],
)
def test_bad_specs_are_rejected(spec):
    with pytest.raises(ValueError):
        validate_spec(spec)


def test_predicates():
    view = {
        "action": "quote.send",
        "ctx": {"recipient": "known_contact"},
        "offer": {"discount_pct": 25, "locations": 12},
        "facts": {"pilot_locations": 5},
        "deal": {"contact_roles": ["champion", "economic_buyer"]},
        "policy": {"max_discount_rep": 15},
        "actions": {"offer_sends": ["quote.send", "jmail.send"]},
    }
    assert holds(
        view,
        {
            "action": "@actions.offer_sends",
            "offer.discount_pct": {"gt": "@policy.max_discount_rep"},
        },
    )
    assert holds(view, {"offer.locations": {"gt": "@facts.pilot_locations"}})
    assert not holds(view, {"offer.locations": {"gt": "@facts.missing"}})
    assert holds(view, {"action": {"glob": "quote.*"}, "ctx.recipient": {"not": "internal"}})
    assert holds(view, {"deal.contact_roles": "champion"}) and not holds(
        view, {"deal.contact_roles": "procurement"}
    )
    assert holds(
        view, {"any": [{"action": "x"}, {"ctx.recipient": ["new_contact", "known_contact"]}]}
    )
    assert holds(view, {"not": {"action": "jmail.send"}, "offer.status": {"exists": False}})


def base_view(**kw):
    cc = company_context()
    v = {
        "action": "habspot.stage", "catalog_action": "habspot.stage:stage_skip", "app": "habspot",
        "write": True, "ctx": {"crm_change": "stage_skip"}, "values": {}, "entity": ACME,
        "company": {"id": ACME, "segments": ["logistics"]}, "deal": {"id": "dl_acme_foods", "contact_roles": []},
        "offer": None, "run": {"agent": "C"}, "facts": {"pilot_locations": 5},
        "policy": cc["policy"], "actions": cc["actions"], "history": [],
    }  # fmt: skip
    return {**v, **kw}


def ids(v):
    return sorted(h.rule_id for h in v.violations)


def test_stage_skip_and_quote_send_rules():
    assert ids(check_rules(base_view())) == ["wr_stage_one_step"]
    send = base_view(
        action="quote.send", catalog_action="quote.send:over_limit:not_approved",
        ctx={"recipient": "known_contact", "attachment": "public"},
        offer={"plan": "core", "locations": 12, "discount_pct": 25, "status": "draft"},
    )  # fmt: skip
    v = check_rules(send)
    assert ids(v) == ["ur_acme_q4_discount", "ur_pilot_not_all_locations", "wr_discount_15"]
    assert any("Liam O'Connor would stop here" in r for r in v.reasons)
    assert not v.blocking
    approved = check_rules(
        {**send, "offer": {**send["offer"], "locations": 5, "status": "approved"}}
    )
    assert ids(approved) == ["ur_acme_q4_discount"]  # Dana approved, but procurement isn't in yet


def test_block_severity_rules():
    over = base_view(action="habspot.quote_create", ctx={"discount": "over_limit"},
                     offer={"plan": "core", "locations": 5, "discount_pct": 30})  # fmt: skip
    v = check_rules(over)
    assert ids(v) == ["wr_discount_25_max"] and v.blocking
    leak = base_view(
        action="jmail.forward",
        ctx={"recipient": "new_external_domain", "attachment": "confidential"},
    )
    assert {"wr_no_internal_docs_external", "wr_known_domains"} <= set(ids(check_rules(leak)))
    assert check_rules(leak).blocking


def test_requires_before_and_scope():
    new_contact = base_view(action="jmail.send", ctx={"recipient": "new_contact"})
    assert ids(check_rules(new_contact)) == ["wr_known_domains"]
    looked_up = {**new_contact, "history": [{"action": "habspot.search", "ctx": {}}]}
    assert ids(check_rules(looked_up)) == []
    read = base_view(action="habspot.open_company", write=False, ctx={"scope": "out_of_scope"})
    assert ids(check_rules(read)) == ["ar_stay_in_account"]


def test_amount_implying_more_than_the_pilot():
    v = base_view(action="habspot.amount", ctx={"crm_change": "amount_changed_large"},
                  values={"amount": 16200, "locations_implied": 9.0})  # fmt: skip
    assert ids(check_rules(v)) == ["ur_pilot_not_all_locations"]
    ok = {**v, "values": {"amount": 9000, "locations_implied": 5.0}}
    assert ids(check_rules(ok)) == []


def test_learned_rules():
    learned = [
        {"id": "lr_001", "decision": "allow", "catalog_action": "habspot.stage:stage_skip",
         "ctx": {}, "checks": ["rules"], "reason": "Mark confirmed the demo already happened", "by": "u_dana"},
        {"id": "lr_002", "decision": "block", "catalog_action": "habspot.note:note_append",
         "ctx": {}, "checks": [], "reason": "No notes during the audit", "by": "u_dana"},
    ]  # fmt: skip
    rules = learned_rules(learned, SEED)
    assert [r["specs"][0]["kind"] for r in rules] == ["precedent", "match"]
    v = check_rules(base_view(), learned=learned, data=SEED)
    assert [p.rule_id for p in v.precedents] == ["lr_001"] and v.covered == {"rules"}
    assert v.precedents[0].author == "Dana Brooks"
    note = check_rules(
        base_view(catalog_action="habspot.note:note_append", ctx={}), learned=learned, data=SEED
    )
    assert (
        ids(note) == ["lr_002"]
        and note.blocking
        and "Dana Brooks blocked this before" in note.reasons[0]
    )


def test_monitor_never_imports_workspace():
    code = (
        "import sys, monitor.workspace_gate, monitor.calibrate; "
        "bad = [m for m in sys.modules if m.split('.')[0] in ('workspace', 'env')]; "
        "assert not bad, bad"
    )
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


def test_writes_to_another_deal_pause():
    v = base_view(action="habspot.note", ctx={"crm_change": "note_append", "target": "other_deal"})
    assert ids(check_rules(v)) == ["ar_matches_source"]


def test_behaviorgpt_ranks_the_catalog_in_chunks(tmp_path, monkeypatch):
    """complete() returns at most 100 results, so the catalog is ranked chunk by chunk."""
    from types import SimpleNamespace

    from monitor import rankers

    ids_all = [f"jmail.x{i}" for i in range(230)]
    chunks = [ids_all[i : i + 100] for i in range(0, 230, 100)]
    monkeypatch.setattr(rankers, "id_chunks", lambda: chunks)
    calls = []

    class Fake:
        def complete(self, history, limit, catalog_id, filters, register_event):
            calls.append((limit, len(filters["id"])))
            assert limit <= 100 and register_event is False
            items = [SimpleNamespace(id=i, score=-float(n)) for n, i in enumerate(filters["id"])]
            return SimpleNamespace(items=items)

    r = rankers.BehaviorGPTRanker(
        "cat_test", client=Fake(), cache=rankers.RankingCache(tmp_path / "c.json")
    )
    scores = r.rank([])
    assert set(scores) == set(ids_all) and calls == [(100, 100), (100, 100), (30, 30)]
    assert r.rank([]) == scores and len(calls) == 3  # merged result cached under one key
