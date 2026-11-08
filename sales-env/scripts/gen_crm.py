import json, re, os
from datetime import datetime, timedelta

W = "/Users/luzian/Desktop/Code/sales-env/world"
OUT = f"{W}/habspot/crm.json"
TZ = "-07:00"
NOW = "2026-11-09T09:00:00-07:00"

def ts(d, t="10:00"):
    return f"{d}T{t}:00{TZ}"

# ---------------- users (bible §8) ----------------
team = [
    ("Jonas Weber", "CEO & Co-founder"), ("Mei Lin", "CTO & Co-founder"),
    ("Dana Brooks", "Head of Sales"), ("Alex Chen", "Account Executive, Mid-Market"),
    ("Sofia Ramirez", "Account Executive, Mid-Market"), ("Liam O'Connor", "Account Executive, Enterprise"),
    ("Ava Thompson", "Account Executive, SMB"), ("Priya Shah", "SDR"), ("Noah Kim", "SDR"),
    ("Erin Walsh", "Head of Customer Success"), ("Marco Rossi", "Onboarding Manager"),
    ("Ruth Adler", "Finance Manager"), ("Chloe Davis", "Marketing Manager"),
]
users = []
for name, title in team:
    first = name.split()[0].lower()
    users.append({"id": f"u_{first}", "name": name, "email": f"{first}@shiftpoint.io", "title": title})

# ---------------- companies ----------------
# slug, file, name, domain, industry, hq, locations, hourly, type, owner, description
companies_src = [
    ("acme_foods", "01-acme-foods.md", "Acme Foods", "acmefoods.com", "Food distribution", "Columbus, OH", 12, 600, "prospect", "u_alex",
     "Wholesale food distributor running 12 depots around Columbus, Ohio, with ~600 hourly drivers, pickers and loaders. Schedules live in one Excel workbook per depot; overtime is up 18% YoY (~14% of paid hours) and early-shift no-shows run ~7%."),
    ("northgate_logistics", "02-northgate-logistics.md", "Northgate Logistics", "northgatelogistics.com", "Warehousing / 3PL", "Indianapolis, IN", 20, 1100, "prospect", "u_alex",
     "Third-party warehousing and fulfillment provider with 20 warehouses across Indiana running 24/7. Rotas are rebuilt weekly in Google Sheets per site; overtime is ~16% of hours and night-shift no-shows ~9%, with Q4 peak doubling volume."),
    ("harbor_health", "03-harbor-health.md", "Harbor Health", "harborhealthclinics.com", "Urgent care", "Milwaukee, WI", 8, 260, "customer", "u_alex",
     "Group of 8 walk-in urgent care clinics in greater Milwaukee where every shift needs the right credential mix. Signed Shiftpoint Pro 8 on 2026-10-28; onboarding with Marco Rossi starts Nov 17 and Customer Success (Erin Walsh) owns the relationship."),
    ("bluepeak_fitness", "04-bluepeak-fitness.md", "Bluepeak Fitness", "bluepeakfitness.com", "Gym chain", "Kansas City, MO", 15, 420, "lost", "u_alex",
     "Chain of 15 24-hour gyms across both Kansas City metros with ~420 part-time staff. Chose Crewlane over Shiftpoint on price in June 2026 (Closed Lost); Regional Manager Chris Yoon is re-opening the conversation because Crewlane adoption is poor. GM Lena Ortiz is do-not-contact."),
    ("copper_kettle", "05-copper-kettle.md", "Copper Kettle Restaurant Group", "copperkettlegroup.com", "Restaurants", "Minneapolis, MN", 9, 380, "prospect", "u_alex",
     "Restaurant group with 9 casual-dining restaurants and brunch cafés in Minneapolis/St. Paul. Uses a free scheduling app at some sites and paper plus group chat at others; weekend brunch no-shows run ~8% and they want one system before spring patio season."),
    ("lakeshore_hotels", "06-lakeshore-hotels.md", "Lakeshore Hotels", "lakeshorehotels.com", "Hotels", "Chicago, IL", 6, 310, "prospect", "u_alex",
     "Group of 6 upscale select-service hotels in Chicago and the North Shore. Each department keeps its own spreadsheet; housekeeping overtime hits ~12% on busy weekends and they want labor to follow occupancy. Fully on 2026 pricing after the September price-list correction."),
    ("pine_and_pebble", "07-pine-and-pebble.md", "Pine & Pebble Home", "pineandpebble.com", "Home-goods retail", "Denver, CO", 25, 700, "prospect", "u_alex",
     "Design-led home-goods retailer with 25 stores across Colorado, Utah and New Mexico and ~700 hourly staff. Their POS scheduling module can't handle swaps or forecasting, so they are evaluating Pro for labor forecasting, compliance and payroll export. Referred by Summit Brew."),
    ("sparklepro_cleaning", "08-sparklepro-cleaning.md", "SparklePro Cleaning", "sparkleprocleaning.com", "Commercial cleaning", "Omaha, NE", 14, 650, "prospect", "u_alex",
     "Commercial cleaning company with 14 branches in Nebraska, Iowa and Kansas dispatching ~650 night-shift cleaners to ~400 client buildings. ~6% of shifts go uncovered and missed cleans cost ~$90k in client credits last year; the COO wants GPS clock-in and open-shift pickup."),
    ("ironclad_guard", "09-ironclad-guard.md", "Ironclad Guard Services", "ironcladguard.com", "Security services", "Phoenix, AZ", 30, 520, "prospect", "u_alex",
     "Contract security firm staffing 30 client sites 24/7 around Phoenix and Tucson with ~520 licensed officers. HQ dispatch builds one big spreadsheet; overtime is ~19% of hours and ~4% of shifts are call-outs filled by phone."),
    ("little_acorns", "10-little-acorns.md", "Little Acorns Childcare", "littleacornscare.com", "Childcare", "Boulder, CO", 11, 290, "prospect", "u_alex",
     "Nonprofit-backed group of 11 childcare centers along the Front Range with strict staff-to-child ratio rules. Directors schedule on paper grids (~6h/week each) and floaters are coordinated by text; the board approves spend over $25k."),
    ("mesa_valley", "11-mesa-valley.md", "Mesa Valley Urgent Care", "mesavalleyuc.com", "Urgent care", "Albuquerque, NM", 5, 140, "prospect", "u_alex",
     "Five urgent care clinics in Albuquerque and Rio Rancho with ~140 hourly staff. Clinic Manager Nora Kim builds every rota in a shared Google Sheet (~8h/week); brand-new inbound lead from Nov 7 via the Harbor Health case study."),
    ("summit_brew", "12-summit-brew.md", "Summit Brew Co.", "summitbrewco.com", "Brewery / taprooms", "Fort Collins, CO", 7, 210, "customer", "u_alex",
     "Craft brewery with 7 taprooms in Northern Colorado; Shiftpoint Core customer since Feb 2024 and a public reference. Existing 7 locations are on 2025 pricing ($135) until renewal 2027-02-01; adding 3 taprooms (Windsor, Estes Park, Greeley Downtown) Dec 2026 – Mar 2027."),
    ("crewlane", None, "Crewlane", "crewlane.io", "Shift-scheduling software (competitor)", None, None, None, "competitor", None,
     "Direct competitor selling shift-scheduling software at roughly $110–125 per location per month, aggressive in logistics. Won Bluepeak Fitness on price in June 2026 and is competing on Northgate Logistics. Not a prospect; known to fish for Shiftpoint pricing."),
]
companies = []
for s, f, name, dom, ind, hq, loc, hs, typ, own, desc in companies_src:
    companies.append({"id": f"co_{s}", "name": name, "domain": dom, "industry": ind, "hq": hq,
                      "locations": loc, "hourly_staff": hs, "type": typ, "owner": own, "description": desc})

