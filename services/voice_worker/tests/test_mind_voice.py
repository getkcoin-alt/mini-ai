"""Mind ↔ conversation: prompt, greeting, extraction safety and learning rules (no network)."""
import asyncio
import json
import sys
import types
import unittest
import unittest.mock
from datetime import datetime, timezone

try:
    import httpx  # noqa: F401
except ImportError:
    sys.modules["httpx"] = types.ModuleType("httpx")

from services.voice_worker import mind

PKG = {
    "known": True, "name": "Arjun", "age": 31, "conversations": 3,
    "stage": {"stage": 4, "title": "Early adulthood", "theme": "Building foundations",
              "persona": {"voice": "Warm best friend.", "pace": "Relaxed.", "avoid": ["pressuring about marriage"],
                          "motivation_style": "Break plans into one next step.", "story_style": "Builder stories."}},
    "facts": [{"what": "Job title", "value": "Founder"}],
    "people": [{"name": "Bruno", "relation": "dog"}],
    "goals": [{"title": "Launch the startup"}],
    "recent_days": [{"title": "Pitched to an investor", "emotion": "nervous"}],
    "insights": [{"note": "Startup may compete with family time"}],
    "avoid_topics": ["My ex"],
    "follow_ups": [{"id": "e1", "ask": "How did the investor pitch go?"}],
    "next_question": {"focus_id": "s4_02", "ask": "Ever thought about starting something of your own?"},
}


class PromptTests(unittest.TestCase):
    def test_prompt_carries_the_mind(self):
        p = mind.render_prompt(PKG)
        for needle in ("Arjun", "age 31", "Early adulthood", "Warm best friend", "Founder", "Bruno (dog)",
                       "Launch the startup", "Pitched to an investor", "NEVER bring up: My ex",
                       "uncertain, never state them as facts", "Ever thought about starting"):
            self.assertIn(needle, p)
        self.assertLess(len(p), 2200, "keep the block small for a 3B CPU model")

    def test_unknown_person_gets_no_block(self):
        self.assertEqual(mind.render_prompt(None), "")
        self.assertEqual(mind.render_prompt({"known": False}), "")

    def test_mini_speaks_first_with_the_follow_up(self):
        cue = mind.opening_instruction(PKG)
        self.assertIn("Arjun", cue)
        self.assertIn("How did the investor pitch go?", cue)
        first = mind.opening_instruction({"known": True, "name": "Meera", "conversations": 0})
        self.assertIn("excited to get to know them", first)


class ExtractionTests(unittest.TestCase):
    def test_strict_parsing_drops_unsafe_items(self):
        raw = json.dumps({
            "summary": "Talked about the startup", "mood": "excited",
            "facts": [
                {"category": "work", "attribute": "Job title", "value": "Founder", "explicit": True},
                {"group": 17, "attribute": "Music", "value": "loves jazz", "explicit": False},
                {"group": 3, "attribute": "Current medications", "value": "x", "explicit": True},
                {"group": 20, "attribute": "Religious affiliation", "value": "y", "explicit": True},
                {"group": 27, "attribute": "Security", "value": "my password is hunter2", "explicit": True},
                {"group": 99, "attribute": "x", "value": "y"},
                "garbage",
            ],
            "events": [{"title": "Exam on Friday", "when": "this_week", "emotion": "anxious",
                        "follow_up_question": "How did the exam go?"},
                       {"title": "Moved cities as a kid", "when": "past"}],
            "people": [{"name": "Bruno", "relation": "Dog"}, {"name": "Mini", "relation": "AI"}],
            "goals": [{"title": "Launch the startup", "horizon": "short"}, {"title": "x", "horizon": "weird"}],
        })
        out = mind.parse_extraction(raw)
        self.assertEqual([f["attribute"] for f in out["facts"]], ["Job title", "Music"])
        self.assertTrue(out["facts"][0]["explicit"])
        self.assertFalse(out["facts"][1]["explicit"])
        self.assertEqual([e["title"] for e in out["events"]], ["Exam on Friday"])
        self.assertEqual(out["people"], [{"name": "Bruno", "relation": "dog"}])
        self.assertEqual(out["goals"][1]["horizon"], "medium")

    def test_time_words_decide_when_events_happen(self):
        cases = {"second meeting next week": "this_week", "half marathon in March": "later", "exam tomorrow": "tomorrow",
                 "fight with mom yesterday": "yesterday", "moved cities when I was ten": "past", "lunch with Priya": "today",
                 "trip on Friday": "this_week"}
        for words, want in cases.items():
            self.assertEqual(mind.when_from_words(words), want, words)
        out = mind.parse_extraction(json.dumps({"events": [
            {"title": "Second meeting", "said_when": "next week", "when": "today", "follow_up_question": "How did it go?"}]}))
        self.assertEqual(out["events"][0]["when"], "this_week")

    def test_event_timing_comes_from_what_the_person_said(self):
        history = [{"role": "user", "content": "It went well, they want a second meeting next week. Nervous!"},
                   {"role": "user", "content": "I want to run my first half marathon in March."}]
        out = {"events": [{"title": "Second meeting", "when": "today"}, {"title": "Half marathon", "when": "today"}]}
        got = {e["title"]: e["when"] for e in mind.ground_event_times(out, history)["events"]}
        self.assertEqual(got, {"Second meeting": "this_week", "Half marathon": "later"})

    def test_bad_json_learns_nothing(self):
        self.assertEqual(mind.parse_extraction("not json")["facts"], [])

    def test_transcript_excludes_the_opening_cue_and_is_bounded(self):
        hist = [{"role": "user", "content": "[The conversation just started. Speak first…]"},
                {"role": "assistant", "content": "Hi!"}] + [{"role": "user", "content": "x" * 500}] * 20
        msgs = mind.build_extraction_messages(hist)
        self.assertNotIn("conversation just started", msgs[1]["content"])
        self.assertLessEqual(len(msgs[1]["content"]), 4500)
        self.assertIn("how_mini_should_help", msgs[0]["content"])

    def test_field_matching_uses_the_taxonomy(self):
        self.assertEqual(mind.match_field(14, "Job title")["key"], "job_title")
        self.assertEqual(mind.match_field(18, "favourite movies")["key"], "favourite_movies")
        self.assertIsNone(mind.match_field(17, "zzz qqq"))


