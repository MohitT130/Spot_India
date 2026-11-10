"""Analysis engine: phases, growth index, pace, revenue scenarios and the rule-based recommender.

Everything here is deterministic and works offline, so the live demo never depends on an LLM.
"""
import math
from datetime import date, datetime

from config import FEATURES, PHASES, SPOT_USP, COMPETITORS

FEATURE_NAME = {f["id"]: f["name"] for f in FEATURES}
CMETA = {c["id"]: c for c in COMPETITORS}

DEFAULT_ASSUMPTIONS = {
    "scenario": "hybrid",          # organic | hybrid | b2g
    "benchmark": "mycure",
    "arpu_ulb_lakh": 2.5,          # Rs lakh per ULB-equivalent per year (blended licence)
    "arpu_org_lakh": 0.6,          # Rs lakh per organisation per year
    "premium_conv_pct": 0.5,       # % of users on a paid tier
    "arpu_user": 300,              # Rs per paying user per year
    "csr_lakh_per_100k": 5,        # Rs lakh CSR sponsorship per 100K users per year
    "pilot_month": 6,              # first paying government pilot
    "ulb_adds": {"organic": 0.1, "hybrid": 0.5, "b2g": 1.5},   # ULB-equivalents added per month after pilot
    "horizon": 60,
}


# ------------------------------------------------------------------------------------------ dates
def d(s):
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def plot_date(e):
    """Year-precision events are drawn mid-year; month-precision on the 15th."""
    x = d(e["date"])
    if e.get("precision") == "year":
        return date(x.year, 7, 1)
    return x


def decyear(x):
    return x.year + (x.timetuple().tm_yday - 1) / 365.25


def months_between(a, b):
    return (b.year - a.year) * 12 + (b.month - a.month) + (b.day - a.day) / 30.4


def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


# ------------------------------------------------------------------------------------------ per-competitor state
def latest_metric(c, key, asof):
    pts = [m for m in c["metrics"] if m["key"] == key and d(m["date"]) <= asof]
    if not pts:
        return None
    pts.sort(key=lambda m: m["date"])
    return pts[-1]


def dedupe_events(c):
    seed_keys = {(e["date"], e["type"]) for e in c["events"] if e.get("src") != "live"}
    out = []
    for e in c["events"]:
        if e.get("src") == "live" and e["title"] in ("Play Store listing updated",) and (e["date"], e["type"]) in seed_keys:
            continue
        out.append(e)
    return out


def launch_date(c):
    launches = [plot_date(e) for e in c["events"] if e["type"] == "launch"]
    if not launches:
        return None
    first = min(launches)
    ev = next(e for e in c["events"] if e["type"] == "launch" and plot_date(e) == first)
    if ev.get("precision") == "year":
        return date(first.year, 1, 1)  # conservative: slowest implied pace
    return first


def phase_at(c, asof):
    evs = [e for e in c["events"] if d(e["date"]) <= asof and e["type"] != "news"]
    reach = latest_metric(c, "reach", asof)
    r = reach["value"] if reach else 0
    if not evs and not r:
        return None
    feats = c.get("features", {})
    if r >= 1_000_000:
        officer = feats.get("officer_app", [0])[0] >= 1 or feats.get("service_bundle", [0])[0] >= 1
        return 5 if (c.get("gov_scaled") and officer and len(evs) >= 3) else 4
    if r >= 100_000:
        return 3
    if r >= 1_000:
        return 2
    if c.get("kind") == "Prototype" or c["id"] == "meraward":
        return 1
    return 2


def last_release_at(c, asof):
    rel = [d(e["date"]) for e in c["events"] if e["type"] in ("feature", "launch") and d(e["date"]) <= asof and e.get("src") != "news"]
    if c.get("last_release") and d(c["last_release"]) <= asof:
        rel.append(d(c["last_release"]))
    return max(rel) if rel else None


def status_at(c, asof):
    lr = last_release_at(c, asof)
    if not lr:
        return "No release data", None
    m = months_between(lr, asof)
    authoritative = bool(c.get("last_release")) and d(c["last_release"]) <= asof
    n_ev = len([e for e in c["events"] if d(e["date"]) <= asof and e["type"] != "news"])
    if m > 12 and not authoritative and n_ev < 4:
        return "Insufficient history", round(m, 1)
    if m <= 6:
        return "Active", round(m, 1)
    if m <= 12:
        return "Slowing", round(m, 1)
    return "Dormant", round(m, 1)