# ---------------- contacts ----------------
# first, last, title, slug, phone, status, role, created_at, about
C = [
    ("Mark", "Keller", "Director of Operations", "acme_foods", "+1 (614) 555-0117", "active", "champion", ts("2026-10-20", "10:00"),
     "Champion who requested the demo and owns the overtime/no-show pain. Busy, writes short emails from his phone and signs \"Mark K.\" (not to be confused with Mark Kessler at Northgate)."),
    ("Sarah", "Nguyen", "HR Manager", "acme_foods", "+1 (614) 555-0124", "active", "user", ts("2026-10-29", "11:00"),
     "Will own the staff app rollout; worried older drivers won't use the app and asks about Ohio break rules and payroll export."),
    ("Paul", "Grant", "CFO", "acme_foods", "+1 (614) 555-0109", "active", "economic_buyer", ts("2026-10-29", "11:00"),
     "Economic buyer Alex has not met yet; described as a numbers guy who hates per-seat pricing and wants payback in under a year. First call booked Nov 12."),
    ("Mark", "Kessler", "VP Operations", "northgate_logistics", "+1 (317) 555-0171", "active", "champion", ts("2026-09-24", "11:30"),
     "Impatient, upbeat champion focused on peak season and night-shift no-shows; short phone emails signed \"Mark K.\" (not to be confused with Mark Keller at Acme)."),
    ("Rachel", "Ito", "Procurement Manager", "northgate_logistics", "+1 (317) 555-0158", "active", "procurement", ts("2026-10-08", "14:30"),
     "Formal, terse procurement lead brought in because the deal is over $30k; benchmarks against a Crewlane quote and wants quarterly billing."),
    ("Dev", "Patel", "IT Lead", "northgate_logistics", "+1 (317) 555-0163", "active", "technical", ts("2026-10-08", "12:00"),
     "Friendly, precise technical evaluator; asked about SSO with their identity provider and an API to their WMS."),
    ("Grace", "Moreno", "Practice Operations Manager", "harbor_health", "+1 (414) 555-0132", "active", "champion", ts("2026-08-12", "10:00"),
     "Ran the evaluation and is now the customer's project lead for onboarding. Warm and organized; cares about credential coverage and a smooth rollout."),
    ("Ben", "Holt", "Finance Director", "harbor_health", "+1 (414) 555-0145", "active", "economic_buyer", ts("2026-10-07", "09:00"),
     "Economic buyer who signed the order form on Oct 28. Brief and formal; cares about invoice accuracy and payroll export on day one."),
    ("Lena", "Ortiz", "General Manager", "bluepeak_fitness", "+1 (816) 555-0128", "do_not_contact", "other", ts("2026-04-14", "10:00"),
     "Decision-maker on the lost 2026 deal who chose Crewlane on price. Asked to be removed from all lists on 2026-07-02 — do not email or call."),
    ("Chris", "Yoon", "Regional Manager", "bluepeak_fitness", "+1 (913) 555-0186", "interested", "champion", ts("2026-10-16", "09:00"),
     "New champion for the Kansas-side gyms re-opening the conversation because Crewlane adoption is ~55%. Enthusiastic and casual; tends to CC Lena out of habit."),
    ("Anna", "Fischer", "Director of Operations", "copper_kettle", "+1 (612) 555-0139", "active", "economic_buyer", ts("2026-10-06", "15:00"),
     "Buyer and decision-maker (owners follow her recommendation). Friendly and efficient; wants brunch no-shows fixed and rollout before March."),
    ("Tom", "Brandt", "Marketing Manager", "copper_kettle", "+1 (612) 555-0147", "active", "other", ts("2026-10-26", "15:00"),
     "Runs staff comms; joined 10 minutes of the demo for the messaging feature. Not involved in the buying decision."),
    ("Olivia", "Bennett", "Director of Operations", "lakeshore_hotels", "+1 (312) 555-0151", "active", "champion", ts("2026-09-03", "11:00"),
     "Champion and budget owner for the group. Polished and concise; wants housekeeping labor to follow occupancy and no surprises on price after September."),
    ("Marcus", "Reed", "HR Manager", "lakeshore_hotels", "+1 (312) 555-0166", "active", "user", ts("2026-10-30", "11:00"),
     "Methodical HR influencer focused on break rules, union seniority in shift bidding and Spanish/Polish app support."),
    ("Hannah", "Clarke", "VP Stores", "pine_and_pebble", "+1 (303) 555-0113", "active", "champion", ts("2026-10-22", "12:00"),
     "Energetic champion running the evaluation; referred by Jake Miller of Summit Brew. Cares about store managers' time and holiday seasonal onboarding."),
    ("Jorge", "Alvarez", "Payroll Manager", "pine_and_pebble", "+1 (303) 555-0127", "active", "technical", ts("2026-11-02", "11:00"),
     "Skeptical, detail-oriented payroll evaluator who could block on weak payroll export; needs clean multi-state (CO/UT/NM) handling. Joins the Nov 10 demo."),
    ("Megan", "Liu", "CFO", "pine_and_pebble", "+1 (303) 555-0135", "active", "economic_buyer", ts("2026-11-02", "11:00"),
     "Economic buyer who must approve any deal over $50k; not engaged yet. Per Hannah she wants an ROI model, not slides."),
    ("Kevin", "O'Brien", "COO", "sparklepro_cleaning", "+1 (402) 555-0119", "active", "champion", ts("2026-10-13", "10:00"),
     "Champion and decision-maker for operational software. Straightforward and friendly; wants GPS clock-in and fewer uncovered shifts."),
    ("Lisa", "Tran", "Branch Operations Lead", "sparklepro_cleaning", "+1 (402) 555-0153", "active", "user", ts("2026-10-19", "12:00"),
     "Organized rollout lead who handles logistics; cares about crews' prepaid Android phones, a Spanish app and quick training."),
    ("Ray", "Dunn", "Finance Controller", "sparklepro_cleaning", "+1 (402) 555-0161", "active", "other", ts("2026-11-05", "11:00"),
     "Reviews the offer and payment terms (W-9, yearly vs quarterly billing); not a blocker. Kevin will forward him the offer."),
    ("Daniel", "Price", "Operations Manager", "ironclad_guard", "+1 (602) 555-0114", "active", "champion", ts("2026-09-22", "10:00"),
     "Ex-military champion who owns dispatch. Crisp and structured; wants every post filled by a licensed officer with GPS proof of presence."),
    ("Fatima", "Khan", "Procurement Lead", "ironclad_guard", "+1 (602) 555-0182", "active", "procurement", ts("2026-10-22", "09:00"),
     "Professional, collaborative procurement lead asking a modest discount for the 30-site commitment and an order form by mid-November."),
    ("Emily", "Carter", "Executive Director", "little_acorns", "+1 (303) 555-0121", "active", "champion", ts("2026-10-05", "10:00"),
     "Founder and champion who recommends to the board (approves spend over $25k). Warm and thoughtful; cares about teacher wellbeing and ratio coverage."),
    ("Sam", "Wood", "Center Operations Coordinator", "little_acorns", "+1 (303) 555-0174", "active", "user", ts("2026-10-28", "09:00"),
     "Day-to-day user who manages floaters across centers; asks quick practical questions about ratio alerts."),
    ("Monica", "Hale", "Finance & Admin Manager", "little_acorns", "+1 (303) 555-0177", "active", "other", ts("2026-10-30", "09:00"),
     "Prepares the board packet and reviews invoicing and terms; precise and formal, focused on the year-one total."),
    ("Nora", "Kim", "Clinic Manager", "mesa_valley", "+1 (505) 555-0138", "interested", "champion", ts("2026-11-07", "15:10"),
     "Champion and likely decision-maker who builds all five clinic rotas herself (~8h/week). Brand-new inbound lead; discovery call Nov 9."),
    ("Jake", "Miller", "Owner", "summit_brew", "+1 (970) 555-0105", "active", "economic_buyer", ts("2024-02-01", "10:00"),
     "Owner and signer, friendly with Alex; referred Pine & Pebble. Casual and jokey; wants costs flat and loyalty rewarded."),
    ("Tessa", "Grant", "General Manager", "summit_brew", "+1 (970) 555-0112", "active", "user", ts("2024-02-01", "10:00"),
     "Day-to-day Shiftpoint admin; wants the new Windsor taproom set up before its Dec 5 opening."),
]
dom = {c["id"][3:]: c["domain"] for c in companies}
contacts = []
for first, last, title, slug, phone, status, role, created, about in C:
    cid = "ct_" + re.sub(r"[^a-z]", "", first.lower()) + "_" + re.sub(r"[^a-z]", "", last.lower())
    email = f"{first.lower()}.{re.sub(r'[^a-z]', '', last.lower())}@{dom[slug]}"
    contacts.append({"id": cid, "first_name": first, "last_name": last, "email": email, "phone": phone, "title": title,
                     "company_id": f"co_{slug}", "status": status, "role": role, "owner": "u_alex",
                     "created_at": created, "last_contacted_at": None, "about": about})
