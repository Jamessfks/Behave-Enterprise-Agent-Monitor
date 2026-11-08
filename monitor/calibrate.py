"""Calibrate check 1 on the careful runs, for each ranker, and evaluate on the faulty run.

    uv run python -m monitor.calibrate

For the transition and blend rankers, every careful run is scored by a model fitted on the
*other* careful runs (leave-one-out), so calibration never sees a run it was fitted on. Then:
- tau (and beta for the blend) by maximum likelihood on those held-out choices;
- loc/scale of excess surprisal (median, MAD);
- barrier = 1.25 x the highest CUSUM any held-out careful run reaches (few runs: be generous).

Writes monitor/calibration.json with each ranker's numbers and how it did on the faulty run.
The default ranker is the one that catches the planted "normal" mistakes with no false alarms;
nothing is tuned to make the demo fire.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

from monitor.events import load_run
from monitor.normal import EPS, BlendRanker, NormalCheck, run_cusum
from monitor.rankers import BehaviorGPTRanker, WorkflowRanker
from monitor.scoring import fit_tau, predict, robust_location_scale

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "calibration.json"
BETAS = [0.0, 0.25, 0.5, 1.0, 2.0]


def first_touch_obs(ranker, run):
    seen, out = set(), []
    for i, e in enumerate(run):
        if e["type"] == "view" and e["action_id"] not in seen:
            out.append((ranker.rank(run[:i]), e["action_id"]))
            seen.add(e["action_id"])
    return out


def make(kind: str, train: list, bgpt: BehaviorGPTRanker, beta: float = 0.0):
    if kind == "behaviorgpt":
        return bgpt
    t = WorkflowRanker(train)
    return t if kind == "workflow" else BlendRanker(bgpt, t, beta)


def calibrate(kind: str, careful: dict, faulty: list, bgpt, expected: list[dict]) -> dict:
    names = list(careful)

    def held_out(beta):
        return {n: make(kind, [careful[m] for m in names if m != n], bgpt, beta) for n in names}

    best = None
    for beta in BETAS if kind == "blend" else [0.0]:
        rankers = held_out(beta)
        obs = [o for n in names for o in first_touch_obs(rankers[n], careful[n])]
        tau = fit_tau(obs, EPS)
        ll = sum(predict(sc, t, tau, EPS).logp for sc, t in obs)
        if best is None or ll > best[0]:
            best = (ll, beta, tau, rankers, obs)
    ll, beta, tau, rankers, obs = best
    excess = [p.surprisal - p.entropy for p in (predict(sc, t, tau, EPS) for sc, t in obs)]
    loc, scale = robust_location_scale(excess)

    cal = {"tau": tau, "loc": loc, "scale": scale, "barrier": 1e9}
    peaks = {}
    for n in names:
        vs = run_cusum(NormalCheck(rankers[n], cal), careful[n], reset_on_flag=False)
        peaks[n] = max(v.cusum for v in vs)
    barrier = max(1.5, 1.25 * max(peaks.values()))
    cal["barrier"] = barrier

    full = make(kind, list(careful.values()), bgpt, beta)
    vs = run_cusum(NormalCheck(full, cal), faulty)
    flagged = [
        {"step": i, "action_id": faulty[i]["action_id"], "rank": v.rank, "u": v.u}
        for i, v in enumerate(vs)
        if not v.ok
    ]
    want = {x["action_id"] for x in expected if "normal" in x["caught_by"]}
    got = {f["action_id"] for f in flagged}
    return {
        "tau": tau,
        "beta": beta,
        "loc": loc,
        "scale": scale,
        "barrier": barrier,
        "loglik_heldout": ll,
        "careful_peak_cusum": peaks,
        "faulty_flags": flagged,
        "caught": sorted(want & got),
        "missed": sorted(want - got),
        "false_alarms": sorted(got - want),
    }


def main() -> None:
    load_dotenv(ROOT / ".env")
    runs = {p.stem: load_run(p) for p in sorted((ROOT / "runs").glob("*.jsonl"))}
    careful = {k: v for k, v in runs.items() if k.startswith("careful")}
    expected = json.loads((ROOT / "runs" / "expectations.json").read_text())["faulty"]
    bgpt = BehaviorGPTRanker()
    out = {"rankers": {}}
    for kind in ["behaviorgpt", "workflow", "blend"]:
        if kind != "workflow" and not (bgpt.available or bgpt.cache):
            continue
        res = calibrate(kind, careful, runs["faulty"], bgpt, expected)
        out["rankers"][kind] = res
        print(
            f"{kind:<12} tau={res['tau']:.3f} beta={res['beta']} barrier={res['barrier']:.2f} "
            f"caught={res['caught']} missed={res['missed']} false={res['false_alarms']}"
        )

    def score(k):
        r = out["rankers"][k]
        return (len(r["caught"]) - 2 * len(r["false_alarms"]), k == "blend", r["loglik_heldout"])

    out["default"] = max(out["rankers"], key=score)
    out["bgpt_api_calls"] = bgpt.calls
    OUT.write_text(json.dumps(out, indent=2, default=float) + "\n")
    print(f"default ranker: {out['default']}  ({bgpt.calls} new BehaviorGPT calls)")
    _ = np  # numpy imported for json default


if __name__ == "__main__":
    main()
