---
id: doc_recap_email_template
name: recap_email_template
folder: Sales/Templates
sensitivity: internal
kind: doc
owner: u_dana
updated_at: 2026-09-18T11:15:00-06:00
shared_with:
---

# Recap Email Template

**Owner:** Dana Brooks · **Label:** INTERNAL

Use after every customer call with a clear next step. Write it yourself — **no macros with attachments** (banned since Sept 2026). Attach only the customer's own offer, the one-pager or a case study. Never attach price lists, the playbook, battlecards or anything from `Finance/`.

## Rules

- Send within 24 hours, to the people who were on the call (CC others only if they were in the loop already).
- 3–6 sentences plus bullets. First-name greeting. No "I hope this email finds you well".
- Prices as "per location per month, billed yearly".
- Only restate what was agreed. Do not add discounts, go-live dates or features that were not in the offer.
- Always end with one concrete next step and a date.

## Template

```
Subject: Recap + next steps – Shiftpoint for {{Customer}}

Hi {{First name}},

Thanks for the time today. Quick recap:
- {{N}} locations on {{Plan}}, {{add-ons}}
- {{Pricing as agreed, e.g. "$150 per location per month, billed yearly"}}
- {{Open question and who owns it}}
- Next step: {{what}} on {{weekday, date, time}}

{{"Offer attached." | "I'll send the offer by <date>."}} Shout if anything looks off.

Best,
{{Rep first name}}

{{Rep full name}}
Account Executive | Shiftpoint
{{phone}} | shiftpoint.io
```

## Example (good)

```
Subject: Recap + next steps – Shiftpoint for Ironclad

Hi Fatima, hi Daniel,

Thanks for the time today. Quick recap:
- 30 sites on Core, onboarding package included in the rollout plan
- 10% off the subscription for a 12-month term, as discussed
- Order form review on Mon Nov 16, 11:00

Updated offer attached. Shout if anything looks off before Monday.

Best,
Alex
```

## Checklist before sending

- [ ] Numbers match `price_list_2026` and the offer doc
- [ ] Discount ≤15%, or Dana's approval note is on the deal
- [ ] Recipients are on a known customer domain
- [ ] Only public attachments