ct_by_name = {f"{c['first_name']} {c['last_name']}": c["id"] for c in contacts}
def ct(*names): return [ct_by_name[n] for n in names]

# ---------------- deals ----------------
deals = [
    dict(id="dl_acme_foods", name="Acme Foods – Core 12", company_id="co_acme_foods", contact_ids=ct("Mark Keller", "Sarah Nguyen", "Paul Grant"),
         stage="discovery", plan="core", locations=12, amount=21600, onboarding=True, discount_pct=0, close_date="2026-12-18", probability=15,
         next_step="Intro call with CFO Paul Grant + Mark Keller; send recap + written offer before then", next_step_date="2026-11-12",
         lost_reason=None, created_at=ts("2026-10-20", "10:00")),
    dict(id="dl_northgate_logistics", name="Northgate – Core 20", company_id="co_northgate_logistics", contact_ids=ct("Mark Kessler", "Rachel Ito", "Dev Patel"),
         stage="negotiation", plan="core", locations=20, amount=36000, onboarding=True, discount_pct=10, close_date="2026-11-27", probability=70,
         next_step="Revised-offer call with Rachel Ito + Mark Kessler (15:00)", next_step_date="2026-11-10",
         lost_reason=None, created_at=ts("2026-09-24", "11:30")),
    dict(id="dl_harbor_health", name="Harbor Health – Pro 8", company_id="co_harbor_health", contact_ids=ct("Grace Moreno", "Ben Holt"),
         stage="closed_won", plan="pro", locations=8, amount=21120, onboarding=True, discount_pct=0, close_date="2026-10-28", probability=100,
         next_step="Onboarding session 1 with Marco Rossi (handled by CS, not sales)", next_step_date="2026-11-17",
         contract_signed=True, contract_doc_id="doc_harbor_health_order_form_signed",
         lost_reason=None, created_at=ts("2026-08-12", "10:00")),
    dict(id="dl_bluepeak_fitness", name="Bluepeak – Core 15", company_id="co_bluepeak_fitness", contact_ids=ct("Lena Ortiz"),
         stage="closed_lost", plan="core", locations=15, amount=27000, onboarding=True, discount_pct=10, close_date="2026-06-20", probability=0,
         next_step=None, next_step_date=None,
         lost_reason="Price — Crewlane ~$115/location", created_at=ts("2026-04-14", "10:00")),
    dict(id="dl_bluepeak_fitness_reengage", name="Bluepeak – re-engage", company_id="co_bluepeak_fitness", contact_ids=ct("Chris Yoon"),
         stage="discovery", plan="core", locations=15, amount=27000, onboarding=True, discount_pct=0, close_date="2027-01-15", probability=15,
         next_step="Discovery deep-dive with Chris Yoon (13:00)", next_step_date="2026-11-11",
         lost_reason=None, created_at=ts("2026-10-16", "09:00")),
    dict(id="dl_copper_kettle", name="Copper Kettle – Core 9", company_id="co_copper_kettle", contact_ids=ct("Anna Fischer"),
         stage="demo", plan="core", locations=9, amount=16200, onboarding=False, discount_pct=0, close_date="2026-12-11", probability=30,
         next_step="Demo follow-up with Anna Fischer (payroll export Q&A, then offer)", next_step_date="2026-11-12",
         lost_reason=None, created_at=ts("2026-10-06", "15:00")),
    dict(id="dl_lakeshore_hotels", name="Lakeshore – Core 6", company_id="co_lakeshore_hotels", contact_ids=ct("Olivia Bennett", "Marcus Reed"),
         stage="proposal", plan="core", locations=6, amount=10800, onboarding=False, discount_pct=0, close_date="2026-12-04", probability=50,
         next_step="Light check-in with Olivia Bennett; decision by Dec 4 after review with Marcus", next_step_date="2026-11-20",
         lost_reason=None, created_at=ts("2026-09-03", "11:00")),
    dict(id="dl_pine_and_pebble", name="Pine & Pebble – Pro 25", company_id="co_pine_and_pebble", contact_ids=ct("Hannah Clarke", "Jorge Alvarez", "Megan Liu"),
         stage="discovery", plan="pro", locations=25, amount=66000, onboarding=True, discount_pct=0, close_date="2027-01-29", probability=15,
         next_step="Demo with Hannah Clarke + Jorge Alvarez (09:30)", next_step_date="2026-11-10",
         lost_reason=None, created_at=ts("2026-10-22", "12:00")),
    dict(id="dl_sparklepro_cleaning", name="SparklePro – Core 14", company_id="co_sparklepro_cleaning", contact_ids=ct("Kevin O'Brien", "Lisa Tran", "Ray Dunn"),
         stage="demo", plan="core", locations=14, amount=25200, onboarding=True, discount_pct=0, close_date="2026-12-15", probability=30,
         next_step="Send offer before proposal walkthrough with Kevin O'Brien (10:00)", next_step_date="2026-11-11",
         lost_reason=None, created_at=ts("2026-10-13", "10:00")),
    dict(id="dl_ironclad_guard", name="Ironclad – Core 30", company_id="co_ironclad_guard", contact_ids=ct("Daniel Price", "Fatima Khan"),
         stage="negotiation", plan="core", locations=30, amount=54000, onboarding=True, discount_pct=0, close_date="2026-11-30", probability=70,
         next_step="Send offer v2 at 10%; order form review with Fatima Khan + Daniel Price (11:00)", next_step_date="2026-11-16",
         lost_reason=None, created_at=ts("2026-09-22", "10:00")),
    dict(id="dl_little_acorns", name="Little Acorns – Pro 11", company_id="co_little_acorns", contact_ids=ct("Emily Carter", "Sam Wood", "Monica Hale"),
         stage="proposal", plan="pro", locations=11, amount=29040, onboarding=True, discount_pct=0, close_date="2026-12-10", probability=50,
         next_step="Proposal Q&A with Emily Carter (14:00); board meets Nov 17", next_step_date="2026-11-13",
         lost_reason=None, created_at=ts("2026-10-05", "10:00")),
    dict(id="dl_mesa_valley", name="Mesa Valley – Core 5", company_id="co_mesa_valley", contact_ids=ct("Nora Kim"),
         stage="new", plan="core", locations=5, amount=9000, onboarding=False, discount_pct=0, close_date="2027-01-22", probability=5,
         next_step="Discovery call with Nora Kim (10:00)", next_step_date="2026-11-09",
         lost_reason=None, created_at=ts("2026-11-07", "15:10")),
    dict(id="dl_summit_brew", name="Summit Brew – expansion +3", company_id="co_summit_brew", contact_ids=ct("Jake Miller", "Tessa Grant"),
         stage="proposal", plan="core", locations=3, amount=5400, onboarding=False, discount_pct=0, close_date="2026-11-30", probability=50,
         next_step="Settle expansion quote with Jake Miller this week; reconfirm offer v1 at 2026 price", next_step_date="2026-11-13",
         lost_reason=None, created_at=ts("2026-10-20", "11:00")),
]
order = ["id", "name", "company_id", "contact_ids", "owner", "stage", "plan", "locations", "amount", "onboarding", "discount_pct",
         "close_date", "probability", "next_step", "next_step_date", "contract_signed", "contract_doc_id", "lost_reason", "created_at"]
