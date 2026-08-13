"""Verify the percentage-clarification guard (rag/guards.py's
_percentage_clarify_guard, backed by core/intent.needs_percentage_clarification)
fires correctly across English, Hindi, and Marathi, stays silent when the
student already resolved the ambiguity themselves, and still takes
precedence over comparison-routing and program-clarification exactly as
documented in guards.py. Companion to the 2026-08-13 Hindi/Marathi
extension (Phase 8 of the backend re-architecture) - the English cases are
a regression check against the original 2026-08-12 reported bug.
"""
import json
import os
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")  # Windows console default (cp1252) can't print Devanagari

ADMIN = os.environ.get("ADMIN_TOKEN", "poc-admin-dev-token")
BASE = "http://localhost:5050"

_created_key_ids = []


def _make_key(project_id):
    req = urllib.request.Request(
        f"{BASE}/admin/keys",
        data=json.dumps({"label": "test-clarification-run", "project_id": project_id}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Admin-Token": ADMIN}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        entry = json.loads(resp.read().decode("utf-8"))
    _created_key_ids.append(entry["id"])
    return entry["key"]


def _cleanup_keys():
    for key_id in _created_key_ids:
        req = urllib.request.Request(f"{BASE}/admin/keys/{key_id}",
                                      headers={"X-Admin-Token": ADMIN}, method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=30)
        except Exception:
            pass


def ask(key, question, ui_language=None):
    body = {"question": question}
    if ui_language:
        body["uiLanguage"] = ui_language
    req = urllib.request.Request(f"{BASE}/api/chat", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": key}, method="POST")
    with urllib.request.urlopen(req, timeout=200) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check(label, got_source, expected_source, answer_text=""):
    ok = got_source == expected_source
    print(f"{'PASS' if ok else 'FAIL'}  {label}: expected source={expected_source!r} got={got_source!r}")
    if answer_text:
        print("   A:", answer_text[:150].replace("\n", " "))
    return ok


results = []
mvsc_key = _make_key("mvsc")
default_key = _make_key("default")

print("=== English: ambiguous percentage (2026-08-12 regression) ===")
r = ask(mvsc_key, "I have scored 60%, am I eligible for M.V.Sc.?", "en")
results.append(check("EN ambiguous", r.get("source"), "clarify-percentage", r.get("answerText", "")))

print("\n=== English: already-qualified percentage (must NOT clarify) ===")
r = ask(mvsc_key, "I have 51% overall in 12th but 45% in PCB and English, am I eligible for M.V.Sc.?", "en")
ok = r.get("source") != "clarify-percentage"
print(f"{'PASS' if ok else 'FAIL'}  EN qualified: expected NOT clarify-percentage, got={r.get('source')!r}")
results.append(ok)

print("\n=== Hindi: ambiguous percentage ===")
r = ask(mvsc_key, "मुझे 60% मिले हैं, क्या मैं एम.व्ही.एससी. के लिए पात्रता रखता हूँ?", "hi")
results.append(check("HI ambiguous", r.get("source"), "clarify-percentage", r.get("answerText", "")))

print("\n=== Marathi: ambiguous percentage ===")
r = ask(mvsc_key, "मला 60% मिळाले आहेत, मला एम.व्ही.एससी.साठी प्रवेश मिळेल का?", "mr")
results.append(check("MR ambiguous", r.get("source"), "clarify-percentage", r.get("answerText", "")))

print("\n=== Program-clarification still works: English ===")
r = ask(default_key, "What is the fee?", "en")
results.append(check("EN program-clarify", r.get("source"), "clarify-program"))

print("\n=== Program-clarification still works: Hindi ===")
r = ask(default_key, "शुल्क कितना है?", "hi")
results.append(check("HI program-clarify", r.get("source"), "clarify-program"))

print("\n=== Program-clarification still works: Marathi ===")
r = ask(default_key, "फी किती आहे?", "mr")
results.append(check("MR program-clarify", r.get("source"), "clarify-program"))

print("\n=== Precedence: ambiguous percentage naming several programs must clarify, not compare ===")
r = ask(default_key, "I scored 60%, am I eligible for B.V.Sc., B.F.Sc., or B.Tech Dairy?", "en")
results.append(check("Percentage-clarify beats comparison", r.get("source"), "clarify-percentage"))

_cleanup_keys()

print()
if all(results):
    print(f"ALL {len(results)} CLARIFICATION CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
