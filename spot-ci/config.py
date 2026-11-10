"""Static configuration: competitor registry, feature taxonomy, lifecycle phases, Spot India profile."""

AS_OF_DEFAULT = "2026-10-09"

PHASES = [
    {"id": 1, "name": "Seed", "blurb": "Prototype, hackathon or pilot. No real usage yet."},
    {"id": 2, "name": "Launch", "blurb": "Public release in one geography. Under 100K users."},
    {"id": 3, "name": "Traction", "blurb": "Organic or sponsored growth. 100K to 1M users."},
    {"id": 4, "name": "Scale", "blurb": "1M+ users or multi-city footprint."},
    {"id": 5, "name": "Entrench", "blurb": "Embedded in government workflow, bundled services, or monetised."},
]

EVENT_TYPES = ["launch", "feature", "expansion", "funding", "policy", "milestone", "news"]

# Colour-blind safe categorical palette (Okabe-Ito derived)
COMPETITORS = [

    {"id": "mycure", "name": "MyCURE (GHMC)", "short": "MyCURE", "color": "#0072B2", "color_dark": "#3a8fd6",
     "owner": "Greater Hyderabad Municipal Corporation", "kind": "Government",
     "geo": "Hyderabad", "play_pkg": "cgg.gov.ghmc", "ios_id": None,
     "sites": [],
     "news_q": '"MyCURE" GHMC app',
     "gov_channel": True},

    {"id": "swachhata", "name": "Swachhata-MoHUA", "short": "Swachhata", "color": "#E69F00", "color_dark": "#bd7f12",
     "owner": "Janaagraha with MoHUA (Govt. of India)", "kind": "NGO + Government",
     "geo": "India (sanitation)", "play_pkg": "com.ichangemycity.swachhbharat", "ios_id": "1124033628",
     "sites": [{"url": "https://www.janaagraha.org/work/swachhata-technology-platform/", "role": "kpi"}],
     "news_q": '"Swachhata app" MoHUA complaints',
     "gov_channel": True},

    {"id": "icmc", "name": "I Change My City", "short": "ICMC", "color": "#009E73", "color_dark": "#1ea67c",
     "owner": "Janaagraha (NGO)", "kind": "NGO",
     "geo": "Bengaluru, Mumbai", "play_pkg": None, "ios_id": "1239689812",
     "sites": [{"url": "https://www.janaagraha.org/i-change-my-city/", "role": "kpi"}],
     "news_q": '"I Change My City" OR Ichangemycity Janaagraha',
     "gov_channel": False},

    {"id": "tracsha", "name": "T-RACSHA", "short": "T-RACSHA", "color": "#D55E00", "color_dark": "#e0622a",
     "owner": "Roads & Buildings Dept, Telangana (built by Osmosys)", "kind": "Government",
     "geo": "Telangana state roads", "play_pkg": "com.oqsha.t_racsha", "ios_id": None,
     "sites": [{"url": "https://t-racsha.com/", "role": "profile"}],
     "news_q": 'T-RACSHA Telangana road app',
     "gov_channel": True},

    {"id": "meraward", "name": "MeraWard", "short": "MeraWard", "color": "#56B4E9", "color_dark": "#4b96c9",
     "owner": "Hackathon team 'Sleepy peeps'", "kind": "Prototype",
     "geo": "Delhi MCD wards (prototype)", "play_pkg": None, "ios_id": None,
     "sites": [{"url": "https://meraward.in/", "role": "profile"}],
     "github": "amritkang165/meraward",
     "news_q": '"MeraWard" civic app',
     "gov_channel": False},

    {"id": "civisence", "name": "CiviSence", "short": "CiviSence", "color": "#CC79A7", "color_dark": "#bf6fa6",
     "owner": "Private vendor (details not public)", "kind": "Startup (B2B)",
     "geo": "Campuses and organisations", "play_pkg": None, "ios_id": None,
     "sites": [{"url": "https://civisence.in/", "role": "profile"}],
     "news_q": '"CiviSence" civic',
     "gov_channel": False},
]

# Feature taxonomy. kw = keywords used by the website scraper to detect a feature on a page.
FEATURES = [
    {"id": "geo_photo", "name": "Geo-tagged photo reporting", "kw": ["geo-tag", "geotag", "geo-location", "gps", "photo", "location"]},
    {"id": "status_tracking", "name": "Real-time status tracking", "kw": ["track", "status", "real-time", "real time"]},
    {"id": "reopen_feedback", "name": "Reopen or rate a closure", "kw": ["reopen", "re-open", "feedback", "rate the resolution"]},
    {"id": "upvote", "name": "Upvote and community validation", "kw": ["upvote", "vote up", "voting", "support this complaint"]},
    {"id": "multilingual", "name": "Multi-language", "kw": ["hindi", "kannada", "tamil", "telugu", "multilingual", "regional language"]},
    {"id": "volunteer_community", "name": "Volunteer and community events", "kw": ["volunteer", "community event", "swachh manch", "attendance"]},
    {"id": "officer_app", "name": "Officer or engineer workflow app", "kw": ["engineer app", "field officer", "supervisory", "councillor app", "officer login", "engineers can log in"]},
    {"id": "gallery_upload", "name": "Gallery upload with location", "kw": ["gallery", "upload from gallery"]},
    {"id": "ai_assist", "name": "AI drafting or routing", "kw": ["ai-powered", "ai powered", "ai-assisted", "ai routing", "machine learning", "bedrock"]},
    {"id": "public_dashboard", "name": "Public accountability dashboard", "kw": ["heatmap", "neglect index", "leaderboard", "ward statistics", "public dashboard", "resolution dashboard"]},
    {"id": "service_bundle", "name": "Bundled civic services and payments", "kw": ["property tax", "trade licen", "certificate", "payment"]},
    {"id": "marketplace", "name": "Marketplace or circular economy", "kw": ["marketplace", "waste buyer", "recycling", "scrap"]},
    {"id": "org_dashboards", "name": "Organisation (B2B) dashboards", "kw": ["organization", "organisation", "campus", "enterprise dashboard"]},
    {"id": "animal_emergency", "name": "Injured animal, accident and abuse reporting", "kw": ["injured animal", "animal rescue", "accident", "abuse", "emergency"]},
    {"id": "smart_routing", "name": "Auto-route to the right authority (who to contact)", "kw": ["routes to", "auto-route", "right authority", "correct department", "routing"]},
    {"id": "ngo_network", "name": "NGO and specialist responder network", "kw": ["ngo partner", "rescue partner", "responder network", "specialist responder"]},
]

# Spot India's own unique idea, taken from the deck (editable in the dashboard).
SPOT_USP = ["animal_emergency", "smart_routing", "ngo_network"]

SPOT_DEFAULT_BUILT = []  # nothing shipped yet; owner toggles features as they get built

# Review pain-theme keywords (used on scraped review text, and to label seeded themes).
PAIN_THEMES = {
    "fake_closure": ["closed without", "not resolved", "fake", "marked resolved", "false resolution", "no action"],
    "no_gallery_upload": ["gallery", "cannot upload", "only camera", "live capture"],
    "location_problems": ["location", "gps", "wrong place", "cannot set"],
    "coverage_gap": ["ghmc", "not covered", "not available in", "my area", "my city"],
    "crashes_login": ["crash", "otp", "login", "not working", "hang", "bug"],
    "slow_response": ["no response", "slow", "weeks", "months", "ignored", "delay"],
}
