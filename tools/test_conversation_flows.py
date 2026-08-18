"""Multi-turn regression coverage for the guided eligibility interview and
the topic-menu chips (rag/guards.py: _eligibility_guard/_eligibility_
interview_ask/_eligibility_percent_ask, _topic_menu_guard).

Both features are round-trip state machines built on conversationState
(interviewOptions/interviewField/slotUpdate/carryQuestion/topicOptions in
the response, echoed back as conversationState on the next request) - see
CLAUDE.md's "Guided eligibility interview" note. tools/eval_admissions.py's
C() framework is single-turn only and cannot express this, which is why
this suite exists as its own file rather than more cases added there.

Each test drives the SAME mechanism static/app.js's pickInterview/pickTopic
use: resend the server's own `carryQuestion` text, with conversationState
built by spreading the prior state and setting exactly the field the chip
click would set - never relying on free-text reply parsing (that is a
separate, already-covered path: bare_entrance_reply/bare_percent).
"""
import json
import os
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")  # Windows console default (cp1252) can't print Devanagari

ADMIN = os.environ.get("ADMIN_TOKEN", "poc-admin-dev-token")
BASE = "http://127.0.0.1:5050"

_created_key_ids = []


def _make_key(project_id):
    req = urllib.request.Request(
        f"{BASE}/admin/keys",
        data=json.dumps({"label": "test-conversation-flows", "project_id": project_id}).encode("utf-8"),
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


def ask(key, question, conversation_state=None, ui_language=None):
    body = {"question": question}
    if conversation_state is not None:
        body["conversationState"] = conversation_state
    if ui_language:
        body["uiLanguage"] = ui_language
    req = urllib.request.Request(f"{BASE}/api/chat", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": key}, method="POST")
    with urllib.request.urlopen(req, timeout=200) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not condition else ""))
    return condition


results = []
bvsc_key = _make_key("bvsc")
default_key = _make_key("default")

# ---------------------------------------------------------------------
print("=== Topic menu: chip click resolves to a real answer, not the menu again ===")
r1 = ask(default_key, "What can you help with?")
results.append(check("turn 1: capability question -> topic-menu",
                      r1.get("source") == "topic-menu", r1.get("source")))
results.append(check("turn 1: six chip options offered",
                      len(r1.get("topicOptions") or []) == 6, r1.get("topicOptions")))
r2 = ask(default_key, "What is the eligibility criteria?")
results.append(check("turn 2: clicking the Eligibility chip does not re-show the menu",
                      r2.get("source") != "topic-menu", r2.get("source")))

# ---------------------------------------------------------------------
print("\n=== Guided interview: missing entrance exam short-circuits straight to a verdict ===")
r1 = ask(bvsc_key, "Am I eligible for B.V.Sc.?")
results.append(check("turn 1: bare eligibility question -> interview, asking entrance status",
                      r1.get("source") == "eligibility-interview"
                      and r1.get("interviewField") == "entranceExamStatus",
                      (r1.get("source"), r1.get("interviewField"))))
state = dict.fromkeys(
    ["programme", "intent", "category", "subjectPercent", "overallPercent", "entranceExamStatus"])
state.update(r1.get("slotUpdate") or {})
results.append(check("turn 1: slotUpdate pins programme=bvsc",
                      state.get("programme") == "bvsc", state))

state["entranceExamStatus"] = "no"  # simulates clicking "No, not yet"
r2 = ask(bvsc_key, r1.get("carryQuestion") or "Am I eligible for B.V.Sc.?", conversation_state=state)
results.append(check("turn 2: 'no' to entrance skips the category question entirely -> immediate verdict",
                      r2.get("source") == "eligibility", r2.get("source")))
answer2 = (r2.get("answerText") or "").lower()
results.append(check("turn 2: verdict text actually explains the entrance-exam reason",
                      "neet" in answer2, r2.get("answerText", "")[:200]))

# ---------------------------------------------------------------------
print("\n=== Guided interview: full happy path (entrance -> category -> percent -> verdict) ===")
r1 = ask(bvsc_key, "Am I eligible for B.V.Sc.?")
state = dict.fromkeys(
    ["programme", "intent", "category", "subjectPercent", "overallPercent", "entranceExamStatus"])
state.update(r1.get("slotUpdate") or {})
state["entranceExamStatus"] = "yes"  # simulates clicking "Yes, I've appeared"
r2 = ask(bvsc_key, r1.get("carryQuestion") or "Am I eligible for B.V.Sc.?", conversation_state=state)
results.append(check("step 2: entrance=yes moves on to asking category",
                      r2.get("source") == "eligibility-interview"
                      and r2.get("interviewField") == "category",
                      (r2.get("source"), r2.get("interviewField"))))

state.update(r2.get("slotUpdate") or {})
state["category"] = "unreserved"  # simulates clicking "Unreserved / General"
r3 = ask(bvsc_key, r2.get("carryQuestion") or "Am I eligible for B.V.Sc.?", conversation_state=state)
results.append(check("step 3: category resolved, only the percentage is missing -> percent ask",
                      r3.get("source") == "clarify-percentage", r3.get("source")))

state.update(r3.get("slotUpdate") or {})
r4 = ask(bvsc_key, "70% in Physics, Chemistry, Biology and English", conversation_state=state)
results.append(check("step 4: subject-combination percentage given -> real verdict",
                      r4.get("source") == "eligibility", r4.get("source")))
answer4 = (r4.get("answerText") or "").lower()
results.append(check("step 4: verdict reflects a clear pass (70% well above the 50% threshold)",
                      "meet" in answer4 or "eligible" in answer4, r4.get("answerText", "")[:200]))

# ---------------------------------------------------------------------
print("\n=== conversationState precedence: this message's own programme beats stale carried state ===")
r1 = ask(bvsc_key, "Am I eligible for B.V.Sc.?")
stale_state = dict.fromkeys(
    ["programme", "intent", "category", "subjectPercent", "overallPercent", "entranceExamStatus"])
stale_state.update(r1.get("slotUpdate") or {})  # programme=bvsc, intent=eligibility_awaiting_entrance, still attached
r2 = ask(default_key, "Am I eligible for B.F.Sc. with 70% in PCB, unreserved, and I've cleared NEET?",
         conversation_state=stale_state)
answer2 = (r2.get("answerText") or "")
results.append(check("a fresh question naming B.F.Sc. is answered about B.F.Sc., not stale B.V.Sc. state",
                      "b.v.sc" not in answer2.lower() or "b.f.sc" in answer2.lower(), answer2[:200]))

_cleanup_keys()

print()
if all(results):
    print(f"ALL {len(results)} CONVERSATION-FLOW CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