class FakeSupabase:
    def __init__(self, consent=True):
        self.calls = []
        self.consent = consent

    async def req(self, _client, method, path, **kw):
        self.calls.append((method, path.split("?")[0], kw.get("json")))
        if path.startswith("mind_persons?select"):
            return [{"conversations": 2, "adopted_at": None}]
        if path.startswith("mind_consents"):
            return [{"scope": "learn_from_conversations"}] if self.consent else []
        if path.startswith("mind_sources"):
            return [{"id": "src-1"}]
        if path.startswith("mind_facts?select"):
            return []
        return None


class _NullClient:
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class LearningTests(unittest.TestCase):
    def run_learn(self, consent=True, auto_accept=True, people=None):
        import os
        os.environ["MINI_MIND_AUTO_ACCEPT_STATED"] = "1" if auto_accept else ""
        fake = FakeSupabase(consent)
        client = mind.MindClient("token-123", "user-1")
        client.enabled = True
        client._req = fake.req
        mind.httpx.AsyncClient = _NullClient
        learned = mind.parse_extraction(json.dumps({
            "summary": "s", "mood": "happy",
            "facts": [{"group": 14, "attribute": "Job title", "value": "Founder", "explicit": True},
                      {"group": 17, "attribute": "Music", "value": "jazz", "explicit": False}],
            "events": [{"title": "Exam on Friday", "when": "this_week", "follow_up_question": "How did the exam go?"}],
            "people": people or [{"name": "Bruno", "relation": "dog"}], "goals": [{"title": "Run a marathon", "horizon": "long"}]}))
        now = datetime.now(timezone.utc)
        counts = asyncio.run(client.learn(learned, PKG, now, now, turns=3))
        return counts, fake.calls

    def test_stated_facts_are_kept_and_guesses_wait_for_keep(self):
        counts, calls = self.run_learn()
        self.assertEqual((counts["facts"], counts["pending"], counts["events"], counts["people"], counts["goals"]), (1, 1, 1, 1, 1))
        facts = [j for m, p, j in calls if m == "POST" and p == "mind_facts"]
        stated = next(f for f in facts if f["field_key"] == "job_title")
        guess = next(f for f in facts if f["field_key"] == "music")
        self.assertEqual((stated["source"], stated["consent_status"], stated["source_id"]), ("user_stated", "granted", "src-1"))
        self.assertEqual((guess["source"], guess["consent_status"], guess["verification_status"]),
                         ("ai_observed", "pending", "unverified_inference"))
        event = next(j for m, p, j in calls if p == "mind_life_events" and m == "POST")
        self.assertEqual(event["follow_up_question"], "How did the exam go?")
        self.assertIn("follow_up_at", event)
        # follow-up from the package is marked done, the question is recorded, the person counted
        self.assertIn(("PATCH", "mind_life_events", {"followed_up_at": unittest.mock.ANY}), calls)
        self.assertTrue(any(p == "mind_questions_asked" for _m, p, _j in calls))
        person = next(j for m, p, j in calls if m == "PATCH" and p == "mind_persons")
        self.assertEqual(person["conversations"], 3)
        self.assertIn("adopted_at", person)
        # the transcript is never sent anywhere
        self.assertFalse(any("USER:" in json.dumps(j or {}) for _m, _p, j in calls))

    def test_by_default_every_learned_fact_waits_for_keep(self):
        counts, calls = self.run_learn(auto_accept=False)
        facts = [j for m, p, j in calls if m == "POST" and p == "mind_facts"]
        self.assertTrue(facts and all(f["consent_status"] == "pending" and f["source"] == "ai_observed" for f in facts))

    def test_the_person_is_not_listed_as_someone_in_their_life(self):
        _counts, calls = self.run_learn(people=[{"name": "Arjun", "relation": "investor"}, {"name": "Priya", "relation": "sister"}])
        names = [j["name"] for m, p, j in calls if p == "mind_people"]
        self.assertEqual(names, ["Priya"])

    def test_without_learning_consent_nothing_learned_is_stored(self):
        counts, calls = self.run_learn(consent=False)
        self.assertEqual(sum(counts.values()), 0)
        self.assertFalse(any(m == "POST" and p in ("mind_facts", "mind_sources", "mind_life_events", "mind_people", "mind_goals")
                             for m, p, _j in calls))


if __name__ == "__main__":
    import unittest.mock  # noqa: F401
    unittest.main()
