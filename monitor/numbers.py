"""Numbers in sources: number words to digits, numbers, location counts and dates, with the
original sentence kept as evidence.

Call transcripts spell numbers out ("twelve depots", "twenty-one thousand six hundred a year"),
so the fact check normalizes every sentence first: "twelve" -> 12, "twenty-one thousand six
hundred" -> 21600, "five" -> 5. Adjacent numbers that don't compose stay separate
("twenty-one six" -> "21 6").
"""

from __future__ import annotations

import re
from collections.abc import Iterable

UNITS = {
    w: i
    for i, w in enumerate(
        ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    )
}
TEENS = {
    w: 10 + i
    for i, w in enumerate(
        [
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
        ]
    )
}
TENS = {
    w: 20 + 10 * i
    for i, w in enumerate(
        ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    )
}
SCALES = {"thousand": 1000, "million": 1_000_000}
WORDS = {**UNITS, **TEENS, **TENS, "hundred": 100, **SCALES}
_WORD = "|".join(sorted(WORDS, key=len, reverse=True))
RUN_RE = re.compile(rf"\b(?:{_WORD})\b(?:(?:[\s-]+(?:and[\s-]+)?)(?:{_WORD})\b)*", re.IGNORECASE)
# What may follow what inside one number ("tens_unit" = twenty-one).
FOLLOWS = {
    None: {"unit", "teen", "tens", "hundred", "scale"},
    "unit": {"hundred", "scale"},
    "teen": {"hundred", "scale"},
    "tens": {"unit", "hundred", "scale"},
    "tens_unit": {"hundred", "scale"},
    "hundred": {"unit", "teen", "tens", "scale"},
    "scale": {"unit", "teen", "tens"},
}
NUM_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?(?:\s?[kK]\b)?")
STOP = "per|a|an|each|every|of|for|to|at|and|or|than|in|on|by|from|with|dollars|usd"
THRESHOLD = "at|minimum|min|at least|up to|under|over|above|below|from|max|maximum"
MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]


def _kind(w: str) -> str:
    if w in UNITS:
        return "unit"
    if w in TEENS:
        return "teen"
    if w in TENS:
        return "tens"
    return "hundred" if w == "hundred" else "scale"


def _parse_run(run: str) -> str:
    """'twenty-one thousand six hundred' -> '21600'; 'twenty-one six' -> '21 6'."""
    out: list[str] = []
    total = cur = 0
    last: str | None = None
    pending_and = False

    def flush():
        nonlocal total, cur, last
        if last is not None:
            out.append(str(total + cur))
        total = cur = 0
        last = None

    for w in re.split(r"[\s-]+", run.strip()):
        lw = w.lower()
        if lw == "and":
            if last in ("hundred", "scale"):
                pending_and = True
            else:
                flush()
                out.append(w)
            continue
        kind = _kind(lw)
        if kind not in FOLLOWS[last] or (pending_and and kind not in ("unit", "teen", "tens")):
            flush()
            if pending_and:
                out.append("and")
        pending_and = False
        val = WORDS[lw]
        if kind in ("unit", "teen", "tens"):
            cur += val
            kind = "tens_unit" if kind == "unit" and last == "tens" else kind
        elif kind == "hundred":
            cur = (cur or 1) * 100
        else:
            total += (cur or 1) * val
            cur = 0
        last = kind
    flush()
    if pending_and:
        out.append("and")
    return " ".join(out)


def normalize(text: str) -> str:
    """The text with spelled-out numbers replaced by digits."""
    return RUN_RE.sub(lambda m: _parse_run(m.group(0)), text)


def sentences(text: str) -> list[tuple[str, str]]:
    """(original sentence, normalized sentence) for every sentence or line of `text`."""
    out = []
    for s in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        s = s.strip()
        if s:
            out.append((s, normalize(s)))
    return out


def numbers_in(normalized: str) -> list[float]:
    """Every number in a normalized sentence: '$21,600' -> 21600, '$20k' -> 20000, '25%' -> 25."""
    out = []
    for m in NUM_RE.finditer(normalized):
        raw = m.group(0)
        k = raw.lower().endswith("k")
        num = re.sub(r"[^\d.]", "", raw.rstrip("kK"))
        if not num or num == ".":
            continue
        try:
            v = float(num.rstrip("."))
        except ValueError:
            continue
        out.append(v * 1000 if k else v)
    return out


def location_counts(normalized: str, nouns: Iterable[str], plans: Iterable[str] = ()) -> list[int]:
    """Location counts stated in a normalized sentence: a number next to a location noun
    ('5 Columbus-area depots', '12-depot', '"locations": 12') or after a plan name ('Core 12')."""
    noun = "|".join(re.escape(n) for n in nouns)
    # Up to two describing words in between ("5 Columbus-area depots"), never a price or a
    # threshold ("$150 per location", "at 10 locations and up", "minimum 3 locations").
    between = rf"(?:(?!(?:{STOP})\b)[A-Za-z][\w-]*\s+){{0,2}}?"
    pats = [
        rf"(?<![$\d.,])\b(\d+)(\+?)[\s-]+{between}(?:{noun})(?:e?s)?\b(?!\s+(?:and up|or more))",
        rf"\b(?:{noun})(?:e?s)?\"?\s*[:=]\s*(\d+)()\b",
    ]
    if plans:
        pats.append(rf"\b(?:{'|'.join(re.escape(p) for p in plans)})\s+(\d+)()\b")
    out: list[int] = []
    for p in pats:
        for m in re.finditer(p, normalized, re.IGNORECASE):
            lead = normalized[max(0, m.start() - 14) : m.start()].lower()
            if m.group(2) or re.search(rf"\b(?:{THRESHOLD})\s*$", lead):
                continue
            out.append(int(m.group(1)))
    return out


def date_patterns(value: str) -> list[re.Pattern]:
    """Ways a source can state an ISO date: 2026-12-15, December 15(th), Dec 15, 15 December,
    12/15/2026, 12/15."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(value).strip()[:10])
    if not m:
        return [re.compile(re.escape(str(value)), re.IGNORECASE)]
    y, mo, d = int(m[1]), int(m[2]), int(m[3])
    month = MONTHS[mo - 1]
    forms = [
        rf"{y}-{mo:02d}-{d:02d}",
        rf"\b{month}\s+{d}(?:st|nd|rd|th)?(?!\d)",
        rf"\b{month[:3]}\.?\s+{d}(?:st|nd|rd|th)?(?!\d)",
        rf"(?<!\d){d}(?:st|nd|rd|th)?\s+(?:of\s+)?{month}\b",
        rf"(?<![\d/]){mo}/{d}(?:/{y}|/{y % 100})?(?![\d/])",
    ]
    return [re.compile(f, re.IGNORECASE) for f in forms]
