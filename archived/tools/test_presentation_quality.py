"""Presentation/tone/Indic answer QUALITY - deliberately distinct from
every other suite in tools/, which checks source/figure correctness
(the right number, the right programme) but never whether the answer is
presentable: right script, no leaked markdown, professional regardless
of the student's tone, and a real answer even to a terse or rude message.

This gap was named explicitly, more than once, by the project owner and
tracked in CLAUDE.md's Open section as unaddressed. test_hinglish.py
already covers the CORE script-consistency mechanic for one canonical
Hindi question (auto/native/romanized); this file extends that to
Marathi (previously untested for script consistency at all), a broader
set of realistic questions, and tone/format robustness the existing
suites never touch.

Honesty about what this can and cannot automate: whether an answer
genuinely READS WELL in Marathi is a judgement call a script-ratio check
cannot make. What IS reliably automatable, and is exactly what this
project's own bug history shows breaks in practice (see CLAUDE.md's
"Client-side React stale-closure" and language-hint notes): does the
reply's SCRIPT match what the input's script/script-preference demands,
does markdown leak into what is supposed to be plain spoken prose, and
does a real question get a real answer regardless of how rudely or
tersely it was asked. Genuine subjective tone quality still needs a
human (or a future LLM-judge pass, deliberately not added here - see
this file's own docstring on why: an extra LLM call per question is a
real latency/cost tradeoff this project has repeatedly chosen against
elsewhere, see llm.py's ORCHESTRATOR_PROVIDER history).
"""
import json
import os
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")  # Windows console default (cp1252) can't print Devanagari/Tamil

BASE = os.environ.get("BACKEND_URL", "http://127.0.0.1:5050")
ADMIN = os.environ.get("ADMIN_TOKEN", "poc-admin-dev-token")

_created_key_ids = []


def _make_key(project_id, label):
    req = urllib.request.Request(
        f"{BASE}/admin/keys",
        data=json.dumps({"label": label, "project_id": project_id}).encode("utf-8"),
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


def ask(key, question, ui_language=None, script_pref=None, timeout=90):
    body = {"question": question}
    if ui_language:
        body["uiLanguage"] = ui_language
    if script_pref:
        body["scriptPreference"] = script_pref
    req = urllib.request.Request(f"{BASE}/api/chat", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": key}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def devanagari_ratio(text):
    letters = [c for c in (text or "") if c.isalpha()]
    return sum(1 for c in letters if 0x0900 <= ord(c) <= 0x097F) / len(letters) if letters else 0


# Plain spoken prose has none of these - every eligibility/facts prompt in
# this codebase explicitly forbids them (see prompts/system.py's
# "Plain spoken prose, no markdown, no bullet markers, no headings").
_MARKDOWN_LEAK_RE = re.compile(r"^\s*#{1,6}\s|^\s*[-*]\s|\*\*[^*]+\*\*", re.MULTILINE)

results = []


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    results.append(ok)
    return ok


bvsc_key = _make_key("bvsc", "presentation-quality-run")

# ---------------------------------------------------------------------
print("=== Marathi native script consistency (untested until now - test_hinglish.py covers Hindi only) ===")
r = ask(bvsc_key, f"बी.व्ही.एससी.साठी फी किती आहे? [{int(time.time()*1000)}]", ui_language="mr")
ratio = devanagari_ratio(r.get("answerText"))
check("Marathi native input -> Devanagari-script reply", ratio > 0.5,
      f"devanagari_ratio={ratio:.2f}")
check("Marathi native reply is speakable", r.get("speakable") is True)

print("\n=== Marathi romanized input stays romanized (not switched to Devanagari) ===")
r = ask(bvsc_key, f"bvsc sathi fee kiti aahe? [{int(time.time()*1000)}]")
ratio = devanagari_ratio(r.get("answerText"))
check("Romanized Marathi input -> Latin-script reply", ratio < 0.3,
      f"devanagari_ratio={ratio:.2f}")

# ---------------------------------------------------------------------
print("\n=== Tone robustness: rude/sarcastic phrasing still gets a real, professional answer ===")
r = ask(bvsc_key, "ugh whatever just tell me the fee already, this bot is useless")
check("Sarcastic/rude tone still gets a substantive answer",
      bool(r.get("answerText")) and len(r.get("answerText", "")) > 20,
      repr(r.get("answerText", ""))[:100])
check("Reply doesn't mirror the rudeness back (no 'useless' in the reply)",
      "useless" not in (r.get("answerText") or "").lower())

print("\n=== Terse/minimal input still gets a complete answer, not a confused one ===")
r = ask(bvsc_key, "fee?")
check("A 1-word question still gets a non-trivial answer",
      bool(r.get("answerText")) and len(r.get("answerText", "")) > 15,
      repr(r.get("answerText", ""))[:100])

# ---------------------------------------------------------------------
print("\n=== No markdown leaking into plain spoken-prose answers ===")
r = ask(bvsc_key, f"What documents are required to apply for B.V.Sc.? [{int(time.time()*1000)}]")
leaked = _MARKDOWN_LEAK_RE.search(r.get("answerText") or "")
check("Documents-list answer has no leaked markdown (#, -, **bold**)",
      leaked is None, f"found: {leaked.group(0)!r}" if leaked else "")

_cleanup_keys()

print()
if all(results):
    print(f"ALL {len(results)} PRESENTATION-QUALITY CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
