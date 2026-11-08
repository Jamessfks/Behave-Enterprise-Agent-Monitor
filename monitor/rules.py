"""Check 3, "Is this allowed?": written policies, unwritten rules, agent roles and learned rules.

Rules are data (ADR 0008). Each rule's `spec` is one (or a list) of a few generic kinds, tested
against the step's rule view (monitor/adapter.py `rule_view`):

- match: `when` holds and `unless` doesn't -> a violation with `severity` pause or block.
- requires_before: `when` holds and no earlier step of the run satisfies `requires`.
- advisory: shown to people when `when` holds (or always); never pauses.
- precedent: a person allowed this step before, with a reason (learned "allow"); the step
  passes, citing them, if the checks that failed are the ones they allowed.
A learned "block" becomes a match rule on the same catalog action, citing the person.

Predicates: {path: condition, ...} (all must hold), plus "all"/"any"/"not". A path is dotted
into the view ("ctx.crm_change", "offer.discount_pct", "company.id"). A condition is a value
(equals; on a list value, contains), a list (in), or {gt|ge|lt|le: n}, {glob: "quote.send*"},
{not: condition}, {exists: bool}. A string "@path" reads its value from the view
("@policy.max_discount_rep", "@facts.pilot_locations").
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any

from monitor.context import company_rules, user_name

KINDS = {"match", "requires_before", "advisory", "precedent"}
SEVERITIES = {"pause", "block"}
CMP = {"gt": operator.gt, "ge": operator.ge, "lt": operator.lt, "le": operator.le}
OPS = {*CMP, "glob", "not", "exists", "in"}


@dataclass
class RuleHit:
    rule_id: str
    text: str
    group: str  # written | unwritten | agent | learned
    author: str | None = None
    source: str | None = None
    severity: str | None = None


@dataclass
class RuleVerdict:
    ok: bool = True
    violations: list[RuleHit] = field(default_factory=list)
    precedents: list[RuleHit] = field(default_factory=list)
    advisories: list[RuleHit] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    covered: set[str] = field(default_factory=set)  # checks the matched precedents allow

    @property
    def blocking(self) -> bool:
        return any(h.severity == "block" for h in self.violations)


# ---------------------------------------------------------------- predicates


def resolve(view: dict[str, Any], path: str) -> Any:
    cur: Any = view
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _ref(view: dict[str, Any], x: Any) -> Any:
    return resolve(view, x[1:]) if isinstance(x, str) and x.startswith("@") else x


def _eq(value: Any, c: Any) -> bool:
    return c in value if isinstance(value, list) else value == c


def _number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def test(view: dict[str, Any], value: Any, cond: Any) -> bool:
    if isinstance(cond, dict):
        for op, arg in cond.items():
            arg = _ref(view, arg)
            if op == "not":
                ok = not test(view, value, arg)
            elif op in CMP:
                ok = _number(value) and _number(arg) and CMP[op](value, arg)
            elif op == "glob":
                ok = value is not None and any(
                    fnmatch(str(value), p) for p in (arg if isinstance(arg, list) else [arg])
                )
            elif op == "exists":
                ok = (value is not None) == bool(arg)
            elif op == "in":
                ok = any(_eq(value, c) for c in arg or [])
            else:
                raise ValueError(f"unknown operator {op!r}")
            if not ok:
                return False
        return True
    cond = _ref(view, cond)
    if isinstance(cond, list):
        return any(_eq(value, c) for c in cond)
    return _eq(value, cond)


def holds(view: dict[str, Any], pred: dict[str, Any] | None) -> bool:
    """True when every clause of the predicate holds for the view (an empty predicate holds)."""
    for key, cond in (pred or {}).items():
        if key == "all":
            ok = all(holds(view, p) for p in cond)
        elif key == "any":
            ok = any(holds(view, p) for p in cond)
        elif key == "not":
            ok = not holds(view, cond)
        else:
            ok = test(view, resolve(view, key), cond)
        if not ok:
            return False
    return True


def _check_pred(pred: Any, where: str) -> None:
    if not isinstance(pred, dict):
        raise TypeError(f"{where}: a predicate is an object")
    for key, cond in pred.items():
        if key in ("all", "any"):
            for p in cond:
                _check_pred(p, where)
        elif key == "not":
            _check_pred(cond, where)
        else:
            _check_cond(cond, f"{where}.{key}")


def _check_cond(cond: Any, where: str) -> None:
    if isinstance(cond, dict):
        for op, arg in cond.items():
            if op not in OPS:
                raise ValueError(f"{where}: unknown operator {op!r}")
            if op == "not":
                _check_cond(arg, where)


def validate_spec(spec: dict[str, Any]) -> None:
    """Raise ValueError (TypeError for a predicate that isn't an object) unless the spec is one
    of the generic kinds, well formed."""
    kind = spec.get("kind")
    if kind not in KINDS:
        raise ValueError(f"unknown rule kind {kind!r}")
    for key in ("when", "unless", "requires"):
        if key in spec:
            _check_pred(spec[key], key)
    if kind in ("match", "requires_before") and spec.get("severity") not in SEVERITIES:
        raise ValueError(f"{kind} needs severity pause or block")
    if kind == "match" and "when" not in spec:
        raise ValueError("match needs `when`")
    if kind == "requires_before" and not ("when" in spec and "requires" in spec):
        raise ValueError("requires_before needs `when` and `requires`")
    if kind == "precedent" and not spec.get("catalog_action"):
        raise ValueError("precedent needs catalog_action")


# ---------------------------------------------------------------- learned rules


def learned_rules(learned: list[dict[str, Any]], data: dict | None = None) -> list[dict[str, Any]]:
    """The workspace's learned rules ({id, decision, catalog_action, ctx, checks, reason, by,
    entity?}) as rules with specs. Allow -> precedent; block -> match, severity block."""
    out = []
    for r in learned or []:
        ca = r.get("catalog_action")
        if not ca or not r.get("reason"):
            continue
        if r.get("decision") == "block":
            when = {"catalog_action": ca}
            if r.get("entity"):
                when["entity"] = r["entity"]
            spec = {"kind": "match", "when": when, "severity": "block"}
        else:
            spec = {
                "kind": "precedent",
                "catalog_action": ca,
                "entity": r.get("entity"),
                "checks": list(r.get("checks") or []),
            }
        out.append(
            {
                "id": r.get("id") or f"learned.{ca}",
                "group": "learned",
                "text": r["reason"].strip(),
                "author": user_name(data, r.get("by")) or "a person",
                "source": "Learned rule",
                "specs": [spec],
            }
        )
    return out


# ---------------------------------------------------------------- the check


GROUP_LABEL = {"written": "Written policy", "agent": "Agent role"}


def _reason(h: RuleHit) -> str:
    if h.group == "learned":
        return f"{h.author} blocked this before: “{h.text}”"
    if h.author:
        return f"{h.author} would stop here: “{h.text}”"
    return f"{GROUP_LABEL.get(h.group, 'Policy')}: {h.text}"


def _done(view: dict[str, Any], requires: dict[str, Any]) -> bool:
    return any(holds(e, requires) for e in view.get("history") or [])


def check_rules(
    view: dict[str, Any],
    rules: list[dict[str, Any]] | None = None,
    learned: list[dict[str, Any]] | None = None,
    checks_failed: list[str] | tuple = (),
    data: dict | None = None,
) -> RuleVerdict:
    """Violations, precedents and advisories for one step. `checks_failed` are the other checks
    that already failed (normal, facts); a precedent must cover all failed checks to apply."""
    v = RuleVerdict()
    all_rules = list(rules if rules is not None else company_rules()) + learned_rules(
        learned or [], data
    )
    precedents: list[tuple[dict, dict]] = []
    for r in all_rules:
        for spec in r["specs"]:
            kind = spec.get("kind")
            if kind == "precedent":
                precedents.append((r, spec))
                continue
            if not holds(view, spec.get("when")):
                continue
            hit = RuleHit(r["id"], r["text"], r["group"], r.get("author"), r.get("source"))
            if kind == "advisory":
                v.advisories.append(hit)
                continue
            if kind == "match" and spec.get("unless") and holds(view, spec["unless"]):
                continue
            if kind == "requires_before" and _done(view, spec["requires"]):
                continue
            hit.severity = spec.get("severity", "pause")
            v.violations.append(hit)
            v.reasons.append(_reason(hit))
            break  # one violation per rule
    v.ok = not v.violations
    failed = set(checks_failed) | ({"rules"} if v.violations else set())
    for r, spec in precedents:
        same = spec["catalog_action"] == view.get("catalog_action") and (
            not spec.get("entity") or spec["entity"] == view.get("entity")
        )
        checks = set(spec.get("checks") or [])
        if same and (not checks or checks & failed):
            v.precedents.append(
                RuleHit(r["id"], r["text"], "learned", r.get("author"), r["source"])
            )
            v.covered |= checks or failed
    return v
