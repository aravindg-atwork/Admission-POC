"""P95 latency measurement - HANDOFF.md's own "Open" item: median is known
(~2-3s, in target), the tail is not. This runs the same curated question set
tools/eval_admissions.py already uses (ground-truthed, realistic phrasing)
against a live backend, records every individual response time - not just
the ones a human eye would flag as slow - and reports the actual
distribution (p50/p90/p95/p99), not an average that a few outliers can hide
inside.

Deliberately reuses eval_admissions.CASES rather than a new question set:
those questions are already the ones this project has decided represent
real usage, and a second, invented list would just be a second thing to
keep in sync with the corpus.

Usage:
    ADMIN_TOKEN=... .venv-backend/bin/python3 -u tools/measure_latency_p95.py
    ... --base http://159.69.210.30      # measure the live deployment
    ... --runs 2                          # repeat the whole set N times
"""

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402
from backend.storage import apikeys, faq, projects  # noqa: E402

from eval_admissions import CASES  # noqa: E402


def _ask(base, question, key, timeout=240):
    body = json.dumps({"question": question, "uiLanguage": "en"}).encode()
    req = urllib.request.Request(
        f"{base}/api/chat", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": key})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            json.loads(resp.read().decode())
        return time.time() - started, None
    except Exception as exc:  # noqa: BLE001 - a timeout/error IS a latency data point
        return time.time() - started, repr(exc)


def _percentile(sorted_values, p):
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (p / 100)
    f, c = int(k), min(int(k) + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=f"http://127.0.0.1:{config.PORT}")
    ap.add_argument("--runs", type=int, default=1,
                     help="repeat the whole question set this many times")
    ap.add_argument("--section", default=None)
    ap.add_argument("--keep-cache", action="store_true",
                     help="don't clear FAQ caches first - measures WARM latency instead of cold")
    args = ap.parse_args()

    if not args.keep_cache:
        for project in projects.list_projects():
            faq.clear(projects.faq_path(project["id"]))

    keys = [k for k in apikeys.list_keys(config.DEFAULT_PROJECT_ID) if k.get("active")]
    if not keys:
        print("no active key on the default project")
        return 1
    key = keys[0]["key"]

    cases = [c for c in CASES if not args.section or c["section"] == args.section.upper()]

    latencies = []
    errors = []
    print(f"Measuring against {args.base} - {len(cases)} questions x {args.runs} run(s) "
          f"= {len(cases) * args.runs} requests\n")

    n = 0
    for run in range(args.runs):
        for case in cases:
            n += 1
            elapsed, err = _ask(args.base, case["q"], key)
            latencies.append(elapsed)
            marker = "ERR" if err else "ok "
            print(f"  [{n:4}/{len(cases) * args.runs}] {marker} {elapsed:6.1f}s  "
                  f"[{case['section']}] Q{case['n']}: {case['q'][:50]}")
            if err:
                errors.append((case, err))

    latencies.sort()
    print("\n" + "=" * 70)
    print(f"N = {len(latencies)} requests, {len(errors)} errors/timeouts")
    print(f"  min    : {latencies[0]:6.1f}s")
    print(f"  p50    : {_percentile(latencies, 50):6.1f}s")
    print(f"  p90    : {_percentile(latencies, 90):6.1f}s")
    print(f"  p95    : {_percentile(latencies, 95):6.1f}s")
    print(f"  p99    : {_percentile(latencies, 99):6.1f}s")
    print(f"  max    : {latencies[-1]:6.1f}s")
    print(f"  mean   : {sum(latencies) / len(latencies):6.1f}s")

    slow = [l for l in latencies if l > 15]
    print(f"\n  >15s   : {len(slow)}/{len(latencies)} ({100 * len(slow) / len(latencies):.1f}%)")

    if errors:
        print(f"\nERRORS/TIMEOUTS ({len(errors)}):")
        for case, err in errors:
            print(f"  [{case['section']}] Q{case['n']}: {case['q'][:50]}  -> {err}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