def growth_index(c, asof):
    reach = latest_metric(c, "reach", asof)
    reviews = latest_metric(c, "reviews", asof)
    cities = latest_metric(c, "cities", asof)
    r = reach["value"] if reach else 0
    rv = reviews["value"] if reviews else 0
    foot = cities["value"] if cities else (c["footprint"]["ulb_eq"] + 0.1 * c["footprint"]["org_eq"] if phase_at(c, asof) else 0)
    since = date(asof.year - 2, asof.month, min(asof.day, 28))
    mom = len([e for e in c["events"] if e["type"] in ("feature", "launch", "policy", "expansion", "milestone", "funding") and since < d(e["date"]) <= asof and e.get("src") != "news"])
    lr = last_release_at(c, asof)
    rec_m = months_between(lr, asof) if lr else 99
    parts = {
        "reach": clamp(math.log10(r + 1) / 7 * 100),
        "footprint": clamp(math.log10(foot + 1) / math.log10(4500) * 100),
        "momentum": clamp(mom / 6 * 100),
        "recency": 100 if rec_m <= 6 else 60 if rec_m <= 12 else 25 if rec_m <= 24 else 0,
        "reviews": clamp(math.log10(rv + 1) / 5 * 100),
    }
    w = {"reach": .35, "footprint": .20, "momentum": .20, "recency": .15, "reviews": .10}
    total = sum(parts[k] * w[k] for k in parts)
    return round(total, 1), {k: round(v, 1) for k, v in parts.items()}


def feature_value(c, fid):
    v = c.get("features", {}).get(fid)
    return v[0] if v else 0


# ------------------------------------------------------------------------------------------ pace & revenue
def pace(c):
    """Users added per month between launch and the most informative reach observation."""
    ld = launch_date(c)
    pts = sorted([m for m in c["metrics"] if m["key"] == "reach"], key=lambda m: m["date"])
    if not ld or not pts:
        return None
    out = []
    for p in pts:
        mths = months_between(ld, d(p["date"]))
        if mths >= 3:
            out.append({"at": p["date"], "months": round(mths, 1), "users": p["value"], "per_month": round(p["value"] / mths), "kind": p["kind"]})
    return out or None


def scenario_paces(comps):
    """Derive organic and mandated users/month from observed competitors, not from guesses."""
    organic, mandated = [], []
    for c in comps.values():
        ps = pace(c)
        if not ps:
            continue
        if c["id"] == "tracsha":  # dormant, not a growth reference
            continue
        first = ps[0]
        (mandated if c.get("gov_scaled") and first["months"] < 36 else organic).append((c["short"] if "short" in c else c["id"], first))
    # earliest observation of mandated players is the burst phase; organic uses the long-run average
    org_vals = [x[1]["per_month"] for x in organic] or [8000]
    man_vals = [x[1]["per_month"] for x in mandated] or [60000]
    org = sum(org_vals) / len(org_vals)
    man = max(man_vals)
    return {"organic": round(org), "mandated": round(man), "hybrid": round((org + man) / 2),
            "organic_from": [x[0] for x in organic], "mandated_from": [x[0] for x in mandated]}


def annual_value(a, ulb, org, users):
    prem = users * a["premium_conv_pct"] / 100 * a["arpu_user"]
    csr = math.floor(users / 100_000) * a["csr_lakh_per_100k"] * 1e5
    lic = ulb * a["arpu_ulb_lakh"] * 1e5 + org * a["arpu_org_lakh"] * 1e5
    return {"licence": lic, "premium": prem, "csr": csr, "total": lic + prem + csr}


