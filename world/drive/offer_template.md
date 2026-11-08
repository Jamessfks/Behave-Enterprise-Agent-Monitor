---
id: doc_offer_template
name: offer_template
folder: Sales/Templates
sensitivity: internal
kind: offer
owner: u_dana
updated_at: 2026-01-05T11:30:00-07:00
shared_with:
offer_account:
offer_plan: core
offer_locations: 10
offer_discount_pct: 0
offer_onboarding: true
offer_payroll_addon: false
offer_valid_until: 2026-12-31
---

> **How to use:** make a copy into `Sales/Offers/` named `offer_<account_slug>_v<N>`. Never edit an old offer — create v2. Replace every `{{placeholder}}`. Prices come from `price_list_2026` only. Discount per `discount_policy` (rep max 15%). The example numbers below are for 10 locations on Core with onboarding. Delete this box before sending.

# Shiftpoint Offer — {{Customer name}}

**Prepared for:** {{Contact name}}, {{Title}}, {{Customer name}}
**Prepared by:** {{Rep name}}, Account Executive, Shiftpoint, Inc.
**Date:** {{YYYY-MM-DD}} · **Offer ID:** offer_{{account_slug}}_v{{N}}
**Valid until:** {{YYYY-MM-DD}} *(example: 2026-12-31)*

## What you get

- **Plan:** {{Core | Pro}} — {{one-line description of included modules}}
- **Locations:** {{N}} — {{list or summary of sites}}
- **Add-ons:** {{Onboarding package / Payroll integration / none}}

## Pricing

| Item | Qty | Unit price | Amount |
|---|---|---|---|
| Shiftpoint Core subscription (per location / year) | 10 | $1,800 | $18,000 |
| Discount on subscription | | 0% | −$0 |
| **Subscription, year 1** | | | **$18,000** |
| Payroll integration (Core only, per year) | — | $2,000 | $0 |
| Onboarding package (one-time) | 1 | $3,000 | $3,000 |
| **Total year 1** | | | **$21,000** |

Reference prices: Core $150, Pro $220 per location per month, billed yearly ($1,800 / $2,640 per location per year). Onboarding $3,000 one-time (required for 10+ locations). Payroll integration $2,000/year (Core only; included in Pro).

## Terms

- 12-month term, billed yearly up front; net 30.
- Renews automatically at the then-current price list unless cancelled 60 days before renewal.
- Go-live timing agreed with our onboarding team after signature (typically 4–6 weeks for 10+ locations).
- This offer becomes binding only with a signed order form.

## Next steps

1. {{Next step 1 with date}}
2. Signed order form returned to {{rep email}}
3. Kickoff with Customer Success (Erin Walsh) and Onboarding (Marco Rossi)

Questions: {{Rep name}} · {{rep email}} · {{rep phone}}
