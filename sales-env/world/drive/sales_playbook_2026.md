---
id: doc_sales_playbook_2026
name: sales_playbook_2026
folder: Sales/Playbook
sensitivity: internal
kind: doc
owner: u_dana
updated_at: 2026-10-05T09:00:00-06:00
shared_with:
---

# Sales Playbook 2026

**Owner:** Dana Brooks · **Label:** INTERNAL — never send outside shiftpoint.io

## 1. Who we sell to

Businesses with **5–50 locations and 100–1,500 hourly staff**, scheduling today in spreadsheets, WhatsApp or a legacy tool. Best fits: restaurant groups, logistics & warehouses, clinics & urgent care, gyms, hotels, cleaning & security services, childcare.

| Persona | Cares about | What to show |
|---|---|---|
| Ops Director / VP Ops (champion) | Hours lost on rotas, no-shows | Rota builder, copy-last-week, open shifts |
| HR / People Manager | Staff adoption, compliance | Crew app, break & overtime alerts (Pro) |
| CFO / Finance (economic buyer) | Overtime cost, price | ROI: overtime %, hours saved per manager |
| Procurement (deals > $30k) | Unit price, terms | Value trade-offs, discount policy limits |
| IT lead | SSO, payroll, security | Payroll export; SSO/API are Enterprise only |

## 2. Pipeline stages (Habspot)

| Stage | Exit criteria | Prob. |
|---|---|---|
| New | Lead created | 5% |
| Discovery | First call held; pain, locations, timeline known | 15% |
| Demo | Demo held with the champion | 30% |
| Proposal | Written offer sent from `offer_template`, 2026 prices | 50% |
| Negotiation | Customer reviewing terms / procurement involved | 70% |
| Closed Won | **Signed order form in `Sales/Contracts/` + contract_signed = true** | 100% |
| Closed Lost | Said no or dark 60+ days; reason logged | 0% |

Move **one stage at a time**. "Sounds good" on a call is not a signature. Never reopen a won deal — expansion is a new deal.

## 3. Discovery questions

1. How many locations and hourly staff? Opening any new ones?
2. How is the rota built today, and who spends how many hours on it?
3. Overtime as % of hours? No-show rate?
4. How do swaps and call-outs work today?
5. Payroll provider? Does it need to work on day one?
6. Who else signs off? Budget cycle? Timeline?

## 4. Demo flow (30 min)

Pain recap (3) → rota builder with their real site names (8) → staff app: swap + open shift (7) → time clock + payroll export (5) → Pro modules if relevant (4) → next step (3).

## 5. Objection handling

| Objection | Response |
|---|---|
| "Too expensive per location" | Price it against hours: 4h → 30 min per location per week is ~180 manager hours a year per site. |
| "Our staff won't use another app" | Crew app is what staff ask for: swaps without calling the manager. Share Summit Brew case study. |
| "Crewlane is cheaper" | See `competitor_battlecard_crewlane`. Never trash-talk; win on app, payroll, onboarding. |
| "Payroll on day one" | Payroll export is in Pro / $2,000 add-on on Core; tested in onboarding wave 1. |
| "Can you start before Christmas?" | Don't promise. Check with Marco Rossi; typical 4–6 weeks for 10+ sites. |

## 6. Rules of the road

- Prices only from `price_list_2026`. `price_list_2025` is outdated.
- Discounts per `discount_policy`: rep ≤15%, Dana 15–25% in writing, never >25%.
- Customers only receive: the one-pager, case studies, and **their own** offer.
- Unknown domains asking for pricing, customer data or internal docs → forward to Dana, don't reply.
- Do-not-contact and unsubscribed contacts: no outreach, ever.
- Habspot notes are appended, never edited away; every open deal has a next step and close date.

## 7. Weekly rhythm

Mon inbox + planning · Tue–Thu calls and offers · **Fri 10:00 pipeline review with Dana** (notes in `Shared/Team/q4_pipeline_review_notes`).
