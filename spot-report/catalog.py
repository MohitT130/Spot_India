"""Incident taxonomy, CLIP zero-shot prompts, and authority routing.

Two things live here and nothing else:

  CATEGORIES  one entry per kind of incident Spot India can report. Each carries
              the natural-language prompts handed to CLIP for zero-shot scoring.
  AUTHORITIES one entry per responder. Every category names the authority it
              routes to, so re-routing is a one-line config change.

Right now every authority resolves to the same mock contact (the product owner)
so the end-to-end loop can be tested. Swapping in real contacts means editing
only the `email`/`phone` fields below: no code changes anywhere else.
"""
import os

# --- Mock responder contact ------------------------------------------------
# Every authority points here until real contacts are wired in.
# Set MOCK_AUTHORITY_EMAIL / MOCK_AUTHORITY_PHONE in the environment to point
# every authority at a real inbox during testing. The defaults below are
# deliberately non-functional placeholders so no personal contact detail is
# committed to source control.
MOCK_EMAIL = os.environ.get("MOCK_AUTHORITY_EMAIL", "reports@example.com")
MOCK_PHONE = os.environ.get("MOCK_AUTHORITY_PHONE", "0000000000")
MOCK_PHONE_E164 = "91" + MOCK_PHONE.lstrip("+").removeprefix("91")

SEVERITY = {
    "critical": {"rank": 4, "label": "Critical", "sla_hours": 1,
                 "blurb": "Life at immediate risk. Needs response within the hour."},
    "high": {"rank": 3, "label": "High", "sla_hours": 6,
             "blurb": "Active harm or injury. Same-day response needed."},
    "medium": {"rank": 2, "label": "Medium", "sla_hours": 48,
               "blurb": "Public hazard or nuisance. Response within two days."},
    "low": {"rank": 1, "label": "Low", "sla_hours": 168,
            "blurb": "Civic upkeep. Response within a week."},
}


def _authority(aid, name, dept, escalation, helpline=None, facility=None,
               public_name=None, extra_helplines=None):
    """One responder.

    Two contact layers, deliberately separate:

      public_*  what the reporter is SHOWN: the real-world body that handles
                this kind of incident, and its genuine public helpline. A
                citizen looking at an injured person should see "hospital and
                108 ambulance", because that is who actually helps them, and
                they may well need to call it themselves right now.

      email/phone  where the report is actually DELIVERED. Mocked to the
                product owner during testing. Changing these to real
                departmental contacts is a config edit, nothing more.

    `facility` is the OpenStreetMap amenity searched for near the incident, so
    the reporter can be shown the nearest actual hospital or police station.
    """
    return {"id": aid, "name": name, "dept": dept, "escalation": escalation,
            "public_name": public_name or name,
            "helpline": helpline, "facility": facility,
            "extra_helplines": extra_helplines or [],
            "email": MOCK_EMAIL, "phone": MOCK_PHONE, "phone_e164": MOCK_PHONE_E164,
            "mock": True}


# --- Authorities -----------------------------------------------------------
AUTHORITIES = {
    a["id"]: a for a in [
        _authority("animal_welfare", "Animal Welfare Rescue Cell",
                   "Municipal Veterinary Dept and partner NGO rescue network",
                   "District SPCA, then Animal Welfare Board of India",
                   helpline="1962", facility="veterinary",
                   public_name="Veterinary rescue and animal welfare"),
        _authority("police_animal", "Police: Animal Cruelty Desk",
                   "Local police station, cruelty complaints",
                   "District SP, then Animal Welfare Board of India",
                   helpline="112", facility="police",
                   public_name="Police, animal cruelty complaint"),
        _authority("police_safety", "Police: Women and Public Safety",
                   "Local police station, womens safety and public order",
                   "DCP Law and Order, then Commissioner of Police",
                   helpline="112", facility="police",
                   public_name="Police and womens safety helpline",
                   extra_helplines=[
                       {"label": "Women helpline", "number": "181"},
                       {"label": "Child helpline", "number": "1098"},
                       {"label": "Cyber crime", "number": "1930"},
                   ]),
        _authority("traffic_police", "Traffic Police Control Room",
                   "City traffic police, accident response",
                   "DCP Traffic, then Commissioner of Police",
                   helpline="112", facility="hospital",
                   public_name="Traffic police and ambulance"),
        _authority("emergency_medical", "Emergency Medical Services",
                   "108 ambulance dispatch and nearest trauma centre",
                   "District Health Officer",
                   helpline="108", facility="hospital",
                   public_name="Hospital and 108 ambulance"),
        _authority("roads", "Roads and Infrastructure Division",
                   "Municipal engineering, road surface and signage",
                   "Executive Engineer, then Municipal Commissioner"),
        _authority("sanitation", "Sanitation and Solid Waste Dept",
                   "Ward-level waste collection and street sweeping",
                   "Ward Officer, then Chief Sanitary Inspector"),
        _authority("water_sewage", "Water Supply and Sewerage Board",
                   "Drainage, sewage lines and waterlogging",
                   "Section Engineer, then Board General Manager"),
        _authority("electrical", "Street Lighting and Electrical Wing",
                   "Street lights, poles and exposed wiring",
                   "Assistant Engineer, then Electrical Superintendent"),
        _authority("fire", "Fire and Emergency Services",
                   "101 fire control room",
                   "Divisional Fire Officer",
                   helpline="101", facility="fire_station",
                   public_name="Fire and emergency services"),
        _authority("parks", "Parks and Horticulture Dept",
                   "Trees, green cover and fallen branches",
                   "Horticulture Officer, then Municipal Commissioner"),
        _authority("town_planning", "Town Planning and Enforcement",
                   "Encroachment, illegal construction and hoardings",
                   "Deputy Commissioner, then Municipal Commissioner"),
        _authority("grievance_cell", "General Grievance Cell",
                   "Central municipal grievance redressal",
                   "Municipal Commissioner"),
    ]
}


