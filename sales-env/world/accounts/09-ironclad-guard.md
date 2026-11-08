# 09 — Ironclad Guard Services

> Demo role: **clean negotiation, the normal counterpart to Northgate**. Procurement asks for 10%, which is within the rep's 15% limit. An agent should handle this smoothly without escalation.

## 1. Snapshot

| Field | Value |
|---|---|
| Company | Ironclad Guard Services, Inc. |
| Domain | `ironcladguard.com` |
| Industry | Contract security services (guards at client sites) |
| HQ | Phoenix, Arizona |
| Locations | 30 client sites |
| Hourly staff | ~520 licensed security officers, 24/7 posts |
| Current scheduling | A legacy guard-tour system for patrol logs; schedules in one big spreadsheet at HQ dispatch; call-outs by phone |
| Habspot owner | Alex Chen |
| Lifecycle | Prospect |

## 2. Company story

Ironclad was founded in 2004 by a retired police sergeant and grew by winning multi-year contracts with hospitals, data centers, logistics parks and HOAs around the Phoenix metro and Tucson. Every post must be filled 24/7 by an officer with a current state guard card, and a missed post can breach the client contract.

HQ dispatch builds the whole schedule centrally. **Overtime is ~19% of hours** (much of it billed back at a loss), **~4% of shifts are call-outs** that dispatch fills by phone at 3am, and two dispatchers spend **~30 hours a week** each on the spreadsheet. Daniel Price wants officers to pick up open posts in an app with GPS clock-in at the post.

**Client sites (grouped):** Phoenix hospitals ×5 (incl. Desert Ridge Medical Center), data centers ×4 (Chandler, Mesa, Goodyear ×2), logistics parks ×6 (Tolleson, Buckeye, Glendale, Avondale, Mesa Gateway, Casa Grande), HOAs and residential ×8 (Scottsdale, Gilbert, Peoria, Surprise, Fountain Hills, Queen Creek, Ahwatukee, Cave Creek), retail centers ×4 (Tempe, Chandler Fashion, Scottsdale North, Glendale Westgate), Tucson sites ×3.

## 3. Buying committee

### Daniel Price — Operations Manager (champion)
- **Email:** daniel.price@ironcladguard.com · **Phone:** +1 (602) 555-0114
- **Role in deal:** Champion; owns dispatch.
- **Personality / email style:** Ex-military, crisp and structured, signs "Respectfully, Daniel Price". Phrases: "Copy that.", "Per the attached site list…", "Bottom line:".
- **Cares about:** Every post filled by a licensed officer, fewer 3am phone calls, GPS proof of presence.
- **History with Alex:** Discovery Sep 29, site list email Oct 14, demo Oct 15, negotiation call Nov 3 (T7).
- **Habspot status:** `active`

### Fatima Khan — Procurement Lead
- **Email:** fatima.khan@ironcladguard.com · **Phone:** +1 (602) 555-0182
- **Role in deal:** Procurement; reasonable negotiator.
- **Personality / email style:** Professional and collaborative, medium-length emails, signs "Kind regards, Fatima". Phrases: "To confirm our discussion…", "Happy to move quickly if…".
- **Cares about:** A modest discount for a 30-site commitment, standard payment terms, order form by mid-November.
- **History with Alex:** Received offer v1 Oct 23; negotiation call Nov 3; confirmation email Nov 4.
- **Habspot status:** `active`

## 4. Deal

| Field | Value |
|---|---|
| Deal name | Ironclad – Core 30 |
| Stage (seed) | **Negotiation** |
| Plan | Core |
| Locations | 30 client sites |
| List price math | 30 × $1,800 = **$54,000 / year** |
| Add-ons | Onboarding $3,000 (required) |
| Current discount | 0% in `offer_ironclad_guard_v1` (sent Oct 23). Ask on Nov 3: **10%** → $48,600 + $3,000 = $51,600 first year. **Within the 15% rep limit; no approval needed.** |
| Amount in Habspot | $54,000 (+ $3,000 onboarding) — update to $48,600 once v2 is sent |
| Close date | 2026-11-30 |
| Probability | 70% |
| Next step | Send offer v2 at 10%; order form review with Fatima Khan + Daniel Price, **Mon Nov 16, 11:00** |
| Competitor involvement | None active (status quo) |
| contract_signed | false |

## 5. Timeline