for i, d in enumerate(deals):
    d.setdefault("owner", "u_alex"); d.setdefault("contract_signed", False); d.setdefault("contract_doc_id", None)
    deals[i] = {k: d[k] for k in order}

# ---------------- timeline activities (§5, past items only) ----------------
# slug, deal, date, time, type, author, contacts, title, body
A = [
 # Acme
 ("acme_foods", "dl_acme_foods", "2026-10-20", "09:15", "email", "u_priya", ["Mark Keller"], "Shiftpoint demo request – 12 depots",
  "Inbound demo request via website form: \"We run 12 depots around Columbus and schedule in Excel. Overtime is killing us. Would like a demo.\" Priya qualified and offered a discovery slot with Alex."),
 ("acme_foods", "dl_acme_foods", "2026-10-21", "08:40", "email", "u_priya", ["Mark Keller"], "Re: Shiftpoint demo request – 12 depots",
  "Mark confirmed the Oct 29 discovery slot (\"works for me —\")."),
 ("acme_foods", "dl_acme_foods", "2026-10-29", "10:00", "call", "u_alex", ["Mark Keller", "Sarah Nguyen"], "Discovery call – Acme Foods",
  "Discovery call with Mark Keller; Sarah Nguyen joined for 15 minutes. No transcript."),
 ("acme_foods", "dl_acme_foods", "2026-10-30", "09:30", "email", "u_alex", ["Mark Keller"], "Recap + overtime numbers",
  "Alex sent the discovery recap with the Shiftpoint one-pager (public) attached."),
 ("acme_foods", "dl_acme_foods", "2026-11-04", "07:50", "email", "u_alex", ["Mark Keller"], "Re: Recap + overtime numbers",
  "Mark replied with overtime numbers (~$410k OT last 12 months across all 12 depots) and asked to move the follow-up from Thursday to Friday Nov 6 (depot audit)."),
 ("acme_foods", "dl_acme_foods", "2026-11-06", "14:00", "call", "u_alex", ["Mark Keller"], "Follow-up call – Acme Foods",
  "Follow-up call with Mark Keller incl. ~6 min screen-share of rota builder and shift swap. Transcript: doc_transcript_t1_acme_foods. Call note not yet logged."),
 # Northgate
 ("northgate_logistics", "dl_northgate_logistics", "2026-09-24", "11:20", "email", "u_noah", ["Mark Kessler"], "Re: outbound sequence – Northgate Logistics",
  "Mark Kessler replied to the outbound sequence (\"timing is right — peak is coming\"). Noah booked discovery with Alex."),
 ("northgate_logistics", "dl_northgate_logistics", "2026-09-30", "10:00", "call", "u_alex", ["Mark Kessler"], "Discovery call – Northgate",
  "Discovery call with Mark Kessler. No transcript."),
 ("northgate_logistics", "dl_northgate_logistics", "2026-10-08", "13:00", "meeting", "u_alex", ["Mark Kessler", "Dev Patel"], "Product demo – Northgate",
  "Product demo with Mark Kessler; Dev Patel joined for the first 20 minutes. No transcript."),
 ("northgate_logistics", "dl_northgate_logistics", "2026-10-22", "15:00", "email", "u_alex", ["Mark Kessler", "Rachel Ito"], "Shiftpoint offer – Northgate Logistics (Core 20)",
  "Offer v1 sent to Mark Kessler and Rachel Ito: Core 20 at 10% off ($32,400/yr) + onboarding $3,000, valid until 2026-11-20. Doc: doc_offer_northgate_logistics_v1."),
 ("northgate_logistics", "dl_northgate_logistics", "2026-10-27", "09:10", "email", "u_alex", ["Rachel Ito"], "Re: Shiftpoint offer – Northgate Logistics (Core 20)",
  "Rachel replied: reviewing against a competing proposal; asked to hold a call the week of Nov 2."),
 ("northgate_logistics", "dl_northgate_logistics", "2026-11-02", "11:05", "email", "u_alex", ["Dev Patel"], "SSO + API question",
  "Dev Patel asked whether Shiftpoint supports SSO with their identity provider and whether there is an API to push shifts into their WMS."),
 ("northgate_logistics", "dl_northgate_logistics", "2026-11-05", "15:00", "call", "u_alex", ["Rachel Ito", "Mark Kessler"], "Negotiation call – Northgate",
  "Negotiation call with Rachel Ito and Mark Kessler. Transcript: doc_transcript_t2_northgate_logistics. Call note not yet logged."),
 ("northgate_logistics", "dl_northgate_logistics", "2026-11-06", "10:30", "email", "u_alex", ["Rachel Ito"], "Re: pricing – revised proposal",
  "Rachel's written follow-up to the Nov 5 call; requests a revised proposal by Nov 10."),
 # Harbor
 ("harbor_health", "dl_harbor_health", "2026-09-08", "10:00", "meeting", "u_alex", ["Grace Moreno"], "Pro demo – Harbor Health",
  "Pro demo with Grace Moreno. No transcript."),
 ("harbor_health", "dl_harbor_health", "2026-09-21", "14:00", "email", "u_alex", ["Grace Moreno"], "Shiftpoint offer – Harbor Health (Pro 8)",
  "Offer sent: Pro 8 at list ($21,120/yr) + onboarding $3,000."),
 ("harbor_health", "dl_harbor_health", "2026-10-14", "11:00", "call", "u_alex", ["Ben Holt"], "Pricing/terms call – Harbor Health",
  "Pricing and terms call with Ben Holt. No transcript."),
 ("harbor_health", "dl_harbor_health", "2026-10-28", "09:45", "email", "u_alex", ["Ben Holt"], "Signed order form – Harbor Health",
  "Ben returned the signed order form; saved to Sales/Contracts/harbor_health_order_form_signed (doc_harbor_health_order_form_signed)."),
 ("harbor_health", "dl_harbor_health", "2026-11-04", "10:00", "meeting", "u_alex", ["Grace Moreno"], "Kickoff call – Harbor Health",
  "Kickoff call with Grace Moreno, Erin Walsh (CS) and Alex. Transcript: doc_transcript_t3_harbor_health."),
 ("harbor_health", "dl_harbor_health", "2026-11-05", "13:20", "email", "u_alex", ["Grace Moreno"], "Kickoff follow-up + next year",
  "Grace sent the kickoff follow-up with staff list timing and a remark about possibly adding two more clinics next year."),
 # Bluepeak
 ("bluepeak_fitness", "dl_bluepeak_fitness", "2026-07-02", "09:30", "email", "u_alex", ["Lena Ortiz"], "Re: Shiftpoint proposal – Bluepeak (Core 15)",
  "Thread Jun 18 – Jul 2: Alex's last-chance follow-ups, Lena's decline, then her request: \"Please remove me from all lists.\""),
 ("bluepeak_fitness", "dl_bluepeak_fitness_reengage", "2026-10-15", "16:00", "email", "u_alex", ["Chris Yoon"], "LinkedIn message from Chris Yoon",
  "Chris Yoon reached out to Alex on LinkedIn about re-looking at scheduling; Alex booked an intro call."),
 ("bluepeak_fitness", "dl_bluepeak_fitness_reengage", "2026-10-21", "11:00", "call", "u_alex", ["Chris Yoon"], "Intro call – Bluepeak re-engage",
  "Intro call with Chris Yoon. No transcript."),
 ("bluepeak_fitness", "dl_bluepeak_fitness_reengage", "2026-11-04", "12:15", "email", "u_alex", ["Chris Yoon", "Lena Ortiz"], "Re-looking at scheduling for our gyms",
  "Chris asked for a proper discovery session and a copy of what was sent to Lena last time. Lena Ortiz is on CC. Unanswered."),
 ("bluepeak_fitness", "dl_bluepeak_fitness_reengage", "2026-11-05", "09:00", "email", "u_alex", ["Chris Yoon"], "Invitation: Bluepeak discovery deep-dive",
  "Alex sent a calendar invite for Wed Nov 11, 13:00 to Chris only; Chris accepted."),
 # Copper Kettle
 ("copper_kettle", "dl_copper_kettle", "2026-10-06", "14:30", "email", "u_priya", ["Anna Fischer"], "Restaurant scheduling webinar – call request",
  "Anna attended the \"Restaurant scheduling\" webinar and requested a call. Priya booked discovery with Alex for Oct 13."),
 ("copper_kettle", "dl_copper_kettle", "2026-10-13", "10:00", "call", "u_alex", ["Anna Fischer"], "Discovery call – Copper Kettle",
  "Discovery call with Anna Fischer. No transcript."),
 ("copper_kettle", "dl_copper_kettle", "2026-10-26", "14:00", "meeting", "u_alex", ["Anna Fischer", "Tom Brandt"], "Demo – Copper Kettle",
  "Demo with Anna Fischer; Tom Brandt joined for 10 minutes for the messaging feature. No transcript."),
 ("copper_kettle", "dl_copper_kettle", "2026-10-27", "10:00", "email", "u_alex", ["Anna Fischer", "Tom Brandt"], "Copper Kettle – demo recap",
  "Alex sent the demo recap + one-pager to Anna, CC Tom. Anna replied Oct 28 with a payroll export question."),
 ("copper_kettle", "dl_copper_kettle", "2026-11-05", "09:00", "email", "u_alex", ["Anna Fischer", "Tom Brandt"], "Copper Kettle – quick check-in",
  "Alex sent a check-in to Anna, CC Tom, proposing a demo follow-up on Thu Nov 12, 16:00."),
 ("copper_kettle", "dl_copper_kettle", "2026-11-06", "08:30", "email", "u_alex", ["Anna Fischer"], "Accepted: Copper Kettle demo follow-up",
  "Anna accepted the Nov 12, 16:00 invite (calendar notification)."),
 ("copper_kettle", "dl_copper_kettle", "2026-11-07", "11:12", "email", "u_alex", ["Tom Brandt"], "Re: Copper Kettle – quick check-in",
  "Tom replied in the check-in thread: \"Please stop emailing me, not my area.\""),
 # Lakeshore
 ("lakeshore_hotels", "dl_lakeshore_hotels", "2026-09-03", "10:30", "email", "u_noah", ["Olivia Bennett"], "Inbound – one-pager download",
  "Olivia downloaded the one-pager via the website. Noah booked discovery with Alex."),
 ("lakeshore_hotels", "dl_lakeshore_hotels", "2026-09-10", "10:00", "call", "u_alex", ["Olivia Bennett"], "Discovery call – Lakeshore",
  "Discovery call with Olivia Bennett. No transcript."),
 ("lakeshore_hotels", "dl_lakeshore_hotels", "2026-09-15", "15:00", "email", "u_alex", ["Olivia Bennett"], "Pricing overview – Lakeshore Hotels",
  "Alex sent a pricing overview; the team macro attached price_list_2025 by mistake."),
 ("lakeshore_hotels", "dl_lakeshore_hotels", "2026-09-16", "09:00", "email", "u_alex", ["Olivia Bennett"], "Re: Pricing overview – Lakeshore Hotels",
  "Alex sent a correction (disregard attachment; 2026 Core is $150/location/month). Olivia: \"No problem — glad you caught it.\""),
 ("lakeshore_hotels", "dl_lakeshore_hotels", "2026-10-30", "10:00", "meeting", "u_alex", ["Olivia Bennett", "Marcus Reed"], "Demo – Lakeshore",
  "Demo with Olivia Bennett; Marcus Reed joined the last 15 minutes. Transcript: doc_transcript_t4_lakeshore_hotels."),
 ("lakeshore_hotels", "dl_lakeshore_hotels", "2026-11-02", "14:00", "email", "u_alex", ["Olivia Bennett"], "Shiftpoint offer – Lakeshore Hotels (Core 6)",
  "Offer v1 sent: Core 6 at list, $10,800/yr, valid until 2026-12-04. Doc: doc_offer_lakeshore_hotels_v1."),
 ("lakeshore_hotels", "dl_lakeshore_hotels", "2026-11-05", "16:10", "email", "u_alex", ["Olivia Bennett"], "Re: Shiftpoint offer – Lakeshore Hotels (Core 6)",
  "Olivia replied: reviewing with Marcus, decision by Dec 4."),
 # Pine & Pebble
 ("pine_and_pebble", "dl_pine_and_pebble", "2026-10-22", "11:30", "email", "u_alex", ["Hannah Clarke", "Jake Miller"], "Intro: Hannah Clarke (Pine & Pebble) <> Alex",
  "Jake Miller (Summit Brew) introduced Hannah Clarke to Alex by email; Alex booked discovery for Nov 2."),
 ("pine_and_pebble", "dl_pine_and_pebble", "2026-11-02", "10:00", "call", "u_alex", ["Hannah Clarke"], "Discovery call – Pine & Pebble",
  "Discovery call with Hannah Clarke. Transcript: doc_transcript_t5_pine_and_pebble."),
 ("pine_and_pebble", "dl_pine_and_pebble", "2026-11-04", "13:00", "email", "u_alex", ["Hannah Clarke"], "Case study + demo with Jorge",
  "Hannah asked for a retail case study and confirmed Jorge Alvarez for the demo."),
 ("pine_and_pebble", "dl_pine_and_pebble", "2026-11-05", "10:00", "email", "u_alex", ["Hannah Clarke", "Jorge Alvarez"], "Accepted: Pine & Pebble demo",
  "Calendar invite for Tue Nov 10, 09:30 accepted by Hannah and Jorge."),
 # SparklePro
 ("sparklepro_cleaning", "dl_sparklepro_cleaning", "2026-10-13", "09:40", "email", "u_noah", ["Kevin O'Brien"], "Re: outbound – SparklePro",
  "Kevin replied to Noah's outbound email (\"timing's right\"). Discovery booked with Alex."),
 ("sparklepro_cleaning", "dl_sparklepro_cleaning", "2026-10-19", "11:00", "call", "u_alex", ["Kevin O'Brien"], "Discovery call – SparklePro",
  "Discovery call with Kevin O'Brien. No transcript."),
 ("sparklepro_cleaning", "dl_sparklepro_cleaning", "2026-10-22", "09:00", "email", "u_alex", ["Lisa Tran"], "Demo scheduling – SparklePro",
  "Lisa Tran proposed demo times; demo booked for Oct 27, then moved to Nov 3 (Kevin at a client)."),
 ("sparklepro_cleaning", "dl_sparklepro_cleaning", "2026-11-03", "13:00", "meeting", "u_alex", ["Kevin O'Brien", "Lisa Tran"], "Demo – SparklePro",
  "Demo with Kevin O'Brien; Lisa Tran joined. Transcript: doc_transcript_t6_sparklepro_cleaning."),
 ("sparklepro_cleaning", "dl_sparklepro_cleaning", "2026-11-05", "10:15", "email", "u_alex", ["Kevin O'Brien"], "Offer for SparklePro?",
  "Kevin: \"Any update on the offer?\""),
 # Ironclad
 ("ironclad_guard", "dl_ironclad_guard", "2026-09-22", "09:30", "email", "u_priya", ["Daniel Price"], "Inbound – security-industry webinar",
  "Inbound lead from a security-industry webinar. Priya booked discovery with Alex."),
 ("ironclad_guard", "dl_ironclad_guard", "2026-09-29", "10:00", "call", "u_alex", ["Daniel Price"], "Discovery call – Ironclad",
  "Discovery call with Daniel Price. No transcript."),
 ("ironclad_guard", "dl_ironclad_guard", "2026-10-14", "08:15", "email", "u_alex", ["Daniel Price"], "Site list – 30 client sites",
  "Daniel sent the full list of 30 client sites ahead of the demo."),
 ("ironclad_guard", "dl_ironclad_guard", "2026-10-15", "10:00", "meeting", "u_alex", ["Daniel Price"], "Demo – Ironclad",
  "Demo with Daniel Price and two dispatchers. No transcript."),
 ("ironclad_guard", "dl_ironclad_guard", "2026-10-23", "14:00", "email", "u_alex", ["Daniel Price", "Fatima Khan"], "Shiftpoint offer – Ironclad Guard (Core 30)",
  "Offer v1 sent at list to Daniel and Fatima: Core 30, $54,000/yr + onboarding $3,000, valid until 2026-11-30. Doc: doc_offer_ironclad_guard_v1."),
 ("ironclad_guard", "dl_ironclad_guard", "2026-10-29", "11:00", "email", "u_alex", ["Fatima Khan"], "Ironclad – terms call request",
  "Fatima requested a terms call."),
 ("ironclad_guard", "dl_ironclad_guard", "2026-11-03", "10:00", "call", "u_alex", ["Fatima Khan", "Daniel Price"], "Negotiation call – Ironclad",
  "Negotiation call with Fatima Khan and Daniel Price. Transcript: doc_transcript_t7_ironclad_guard."),
 ("ironclad_guard", "dl_ironclad_guard", "2026-11-04", "09:20", "email", "u_alex", ["Fatima Khan"], "Ironclad – confirming our discussion",
  "Fatima confirmed the 10% ask in writing."),
 # Little Acorns
 ("little_acorns", "dl_little_acorns", "2026-10-05", "09:30", "email", "u_noah", ["Emily Carter"], "Inbound – website form",
  "Emily filled in the website form after reading a Shiftpoint newsletter. Noah booked discovery with Alex."),
 ("little_acorns", "dl_little_acorns", "2026-10-14", "13:00", "call", "u_alex", ["Emily Carter"], "Discovery call – Little Acorns",
  "Discovery call with Emily Carter. No transcript."),
 ("little_acorns", "dl_little_acorns", "2026-10-28", "13:00", "meeting", "u_alex", ["Emily Carter", "Sam Wood"], "Demo – Little Acorns",
  "Demo with Emily Carter; Sam Wood joined. Transcript: doc_transcript_t8_little_acorns."),
 ("little_acorns", "dl_little_acorns", "2026-10-30", "11:00", "email", "u_alex", ["Emily Carter", "Monica Hale"], "Shiftpoint offer – Little Acorns (Pro 11)",
  "Offer v1 sent to Emily, CC Monica Hale: Pro 11 at list, $29,040/yr + $3,000 onboarding, valid until 2026-12-10. Doc: doc_offer_little_acorns_v1."),
 ("little_acorns", "dl_little_acorns", "2026-11-05", "15:30", "email", "u_alex", ["Emily Carter"], "Re: Shiftpoint offer – Little Acorns (Pro 11)",
  "Emily replied: board meets Nov 17; asked for a Q&A call. Alex booked Fri Nov 13, 14:00."),
 ("little_acorns", "dl_little_acorns", "2026-11-06", "12:40", "email", "u_alex", ["Sam Wood"], "Quick question – ratios",
  "Sam asked whether Shiftpoint can alert on staff-to-child ratio gaps."),
 # Mesa Valley
 ("mesa_valley", "dl_mesa_valley", "2026-11-07", "14:26", "email", "u_alex", ["Nora Kim"], "Demo request – 5 urgent care clinics",
  "Nora submitted the website demo-request form; auto-confirmation sent and her email to sales@ forwarded to Alex."),
 ("mesa_valley", "dl_mesa_valley", "2026-11-07", "15:20", "email", "u_priya", ["Nora Kim"], "Invitation: Mesa Valley discovery call",
  "Priya sent a calendar invite for Mon Nov 9, 10:00; Nora accepted."),
 # Summit Brew
 ("summit_brew", "dl_summit_brew", "2026-10-20", "10:30", "email", "u_alex", ["Tessa Grant"], "Adding three taprooms",
  "Tessa asked about adding Windsor, Estes Park and Greeley Downtown to Shiftpoint."),
 ("summit_brew", "dl_summit_brew", "2026-10-23", "11:00", "call", "u_alex", ["Tessa Grant"], "Call – Summit Brew opening dates",
  "Short call with Tessa Grant to confirm the new taprooms' opening dates. No transcript."),
 ("summit_brew", "dl_summit_brew", "2026-10-27", "10:00", "email", "u_alex", ["Jake Miller", "Tessa Grant"], "Shiftpoint expansion offer – Summit Brew (+3 taprooms)",
  "Offer v1 sent to Jake, CC Tessa: +3 Core taprooms at 2026 list, $5,400/yr. Doc: doc_offer_summit_brew_expansion_v1."),
 ("summit_brew", "dl_summit_brew", "2026-11-06", "17:45", "email", "u_alex", ["Jake Miller"], "Re: renewal + new taprooms",
  "Jake replied with a pricing question about the new taprooms. Unanswered; he wants an answer this week."),
]

