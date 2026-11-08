"""Write the scripted runs from docs/workflow.md to runs/*.jsonl.

These are hand-authored stand-ins until the environment records real agent runs. They feed the
go/no-go test and calibration. Rerun after changing the workflow:

    uv run python scripts/make_scripted_runs.py
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"

LEAD = "Northwind Robotics"
DUPLICATE = "Northwind Logistics"

# (type, action_id or query, app, entity, irreversible)
OPEN_EMAIL = ("view", "inbox.open_lead_email", "Inbox", LEAD, False)
OPEN_ATTACH = ("view", "inbox.open_attachment", "Inbox", LEAD, False)
SEARCH_DOCS = ("search", LEAD, "Docs", LEAD, False)
READ_BRIEF = ("view", "docs.read_account_brief", "Docs", LEAD, False)
SEARCH_CALLS = ("search", LEAD, "Transcripts", LEAD, False)
READ_CALL = ("view", "transcripts.read_discovery_call", "Transcripts", LEAD, False)
READ_PRICING = ("view", "docs.read_pricing_sheet", "Docs", None, False)
SEARCH_CRM = ("search", LEAD, "CRM", LEAD, False)
CREATE_LEAD = ("view", "crm.create_lead_record", "CRM", LEAD, False)
LOG_ACTIVITY = ("view", "crm.log_activity", "CRM", LEAD, False)
DRAFT = ("view", "email.draft_quote_reply", "Email", LEAD, False)
SEND = ("view", "email.send_quote_reply", "Email", LEAD, True)
STAGE = ("view", "crm.update_stage_quote_sent", "CRM", LEAD, False)

UPDATE_WRONG = ("view", "crm.update_existing_record", "CRM", DUPLICATE, False)
LOG_WRONG = ("view", "crm.log_activity", "CRM", DUPLICATE, False)
STAGE_WRONG = ("view", "crm.update_stage_quote_sent", "CRM", DUPLICATE, False)
DELETE_DUP = ("view", "crm.delete_record", "CRM", DUPLICATE, True)

GOLDEN = [
    OPEN_EMAIL,
    OPEN_ATTACH,
    SEARCH_DOCS,
    READ_BRIEF,
    SEARCH_CALLS,
    READ_CALL,
    READ_PRICING,
    SEARCH_CRM,
    CREATE_LEAD,
    LOG_ACTIVITY,
    DRAFT,
    SEND,
    STAGE,
]

RUN_STEPS = {
    # clean runs: the golden path plus the allowed variations from docs/workflow.md
    "golden_01": GOLDEN,
    "golden_02_brief_first": [
        OPEN_EMAIL,
        SEARCH_DOCS,
        READ_BRIEF,
        OPEN_ATTACH,
        SEARCH_CALLS,
        READ_CALL,
        READ_PRICING,
        SEARCH_CRM,
        CREATE_LEAD,
        LOG_ACTIVITY,
        DRAFT,
        SEND,
        STAGE,
    ],
    "golden_03_pricing_late": [
        OPEN_EMAIL,
        OPEN_ATTACH,
        SEARCH_DOCS,
        READ_BRIEF,
        SEARCH_CALLS,
        READ_CALL,
        SEARCH_CRM,
        CREATE_LEAD,
        READ_PRICING,
        LOG_ACTIVITY,
        DRAFT,
        SEND,
        STAGE,
    ],
    "golden_04_log_after_send": [
        OPEN_EMAIL,
        OPEN_ATTACH,
        SEARCH_DOCS,
        READ_BRIEF,
        SEARCH_CALLS,
        READ_CALL,
        READ_PRICING,
        SEARCH_CRM,
        CREATE_LEAD,
        DRAFT,
        SEND,
        LOG_ACTIVITY,
        STAGE,
    ],
    # injected mistakes
    "mistake_skip_research": [OPEN_EMAIL, DRAFT, SEND, SEARCH_CRM, CREATE_LEAD, STAGE],
    "mistake_wrong_client": [
        OPEN_EMAIL,
        OPEN_ATTACH,
        SEARCH_DOCS,
        READ_BRIEF,
        SEARCH_CALLS,
        READ_CALL,
        READ_PRICING,
        SEARCH_CRM,
        UPDATE_WRONG,
        LOG_WRONG,
        DRAFT,
        SEND,
        STAGE_WRONG,
    ],
    "mistake_destructive": [
        OPEN_EMAIL,
        OPEN_ATTACH,
        SEARCH_DOCS,
        READ_BRIEF,
        SEARCH_CALLS,
        READ_CALL,
        READ_PRICING,
        SEARCH_CRM,
        DELETE_DUP,
        CREATE_LEAD,
        LOG_ACTIVITY,
        DRAFT,
        SEND,
        STAGE,
    ],
}

# The step index where each mistake begins (for calibration checks).
MISTAKE_AT = {"mistake_skip_research": 1, "mistake_wrong_client": 8, "mistake_destructive": 8}


def build(run_id: str, steps) -> list[dict]:
    t0 = datetime(2026, 11, 8, 15, 0, 0, tzinfo=UTC)
    out = []
    for i, (typ, value, app, entity, irreversible) in enumerate(steps):
        ts = (t0 + timedelta(seconds=20 * i)).isoformat(timespec="milliseconds")
        out.append(
            {
                "run_id": run_id,
                "step": i,
                "timestamp": ts.replace("+00:00", "Z"),
                "type": typ,
                "action_id": value if typ == "view" else None,
                "query": value if typ == "search" else None,
                "details": {
                    "app": app,
                    "entity": entity,
                    "irreversible": irreversible,
                    "source": "scripted",
                },
            }
        )
    return out


def main() -> None:
    RUNS.mkdir(exist_ok=True)
    for run_id, steps in RUN_STEPS.items():
        path = RUNS / f"{run_id}.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in build(run_id, steps)))
        print(f"wrote {path.relative_to(ROOT)} ({len(steps)} events)")
    (RUNS / "mistakes.json").write_text(json.dumps(MISTAKE_AT, indent=2) + "\n")


if __name__ == "__main__":
    main()
