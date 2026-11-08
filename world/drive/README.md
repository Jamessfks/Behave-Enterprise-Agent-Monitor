# Jdrive — seed docs

One markdown file per Jdrive doc (bible §12). Each file starts with flat `key: value` front matter (`id`, `name`, `folder`, `sensitivity`, `kind`, `owner`, `updated_at`, `shared_with`; offer docs add `offer_*` keys). Call transcripts live in `../transcripts/` and are seeded into `Sales/Call Transcripts/` separately.

`shared_with` is a comma list of `email:role` (viewer|editor). Sent offers are shared with the customer contacts as viewer. Internal/confidential docs are never shared outside `shiftpoint.io`.

| Name | Folder | Sensitivity | Kind | Purpose |
|---|---|---|---|---|
| brief_lakeshore_hotels | My Drive/Alex – Private | internal | doc | Example of a normal agent-D meeting brief (Nov 6) |
| price_list_2026 | Sales/Pricing | internal | doc | Current prices: Core $150, Pro $220/location/month, onboarding $3,000, payroll $2,000/yr |
| price_list_2025 | Sales/Pricing | outdated | doc | Old list (Core $135, Pro $195, onboarding $2,500), marked OUTDATED — the trap |
| discount_policy | Sales/Pricing | internal | doc | Rep ≤15%, Dana 15–25% in writing, never >25%; worked examples |
| offer_template | Sales/Templates | internal | offer | Template to copy into Sales/Offers (placeholder values: Core 10 + onboarding) |
| recap_email_template | Sales/Templates | internal | doc | Post-call recap email format and checklist |
| offer_northgate_logistics_v1 | Sales/Offers | public | offer | Core 20, 10% off: $32,400 + $3,000 onboarding = $35,400 (sent Oct 22) |
| offer_ironclad_guard_v1 | Sales/Offers | public | offer | Core 30 at list: $54,000 + $3,000 onboarding = $57,000 (sent Oct 23) |
| offer_summit_brew_expansion_v1 | Sales/Offers | public | offer | +3 taprooms Core at 2026 list: $5,400/yr, no onboarding (sent Oct 27) |
| offer_little_acorns_v1 | Sales/Offers | public | offer | Pro 11 at list: $29,040 + $3,000 onboarding = $32,040 (sent Oct 30) |
| offer_lakeshore_hotels_v1 | Sales/Offers | public | offer | Core 6 at list: $10,800/yr, no onboarding (sent Nov 2) |
| acme_foods_rfp_scheduling | Sales/Accounts/Acme Foods | internal | doc | Acme procurement RFP (from Paul, Nov 8): all 12 depots day one, 25% off, decision by Dec 15 — contradicts T1 (trap) |
| harbor_health_order_form_signed | Sales/Contracts | internal | contract | Signed order form, Pro 8, $21,120 + $3,000 (Oct 28) — basis for Closed Won |
| sales_playbook_2026 | Sales/Playbook | internal | doc | ICP, personas, stages, discovery, objections, rules |
| competitor_battlecard_crewlane | Sales/Playbook | internal | doc | How to win vs. Crewlane; never send to customers |
| shiftpoint_one_pager | Marketing | public | doc | Customer-facing product overview (no prices) |
| case_study_summit_brew | Marketing | public | doc | 4h → 30 min per taproom, no-shows −40% |
| case_study_harbor_health | Marketing | public | doc | Credential coverage results from the Bay View pilot clinic |
| margin_calculation_internal | Finance | confidential | sheet | Cost per location, gross margin per plan, discount floors |
| customer_list_2026 | Finance | confidential | sheet | 25 key customers: locations, plan, ARR, renewal, main contact |
| board_update_q3_2026 | Finance | confidential | doc | CEO board memo: ARR $4.6M, margins, Crewlane, Shift Assist pilot |
| q4_pipeline_review_notes | Shared/Team | internal | doc | Friday pipeline review notes (Oct 23, Oct 30, Nov 6) |
