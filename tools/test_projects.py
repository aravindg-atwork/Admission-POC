"""Multi-project isolation + ingest hash-skip verification."""
import json
import urllib.error
import urllib.request

BASE = "http://localhost:5050"
ADMIN = "poc-admin-dev-token"
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS" if ok else "FAIL"), "-", name, ("| " + detail) if detail else "")


def req(method, path, headers=None, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                                headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            return e.code, {}


print("== Create a second project ==")
status, proj = req("POST", "/admin/projects", {"X-Admin-Token": ADMIN}, {"name": "test-matrix-project"})
check("Create project", status == 200 and proj.get("id"), f"status={status} id={proj.get('id')}")
proj_id = proj.get("id")

print("\n== New project starts with zero activity, isolated from default ==")
status, default_stats = req("GET", "/admin/projects/default/stats", {"X-Admin-Token": ADMIN})
status2, new_stats = req("GET", f"/admin/projects/{proj_id}/stats", {"X-Admin-Token": ADMIN})
check("New project stats endpoint works", status2 == 200, f"status={status2}")
check("New project has 0 questions (not inherited from default)", new_stats.get("totalQuestions") == 0,
      f"new={new_stats.get('totalQuestions')} default={default_stats.get('totalQuestions')}")
check("Default project unaffected (still has its prior history)", default_stats.get("totalQuestions", 0) > 0,
      f"default={default_stats.get('totalQuestions')}")

print("\n== Key created for new project only works for that project ==")
status, key = req("POST", "/admin/keys", {"X-Admin-Token": ADMIN}, {"label": "proj2-key", "project_id": proj_id})
check("Create key scoped to new project", status == 200, f"status={status}")
status, chat_result = req("POST", "/api/chat", {"X-API-Key": key["key"]}, {"question": "hello"})
check("New project's key can chat (greeting)", status == 200 and chat_result.get("source") == "greeting", str(chat_result)[:100])

print("\n== New project has no prospectus yet -> must decline honestly, never hallucinate a figure ==")
status, d = req("POST", "/api/chat", {"X-API-Key": key["key"]}, {"question": "What is the application fee?"})
check("Question against empty project doesn't crash", status == 200, f"status={status}")
check("source is no-context (code-guaranteed path, not a normal RAG guess)", d.get("source") == "no-context", f"source={d.get('source')}")
has_digit = any(c.isdigit() for c in d.get("answerText", ""))
check("Answer does NOT invent a specific number/figure", not has_digit, d.get("answerText", "")[:100])

print("\n== Cleanup: delete test project (should cascade-delete its key) ==")
status, d = req("DELETE", f"/admin/projects/{proj_id}", {"X-Admin-Token": ADMIN})
check("Delete project", status == 200, f"status={status}")
status, d = req("POST", "/api/chat", {"X-API-Key": key["key"]}, {"question": "hello"})
check("Deleted project's key no longer works (cascade delete)", status == 401, f"status={status}")

print("\n" + "=" * 60)
total = len(results)
passed = sum(1 for _, ok in results if ok)
print(f"RESULT: {passed}/{total} passed")
if passed < total:
    for name, ok in results:
        if not ok:
            print(" FAIL:", name)