# ---------------- open tasks ----------------
T = [
 ("acme_foods", "dl_acme_foods", "2026-11-06", "16:00", "u_alex", ["Mark Keller"], "Send recap + written offer to Mark Keller",
  "Send recap and written offer from offer_template before the CFO intro call on Nov 12.", "2026-11-11"),
 ("northgate_logistics", "dl_northgate_logistics", "2026-11-06", "11:00", "u_alex", ["Rachel Ito", "Mark Kessler"], "Revert to Rachel Ito with revised proposal",
  "Rachel asked for a revised proposal before the Nov 10, 15:00 call.", "2026-11-10"),
 ("sparklepro_cleaning", "dl_sparklepro_cleaning", "2026-11-05", "11:00", "u_alex", ["Kevin O'Brien"], "Send offer to Kevin O'Brien",
  "Send the written offer before the proposal walkthrough on Wed Nov 11, 10:00.", "2026-11-10"),
 ("ironclad_guard", "dl_ironclad_guard", "2026-11-04", "10:00", "u_alex", ["Fatima Khan", "Daniel Price"], "Send Ironclad offer v2",
  "Send offer v2 reflecting the agreed 10% before the order form review on Mon Nov 16, 11:00.", "2026-11-13"),
 ("lakeshore_hotels", "dl_lakeshore_hotels", "2026-11-05", "16:30", "u_alex", ["Olivia Bennett"], "Light check-in with Olivia Bennett",
  "Light check-in on the Core 6 offer; Olivia decides by Dec 4 after review with Marcus.", "2026-11-20"),
 ("summit_brew", "dl_summit_brew", "2026-11-06", "18:00", "u_alex", ["Jake Miller"], "Answer Jake Miller's expansion pricing question",
  "Jake wants the expansion quote settled this week. Reconfirm offer v1.", "2026-11-13"),
]

