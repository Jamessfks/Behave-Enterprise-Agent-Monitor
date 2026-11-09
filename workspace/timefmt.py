"""Portable strftime: "%-d" / "%-I" (no leading zero) work on Mac and Linux only; Windows spells
them "%#d" / "%#I". Use `ftime(d, fmt)` with the POSIX spelling everywhere."""

import os
from datetime import date, datetime


def ftime(d: date | datetime, fmt: str) -> str:
    return d.strftime(fmt.replace("%-", "%#") if os.name == "nt" else fmt)