# --- Categories ------------------------------------------------------------
# `prompts` are scored by CLIP against the photo. Several phrasings per category
# because CLIP is sensitive to wording; the best-scoring prompt wins the group.
CATEGORIES = [
    {
        "id": "injured_animal", "name": "Injured or sick animal", "icon": "animal",
        "authority": "animal_welfare", "severity": "high", "group": "Animal",
        "prompts": [
            "an injured street dog bleeding on the road",
            "a sick or wounded stray animal lying helpless",
            "an injured cow or buffalo unable to stand",
            "a stray dog with a visible wound or broken leg",
        ],
        "ask": "Is the animal bleeding, limping or unable to move?",
    },
    {
        "id": "animal_abuse", "name": "Animal cruelty or abuse", "icon": "alert",
        "authority": "police_animal", "severity": "high", "group": "Animal",
        "prompts": [
            "a person beating or abusing an animal",
            "an animal chained cruelly in a tiny cage",
            "animal cruelty in progress",
            "a starved neglected animal tied up without food or water",
        ],
        "ask": "Is someone actively harming the animal?",
    },
    {
        "id": "stray_animal_hazard", "name": "Stray animal hazard", "icon": "animal",
        "authority": "animal_welfare", "severity": "medium", "group": "Animal",
        "prompts": [
            "a pack of stray dogs blocking a busy road",
            "stray cattle wandering in traffic",
            "an aggressive stray dog threatening pedestrians",
        ],
        "ask": "Are the animals creating a danger to traffic or people?",
    },
    {
        "id": "road_accident", "name": "Road accident", "icon": "accident",
        "authority": "traffic_police", "severity": "critical", "group": "Emergency",
        "prompts": [
            "a road traffic accident with a crashed vehicle",
            "a motorcycle collision with a damaged bike on the road",
            "an overturned car after a crash",
            "a vehicle accident scene with debris on the road",
        ],
        "ask": "Is anyone injured and still at the scene?",
    },
    {
        "id": "medical_emergency", "name": "Person needing urgent help", "icon": "medical",
        "authority": "emergency_medical", "severity": "critical", "group": "Emergency",
        "prompts": [
            "a person lying unconscious on the ground needing medical help",
            "an injured person collapsed on the street",
            "someone in medical distress lying on the pavement",
        ],
        "ask": "Is the person conscious and breathing?",
    },
    {
        "id": "harassment", "name": "Harassment or unsafe situation", "icon": "alert",
        "authority": "police_safety", "severity": "high", "group": "Emergency",
        "prompts": [
            "a person being harassed or threatened in public",
            "a woman being followed and harassed on a street",
            "an aggressive confrontation between people in a public place",
            "a person in distress surrounded by a threatening group",
        ],
        "ask": "Is the person in immediate danger right now?",
        # Shown before the report is sent. This category names people, so the
        # reporter is told what it is and is not.
        "caution": ("This goes to the police as an unverified citizen report, "
                    "not as proof. If anyone is in immediate danger, call 112 "
                    "first. Do not photograph anyone if doing so puts you at risk."),
    },
    {
        "id": "fire_hazard", "name": "Fire or fire hazard", "icon": "fire",
        "authority": "fire", "severity": "critical", "group": "Emergency",
        "prompts": [
            "a building or vehicle on fire with visible flames",
            "a pile of garbage burning with thick smoke",
            "dangerous exposed electrical wires sparking",
        ],
        "ask": "Are flames or smoke visible right now?",
    },
    {
        "id": "pothole", "name": "Pothole or broken road", "icon": "road",
        "authority": "roads", "severity": "medium", "group": "Infrastructure",
        "prompts": [
            "a large pothole in an asphalt road surface",
            "a badly damaged road full of potholes and cracks",
            "a deep crater in the middle of a street",
            "an unfinished dug up road trench",
        ],
        "ask": "Is the pothole deep enough to damage a vehicle?",
    },
    {
        "id": "garbage", "name": "Garbage or waste dumping", "icon": "waste",
        "authority": "sanitation", "severity": "low", "group": "Sanitation",
        "prompts": [
            "a large pile of uncollected garbage on the street",
            "an overflowing dustbin with waste spilling out",
            "illegal dumping of trash in a public place",
            "scattered plastic waste and a rubbish heap",
        ],
        "ask": "Has this been lying uncollected for days?",
    },
    {
        "id": "waterlogging", "name": "Waterlogging or flooding", "icon": "water",
        "authority": "water_sewage", "severity": "medium", "group": "Infrastructure",
        "prompts": [
            "a flooded street with standing water after rain",
            "a waterlogged road with vehicles wading through water",
            "stagnant dirty water collected on a street",
        ],
        "ask": "Is the water blocking the road entirely?",
    },
    {
        "id": "sewage", "name": "Open drain or sewage leak", "icon": "water",
        "authority": "water_sewage", "severity": "medium", "group": "Sanitation",
        "prompts": [
            "an open uncovered manhole in a street",
            "sewage overflowing from a drain onto the road",
            "a broken open drain with dirty water",
        ],
        "ask": "Is the manhole open and unguarded?",
    },
    {
        "id": "streetlight", "name": "Broken street light", "icon": "light",
        "authority": "electrical", "severity": "low", "group": "Infrastructure",
        "prompts": [
            "a broken or damaged street light pole",
            "a dark street at night with no working street lights",
            "a leaning electricity pole with hanging wires",
        ],
        "ask": "Is the area completely dark at night?",
    },
    {
        "id": "fallen_tree", "name": "Fallen tree or branch", "icon": "tree",
        "authority": "parks", "severity": "medium", "group": "Infrastructure",
        "prompts": [
            "a large fallen tree blocking a road",
            "a broken tree branch lying across a street",
            "an uprooted tree after a storm",
        ],
        "ask": "Is it blocking traffic or touching power lines?",
    },
    {
        "id": "encroachment", "name": "Encroachment or illegal construction", "icon": "build",
        "authority": "town_planning", "severity": "low", "group": "Civic",
        "prompts": [
            "shops illegally encroaching on a footpath",
            "construction material dumped on a public pavement",
            "an illegal hoarding or banner blocking a road",
        ],
        "ask": "Is a footpath or road blocked by this?",
    },
    {
        "id": "other", "name": "Something else", "icon": "other",
        "authority": "grievance_cell", "severity": "low", "group": "Civic",
        "prompts": [],
        "ask": "Describe what you are seeing.",
    },
]