def revenue_projection(comps, a, asof):
    sp = scenario_paces(comps)
    scen = a["scenario"]
    per_month = sp["mandated"] if scen == "b2g" else sp["hybrid"] if scen == "hybrid" else sp["organic"]
    adds = a["ulb_adds"][scen]
    bench = comps[a["benchmark"]]
    b_reach = latest_metric(bench, "reach", asof)
    b_users = b_reach["value"] if b_reach else 0
    bv = annual_value(a, bench["footprint"]["ulb_eq"], bench["footprint"]["org_eq"], b_users)
    rows, parity = [], None
    for t in range(0, a["horizon"] + 1):
        users = per_month * t
        ulb = 0 if t < a["pilot_month"] else 1 + adds * (t - a["pilot_month"])
        v = annual_value(a, ulb, 0, users)
        rows.append({"m": t, "users": round(users), "ulb": round(ulb, 1), **{k: round(x) for k, x in v.items()}})
        if parity is None and v["total"] >= bv["total"] and t > 0:
            parity = t
    return {"paces": sp, "per_month": per_month, "ulb_adds": adds, "benchmark": {"id": bench["id"], "name": CMETA[bench["id"]]["name"], "users": b_users,
            "ulb_eq": bench["footprint"]["ulb_eq"], "org_eq": bench["footprint"]["org_eq"], "note": bench["footprint"]["note"], **{k: round(x) for k, x in bv.items()}},
            "rows": rows, "parity_month": parity}


# ------------------------------------------------------------------------------------------ recommender
def monetisation_streams(comps):
    streams = {}
    for c in comps.values():
        for line in c["business_model"]:
            l = line.lower()
            tags = []
            if "payment" in l or "tax" in l:
                tags.append("Payments bundling")
            if "saas" in l or "b2b" in l:
                tags.append("B2B SaaS")
            if "marketplace" in l or "waste-buyer" in l or "lead-fee" in l:
                tags.append("Marketplace or lead fee")
            if "grant" in l or "award" in l or "mission programme" in l or "government-funded" in l:
                tags.append("Grant or government funded")
            for t in tags:
                streams.setdefault(t, set()).add(c["short"] if "short" in c else CMETA[c["id"]]["short"])
    return {k: sorted(v) for k, v in streams.items()}


