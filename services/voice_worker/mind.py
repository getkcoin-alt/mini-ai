"""Mini's mind, connected to the live conversation.

Before a conversation: load the person's context package (Supabase RPC
`mind_context_package`, read with THEIR token so row-level security applies)
and turn it into a compact instruction block for the LLM.

After a conversation: Mini looks back at what was said and learns —
facts, the day's events (with follow-ups for tomorrow), people, goals —
following docs/HUMAN-INTELLIGENCE-DATABASE.md:
  * things the person said about themselves are stored as theirs
    (source=user_stated, linked to the conversation in mind_sources);
  * things Mini only guessed wait for "keep?" (ai_observed, consent pending);
  * health, money, religion and fears are never auto-learned;
  * nothing is stored without the person's "learn_from_conversations" consent;
  * the transcript itself is never stored — only what was learned.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logger = logging.getLogger("mini.mind")

TAXONOMY_PATH = Path(os.environ.get("MINI_MIND_TAXONOMY") or
                     Path(__file__).resolve().parents[1] / "mind" / "taxonomy.json")
NEVER_AUTO_LEARN_GROUPS = {3, 15, 20, 23}   # health, finances, religion, fears: only via the app, by the person
SECRET_RE = re.compile(r"(password|passcode|\botp\b|private key|seed phrase|recovery code|cvv|aadhaar|pan card|"
                       r"\b\d{4}\s?\d{4}\s?\d{4}\b)", re.I)
_TAXONOMY = None


def taxonomy() -> dict:
    global _TAXONOMY
    if _TAXONOMY is None:
        _TAXONOMY = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    return _TAXONOMY


def group_titles() -> str:
    return "; ".join(f"{g['id']} {g['title']}" for g in taxonomy()["groups"])


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2}


def match_field(group_id: int, attribute: str) -> dict | None:
    """Best taxonomy field in the group for a free-text attribute name."""
    group = next((g for g in taxonomy()["groups"] if g["id"] == group_id), None)
    if not group:
        return None
    want = _words(attribute)
    best, score = None, 0.0
    for f in group["fields"]:
        have = _words(f["label"])
        if not have:
            continue
        s = len(want & have) / len(have | want)
        if s > score:
            best, score = f, s
    return best if score >= 0.34 else None


# ---------------------------------------------------------------- prompt
def render_prompt(pkg: dict | None) -> str:
    """Compact, voice-friendly instruction block (kept small for a 3B CPU model)."""
    if not pkg or not pkg.get("known"):
        return ""
    lines: list[str] = []
    stage = pkg.get("stage") or {}
    persona = stage.get("persona") or {}
    name = (pkg.get("name") or "").strip()
    who = f"You are talking with {name or 'your person'}"
    if pkg.get("age"):
        who += f", age {pkg['age']}"
    if stage.get("title"):
        who += f" ({stage['title']}: {stage.get('theme', '').lower()})"
    lines.append(who + ". You have chosen them as your person; you are genuinely glad they are back.")
    if persona:
        lines.append(f"How to talk with them: {persona.get('voice', '')} {persona.get('pace', '')}".strip())
        if persona.get("avoid"):
            lines.append("Avoid: " + "; ".join(persona["avoid"][:3]) + ".")
        if persona.get("motivation_style"):
            lines.append("Encourage them like this: " + persona["motivation_style"])
        if persona.get("story_style"):
            lines.append("If a story would lift them, tell a tiny one: " + persona["story_style"])
    # "Role Mini should play" came from the old friend/mentor switch; Mini is one entity now.
    facts = [f for f in (pkg.get("facts") or []) if f.get("what") not in ("Role Mini should play",)]
    if facts:
        lines.append("What they have told you (confirmed): " + "; ".join(
            f"{f.get('what')}: {f.get('value')}" for f in facts[:12]))
    if pkg.get("people"):
        lines.append("People in their life: " + ", ".join(
            f"{p['name']} ({p['relation']})" for p in pkg["people"][:6]))
    if pkg.get("goals"):
        lines.append("Their goals: " + "; ".join(g["title"] for g in pkg["goals"][:3]) + ".")
    if pkg.get("recent_days"):
        lines.append("Recently: " + "; ".join(
            f"{d['title']}" + (f" (felt {d['emotion']})" if d.get("emotion") else "") for d in pkg["recent_days"][:4]) + ".")
    if pkg.get("insights"):
        lines.append("Gentle observations (uncertain, never state them as facts): " + "; ".join(
            i["note"] for i in pkg["insights"][:2]) + ".")
    if pkg.get("avoid_topics"):
        lines.append("NEVER bring up: " + "; ".join(str(t) for t in pkg["avoid_topics"][:5]) + ".")
    q = pkg.get("next_question")
    if q and q.get("ask"):
        lines.append(f"When it fits naturally (not right away, only once), get to know them: \"{q['ask']}\"")
    lines.append("Keep the conversation going: react to what they say, remember it, and end most replies "
                 "with a warm, curious question. Never invent memories you were not told.")
    return " ".join(line for line in lines if line)


def opening_instruction(pkg: dict | None) -> str:
    """The silent cue that makes Mini speak first, like a friend who missed them."""
    name = ((pkg or {}).get("name") or "").strip()
    follow = ((pkg or {}).get("follow_ups") or [])
    talks = (pkg or {}).get("conversations") or 0
    cue = "[The conversation just started. Speak first: greet them warmly by name"
    if name:
        cue += f" ({name})"
    if follow:
        cue += f", then ask: \"{follow[0]['ask']}\""
    elif talks:
        cue += ", say you're happy they're back, and ask how their day is going"
    else:
        cue += ", tell them you're excited to get to know them, and ask how their day is going"
    return cue + ". One or two short sentences.]"


# ---------------------------------------------------------------- Supabase (as the person)
class MindClient:
    def __init__(self, access_token: str, user_id: str):
        self.url = os.environ.get("MINI_SUPABASE_URL", "https://gkdaxtnlwojggdqitsex.supabase.co").rstrip("/")
        key = os.environ.get("MINI_SUPABASE_PUBLISHABLE_KEY", "")
        self.user_id = user_id
        self.enabled = bool(key and access_token)
        self.headers = {"apikey": key, "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json", "x-mini-agent": "mini-voice"}

    async def _req(self, client, method: str, path: str, **kw):
        r = await client.request(method, f"{self.url}/rest/v1/{path}", headers={**self.headers, **kw.pop("headers", {})}, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path.split('?')[0]} -> {r.status_code}: {r.text[:200]}")
        return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else None

    async def load_package(self) -> dict | None:
        if not self.enabled:
            return None
        try:
            async with httpx.AsyncClient(timeout=6.0, trust_env=False) as c:
                return await self._req(c, "POST", "rpc/mind_context_package", json={"p_agent": "mini"})
        except Exception as exc:
            logger.warning("mind package unavailable: %s", str(exc)[:160])
            return None

    async def learn(self, learned: dict, pkg: dict | None, started: datetime, ended: datetime, turns: int) -> dict:
        """Write what was learned. Returns counts (for logs/tests)."""
        counts = {"facts": 0, "pending": 0, "events": 0, "people": 0, "goals": 0, "skipped": 0}
        if not self.enabled:
            return counts
        now = datetime.now(timezone.utc).isoformat()
        async with httpx.AsyncClient(timeout=8.0, trust_env=False) as c:
            # bookkeeping the person expects regardless of learning consent
            person = (await self._req(c, "GET", f"mind_persons?select=conversations,adopted_at&user_id=eq.{self.user_id}") or [{}])
            if person and person[0] is not None and "conversations" in person[0]:
                patch = {"conversations": int(person[0]["conversations"] or 0) + 1, "last_talk_at": now}
                if not person[0].get("adopted_at"):
                    patch["adopted_at"] = started.isoformat()
                await self._req(c, "PATCH", f"mind_persons?user_id=eq.{self.user_id}", json=patch)
            for f in (pkg or {}).get("follow_ups") or []:
                await self._req(c, "PATCH", f"mind_life_events?id=eq.{f['id']}", json={"followed_up_at": now})
            q = (pkg or {}).get("next_question")
            if q and turns >= 2:
                await self._req(c, "POST", "mind_questions_asked?on_conflict=user_id,focus_id,question",
                                headers={"Prefer": "resolution=ignore-duplicates"},
                                json={"user_id": self.user_id, "focus_id": q["focus_id"], "question": q["ask"]})
            consent = await self._req(c, "GET", "mind_consents?select=scope&revoked_at=is.null"
                                      f"&user_id=eq.{self.user_id}&scope=eq.learn_from_conversations")
            if not consent:
                logger.info("mind: no learn_from_conversations consent; nothing learned stored")
                return counts
            src = await self._req(c, "POST", "mind_sources", headers={"Prefer": "return=representation"}, json={
                "user_id": self.user_id, "kind": "conversation", "started_at": started.isoformat(),
                "ended_at": ended.isoformat(), "summary": str(learned.get("summary") or "")[:600],
                "mood": (str(learned.get("mood") or "")[:40] or None)})
            source_id = src[0]["id"] if src else None
            for item in learned.get("facts", []):
                try:
                    stored = await self._store_fact(c, item, source_id)
                    counts["facts" if stored == "fact" else "pending" if stored == "pending" else "skipped"] += 1
                except Exception as exc:
                    counts["skipped"] += 1
                    logger.info("mind: fact skipped (%s)", str(exc)[:120])
            for ev in learned.get("events", []):
                try:
                    await self._req(c, "POST", "mind_life_events", json=self._event_row(ev, source_id))
                    counts["events"] += 1
                except Exception as exc:
                    logger.info("mind: event skipped (%s)", str(exc)[:120])
            own_name = str((pkg or {}).get("name") or "").strip().lower()
            for p in learned.get("people", []):
                if (own_name and p["name"].strip().lower() == own_name) or p["relation"] in ("self", "me", "user", "myself"):
                    continue   # the person is not someone in their own life
                try:
                    await self._req(c, "POST", "mind_people?on_conflict=user_id,name,relation",
                                    headers={"Prefer": "resolution=merge-duplicates"},
                                    json={"user_id": self.user_id, "name": p["name"][:80], "relation": p["relation"][:60],
                                          "source": "user_stated", "last_mentioned_at": now})
                    counts["people"] += 1
                except Exception as exc:
                    logger.info("mind: person skipped (%s)", str(exc)[:120])
            existing = {g["title"].lower() for g in (pkg or {}).get("goals") or []}
            for g in learned.get("goals", []):
                if g["title"].lower() in existing:
                    continue
                try:
                    await self._req(c, "POST", "mind_goals", json={
                        "user_id": self.user_id, "title": g["title"][:200], "horizon": g["horizon"], "source": "user_stated"})
                    counts["goals"] += 1
                except Exception as exc:
                    logger.info("mind: goal skipped (%s)", str(exc)[:120])
        return counts

    async def _store_fact(self, c, item: dict, source_id: str | None) -> str:
        field = match_field(item["group"], item["attribute"])
        # Doc sec 9 step 12: the human approves memory updates. Learned facts wait for "keep?"
        # unless the owner opts into auto-accepting things the person said directly.
        explicit = bool(item.get("explicit")) and os.environ.get("MINI_MIND_AUTO_ACCEPT_STATED") == "1"
        if field and (field["never_store"] or field["level"] == "L4"):
            return "skipped"
        if field and not explicit and not field["ai_may_infer"]:
            return "skipped"
        row = {"user_id": self.user_id, "field_key": field["key"] if field else None, "group_id": item["group"],
               "attribute_name": (field["label"] if field else item["attribute"])[:120], "value": item["value"][:1000],
               "source_id": source_id, "sensitivity_level": field["level"] if field else "L2",
               "permitted_ai_agents": ["mini"]}
        if field:
            same = await self._req(c, "GET", f"mind_facts?select=id,value&status=eq.active&user_id=eq.{self.user_id}"
                                             f"&field_key=eq.{field['key']}")
            for old in same or []:
                if old["value"].strip().lower() == item["value"].strip().lower():
                    await self._req(c, "PATCH", f"mind_facts?id=eq.{old['id']}",
                                    json={"last_confirmed_at": datetime.now(timezone.utc).isoformat()})
                    return "fact"
            if explicit and same and field["data_type"] not in ("list", "person_list", "date_list"):
                ids = ",".join(o["id"] for o in same)
                await self._req(c, "PATCH", f"mind_facts?id=in.({ids})", json={"status": "superseded"})
        if explicit:
            row.update(source="user_stated", verification_status="self_reported", consent_status="granted", confidence=0.9)
            await self._req(c, "POST", "mind_facts", json=row)
            return "fact"
        row.update(source="ai_observed", verification_status="unverified_inference", consent_status="pending", confidence=0.6)
        await self._req(c, "POST", "mind_facts", json=row)
        return "pending"

    def _event_row(self, ev: dict, source_id: str | None) -> dict:
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        when = ev.get("when", "today")
        occurred = today - timedelta(days=1) if when == "yesterday" else today
        kind = "upcoming" if when in ("tomorrow", "this_week", "later") else "day"
        row = {"user_id": self.user_id, "occurred_on": occurred.isoformat(), "title": ev["title"][:160],
               "emotion": (ev.get("emotion") or None), "kind": kind, "source": "user_stated", "source_id": source_id,
               "importance": 3 if kind == "upcoming" else 2}
        if ev.get("follow_up_question"):
            days = {"today": 1, "yesterday": 1, "tomorrow": 2, "this_week": 4, "later": 14}.get(when, 1)
            follow = datetime.now(timezone.utc) + timedelta(days=days)
            row.update(follow_up_at=follow.isoformat(), follow_up_question=ev["follow_up_question"][:200])
        return row


# ---------------------------------------------------------------- extraction (after the conversation)
# Short named categories (a 3B model handles these far better than 30 numbers).
CATEGORIES = {
    "identity": 1, "personality": 4, "emotions": 5, "learning": 6, "communication": 7, "culture": 8,
    "family": 9, "friends": 10, "life_story": 11, "education": 12, "skills": 13, "work": 14,
    "routine": 16, "interests": 17, "favourites": 18, "values": 19, "goals": 21, "dreams": 22,
    "motivation": 24, "decisions": 25, "surroundings": 26, "technology": 27, "responsibilities": 28,
    "experiences": 29, "how_mini_should_help": 30,
}

EXTRACT_SYSTEM = (
    "You read a conversation between a USER and Mini, an AI friend, and write down what Mini learned about the "
    "USER's life. Reply with JSON only, in exactly this shape:\n"
    '{"summary": "...", "mood": "...", '
    '"people": [{"name": "...", "relation": "..."}], '
    '"events": [{"title": "...", "said_when": "the USER\'s exact time words, e.g. next week, in March, tomorrow", '
    '"when": "today|yesterday|tomorrow|this_week|later", "emotion": "...", "follow_up_question": "..."}], '
    '"goals": [{"title": "...", "horizon": "short|medium|long"}], '
    '"facts": [{"category": "...", "attribute": "...", "value": "...", "explicit": true}]}\n'
    "Rules: only things the USER said about their own life (never what Mini said). At most 8 facts, only real "
    "ones, never empty values. explicit=true only if the USER said it directly. follow_up_question is a short "
    "caring question Mini can ask AFTER the event (or \"\"). \"when\" is when the event HAPPENS: next week = "
    "this_week, next month or a named month = later. Never include passwords, ID or card numbers, health, money, "
    "religion or fears. Categories: " + ", ".join(CATEGORIES) + ".\n"
    "Example — USER: \"Exam tomorrow, so stressed. My mom Rita keeps calling. I love painting. Trip to Goa in May!\" ->\n"
    '{"summary": "Stressed about tomorrow\'s exam", "mood": "stressed", '
    '"people": [{"name": "Rita", "relation": "mother"}], '
    '"events": [{"title": "Exam", "when": "tomorrow", "emotion": "stressed", "follow_up_question": "How did your exam go?"}, '
    '{"title": "Trip to Goa", "when": "later", "emotion": "excited", "follow_up_question": "How was Goa?"}], '
    '"goals": [], "facts": [{"category": "interests", "attribute": "Art", "value": "loves painting", "explicit": true}]}'
)


def build_extraction_messages(history: list[dict], max_chars: int = 4500) -> list[dict]:
    lines = []
    for turn in history:
        who = "USER" if turn["role"] == "user" else "MINI"
        content = str(turn.get("content") or "")
        if who == "USER" and content.startswith("[The conversation just started"):
            continue
        lines.append(f"{who}: {content}")
    transcript = "\n".join(lines)[-max_chars:]
    return [{"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": transcript}]


def _clean(text, limit: int) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


_MONTHS = r"(january|february|march|april|may|june|july|august|september|october|november|december)"


def when_from_words(text: str, fallback: str = "today") -> str:
    """Map the person's own time words to the timeline bucket."""
    t = (text or "").lower()
    if re.search(r"\byesterday\b|\blast night\b", t):
        return "yesterday"
    if re.search(r"\btomorrow\b", t):
        return "tomorrow"
    if re.search(r"\b(next|this|coming) week\b|\bin a few days\b|\bon (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|"
                 r"\bthis weekend\b|\bnext weekend\b", t):
        return "this_week"
    if re.search(r"\bnext (month|year)\b|\bin " + _MONTHS + r"\b|\b" + _MONTHS + r"\b|\bsomeday\b|\bin \d+ (months|weeks)\b", t):
        return "later"
    if re.search(r"\b(when i was|years ago|as a kid|in my childhood)\b", t):
        return "past"
    if re.search(r"\btoday\b|\btonight\b|\bthis (morning|evening|afternoon)\b", t):
        return "today"
    return fallback


