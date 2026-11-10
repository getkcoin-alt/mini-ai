"""Queue, limits and quotas for live conversations (no models, no network)."""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.voice_worker import admission


class FloorTests(unittest.TestCase):
    def run_async(self, coro):
        return asyncio.run(coro)

    def test_first_come_first_served_with_positions(self):
        async def scenario():
            floor = admission.ConversationFloor()
            seen = {"b": [], "c": []}

            async def pos(name):
                async def report(p):
                    seen[name].append(p)
                return report

            self.assertTrue(await floor.acquire("a", lambda p: asyncio.sleep(0)))
            tb = asyncio.create_task(floor.acquire("b", await pos("b")))
            tc = asyncio.create_task(floor.acquire("c", await pos("c")))
            await asyncio.sleep(0.01)
            self.assertEqual(floor.holder, "a")
            self.assertEqual((seen["b"], seen["c"]), ([1], [2]))
            floor.release("a")
            self.assertTrue(await tb)
            await asyncio.sleep(0.01)
            self.assertEqual(floor.holder, "b")
            self.assertEqual(seen["c"], [2, 1])
            floor.release("b")
            self.assertTrue(await tc)
            self.assertEqual(floor.holder, "c")
        self.run_async(scenario())

    def test_full_queue_is_refused(self):
        async def scenario():
            floor = admission.ConversationFloor()
            noop = lambda p: asyncio.sleep(0)
            await floor.acquire("a", noop)
            waiters = [asyncio.create_task(floor.acquire(f"w{i}", noop, limit=2)) for i in range(2)]
            await asyncio.sleep(0.01)
            self.assertFalse(await floor.acquire("late", noop, limit=2))
            for w in waiters:
                w.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
            self.assertEqual(floor.waiting, 0)
        self.run_async(scenario())

    def test_cancelled_waiter_leaves_queue_and_others_move_up(self):
        async def scenario():
            floor = admission.ConversationFloor()
            noop = lambda p: asyncio.sleep(0)
            await floor.acquire("a", noop)
            tb = asyncio.create_task(floor.acquire("b", noop))
            tc = asyncio.create_task(floor.acquire("c", noop))
            await asyncio.sleep(0.01)
            tb.cancel()
            await asyncio.gather(tb, return_exceptions=True)
            floor.release("a")
            self.assertTrue(await tc)
            self.assertEqual(floor.holder, "c")
        self.run_async(scenario())

    def test_release_by_non_holder_is_ignored(self):
        floor = admission.ConversationFloor()
        floor.holder = "a"
        floor.release("b")
        self.assertEqual(floor.holder, "a")


class UsageTests(unittest.TestCase):
    def test_daily_usage_accumulates_and_resets_next_day(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"MINI_DAILY_SECONDS": "1800"}):
            usage = admission.DailyUsage(Path(tmp) / "u.sqlite3")
            day1 = 1_800_000_000
            usage.add("u1", 600, now=day1)
            usage.add("u1", 300, now=day1)
            usage.add("u2", 100, now=day1)
            self.assertEqual(usage.used("u1", now=day1), 900)
            self.assertEqual(usage.remaining("u1", now=day1), 900)
            self.assertEqual(usage.used("u1", now=day1 + 86400), 0)

    def test_today_uses_india_time_by_default(self):
        # 2026-11-09 20:00 UTC is already 10 Nov in India.
        ts = 1_794_254_400  # 2026-11-09T20:00:00Z
        self.assertEqual(admission.DailyUsage.today(ts), "2026-11-10")


class RateTests(unittest.TestCase):
    def test_sliding_window(self):
        rl = admission.RateLimiter()
        self.assertTrue(all(rl.allow("u", 3, 60, now=t) for t in (0, 1, 2)))
        self.assertFalse(rl.allow("u", 3, 60, now=3))
        self.assertTrue(rl.allow("u", 3, 60, now=61))

    def test_connection_counter(self):
        cc = admission.ConnectionCounter()
        self.assertTrue(cc.try_open("1.2.3.4", 2))
        self.assertTrue(cc.try_open("1.2.3.4", 2))
        self.assertFalse(cc.try_open("1.2.3.4", 2))
        cc.close("1.2.3.4")
        self.assertTrue(cc.try_open("1.2.3.4", 2))


if __name__ == "__main__":
    unittest.main()
