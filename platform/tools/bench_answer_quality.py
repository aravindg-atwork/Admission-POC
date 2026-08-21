"""B.V.Sc. answer-quality checkpoint against the legacy suite's ground truth."""

import json
import re
import sys
import time
import urllib.request


BASE = "http://127.0.0.1:8100"

# Exact B.V.Sc. subset of ../../tools/bench_answer_quality.py.
CASES = [
    ("what is the application fee", ["1000", "700"], []),
    ("what is the admission fee", ["62635", "62,635"], ["40610", "40,610"]),
    ("what is the minimum percentage needed for unreserved category", ["50"], []),
    ("which subjects do I need in 12th", ["Biology"], ["Mathematics"]),
]

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def _norm(text: str) -> str:
    return re.sub(r"[,\s]", "", text.translate(_DEVANAGARI_DIGITS)).lower()


def _ask(question: str, timeout: int = 120) -> tuple[dict, float]:
    body = json.dumps({"projectId": "bvsc", "question": question, "uiLanguage": "en"}).encode()
    request = urllib.request.Request(
        f"{BASE}/api/chat", data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode()), time.time() - started


def main() -> int:
    passed = failed = 0
    total_time = 0.0
    failures = []
    for question, expect, forbid in CASES:
        try:
            data, elapsed = _ask(question)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            failures.append((question, f"request failed: {exc!r}"))
            print(f"  FAIL  {question[:55]:57} request failed", flush=True)
            continue

        total_time += elapsed
        flat = _norm(data.get("answer") or "")
        missing = [value for value in expect if _norm(value) not in flat]
        present = [value for value in forbid if _norm(value) in flat]
        ok = (not expect or len(missing) < len(expect)) and not present
        if ok:
            passed += 1
            print(f"  ok    {question[:55]:57} {elapsed:5.1f}s", flush=True)
        else:
            failed += 1
            reasons = []
            if expect and len(missing) == len(expect):
                reasons.append(f"missing {expect}")
            if present:
                reasons.append(f"wrong-programme figure {present}")
            reason = "; ".join(reasons)
            failures.append((question, reason))
            print(f"  FAIL  {question[:55]:57} {elapsed:5.1f}s  {reason}", flush=True)

    count = passed + failed
    print("\n" + "=" * 78)
    print(f"RESULT: {passed}/{count} correct   avg {total_time / max(count, 1):.1f}s per answer")
    for question, reason in failures:
        print(f"  {question}\n      {reason}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
