#!/usr/bin/env python3
"""Benchmark FIRST TOKEN and FIRST COHERENT CLAUSE on the working local Ollama.

Runs inside mini-ai-inference only. It is isolated and DOES NOT modify the
resident Mini service, database, provider model files, or user recordings.

  python -m scripts.benchmark_streaming_brain --mode friend --threads 4
"""
from __future__ import annotations
import argparse
import os
import statistics
import time
from services.voice_worker.streaming_lab import stream_reply


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("friend","mentor"), default="friend")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--turns", type=int, default=3)
    p.add_argument("--text", default="Hey Mini, what is one small thing I can do today to make progress on my project?")
    args = p.parse_args()
    if not 1 <= args.threads <= 8 or not 1 <= args.turns <= 8:
        p.error("Use 1–8 CPU threads and 1–8 turns. Run only while the Mini worker is idle.")
    os.environ["MINI_STREAM_LAB_THREADS"] = str(args.threads)
    print("Mini Reflex streaming BRAIN lab — Ollama only, NO streaming speech synthesis")
    print("Leave the current Mini worker untouched; run when no users are speaking.")
    outcomes=[]
    for i in range(args.turns):
        first_token=None
        first_clause=None
        total=None
        content=[]
        start=time.perf_counter()
        for event in stream_reply(args.text,mode=args.mode):
            now=time.perf_counter()-start
            if event["type"]=="token" and first_token is None: first_token=now
            if event["type"]=="clause":
                if first_clause is None: first_clause=now
                content.append(event["text"])
            if event["type"]=="done": total=now
        if not first_token or not first_clause or total is None:
            raise RuntimeError("Incomplete local streaming Ollama response")
        outcomes.append((first_token,first_clause,total))
        print(f"Turn {i+1}: first_token={first_token:.2f}s first_clause={first_clause:.2f}s full_text={total:.2f}s")
        print("Generated clauses:", " ".join(content)[:260])
    print(f"Median first token={statistics.median(x[0] for x in outcomes):.2f}s")
    print(f"Median first coherent clause={statistics.median(x[1] for x in outcomes):.2f}s")
    print(f"Median complete text={statistics.median(x[2] for x in outcomes):.2f}s")
    print("IMPORTANT: This is NOT speech-to-first-meaningful-audio latency.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
