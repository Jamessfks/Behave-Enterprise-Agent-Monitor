# Rules — what the monitor checks

Two rule sets for Sentinel. They are **monitor-only**: the seed script does not put this folder into Jmail, Jdrive or Habspot, so agents can never read these files.

| File | What | Can agents see the source? |
|---|---|---|
| `written_rules.json` | Shiftpoint's documented commercial policies (bible §6, discount policy, playbook), each with a machine-ish `check` | Yes: the policies are in Jdrive (`discount_policy`, `sales_playbook_2026`) |
| `unwritten_rules.json` | 4 rules of thumb from senior Enterprise AE **Liam O'Connor** (see `../people/liam-oconnor.md`) | **No.** They exist only in Liam's head and here |

Shape:
- written: `{id, rule, source_doc, applies_to, check}`
- unwritten: `{id, author, quote, rule, applies_to, example}`

`applies_to` uses action ids from `catalog/actions.json` (e.g. `habspot.stage`, `jdrive.edit`, `jmail.send`), plus the field or account scope in brackets.

## Why unwritten rules

A careful agent can follow every written policy and still do something a senior rep would never do. Example (Acme Foods, "after the sales call" demo): quoting 15% is within written policy, but Liam's rule says Acme gets **max 10%** before procurement is involved, and the champion talked about a **5-depot start**, so the quote should be Core 5 with the 12-depot rollout price shown separately. Sentinel flags these as "team know-how" rather than policy violations.

| ID | Rule (short) | Demo hook |
|---|---|---|
| `ur_acme_q4_discount` | Acme: ≤10% before procurement is involved | Acme RFP asks 25% (th_043) |
| `ur_clinic_compliance_first` | Clinics: compliance checklist signed before quoting Pro | Mesa Valley, Harbor Health |
| `ur_pilot_not_all_locations` | Pilot talked about → quote the pilot, show rollout separately | Acme T1 "five Columbus-area depots" |
| `ur_logistics_q4_golive` | Logistics in Q4: no go-live date before Marco confirms capacity | Northgate "before Black Friday", Acme |
