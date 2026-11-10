#!/usr/bin/env python3
"""Build Mini's mind taxonomy from docs/HUMAN-INTELLIGENCE-DATABASE.md.

The owner's document is the single source of truth. This script reads its
30 groups (every field and note) and 8 life stages, adds the privacy rules
the document asks for (access level L0–L4, whether an AI may ever infer the
field, whether it may be stored at all) and writes a versioned
services/mind/taxonomy.json used by the database seed and the worker.

Run:  python3 scripts/mind/build_taxonomy.py          (writes the JSON)
      python3 scripts/mind/build_taxonomy.py --check  (fails if out of date)
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "HUMAN-INTELLIGENCE-DATABASE.md"
OUT = ROOT / "services" / "mind" / "taxonomy.json"
VERSION = "1.0.0"

# Access levels from section 6 of the document.
LEVELS = {
    "L0": "Public",
    "L1": "Personal preferences",
    "L2": "Private context",
    "L3": "Sensitive (health, finances, intimate experiences)",
    "L4": "Highly restricted (identity documents, precise location, protected records)",
}

# Default access level per group (section 6 examples applied to section 1).
GROUP_LEVEL = {
    1: "L2", 2: "L2", 3: "L3", 4: "L1", 5: "L2", 6: "L1", 7: "L1", 8: "L1", 9: "L2", 10: "L2",
    11: "L2", 12: "L1", 13: "L1", 14: "L2", 15: "L3", 16: "L1", 17: "L1", 18: "L1", 19: "L2",
    20: "L3", 21: "L2", 22: "L1", 23: "L3", 24: "L2", 25: "L2", 26: "L2", 27: "L2", 28: "L2",
    29: "L2", 30: "L1",
}

# Field-level overrides where the document is stricter or looser.
LEVEL_OVERRIDES = {
    "unique_human_profile_id": "L2",
    "legal_name": "L2", "previous_names": "L2", "date_of_birth": "L2",
    "personal_identification_documents": "L4",        # kept OUT of general memory
    "place_of_residence": "L3", "citizenship": "L2", "nationality": "L2",
    "gender_identity": "L3", "pronouns": "L1", "marital_status": "L2",
    "emergency_contact_preferences": "L3",
    "body_measurements": "L3", "food_allergies": "L3", "physical_limitations": "L3",
    "mobility_capabilities": "L3", "hearing_accessibility": "L3", "vision_accessibility": "L3",
    "attachment_preferences": "L3", "emotional_triggers": "L3",
    "romantic_partner": "L3", "spouse": "L3", "people_they_avoid": "L3",
    "experiences_they_do_not_want_ai_to_revisit": "L3", "personal_failures": "L3",
    "email_accounts": "L2", "authentication_preferences": "L2", "security_preferences": "L2",
    "memories_that_should_never_be_shared": "L4", "things_they_want_forgotten": "L3",
    "favourite_food": "L1", "dietary_preferences": "L1",
    "legal_commitments": "L3", "contracts": "L3", "end_of_life_preferences": "L3",
}

# Never store these at all (document: L4 stays outside general memory;
# never store passwords, private keys, recovery codes, authentication secrets).
NEVER_STORE = {"personal_identification_documents", "memories_that_should_never_be_shared"}

# Groups/fields an AI must never infer — only the person may state them.
NEVER_INFER_GROUPS = {3, 15, 20, 23}       # health, finances, religion, fears
NEVER_INFER_FIELDS = {
    "gender_identity", "pronouns", "marital_status", "nationality", "citizenship", "cultural_identity",
    "attachment_preferences", "romantic_partner", "spouse", "date_of_birth", "age", "legal_name",
    "existing_diagnoses", "personal_insecurities",
}

TYPE_OVERRIDES = {
    "date_of_birth": "date", "age": "integer", "height": "measurement", "body_measurements": "measurement",
    "wake_up_time": "time", "sleep_time": "time", "monthly_income": "money", "monthly_expenses": "money",
    "savings": "money", "target_dates": "date", "years_of_experience": "integer", "progress": "percent",
    "important_anniversaries": "date_list", "important_birthdays": "date_list",
    "languages_spoken": "list", "other_languages": "list", "siblings": "person_list", "children": "person_list",
    "parents_or_guardians": "person_list", "grandparents": "person_list", "friends": "person_list",
    "best_friends": "person_list", "colleagues": "person_list", "mentors": "person_list", "teachers": "person_list",
    "trusted_individuals": "person_list", "dependants": "person_list", "people_relying_on_them": "person_list",
    "romantic_partner": "person", "spouse": "person",
}

# Section 4: fields per interest need enthusiasm/experience/frequency/current.
INTEREST_FACETS = ["enthusiasm", "experience", "frequency", "current_or_historical"]


def slug(label: str) -> str:
    text = re.sub(r"\(.*?\)", "", label)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text


def optional(label: str) -> bool:
    return "(optional" in label.lower() or "if relevant" in label.lower() or "where appropriate" in label.lower() \
        or "if they choose" in label.lower() or "if desired" in label.lower()


def parse(doc: str) -> dict:
    groups, stages = [], []
    group = stage = None
    section = None
    for raw in doc.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            section = line[3:5].strip()
            group = stage = None
            continue
        m = re.match(r"^### Group (\d{2}) — (.+)$", line)
        if m and section == "2.":
            group = {"id": int(m.group(1)), "title": m.group(2).strip(), "intro": "", "notes": [], "fields": []}
            groups.append(group)
            continue
        m = re.match(r"^### Stage (\d): (.+?) — (\d+)–(\d+)(\+?)$", line)
        if m and section == "3.":
            stage = {"stage": int(m.group(1)), "title": m.group(2).strip(), "min_age": int(m.group(3)),
                     "max_age": None if m.group(5) else int(m.group(4)), "theme": "", "focus": []}
            if m.group(5):
                stage["band_label"] = f"{m.group(3)}–{m.group(4)}+"
            stages.append(stage)
            continue
        if group is not None:
            if line.startswith("- "):
                label = line[2:].strip()
                key = slug(label)
                group["fields"].append({"key": key, "label": label, "optional": optional(label)})
            elif line.startswith("Note: "):
                group["notes"].append(line[6:].strip())
            elif line and not line.startswith("#"):
                group["intro"] = (group["intro"] + " " + line).strip()
        if stage is not None:
            if line.startswith("Theme: "):
                stage["theme"] = line[7:].strip()
            elif line.startswith("- "):
                stage["focus"].append(line[2:].strip())
    return {"groups": groups, "stages": stages}


def enrich(data: dict, meanings: dict) -> dict:
    seen = {}
    for g in data["groups"]:
        g["meaning"] = meanings.get(g["id"], "")
        g["default_level"] = GROUP_LEVEL[g["id"]]
        g["ai_may_infer"] = g["id"] not in NEVER_INFER_GROUPS
        for f in g["fields"]:
            key = f["key"]
            # Same label can appear in two groups (e.g. "Languages", "Certifications").
            if key in seen:
                f["key"] = key = f"{key}_g{g['id']:02d}"
            seen[key] = g["id"]
            base = re.sub(r"_g\d\d$", "", key)
            f["level"] = LEVEL_OVERRIDES.get(base, g["default_level"])
            f["never_store"] = base in NEVER_STORE
            f["ai_may_infer"] = g["ai_may_infer"] and base not in NEVER_INFER_FIELDS and f["level"] not in ("L3", "L4")
            f["data_type"] = TYPE_OVERRIDES.get(base, "text")
            if g["id"] == 17:
                f["facets"] = INTEREST_FACETS
    return data


def build() -> dict:
    doc = DOC.read_text(encoding="utf-8")
    meanings = {int(n): m.strip() for n, _t, m in re.findall(r"^\| (\d{2}) \| (.+?) \| (.+?) \|$", doc, re.M)}
    data = enrich(parse(doc), meanings)
    assert len(data["groups"]) == 30, f"expected 30 groups, found {len(data['groups'])}"
    assert len(data["stages"]) == 8, f"expected 8 life stages, found {len(data['stages'])}"
    return {
        "version": VERSION,
        "source": "docs/HUMAN-INTELLIGENCE-DATABASE.md",
        "access_levels": LEVELS,
        "intelligence_layers": ["descriptive", "contextual", "temporal", "predictive", "partnership"],
        "sources": ["user_stated", "user_confirmed", "ai_observed", "ai_hypothesis", "imported"],
        "groups": data["groups"],
        "life_stages": data["stages"],
    }


def main():
    out = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != out:
            sys.exit("services/mind/taxonomy.json is out of date: run scripts/mind/build_taxonomy.py")
        print("taxonomy up to date")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(out, encoding="utf-8")
    t = json.loads(out)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(t['groups'])} groups, "
          f"{sum(len(g['fields']) for g in t['groups'])} fields, {len(t['life_stages'])} life stages")


if __name__ == "__main__":
    main()
