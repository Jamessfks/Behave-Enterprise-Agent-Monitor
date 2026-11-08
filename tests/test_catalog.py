import csv
from pathlib import Path

import pytest

from monitor.catalog import APP_OF_PREFIX, CATALOG_CSV, ID_RE, PHASES, ROLES, load_catalog
from monitor.events import load_run

RUNS = Path(__file__).resolve().parent.parent / "runs"


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_raw_rows_are_complete():
    with CATALOG_CSV.open(newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        assert r["event_type"] == "product" and r["group"] == "product", r["id"]
        assert r["name"].strip(), r["id"]
        assert r["irreversible"] in {"true", "false"}, r["id"]


def test_size_fits_one_ranking_call(catalog):
    assert 50 <= len(catalog) <= 100


def test_ids_and_apps(catalog):
    for a in catalog.values():
        assert ID_RE.match(a.id), a.id
        assert a.app == APP_OF_PREFIX[a.id.split(".")[0]], a.id
        assert a.role in ROLES and a.phase in PHASES, a.id


def test_names_are_unique_sentences(catalog):
    names = [a.name for a in catalog.values()]
    assert len(set(names)) == len(names)
    assert all(len(n.split()) >= 4 for n in names)


def test_enough_wrong_actions(catalog):
    wrong = sum(a.role == "wrong" for a in catalog.values())
    assert wrong / len(catalog) >= 0.3


def test_every_run_action_is_in_catalog_with_matching_flags(catalog):
    for path in RUNS.glob("*.jsonl"):
        for e in load_run(path):
            if e["type"] != "view":
                continue
            a = catalog.get(e["action_id"])
            assert a is not None, f"{path.stem}: unknown {e['action_id']}"
            assert e["details"]["irreversible"] == a.irreversible, (path.stem, a.id)
            assert e["details"]["app"] == a.app, (path.stem, a.id)


def test_careful_runs_use_no_wrong_actions(catalog):
    for path in RUNS.glob("careful_*.jsonl"):
        for e in load_run(path):
            if e["type"] == "view":
                assert catalog[e["action_id"]].role != "wrong", (path.stem, e["action_id"])
                assert not catalog[e["action_id"]].irreversible, (path.stem, e["action_id"])


def test_converts_to_a_valid_parquet_without_our_columns(tmp_path):
    import pyarrow.parquet as pq
    from behaviorgpt import catalog_from_csv

    src = tmp_path / "actions.csv"
    src.write_bytes(CATALOG_CSV.read_bytes())
    out = catalog_from_csv(str(src))
    cols = set(pq.read_schema(out).names)
    assert {"id", "name", "brand", "categories", "event_type", "group"} <= cols
    assert not cols & {"irreversible", "role", "phase"}
    assert pq.read_metadata(out).num_rows == len(load_catalog())
