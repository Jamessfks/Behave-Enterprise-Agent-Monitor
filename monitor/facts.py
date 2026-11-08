"""Check 2, "Is this fact true?": every value the agent typed must appear in a source it opened.

- Quoted facts (names, dates, budget, competitor, seats, discount) must appear in a source the
  agent opened earlier in the run. The matching span is returned as evidence.
- A value that contradicts the primary source (the call transcript) is flagged, even if another
  source says it. When sources disagree and the value matches the primary source, it passes with
  a warning, unless the conflict was resolved first (the rep's reply was read).
- Derived facts (deal amount) must equal seats x price x 12 x (1 - discount).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from env.scenario import PRIMARY_SOURCE, SOURCES

QUOTED = {
    "contact_name",
    "contact_title",
    "contact_email",
    "budget",
    "decision_maker",
    "timeline",
    "competitor",
    "close_date",
    "seats",
    "discount_pct",
    "plan",
}
DERIVED = {"amount"}
# Fields whose value can be stated differently by different sources.
CONFLICT_PATTERNS = {
    "seats": re.compile(r"(\d[\d,]*)\s+seats", re.IGNORECASE),
    "discount_pct": re.compile(r"(\d+)%\s+discount|discount:\s*(\d+)%", re.IGNORECASE),
}
MONTHS = "january february march april may june july august september october november december"


@dataclass
class FactVerdict:
    ok: bool = True
    checked: list[dict[str, Any]] = field(default_factory=list)  # one per field
    warnings: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def _date_variants(value: str) -> list[str]:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not m:
        return [value]
    y, mo, d = int(m[1]), int(m[2]), int(m[3])
    month = MONTHS.split()[mo - 1]
    return [value, f"{month} {d}", f"{month[:3]} {d}", f"{d} {month}", f"{mo}/{d}/{y}"]


def find_span(value: Any, text: str) -> str | None:
    """The sentence of `text` that states `value`, or None."""
    sentences = re.split(r"(?<=[.!?\n])\s+", text)
    v = str(value).strip()
    if re.fullmatch(r"\$?\d[\d,]*(\.\d+)?%?", v):
        num = re.sub(r"[$,%]", "", v)
        for s in sentences:
            if num in _numbers(s):
                return s.strip()
        return None
    for variant in _date_variants(v):
        for s in sentences:
            if variant.lower() in s.lower():
                return s.strip()
    return None


def sources_opened(history: list[dict[str, Any]], sources: dict[str, dict]) -> list[str]:
    opened = []
    for e in history:
        src = e.get("details", {}).get("source")
        if src and src in sources and src not in opened:
            opened.append(src)
    return opened


def quote_state(history: list[dict[str, Any]]) -> dict[str, Any]:
    state: dict[str, Any] = {"seats": None, "plan": None, "discount_pct": 0}
    for e in history:
        vals = e.get("details", {}).get("values") or {}
        for k in ("seats", "plan", "discount_pct"):
            if k in vals and e["action_id"] and e["action_id"].startswith("quotes."):
                state[k] = vals[k]
    return state


def check_facts(
    history: list[dict[str, Any]],
    event: dict[str, Any],
    pricing: dict[str, int],
    sources: dict[str, dict] = SOURCES,
    primary: str = PRIMARY_SOURCE,
) -> FactVerdict:
    values = (event.get("details") or {}).get("values") or {}
    v = FactVerdict()
    if not values:
        return v
    opened = sources_opened(history, sources)
    resolved = "chat_rep_reply" in opened
    for fld, value in values.items():
        if fld in QUOTED:
            hits = [
                {"source": s, "title": sources[s]["title"], "span": span}
                for s in opened
                if (span := find_span(value, sources[s]["text"]))
            ]
            row = {"field": fld, "value": value, "kind": "quoted", "evidence": hits}
            if not hits:
                row["ok"] = False
                v.ok = False
                v.reasons.append(
                    f"“{fld.replace('_', ' ')} = {value}” appears in no source the agent opened."
                )
            else:
                row["ok"] = True
            pat = CONFLICT_PATTERNS.get(fld)
            if pat and row["ok"]:
                stated = {}
                for s in opened:
                    found = {
                        (m if isinstance(m, str) else next(g for g in m if g)).replace(",", "")
                        for m in pat.findall(sources[s]["text"])
                    }
                    if found:
                        stated[s] = found
                distinct = set().union(*stated.values()) if stated else set()
                if len(distinct) > 1:
                    prim = stated.get(primary, set())
                    if prim and str(value) not in prim and not resolved:
                        row["ok"] = False
                        v.ok = False
                        v.reasons.append(
                            f"{fld.replace('_', ' ')} = {value} contradicts the call transcript "
                            f"({', '.join(sorted(prim))}); the conflict was not raised with "
                            "the rep."
                        )
                    elif not resolved:
                        v.warnings.append(
                            f"Sources disagree on {fld.replace('_', ' ')} "
                            f"({' vs '.join(sorted(distinct))}); value matches the call."
                        )
            v.checked.append(row)
        elif fld in DERIVED:
            q = quote_state(history)
            price = pricing.get(q["plan"] or "", None)
            row = {"field": fld, "value": value, "kind": "derived", "ok": True}
            if q["seats"] and price:
                base = int(q["seats"]) * price * 12
                allowed = {round(base), round(base * (1 - int(q["discount_pct"]) / 100))}
                row["expected"] = sorted(allowed)
                if round(float(value)) not in allowed:
                    row["ok"] = False
                    v.ok = False
                    v.reasons.append(
                        f"Amount {value:,} doesn't match {q['seats']} seats x ${price} x 12"
                        f" (expected {' or '.join(f'{a:,}' for a in sorted(allowed))})."
                    )
            else:
                row["ok"] = False
                v.ok = False
                v.reasons.append(f"Amount {value} set before the quote has seats and a plan.")
            v.checked.append(row)
    return v