def recommend(comps, asof, built, usp, rev):
    n = len(comps)
    steps = []
    names = lambda ids: ", ".join(CMETA[i]["short"] for i in ids)

    adoption = {}
    for f in FEATURES:
        have = [cid for cid, c in comps.items() if feature_value(c, f["id"]) >= 1]
        part = [cid for cid, c in comps.items() if 0 < feature_value(c, f["id"]) < 1]
        adoption[f["id"]] = {"have": have, "partial": part, "share": round((len(have) + 0.5 * len(part)) / n, 2)}

    # R1 whitespace that is part of Spot India's own idea
    for fid in usp:
        a = adoption[fid]
        if a["share"] <= 0.2:
            who = names(a["have"] + a["partial"]) or "none of the tracked competitors"
            steps.append({
                "rule": "R1 whitespace", "phase": 1 if fid != "ngo_network" else 2, "type": "differentiator",
                "title": f"Own this: {FEATURE_NAME[fid]}",
                "action": f"Make '{FEATURE_NAME[fid]}' the first thing a user sees, not a buried category. Validate demand with 30 interviews and a landing-page test before building.",
                "why": f"Only {len(a['have']) + len(a['partial'])} of {n} tracked competitors touch this. Offered by: {who}.",
                "evidence": [{"who": CMETA[i]["short"], "fact": comps[i]["features"][fid][1]} for i in a["have"] + a["partial"] if comps[i]["features"].get(fid, [0, ""])[1]],
                "kpi": "Share of reports in this category; time-to-first-responder", "revenue": "Unlocks CSR sponsorship and NGO or responder subscriptions (no competitor sells this)",
                "score": 100 - a["share"] * 100, "trigger": f"adoption {a['share']:.0%} <= 20% and part of Spot India USP"})

    # R2 table stakes
    ts = [(fid, a) for fid, a in adoption.items() if a["share"] >= 0.5 and fid not in built and fid not in usp]
    ts.sort(key=lambda x: -x[1]["share"])
    for fid, a in ts[:5]:
        steps.append({
            "rule": "R2 table stakes", "phase": 2, "type": "table-stakes",
            "title": f"Ship {FEATURE_NAME[fid]}",
            "action": "Include in the first public release. Users expect it and will not forgive its absence." + (" Hyderabad needs Telugu, Hindi and Urdu." if fid == "multilingual" else ""),
            "why": f"{len(a['have'])} of {n} competitors have it" + (f" and {len(a['partial'])} partially" if a["partial"] else "") + f" ({names(a['have'])}).",
            "evidence": [{"who": CMETA[i]["short"], "fact": comps[i]["features"][fid][1]} for i in a["have"][:3] if comps[i]["features"].get(fid, [0, ""])[1]],
            "kpi": "Feature parity checklist 100% before launch", "revenue": "Hygiene: protects conversion and retention",
            "score": 60 + a["share"] * 30, "trigger": f"adoption {a['share']:.0%} >= 50% and not built"})

    # R3 scale-stage must-haves: features present in every competitor that reached 1M+
    scaled = [cid for cid, c in comps.items() if (latest_metric(c, "reach", asof) or {"value": 0})["value"] >= 1_000_000]
    if len(scaled) >= 2:
        pain_feats = {"gallery_upload"}
        common = [f["id"] for f in FEATURES if all(feature_value(comps[s], f["id"]) >= 1 for s in scaled) and f["id"] not in built and f["id"] not in {x for x, _ in ts[:5]} and f["id"] not in pain_feats]
        for fid in common[:3]:
            steps.append({
                "rule": "R3 scale must-have", "phase": 3, "type": "table-stakes",
                "title": f"Plan {FEATURE_NAME[fid]} before you scale",
                "action": "Build the institution-side workflow now. Citizen growth without a responder workflow produces unresolved tickets and low ratings.",
                "why": f"Every competitor with 1M+ reach ({names(scaled)}) has it.",
                "evidence": [{"who": CMETA[i]["short"], "fact": comps[i]["features"][fid][1]} for i in scaled if comps[i]["features"].get(fid, [0, ""])[1]],
                "kpi": "% tickets acknowledged by an authority within 48h", "revenue": "This is the feature governments and NGOs pay for",
                "score": 75, "trigger": f"present in {len(scaled)}/{len(scaled)} scaled competitors"})

    # R4 fix what users hate
    themes = {}
    for cid, c in comps.items():
        for p in c["pain"]:
            themes.setdefault(p["theme"], []).append((cid, p))
    pain_map = {
        "no_gallery_upload": ("Allow gallery upload with editable location", "gallery_upload", "Let users attach existing photos and set or correct the pin. Two competitors only added this in 2026."),
        "location_problems": ("Let users set and correct the location pin", None, "Never lock the location to the GPS fix. Street-level pins are the core of dispatching."),
        "coverage_gap": ("Cover the roads and areas the government apps exclude", None, "T-RACSHA excludes GHMC roads and MyCURE has no animal or accident categories. Be the single place that works everywhere in the city."),
        "fake_closure": ("Citizen-confirmed closure before a ticket shows 'resolved'", None, "Show the before and after photo, let the reporter confirm, and auto-reopen if they do not. Ratings of 2.3 stars show closure trust is broken."),
        "slow_response": ("Publish response-time commitments per responder", None, "Plateaued community apps show that reports without visible follow-up stop being filed."),
    }
    for th, items in themes.items():
        if th not in pain_map:
            continue
        title, fid, action = pain_map[th]
        if fid and fid in built:
            continue
        steps.append({
            "rule": "R4 fix their failures", "phase": 2, "type": "fix",
            "title": title, "action": action,
            "why": f"Signal in {len(set(c for c, _ in items))} competitor(s): {names(sorted(set(c for c, _ in items)))}. Basis: {', '.join(sorted(set(p['basis'] for _, p in items)))}.",
            "evidence": [{"who": CMETA[c]["short"], "fact": p["text"]} for c, p in items][:3],
            "kpi": "Rating >= 4.2 in first 500 reviews", "revenue": "Retention and word of mouth, the cheapest acquisition channel",
            "score": 70 + 5 * len(items), "trigger": f"pain theme '{th}' seen {len(items)}x"})

    # R5 go-to-market: what drove scale
    big = [cid for cid in scaled]
    gov = [cid for cid in big if comps[cid].get("gov_scaled")]
    paces = rev["paces"]
    if big:
        share = len(gov) / len(big)
        if share >= 0.5:
            steps.append({
                "rule": "R5 go-to-market", "phase": 2, "type": "gtm",
                "title": "Secure a government or NGO pilot before chasing organic growth",
                "action": "Offer a free 90-day pilot to the departments that own the issues MyCURE does not list (animals, accidents, abuse), plus two animal-rescue NGOs. Aim for an MoU letter you can show.",
                "why": f"{len(gov)} of {len(big)} competitors with 1M+ reach grew through a government channel ({names(gov)}). Observed pace: about {paces['organic']:,} users/month organic vs {paces['mandated']:,} when mandated.",
                "evidence": [{"who": CMETA[i]["short"], "fact": comps[i]["summary"][:140]} for i in gov],
                "kpi": "1 signed pilot and 3 NGO partners by month 6", "revenue": "First paying ULB-equivalent at the pilot month (see Revenue path)",
                "score": 90, "trigger": f"{share:.0%} of 1M+ players were government-channelled"})

    # R6 stalled community-first players
    stalled = [cid for cid, c in comps.items() if not c.get("gov_scaled") and status_at(c, asof)[0] == "Dormant" and phase_at(c, asof) and phase_at(c, asof) >= 3]
    for cid in stalled:
        c = comps[cid]
        steps.append({
            "rule": "R6 avoid the plateau", "phase": 3, "type": "gtm",
            "title": "Do not rely on community engagement alone",
            "action": "Pair citizen reporting with a paid institutional workflow (responder dashboards, SLAs). Community features drive reach, but contracts drive survival.",
            "why": f"{CMETA[cid]['short']} reached {latest_metric(c, 'reach', asof)['value']:,} users, then went {status_at(c, asof)[1]} months without a release.",
            "evidence": [{"who": CMETA[cid]["short"], "fact": c["business_model"][0]}],
            "kpi": "Revenue from at least 2 institutions by month 12", "revenue": "Avoids the grant-only trap",
            "score": 65, "trigger": f"{cid} dormant with phase>=3 and no gov channel"})

    # R7 windows of opportunity
    dormant = [cid for cid, c in comps.items() if status_at(c, asof)[0] == "Dormant" and phase_at(c, asof)]
    if dormant:
        steps.append({
            "rule": "R7 opening", "phase": 1, "type": "gtm",
            "title": "Target the users of dormant apps first",
            "action": "Mine their reviews for unmet needs, and reach their user communities with a better replacement. Start with the road-hazard users T-RACSHA left behind.",
            "why": "No release in 12+ months from: " + ", ".join(f"{CMETA[i]['short']} ({status_at(comps[i], asof)[1]} mo)" for i in dormant) + ".",
            "evidence": [{"who": CMETA[i]["short"], "fact": f"Last release {last_release_at(comps[i], asof)}"} for i in dormant],
            "kpi": "100 interviews or reviews analysed; 500 waitlist signups", "revenue": "Lower CAC through a warm audience",
            "score": 55, "trigger": f"{len(dormant)} dormant competitor(s)"})

    # R8 monetisation stack
    streams = monetisation_streams(comps)
    steps.append({
        "rule": "R8 monetise", "phase": 3, "type": "monetise",
        "title": "Layer three revenue streams, not one",
        "action": "1) CSR sponsorship of animal and accident categories. 2) Subscriptions for NGOs and responders who receive routed cases. 3) B2G licence once a pilot proves response times. Keep citizen use free.",
        "why": "No competitor charges citizens. Revenue exists only through " + "; ".join(f"{k} ({', '.join(v)})" for k, v in streams.items() if k != "Grant or government funded") + ". Grant funding sustains " + ", ".join(streams.get("Grant or government funded", [])) + " but caps growth.",
        "evidence": [{"who": k, "fact": ", ".join(v)} for k, v in streams.items()],
        "kpi": "Monthly recurring revenue; first CSR sponsor by month 9", "revenue": f"Projected parity with {rev['benchmark']['name']} in {rev['parity_month'] if rev['parity_month'] else 'more than ' + str(rev['rows'][-1]['m'])} months (hybrid scenario)",
        "score": 80, "trigger": f"{len(streams)} stream types observed"})

    # R9 B2G expansion gate
    steps.append({
        "rule": "R9 scale gate", "phase": 4, "type": "gtm",
        "title": "Expand city by city only after response times are proven",
        "action": "Publish a quarterly response-time report from the pilot. Use it to approach the next ULBs. Add ULBs at the pace the model assumes, not faster.",
        "why": f"Swachhata reached 4,503 cities through a national programme. A startup cannot assume that, so the model uses {rev['ulb_adds']} ULB-equivalents/month after the pilot.",
        "evidence": [{"who": "Swachhata", "fact": comps["swachhata"]["footprint"]["note"]}],
        "kpi": "Median acknowledgement time; ULBs under contract", "revenue": "Licence revenue scales with ULBs",
        "score": 70, "trigger": "scale phase"})

    steps.sort(key=lambda s: (s["phase"], -s["score"]))
    for i, s in enumerate(steps, 1):
        s["id"] = i
    return steps, adoption


