"""Verify: auto mode -> Devanagari + speakable; hinglish mode -> Roman + not speakable."""
import json, os, sys, time, urllib.request

sys.stdout.reconfigure(encoding="utf-8")  # Windows console default (cp1252) can't print Devanagari/Tamil

ADMIN = os.environ.get("ADMIN_TOKEN", "poc-admin-dev-token")


def _make_temp_key():
    req = urllib.request.Request(
        "http://localhost:5050/admin/keys",
        data=json.dumps({"label": "test-hinglish-run"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Admin-Token": ADMIN}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


_created = _make_temp_key()
KEY = _created["key"]
_KEY_ID = _created["id"]


def _delete_temp_key():
    req = urllib.request.Request(
        f"http://localhost:5050/admin/keys/{_KEY_ID}",
        headers={"X-Admin-Token": ADMIN}, method="DELETE")
    urllib.request.urlopen(req, timeout=30)


def devanagari_ratio(text):
    letters = [c for c in text if c.isalpha()]
    return sum(1 for c in letters if 0x0900 <= ord(c) <= 0x097F) / len(letters) if letters else 0

def ask(q, script_pref=None):
    body = {"question": q}
    if script_pref:
        body["scriptPreference"] = script_pref
    req = urllib.request.Request("http://localhost:5050/api/chat", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": KEY}, method="POST")
    with urllib.request.urlopen(req, timeout=200) as resp:
        return json.loads(resp.read().decode("utf-8"))

base_q = "आवेदन शुल्क कितना है?"

print("=== AUTO mode (default, should be Devanagari + speakable) ===")
d1 = ask(base_q + f" [{int(time.time()*1000)}]")
r1 = devanagari_ratio(d1["answerText"])
print(f"devanagari_ratio={r1:.2f} speakable={d1.get('speakable')} model={d1['model']}")
print("A:", d1["answerText"][:150])
assert r1 > 0.5, "FAIL: auto mode not in Devanagari"
assert d1.get("speakable") is True, "FAIL: auto mode should be speakable"
print("PASS\n")

print("=== HINGLISH mode (explicit, should be Roman + NOT speakable) ===")
d2 = ask(base_q + f" [{int(time.time()*1000)}]", script_pref="hinglish")
r2 = devanagari_ratio(d2["answerText"])
print(f"devanagari_ratio={r2:.2f} speakable={d2.get('speakable')} model={d2['model']}")
print("A:", d2["answerText"][:150])
assert r2 < 0.3, "FAIL: hinglish mode still mostly Devanagari"
assert d2.get("speakable") is False, "FAIL: hinglish mode should be marked not speakable"
print("PASS\n")

print("=== Cache isolation: repeat AUTO question should still return Devanagari (not leak hinglish cache) ===")
d3 = ask(base_q)  # same text as d1, no timestamp -> may hit cache from d1
r3 = devanagari_ratio(d3["answerText"])
print(f"source={d3.get('source')} devanagari_ratio={r3:.2f} speakable={d3.get('speakable')}")
assert r3 > 0.5, "FAIL: cache leaked a hinglish answer into auto mode"
assert d3.get("speakable") is True
print("PASS\n")

print("ALL HINGLISH FEATURE CHECKS PASSED")
_delete_temp_key()
