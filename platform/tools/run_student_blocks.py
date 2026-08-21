"""Run quoted questions immediately following **Student:** markers."""
import argparse, json, sys, urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

p = argparse.ArgumentParser()
p.add_argument("input", type=Path)
p.add_argument("--base", default="http://127.0.0.1:8100")
a = p.parse_args()
questions, take = [], False
for line in a.input.read_text(encoding="utf-8").splitlines():
    if line.strip() == "**Student:**":
        take = True
    elif take and line.startswith("> "):
        questions.append(line[2:].strip().strip('“”"'))
        take = False
substantive = fallback = errors = 0
for i, question in enumerate(questions, 1):
    project = "bvsc" if i <= 6 or i >= 16 else "bfsc" if i <= 11 else "btech-dairy"
    state = {"programme": project} if i <= 15 else {}
    req = urllib.request.Request(
        a.base.rstrip("/") + "/api/chat", method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
        data=json.dumps({"question": question, "uiLanguage": "en", "projectId": project,
                         "conversationState": state}).encode("utf-8"))
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            result = json.loads(response.read().decode("utf-8"))
        source = result.get("source")
        if source in {"provider-unavailable", "validation-blocked", "no-context"}: fallback += 1
        else: substantive += 1
        print(f"\nCASE {i:02} [{source}] language={result.get('language')}\n{result.get('answer')}")
    except Exception as exc:
        errors += 1
        print(f"\nCASE {i:02} ERROR {exc!r}")
print(f"\nEXECUTION substantive={substantive} fallback={fallback} errors={errors} total={len(questions)}")