# ------------------------------------------------------------------------------------------ main entry
def build(ds, cfg):
    comps = ds["competitors"]
    asof = d(cfg.get("asof") or ds["as_of"])
    frm = d(cfg.get("from") or "2010-01-01")
    sel_c = cfg.get("competitors") or list(comps)
    sel_p = cfg.get("phases") or [p["id"] for p in PHASES]
    sel_t = cfg.get("types")  # None = all
    built = set(cfg.get("built") or [])
    usp = cfg.get("usp") or SPOT_USP
    a = {**DEFAULT_ASSUMPTIONS, **(cfg.get("assumptions") or {})}
    a["ulb_adds"] = {**DEFAULT_ASSUMPTIONS["ulb_adds"], **(a.get("ulb_adds") or {})}

    for c in comps.values():
        c["events"] = dedupe_events(c)
        c["short"] = CMETA[c["id"]]["short"]
        c["kind"] = CMETA[c["id"]]["kind"]

    # competitor cards
    cards = []
    for cid, c in comps.items():
        ph = phase_at(c, asof)
        st, since = status_at(c, asof)
        gi, parts = growth_index(c, asof)
        reach = latest_metric(c, "reach", asof)
        rating = latest_metric(c, "rating", asof)
        reviews = latest_metric(c, "reviews", asof)
        pc = pace(c)
        cards.append({
            "id": cid, "name": CMETA[cid]["name"], "short": c["short"], "color": CMETA[cid]["color"], "color_dark": CMETA[cid]["color_dark"], "owner": CMETA[cid]["owner"], "kind": CMETA[cid]["kind"],
            "geo": CMETA[cid]["geo"], "summary": c["summary"], "phase": ph, "phase_name": next((p["name"] for p in PHASES if p["id"] == ph), "Not launched"),
            "status": st, "months_since_release": since, "last_release": (last_release_at(c, asof) or None) and last_release_at(c, asof).isoformat(),
            "growth_index": gi, "growth_parts": parts, "reach": reach["value"] if reach else None, "reach_kind": reach["kind"] if reach else None,
            "reach_date": reach["date"] if reach else None, "rating": rating["value"] if rating else None, "reviews": reviews["value"] if reviews else None,
            "evidence_quality": c["evidence_quality"], "evidence_note": c["evidence_note"], "business_model": c["business_model"], "customers": c["customers"],
            "pace": pc[0] if pc else None, "live_metrics": c["live_metrics"], "site_hits": c.get("site_hits", []),
            "selected": cid in sel_c,
        })

    # events (filtered)
    events = []
    for cid, c in comps.items():
        if cid not in sel_c:
            continue
        for e in c["events"]:
            pd = plot_date(e)
            if not (frm <= pd <= asof):
                continue
            ph = e.get("phase") or phase_at(c, d(e["date"])) or 1
            if ph not in sel_p:
                continue
            if sel_t and e["type"] not in sel_t:
                continue
            events.append({"competitor": cid, "short": c["short"], "color": CMETA[cid]["color"], "date": e["date"], "precision": e.get("precision", "day"),
                           "x": round(decyear(pd), 3), "phase": ph, "type": e["type"], "title": e["title"], "detail": e.get("detail", ""), "conf": e.get("conf", "medium"),
                           "src": e.get("src"), "url": e.get("url") or (ds["sources"].get(e.get("src")) or {}).get("url")})
    events.sort(key=lambda e: e["date"], reverse=True)

    # series
    reach_series, momentum = [], []
    for cid, c in comps.items():
        if cid not in sel_c:
            continue
        pts = sorted([m for m in c["metrics"] if m["key"] == "reach" and frm <= d(m["date"]) <= asof], key=lambda m: m["date"])
        reach_series.append({"id": cid, "short": c["short"], "color": CMETA[cid]["color"],
                             "points": [{"x": round(decyear(d(m["date"])), 3), "y": m["value"], "kind": m["kind"], "date": m["date"]} for m in pts]})
        evs = sorted([e for e in c["events"] if e["type"] in ("launch", "feature", "policy", "expansion", "milestone", "funding") and e.get("src") != "news" and plot_date(e) <= asof], key=plot_date)
        cum, pts2 = 0, []
        for e in evs:
            cum += 1
            if plot_date(e) >= frm:
                pts2.append({"x": round(decyear(plot_date(e)), 3), "y": cum, "title": e["title"]})
        if pts2:
            pts2.append({"x": round(decyear(asof), 3), "y": cum, "title": "as of"})
        momentum.append({"id": cid, "short": c["short"], "color": CMETA[cid]["color"], "points": pts2})

    # phase journey matrix
    journey = []
    for cid, c in comps.items():
        if cid not in sel_c:
            continue
        row = {"id": cid, "short": c["short"], "color": CMETA[cid]["color"], "cells": []}
        for p in PHASES:
            evs = [e for e in c["events"] if (e.get("phase") or phase_at(c, d(e["date"])) or 1) == p["id"] and e["type"] != "news" and d(e["date"]) <= asof]
            evs.sort(key=lambda e: e["date"])
            row["cells"].append({"phase": p["id"], "n": len(evs), "first": evs[0]["date"] if evs else None, "titles": [e["title"] for e in evs[:3]]})
        row["current"] = phase_at(c, asof)
        journey.append(row)

    rev = revenue_projection(comps, a, asof)
    steps, adoption = recommend(comps, asof, built, usp, rev)

    # feature matrix
    matrix = []
    for f in FEATURES:
        row = {"id": f["id"], "name": f["name"], "usp": f["id"] in usp, "built": f["id"] in built, "share": adoption[f["id"]]["share"], "cells": {}}
        for cid, c in comps.items():
            v = feature_value(c, f["id"])
            row["cells"][cid] = {"v": v, "note": (c["features"].get(f["id"]) or [0, ""])[1], "hint": f["id"] in c.get("site_hits", []) and v == 0 and c["id"] != "meraward"}
        matrix.append(row)

    # headline insights
    active = [x for x in cards if x["status"] == "Active" and x["selected"]]
    top_threat = max(active, key=lambda x: x["growth_index"]) if active else None
    white = sorted([m for m in matrix if m["share"] <= 0.2], key=lambda m: m["share"])
    insights = []
    if top_threat:
        insights.append({"label": "Strongest active competitor", "value": top_threat["short"], "sub": f"Growth index {top_threat['growth_index']}, {top_threat['phase_name']} phase"})
    insights.append({"label": "Whitespace features", "value": str(len(white)), "sub": ", ".join(m["name"] for m in white[:3]) or "none"})
    dor = [x for x in cards if x["status"] == "Dormant"]
    insights.append({"label": "Dormant competitors", "value": str(len(dor)), "sub": ", ".join(x["short"] for x in dor) or "none"})
    insights.append({"label": "Revenue parity", "value": (f"Month {rev['parity_month']}" if rev["parity_month"] else "Beyond horizon"),
                     "sub": f"vs {rev['benchmark']['name']} ({a['scenario']} scenario)"})

    return {
        "asof": asof.isoformat(), "from": frm.isoformat(), "phases": PHASES, "cards": cards, "events": events, "reach_series": reach_series, "momentum": momentum,
        "journey": journey, "matrix": matrix, "steps": steps, "revenue": rev, "assumptions": a, "insights": insights, "fact_checks": ds["fact_checks"],
        "sources": ds["sources"], "meta": ds["meta"], "usp": usp, "built": sorted(built), "streams": monetisation_streams(comps),
        "feature_names": FEATURE_NAME,
    }
