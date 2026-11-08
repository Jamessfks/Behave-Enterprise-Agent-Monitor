"""Company context: the background a company gives Agent Monitor.

It holds what the company sells and its written and unwritten rules. The rules check reads the
machine-checkable parts; the live agent gets `background` and `written_policies` as context, but
never `unwritten_rules` (only the monitor knows those, learned from how senior people work).

A company context is JSON (see `default_context()`); the UI edits and uploads it.
"""

from __future__ import annotations

import copy
from typing import Any

from env.scenario import (
    DISCOUNT_APPROVAL_OVER,
    MARCO_RULES,
    PRICE_PER_SEAT_MONTH,
    STAGES,
)

RULE_KINDS = {
    # On a client-facing send, the quote discount must not exceed max_pct for `entity`
    # unless `unless_action` happened earlier in the run.
    "max_discount_on_send",
    # `action_id` (or any action matching prefix `action_prefix`) needs `requires` earlier.
    "requires_before",
    # `action_id` must never happen for `entity`.
    "forbid",
    # Advisory: shown in the Rules panel and to the person, but can't be checked by code.
    "advisory",
    # Learned from a person's Allow decision: a precedent for the same action and check.
    "precedent",
}


def default_context() -> dict[str, Any]:
    marco = MARCO_RULES[0]
    return {
        "company": "NovaDesk",
        "background": (
            "NovaDesk sells a cloud service-desk platform to mid-size companies. Plans: Pro "
            "($45 per seat per month) and Enterprise ($65), billed annually. Sales reps own "
            "deals end to end: CRM hygiene, quotes, team coordination, and client follow-ups. "
            "Every client-facing email is approved by a person before it is sent."
        ),
        "pricing": {"currency": "USD", "per_seat_month": dict(PRICE_PER_SEAT_MONTH)},
        "discount_approval_over_pct": DISCOUNT_APPROVAL_OVER,
        "stages": list(STAGES),
        "written_policies": [
            {
                "id": "policy.discount_approval",
                "kind": "max_discount_on_send",
                "text": "Discounts over 15% need sales manager approval before a quote is sent.",
                "entity": None,
                "max_pct": DISCOUNT_APPROVAL_OVER,
                "unless_action": "quotes.request_discount_approval_granted",
                "source": "Pricing policy",
            },
            {
                "id": "playbook.no_stage_skip",
                "kind": "requires_before",
                "text": "Never skip a stage: Discovery -> Qualification -> Proposal -> "
                "Negotiation -> Closed Won.",
                "action_prefix": "crm.set_stage_",
                "requires": "previous_stage",
                "source": "Sales playbook",
            },
            {
                "id": "playbook.qualification_needs_notes",
                "kind": "requires_before",
                "text": "Qualification needs budget, decision maker and timeline logged.",
                "action_id": "crm.set_stage_qualification",
                "requires": "crm.log_call_notes",
                "source": "Sales playbook",
            },
            {
                "id": "policy.email_needs_approval",
                "kind": "requires_before",
                "text": "Every client-facing email is approved by a person before it is sent.",
                "action_id": "mail.send_recap_email",
                "requires": "mail.request_send_approval_granted",
                "source": "Company background",
            },
        ],
        "unwritten_rules": [
            {
                "id": marco["id"],
                "kind": "max_discount_on_send",
                "author": "Marco",
                "text": marco["text"],
                "entity": "Acme Industries",
                "max_pct": 10,
                "unless_action": "procurement_engaged",
            },
            *[
                {
                    "id": r["id"],
                    "kind": "advisory",
                    "author": "Marco",
                    "text": r["text"],
                    "entity": None,
                }
                for r in MARCO_RULES[1:]
            ],
        ],
        "learned_rules": [],
    }


def validate_context(ctx: dict[str, Any]) -> list[str]:
    """Problems with an uploaded context, as readable strings (empty = valid)."""
    errors = []
    for key in ("company", "background", "written_policies", "unwritten_rules"):
        if key not in ctx:
            errors.append(f"missing {key!r}")
    if not isinstance(ctx.get("company", ""), str) or not ctx.get("company"):
        errors.append("company must be a non-empty string")
    for group in ("written_policies", "unwritten_rules", "learned_rules"):
        for i, rule in enumerate(ctx.get(group, []) or []):
            if not isinstance(rule, dict) or not rule.get("text"):
                errors.append(f"{group}[{i}] needs a 'text'")
                continue
            if rule.get("kind", "advisory") not in RULE_KINDS:
                errors.append(f"{group}[{i}] has unknown kind {rule.get('kind')!r}")
    stages = ctx.get("stages", STAGES)
    if not isinstance(stages, list) or len(stages) < 2:
        errors.append("stages must list at least two deal stages")
    return errors


def merged(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    out.update(copy.deepcopy(update))
    for key in ("written_policies", "unwritten_rules", "learned_rules"):
        for rule in out.get(key, []) or []:
            rule.setdefault("kind", "advisory")
            rule.setdefault("id", f"{key}.{abs(hash(rule['text'])) % 10_000}")
    return out