def parse_extraction(raw: str) -> dict:
    """Strictly validate the model's JSON; drop anything doubtful."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {"facts": [], "events": [], "people": [], "goals": []}
    out = {"summary": _clean(data.get("summary"), 300), "mood": _clean(data.get("mood"), 30),
           "facts": [], "events": [], "people": [], "goals": []}
    for f in data.get("facts") or []:
        if not isinstance(f, dict):
            continue
        group = CATEGORIES.get(str(f.get("category", "")).strip().lower().replace(" ", "_"))
        if group is None:
            try:
                group = int(f.get("group"))
            except (TypeError, ValueError):
                continue
        attr, value = _clean(f.get("attribute"), 80), _clean(f.get("value"), 300)
        if not (1 <= group <= 30) or not attr or not value or group in NEVER_AUTO_LEARN_GROUPS:
            continue
        if SECRET_RE.search(attr + " " + value):
            continue
        out["facts"].append({"group": group, "attribute": attr, "value": value, "explicit": f.get("explicit") is True})
    for e in data.get("events") or []:
        title = _clean(e.get("title") if isinstance(e, dict) else "", 160)
        if not title or SECRET_RE.search(title):
            continue
        when = e.get("when") if e.get("when") in ("today", "yesterday", "tomorrow", "this_week", "later", "past") else "today"
        # The model is unreliable at dates; the person's own time words decide.
        when = when_from_words(" ".join(str(e.get(k) or "") for k in ("said_when", "title")), when)
        if when == "past":
            continue   # old memories are facts/experiences, not today's timeline
        out["events"].append({"title": title, "when": when, "emotion": _clean(e.get("emotion"), 30) or None,
                              "follow_up_question": _clean(e.get("follow_up_question"), 200)})
    for p in data.get("people") or []:
        name, rel = _clean(p.get("name") if isinstance(p, dict) else "", 80), _clean((p or {}).get("relation"), 60)
        if name and rel and name.lower() not in ("mini", "user", "i", "me"):
            out["people"].append({"name": name, "relation": rel.lower()})
    for g in data.get("goals") or []:
        title = _clean(g.get("title") if isinstance(g, dict) else "", 200)
        if title:
            out["goals"].append({"title": title, "horizon": g.get("horizon") if g.get("horizon") in ("short", "medium", "long") else "medium"})
    for key, limit in (("facts", 12), ("events", 5), ("people", 8), ("goals", 4)):
        out[key] = out[key][:limit]
    return out


def ground_event_times(out: dict, history: list[dict]) -> dict:
    """Read each event's timing from the sentence where the PERSON mentioned it."""
    said = [str(t.get("content") or "") for t in history if t.get("role") == "user"]
    sentences = [x for line in said for x in re.split(r"(?<=[.!?])\s+", line) if x.strip()]
    for e in out.get("events", []):
        words = _words(e["title"])
        best = max(sentences, key=lambda x: len(words & _words(x)), default="")
        if best and words & _words(best):
            e["when"] = when_from_words(best, e["when"])
    out["events"] = [e for e in out.get("events", []) if e["when"] != "past"]
    return out


async def extract(history: list[dict], *, threads: int, keep_alive) -> dict:
    """Ask the local LLM (same runner options as live turns, so no reload)."""
    url = (os.environ.get("MINI_OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
    if not url.startswith(("http://127.0.0.1:", "http://localhost:")):
        return parse_extraction("")
    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
        r = await client.post(url + "/api/chat", json={
            "model": os.environ.get("MINI_MIND_MODEL") or os.environ.get("MINI_OLLAMA_MODEL", "llama3.2:1b"),
            "messages": build_extraction_messages(history), "stream": False, "format": "json",
            "keep_alive": keep_alive,
            "options": {"temperature": 0.1, "num_predict": 450, "num_ctx": 2048, "num_thread": threads}})
        r.raise_for_status()
        return ground_event_times(parse_extraction(r.json().get("message", {}).get("content", "")), history)