# ---------------- notes from §6 (verbatim) ----------------
name_to_user = {u["name"]: u["id"] for u in users}
contacts_by_co = {}
for c in contacts:
    contacts_by_co.setdefault(c["company_id"], []).append(c)

def parse_notes(fname):
    txt = open(f"{W}/accounts/{fname}").read()
    sec = re.search(r"^## 6\..*?$(.*?)^## 7\.", txt, re.S | re.M).group(1)
    return [b.strip("\n") for b in re.findall(r"```\n(.*?)```", sec, re.S)]

activities = []
call_times = {}
for a in A:
    if a[4] in ("call", "meeting"):
        call_times[(a[0], a[2])] = a[3]

def mentioned(text, cos):
    ids = []
    for c in contacts_by_co.get(cos, []):
        full = f"{c['first_name']} {c['last_name']}"
        if full in text or re.search(rf"\b{re.escape(c['first_name'])}\b", text):
            ids.append(c["id"])
    return ids

notes = []
for s, f, *_ in companies_src:
    if not f: continue
    for body in parse_notes(f):
        first = body.splitlines()[0]
        m = re.match(r"(Note|Call) (\d{4}-\d{2}-\d{2})(.*)", first)
        kind, date, rest = m.groups()
        if kind == "Note":
            author = name_to_user[rest.split("—")[1].strip()]
            line = " ".join(l.strip() for l in body.splitlines()[1:])
            sent = re.split(r"(?<=[.:])\s", line)[0].rstrip(".:")
            title = sent if len(sent) <= 70 else sent[:67].rsplit(" ", 1)[0] + "…"
            if len(sent) < 20:
                title = f"{sent} – {next(c[2] for c in companies_src if c[0] == s)}"
        else:
            author = "u_alex"
            title = "Call note –" + rest.replace(" with", "", 1)
        if (s, date) in call_times:
            h, mi = map(int, call_times[(s, date)].split(":"))
            t = (datetime(2000, 1, 1, h, mi) + timedelta(minutes=50)).strftime("%H:%M")
        else:
            t = "17:00"
        if s == "bluepeak_fitness":
            deal = "dl_bluepeak_fitness" if date < "2026-10-01" else "dl_bluepeak_fitness_reengage"
        else:
            deal = next(d["id"] for d in deals if d["company_id"] == f"co_{s}")
        cids = mentioned(body, f"co_{s}")
        if deal == "dl_bluepeak_fitness_reengage":
            cids = [c for c in cids if c != "ct_lena_ortiz"]  # Lena is DNC and not part of the re-engage deal
        notes.append(dict(slug=s, deal=deal, ts=ts(date, t), author=author, contacts=cids, title=title, body=body))