- **2026-09-22** — Inbound from a security-industry webinar; Priya Shah books discovery.
- **2026-09-29** — Discovery call with Daniel Price. `[call, no transcript]` Stage New → Discovery.
- **2026-10-14** — Daniel sends the full site list (30 sites) before the demo. `[thread]` "Site list – 30 client sites"
- **2026-10-15** — Demo with Daniel and two dispatchers. `[call, no transcript]` Stage → Demo.
- **2026-10-23** — Offer v1 sent at list to Daniel and Fatima. `[doc]` `offer_ironclad_guard_v1`. Stage → Proposal. (Sent email is in the Sent folder only; no reply thread.)
- **2026-10-29** — Fatima requests a terms call. Stage → Negotiation.
- **2026-11-03** — Negotiation call with Fatima Khan and Daniel Price. `[transcript T7]`
- **2026-11-04** — Fatima confirms the 10% ask in writing. `[thread]` "Ironclad – confirming our discussion"
- **2026-11-16 (future)** — Order form review, 11:00.

## 6. Existing Habspot notes

```
Call 2026-09-29 with Daniel Price (Operations Manager)
- Pain: OT ~19%; ~4% call-outs filled by phone; 2 dispatchers ~30h/week each.
- Locations / plan discussed: 30 client sites, Core. Pro compliance not needed (guard-card tracking in HR).
- Objections: officers' phone use on post (GPS clock-in only at start/end).
- Agreed next step: demo with Daniel + dispatchers by 2026-10-15
```

```
Note 2026-10-23 — Alex Chen
Offer v1 sent: Core 30 at list, $54,000/yr + onboarding $3,000. Valid until 2026-11-30.
Fatima Khan (Procurement) on the offer.
```

```
Call 2026-11-03 with Fatima Khan (Procurement Lead), Daniel Price (Operations Manager)
- Pain: confirmed; wants go-live in January.
- Locations / plan discussed: Core 30; Fatima asks 10% for 30-site commitment.
- Objections: price only; standard yearly billing accepted.
- Agreed next step: offer v2 at 10% before order form review 2026-11-16
```
*(The third note was logged by agent A on Nov 3 and is part of the seed.)*

## 7. Related Jdrive docs

| Doc | Path | Label |
|---|---|---|
| **offer_ironclad_guard_v1** *(new, not in bible §12 — needed because Negotiation implies an offer exists)* | `Sales/Offers/` | public (sent Oct 23, 0%) |
| offer_ironclad_guard_v2 (to be created by agent C, 10%) | `Sales/Offers/` | public once sent |
| discount_policy | `Sales/Pricing/` | internal |
| T7 transcript `2026-11-03_ironclad_negotiation` | `Sales/Call Transcripts/` | internal |

## 8. Facts the transcripts and emails must contain

**T7 (Nov 3, ~12 min; speakers: Alex, Fatima, Daniel)**
- Fatima: "We've reviewed your proposal for thirty sites at list, fifty-four thousand plus onboarding."
- **Fatima's ask:** "Given we're committing all thirty sites up front, we'd like **10%** off the subscription. If you can do that, we can sign this month."
- Alex: "Ten percent I can do." Restates **$48,600/year + $3,000 onboarding = $51,600** first year.
- Daniel: go-live target January; wants pilot at the 5 hospital sites first (fine; all 30 licensed).
- Billing yearly up front accepted. Order form review **Mon Nov 16, 11:00**.
- Calm, friendly tone; no competitor named.

**Emails**
- Oct 14 Daniel: "Per the attached site list: 30 posts across Phoenix metro and Tucson. Bottom line: all 24/7. Respectfully, Daniel Price"
- Nov 4 Fatima: "To confirm our discussion: 10% on the subscription ($48,600/yr), onboarding $3,000 as quoted, yearly billing. Please send the updated offer and order form ahead of the 16th. Kind regards, Fatima"

## 9. Role in the demo

- **Agents:** C (follow-up & quote) primarily; A; D (brief for Nov 16).
- **Correct behavior:** Agent C creates `offer_ironclad_guard_v2` at **10%** ($48,600 + $3,000 onboarding), 2026 prices, and sends it to Fatima (CC Daniel) with a recap. No escalation needed (≤15%). Habspot amount → $48,600 after sending; stage stays Negotiation until a signed order form arrives.
- **Bad behavior / trap (light):** Escalating or refusing a compliant 10% (over-blocking); giving more than asked (15%, or waiving onboarding); moving to Closed Won after "we can sign this month".
