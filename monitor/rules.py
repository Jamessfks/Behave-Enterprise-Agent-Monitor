"""Check 3, "Is this allowed?": written policies, unwritten rules, and rules learned from people.

Rules come from the company context (env/company.py). Each kind is checked by code:

- max_discount_on_send: a client-facing send carries a discount above max_pct, for the rule's
  entity (or any), and the rule's `unless_action` hasn't happened.
- requires_before: an action needs another to have happened earlier. The special requirement
  `previous_stage` enforces the stage order.
- forbid: the action never happens (for the rule's entity, if set).
- precedent: a person allowed this action before with a reason; the step passes, citing them.
- advisory: shown to people, not checked by code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CLIENT_SENDS = {
    "quotes.send_quote_to_client",
    "mail.send_recap_email",
    "chat.message_client_directly",
}
# Events that unlock rules. Approvals are granted by a person in the UI (or a scripted reply).
GRANTS = {
    "quotes.request_discount_approval_granted": "discount_approved",
    "mail.request_send_approval_granted": "send_approved",
}


@dataclass
class RuleHit:
    rule_id: str
    text: str
    group: str  # written | unwritten | learned
    author: str | None = None
    source: str | None = None


@dataclass
class RuleVerdict:
    ok: bool = True
    violations: list[RuleHit] = field(default_factory=list)
    precedents: list[RuleHit] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _done(history: list[dict[str, Any]]) -> set[str]:
    out = {e["action_id"] for e in history if e["type"] == "view"}
    for e in history:
        out.update((e.get("details") or {}).get("grants") or [])
    return out


def _discount(history: list[dict[str, Any]], event: dict[str, Any]) -> int:
    d = 0
    for e in [*history, event]:
        vals = (e.get("details") or {}).get("values") or {}
        if "discount_pct" in vals:
            d = int(vals["discount_pct"])
    return d


def _stage(history: list[dict[str, Any]], stages: list[str]) -> str:
    stage = stages[0]
    for e in history:
        vals = (e.get("details") or {}).get("values") or {}
        if (e["action_id"] or "").startswith("crm.set_stage_") and "stage" in vals:
            stage = vals["stage"]
    return stage


def check_rules(
    history: list[dict[str, Any]], event: dict[str, Any], ctx: dict[str, Any], checks_failed=()
) -> RuleVerdict:
    v = RuleVerdict()
    if event["type"] != "view":
        return v
    aid = event["action_id"]
    entity = (event.get("details") or {}).get("entity")
    done = _done(history)
    stages = ctx.get("stages") or []

    groups = [
        ("written", ctx.get("written_policies") or []),
        ("unwritten", ctx.get("unwritten_rules") or []),
    ]
    for group, rules in groups:
        for r in rules:
            kind = r.get("kind", "advisory")
            hit = False
            if kind == "max_discount_on_send" and aid in CLIENT_SENDS:
                applies = not r.get("entity") or r.get("entity") == entity
                unlocked = (
                    r.get("unless_action") in done or GRANTS.get(r.get("unless_action", "")) in done
                )
                hit = applies and not unlocked and _discount(history, event) > r["max_pct"]
            elif kind == "requires_before":
                matches = aid == r.get("action_id") or (
                    r.get("action_prefix") and aid.startswith(r["action_prefix"])
                )
                if matches and r.get("requires") == "previous_stage":
                    target = ((event.get("details") or {}).get("values") or {}).get("stage")
                    cur = _stage(history, stages)
                    if target in stages and cur in stages:
                        hit = stages.index(target) > stages.index(cur) + 1
                elif matches:
                    req = r.get("requires")
                    hit = req not in done and GRANTS.get(req or "") not in done
            elif kind == "forbid":
                hit = aid == r.get("action_id") and (
                    not r.get("entity") or r.get("entity") == entity
                )
            if hit:
                v.ok = False
                h = RuleHit(r["id"], r["text"], group, r.get("author"), r.get("source"))
                v.violations.append(h)
                if h.author:
                    v.reasons.append(f"{h.author} would stop here: “{h.text}”")
                else:
                    v.reasons.append(f"{h.source or 'Policy'}: {h.text}")

    for r in ctx.get("learned_rules") or []:
        same = r.get("action_id") == aid and (not r.get("entity") or r.get("entity") == entity)
        if same and (set(r.get("checks") or []) & set(checks_failed) or not r.get("checks")):
            v.precedents.append(
                RuleHit(r["id"], r["text"], "learned", r.get("author"), "Learned rule")
            )
    return v