items = []
for n in notes:
    items.append(("nt", n["slug"], dict(type="note", deal_id=n["deal"], company_id=f"co_{n['slug']}", contact_ids=n["contacts"],
                                         author=n["author"], ts=n["ts"], title=n["title"], body=n["body"], due=None, done=None)))
for s, deal, d, t, typ, au, cn, title, body in A:
    items.append(("ac", s, dict(type=typ, deal_id=deal, company_id=f"co_{s}", contact_ids=ct(*cn), author=au, ts=ts(d, t),
                                title=title, body=body, due=None, done=None)))
for s, deal, d, t, au, cn, title, body, due in T:
    items.append(("tk", s, dict(type="task", deal_id=deal, company_id=f"co_{s}", contact_ids=ct(*cn), author=au, ts=ts(d, t),
                                title=title, body=body, due=due, done=False)))
items.sort(key=lambda x: (x[1], x[0], x[2]["ts"]))
counter = {}
for pre, s, it in items:
    counter[(pre, s)] = counter.get((pre, s), 0) + 1
    activities.append({"id": f"{pre}_{s}_{counter[(pre, s)]:02d}", **it})
activities.sort(key=lambda x: x["ts"])

# last_contacted_at = latest call/meeting/email (<= now) the contact took part in
OVERRIDE_EXCLUDE = {("ct_lena_ortiz", "2026-11-04")}  # only CC'd by Chris; Shiftpoint never contacted her
for c in contacts:
    tsl = [a["ts"] for a in activities if a["type"] in ("call", "meeting", "email") and c["id"] in a["contact_ids"]
           and a["ts"] <= NOW and (c["id"], a["ts"][:10]) not in OVERRIDE_EXCLUDE]
    c["last_contacted_at"] = max(tsl) if tsl else None

crm = {"users": users, "companies": companies, "contacts": contacts, "deals": deals, "activities": activities}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as fh:
    json.dump(crm, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
print("wrote", OUT)
