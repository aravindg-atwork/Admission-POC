"""Regression coverage for rag/validate.py's check_and_regenerate
skip_llm_check parameter - punch-list item #1 (P95 latency), the second
half after the retry-timeout fix (llm.py, 2026-08-19).

Root cause: config.ORCHESTRATOR_PROVIDER ("hetzner" by default) is
documented at 52-77s for a TRIVIAL prompt, not a failure case - it is the
provider used for the LLM-check/regeneration escalation a flagged answer
triggers. Running that AFTER an already-slow main generation call is
exactly the sequential-LLM-call compounding behind the 2026-08-18
p95/p99 measurement (80.5s/240.1s). rag/answer.py's _pipeline now skips
this escalation once the request has already run longer than
config.VALIDATION_LLM_CHECK_BUDGET_SECONDS (default 20s) - deterministic
checks (free, no LLM call) still run either way; only the expensive
LLM-check/regenerate step is skipped, degrading to the SAME
already-proven-safe path this function already takes when Hetzner fails
to respond at all (flagged, never auto-cached, served as-is).

Pure logic, no backend/network needed - deterministic_checks and
llm_check are monkeypatched so this tests only the skip_llm_check
branch's own control flow, not either check's real behaviour.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.rag import validate  # noqa: E402

results = []


def _fake_flagged(question, context_text, reply, own_project_id):
    return ["unsupported_number: 12345"]


validate.deterministic_checks = _fake_flagged

llm_check_calls = []


def _fake_llm_check(question, context_text, reply):
    llm_check_calls.append(1)
    return True, None


validate.llm_check = _fake_llm_check

# Case 1: within budget - the LLM check must actually run.
before = len(llm_check_calls)
validate.check_and_regenerate("q", "ctx", "reply", "model", "sys", "user",
                               skip_llm_check=False)
ok = len(llm_check_calls) == before + 1
print(f"{'PASS' if ok else 'FAIL'}  within budget: llm_check called "
      f"(count {before} -> {len(llm_check_calls)}, expected +1)")
results.append(ok)

# Case 2: over budget - the LLM check must be skipped entirely.
before = len(llm_check_calls)
result = validate.check_and_regenerate("q", "ctx", "reply", "model", "sys", "user",
                                        skip_llm_check=True)
ok = len(llm_check_calls) == before  # unchanged - not called
print(f"{'PASS' if ok else 'FAIL'}  over budget: llm_check NOT called "
      f"(count stayed at {before})")
results.append(ok)

# The skipped case still returns the flagged-but-not-regenerated shape,
# not an error and not a silent pass - same shape a real Hetzner failure
# already produces via llm_check's own None-on-any-failure safe-degrade.
expected = ("reply", "model", ["unsupported_number: 12345"], False)
ok = result == expected
print(f"{'PASS' if ok else 'FAIL'}  skipped result shape: expected={expected} got={result}")
results.append(ok)

print()
if all(results):
    print(f"ALL {len(results)} VALIDATION-SKIP-BUDGET CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
