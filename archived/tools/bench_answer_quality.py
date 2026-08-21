"""Answer-quality benchmark against figures verified in the prospectus PDFs.

Every existing tool/ script asserts on `source` - which path answered - and
none of them check whether the FIGURE was right. That gap is why a Ph.D. fee
of Rs.30,310 (its reservation fee, sold as its unreserved one) and a
B.V.Sc. figure served under a Ph.D. heading both shipped while the suite
stayed green.

Each case therefore carries two lists:

  expect   - strings that MUST appear. The right answer.
  forbid   - strings that must NOT appear. Almost always another
             programme's figure for the same question, which is exactly how
             cross-programme contamination shows up: fluent, plausible, and
             wrong. A case passes only if it satisfies both.

Ground truth was read out of the 2026-27 PDFs directly (see the page
references beside each case), not from a previous answer - checking the
assistant against its own earlier output would only prove it is consistent,
not that it is correct.

Usage:
    ADMIN_TOKEN=... .venv-backend/bin/python3 tools/bench_answer_quality.py
    ... --model meta/llama-3.1-8b-instruct     # override the answer model
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402
from backend.storage import apikeys  # noqa: E402

# 127.0.0.1, not localhost - see config.py's OLLAMA_URL comment: urllib pays
# a ~2s IPv6-then-IPv4 tax per request on this Windows host that curl/browsers
# don't, on every one of this suite's requests.
BASE = f"http://127.0.0.1:{config.PORT}"

# (project, question, expect, forbid)
CASES = [
    # Questions sent on the DEFAULT key name their programme. The default
    # widget serves all three, so an unqualified "what is the fee" is
    # genuinely ambiguous and correctly answered with a clarification - the
    # first version of this file scored those as failures and made a working
    # guard look like a quality problem.

    # --- application fee: identical across programmes (BVSc p.16, BFSc p.18, BTech p.16)
    ("bvsc", "what is the application fee", ["1000", "700"], []),
    ("bfsc", "what is the application fee", ["1000", "700"], []),
    ("btech-dairy", "what is the application fee", ["1000", "700"], []),

    # --- admission fee: DIFFERENT per programme. The contamination trap.
    ("bvsc", "what is the admission fee", ["62635", "62,635"], ["40610", "40,610"]),
    ("bfsc", "what is the admission fee", ["40610", "40,610"], ["62635", "62,635"]),
    ("btech-dairy", "what is the admission fee", ["40610", "40,610"], ["62635", "62,635"]),

    # --- eligibility percentage (BVSc p.4, BFSc p.10, BTech p.5)
    ("bvsc", "what is the minimum percentage needed for unreserved category", ["50"], []),
    ("bfsc", "what is the minimum percentage needed for unreserved category", ["50"], []),
    ("btech-dairy", "what is the minimum percentage needed for unreserved category", ["50"], []),

    # --- subject stream differs: BTech needs Mathematics, BVSc/BFSc need Biology
    ("btech-dairy", "which subjects do I need in 12th", ["Mathematics"], ["Biology"]),
    ("bvsc", "which subjects do I need in 12th", ["Biology"], ["Mathematics"]),

    # --- routed from the default widget to another programme: the redirect path
    ("default", "what is the admission fee for btech dairy", ["40610", "40,610"], ["62635", "62,635"]),
    ("default", "what is the admission fee for bfsc", ["40610", "40,610"], ["62635", "62,635"]),

    # --- must refuse to invent rather than guess
    ("default", "what is the fee for the MBA programme", [], ["62635", "40610"]),
]


def _key_for(project_id):
    keys = [k for k in apikeys.list_keys(project_id) if k.get("active")]
    return keys[0]["key"] if keys else None


def _ask(question, key, timeout=300):
    body = json.dumps({"question": question, "uiLanguage": "en"}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/chat", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": key})
    started = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode()), time.time() - started


# Devanagari digits fold to ASCII before comparison. Mistral answers Indic
# questions using Devanagari NUMERALS - "किमान ५०% गुण आवश्यक आहेत" - which
# is arguably better for the reader, but a check looking for "50" scores a
# perfectly correct answer as a failure. That happened on the first run and
# briefly looked like a model problem.
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def _norm(text):
    return re.sub(r"[,\s]", "", (text or "").translate(_DEVANAGARI_DIGITS)).lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="override NVIDIA_MODEL for this run")
    args = ap.parse_args()
    if args.model:
        config.NVIDIA_MODEL = args.model
        print(f"NOTE: --model only affects THIS process; the running backend "
              f"still uses its own config. Restart the backend with "
              f"NVIDIA_MODEL={args.model} to benchmark it end to end.\n")

    passed = failed = 0
    total_time = 0.0
    failures = []

    for project_id, question, expect, forbid in CASES:
        key = _key_for(project_id)
        if not key:
            print(f"  SKIP  {project_id}: no active key")
            continue
        try:
            data, elapsed = _ask(question, key)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            failures.append((project_id, question, f"request failed: {exc!r}"))
            print(f"  FAIL  [{project_id:12}] {question[:44]:46} request failed")
            continue

        total_time += elapsed
        answer = data.get("answerText") or ""
        flat = _norm(answer)
        missing = [e for e in expect if _norm(e) not in flat]
        present = [f for f in forbid if _norm(f) in flat]
        # expect is a list of alternatives for the same fact (62635 / 62,635),
        # so satisfying any one of them counts - all missing means it is absent.
        ok = (not expect or len(missing) < len(expect)) and not present

        if ok:
            passed += 1
            print(f"  ok    [{project_id:12}] {question[:44]:46} {elapsed:5.1f}s")
        else:
            failed += 1
            why = []
            if expect and len(missing) == len(expect):
                why.append(f"missing {expect}")
            if present:
                why.append(f"WRONG PROGRAMME'S FIGURE: {present}")
            failures.append((project_id, question, "; ".join(why)))
            print(f"  FAIL  [{project_id:12}] {question[:44]:46} {elapsed:5.1f}s  {'; '.join(why)}")

    n = passed + failed
    print("\n" + "=" * 74)
    print(f"RESULT: {passed}/{n} correct   avg {total_time / max(n, 1):.1f}s per answer")
    if failures:
        print("\nFAILURES:")
        for project_id, question, why in failures:
            print(f"  [{project_id}] {question}\n      {why}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
