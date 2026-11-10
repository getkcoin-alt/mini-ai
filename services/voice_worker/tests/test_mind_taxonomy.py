"""Mini's mind taxonomy must match the owner's Human Intelligence Database doc."""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIND = ROOT / "services" / "mind"
DOC_PATH = ROOT / "docs" / "HUMAN-INTELLIGENCE-DATABASE.md"
DOC = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else ""


def setUpModule():
    if not DOC:
        raise unittest.SkipTest("repo-only test: the owner's doc is not deployed to servers")


def taxonomy():
    return json.loads((MIND / "taxonomy.json").read_text(encoding="utf-8"))


def adult_stages():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((MIND / "stages").glob("stage*.json"))]


class TaxonomyTests(unittest.TestCase):
    def test_generated_file_is_up_to_date(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts/mind/build_taxonomy.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_database_seed_is_up_to_date(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts/mind/build_seed.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_all_30_groups_and_every_field_in_the_doc(self):
        t = taxonomy()
        self.assertEqual([g["id"] for g in t["groups"]], list(range(1, 31)))
        section2 = DOC[DOC.index("## 2."):DOC.index("## 3.")]
        self.assertEqual(sum(len(g["fields"]) for g in t["groups"]), len(re.findall(r"^- ", section2, re.M)))
        keys = [f["key"] for g in t["groups"] for f in g["fields"]]
        self.assertEqual(len(keys), len(set(keys)), "field keys must be unique")

    def test_eight_life_stages_with_doc_bands(self):
        bands = [(s["min_age"], s["max_age"]) for s in taxonomy()["life_stages"]]
        self.assertEqual(bands, [(8, 12), (13, 17), (18, 24), (25, 34), (35, 49), (50, 64), (65, 79), (80, None)])

    def test_privacy_rules_from_the_doc(self):
        fields = {f["key"]: f for g in taxonomy()["groups"] for f in g["fields"]}
        groups = {g["id"]: g for g in taxonomy()["groups"]}
        self.assertTrue(fields["personal_identification_documents"]["never_store"])
        self.assertEqual(fields["personal_identification_documents"]["level"], "L4")
        for gid in (3, 15, 20, 23):  # health, finances, religion, fears: never inferred
            self.assertFalse(groups[gid]["ai_may_infer"], gid)
            self.assertTrue(all(not f["ai_may_infer"] for f in groups[gid]["fields"]), gid)
        self.assertFalse(fields["religious_affiliation"]["ai_may_infer"])
        self.assertEqual(groups[3]["default_level"], "L3")
        self.assertEqual(groups[15]["default_level"], "L3")
        self.assertIn("enthusiasm", fields["music"]["facets"])
        self.assertTrue(any("Never infer someone's religion" in n for n in groups[20]["notes"]))
        self.assertEqual(taxonomy()["intelligence_layers"],
                         ["descriptive", "contextual", "temporal", "predictive", "partnership"])


class AdultStageTests(unittest.TestCase):
    def test_six_adult_stages_cover_18_to_100_plus(self):
        stages = adult_stages()
        self.assertEqual([s["stage"] for s in stages], [3, 4, 5, 6, 7, 8])
        self.assertTrue(all(s["min_age"] >= 18 for s in stages))

    def test_every_focus_item_from_the_doc_is_covered_exactly(self):
        doc_stages = {s["stage"]: s for s in taxonomy()["life_stages"]}
        for s in adult_stages():
            doc = doc_stages[s["stage"]]
            self.assertEqual([f["item"] for f in s["focus"]], doc["focus"], s["title"])
            self.assertEqual(s["theme"], doc["theme"])
            self.assertEqual((s["min_age"], s["max_age"]), (doc["min_age"], doc["max_age"]))

    def test_focus_items_point_at_real_groups_and_fields(self):
        fields = {f["key"]: g["id"] for g in taxonomy()["groups"] for f in g["fields"]}
        for s in adult_stages():
            for f in s["focus"]:
                self.assertTrue(f["groups"] and all(1 <= g <= 30 for g in f["groups"]), f["item"])
                for key in f["fields"]:
                    self.assertIn(key, fields, f"{s['title']} / {f['item']}: unknown field {key}")
                    self.assertIn(fields[key], f["groups"], f"{f['item']}: {key} is in group {fields[key]}")
                if not f.get("only_if_user_raises"):
                    self.assertTrue(f["questions"], f"{s['title']} / {f['item']} needs at least one question")

    def test_sensitive_topics_are_flagged(self):
        level = {f["key"]: f["level"] for g in taxonomy()["groups"] for f in g["fields"]}
        for s in adult_stages():
            for f in s["focus"]:
                if any(level[k] in ("L3", "L4") for k in f["fields"]) and set(f["groups"]) & {3, 15}:
                    self.assertTrue(f.get("sensitive"), f"{s['title']} / {f['item']} touches health/money")

    def test_every_stage_has_a_persona(self):
        for s in adult_stages():
            for key in ("voice", "pace", "lean_into", "avoid", "motivation_style", "story_style"):
                self.assertTrue(s["persona"].get(key), f"{s['title']} persona.{key}")


if __name__ == "__main__":
    unittest.main()
