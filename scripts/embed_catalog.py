"""Convert catalog/actions.csv to parquet and embed it with BehaviorGPT.

Sends the catalog (fictional workplace actions, no personal data) to Unbox AI. The file name
`actions.parquet` is the catalog's name, so re-running refreshes the same catalog slot.
Writes the resulting id to .env as UNBOXAI_CATALOG_ID.

    uv run python scripts/embed_catalog.py [path/to/actions.csv]
"""

from __future__ import annotations

import sys
from pathlib import Path

from behaviorgpt import UnboxAIClient, catalog_from_csv
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def set_env(key: str, value: str) -> None:
    env = ROOT / ".env"
    lines = env.read_text().splitlines() if env.exists() else []
    lines = [ln for ln in lines if not ln.startswith(f"{key}=")] + [f"{key}={value}"]
    env.write_text("\n".join(lines) + "\n")


def embed(csv_path: Path) -> str:
    load_dotenv(ROOT / ".env")
    parquet = catalog_from_csv(str(csv_path))
    print(f"built {parquet}")
    client = UnboxAIClient(market="us")
    job = client.embed(parquet, wait=True, timeout=1800.0)
    print(f"embedded: catalog_id={job.catalog_id}")
    return job.catalog_id


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "catalog" / "actions.csv"
    cid = embed(src)
    set_env("UNBOXAI_CATALOG_ID", cid)
    print("wrote UNBOXAI_CATALOG_ID to .env")