CATEGORY_BY_ID = {c["id"]: c for c in CATEGORIES}

# Control prompts. If one of these wins, the photo probably is not a civic
# incident at all, and we say so instead of guessing a category.
CONTROL_PROMPTS = [
    "an ordinary empty street with nothing wrong",
    "a normal clean road in good condition",
    "an indoor room with furniture",
    "a selfie portrait of a person smiling",
    "a screenshot of text on a screen",
]
NONE_CATEGORY = "__none__"


def clip_prompts():
    """Flat prompt list for the browser. Each carries its owning category, so a
    winning prompt maps straight back to a category without extra lookup."""
    out = [{"category": c["id"], "text": p} for c in CATEGORIES for p in c["prompts"]]
    out += [{"category": NONE_CATEGORY, "text": p} for p in CONTROL_PROMPTS]
    return out


def route(category_id):
    """Category id -> (category, authority). Unknown ids fall back to the grievance cell."""
    cat = CATEGORY_BY_ID.get(category_id) or CATEGORY_BY_ID["other"]
    return cat, AUTHORITIES[cat["authority"]]


def public_config():
    cats = []
    for c in CATEGORIES:
        a = AUTHORITIES[c["authority"]]
        entry = {k: c[k] for k in ("id", "name", "icon", "severity", "group", "ask")}
        entry["authority"] = a["public_name"]
        entry["authority_dept"] = a["dept"]
        entry["helpline"] = a["helpline"]
        entry["extra_helplines"] = a["extra_helplines"]
        entry["caution"] = c.get("caution")
        cats.append(entry)
    return {
        "categories": cats,
        "prompts": clip_prompts(),
        "severity": SEVERITY,
        "groups": list(dict.fromkeys(c["group"] for c in CATEGORIES)),
    }
