import json, collections, re
d = json.load(open("/Users/luzian/Desktop/Code/sales-env/world/habspot/crm.json"))
assert list(d) == ["users","companies","contacts","deals","activities"]
U={u["id"] for u in d["users"]}; CO={c["id"] for c in d["companies"]}; CT={c["id"] for c in d["contacts"]}; DL={x["id"] for x in d["deals"]}
errs=[]
for k in d:
    ids=[x["id"] for x in d[k]]
    if len(ids)!=len(set(ids)): errs.append(f"dup ids in {k}")
for c in d["companies"]:
    if c["owner"] is not None and c["owner"] not in U: errs.append(c["id"])
for c in d["contacts"]:
    if c["company_id"] not in CO or c["owner"] not in U: errs.append(c["id"])
for x in d["deals"]:
    if x["company_id"] not in CO or x["owner"] not in U or any(i not in CT for i in x["contact_ids"]): errs.append(x["id"])
for a in d["activities"]:
    if a["company_id"] not in CO or a["author"] not in U or (a["deal_id"] and a["deal_id"] not in DL) or any(i not in CT for i in a["contact_ids"]): errs.append(a["id"])
    if a["deal_id"] and next(x for x in d["deals"] if x["id"]==a["deal_id"])["company_id"]!=a["company_id"] : errs.append("dealco "+a["id"])
iso=re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d-07:00$")
for k in ("contacts","deals","activities"):
    for x in d[k]:
        for f in ("created_at","last_contacted_at","ts"):
            if x.get(f) and not iso.match(x[f]): errs.append(f"ts {x['id']} {f}")
print("errors:", errs)
print({k: len(v) for k,v in d.items()})
print("companies by type", collections.Counter(c["type"] for c in d["companies"]))
print("deals by stage", collections.Counter(x["stage"] for x in d["deals"]))
print("activities by type", collections.Counter(a["type"] for a in d["activities"]))
print("crewlane contacts:", [c["id"] for c in d["contacts"] if c["company_id"]=="co_crewlane"])
for c in d["contacts"]: print(c["id"], c["status"], c["last_contacted_at"])
for a in d["activities"]:
    if a["type"]=="note": print(a["id"], a["ts"], a["author"], a["contact_ids"], a["title"])
