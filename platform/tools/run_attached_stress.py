"""Run numbered programme questions parsed from a pasted stress-test text file."""

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8100"
HEADINGS = {
    "b.v.sc": "bvsc",
    "b.f.sc": "bfsc",
    "b.tech": "btech-dairy",
}


def parse(path: Path) -> list[tuple[str, int, str]]:
    current = None
    counters = {}
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        low = raw.lower()
        if "cross-rule questions" in low:
            current = "cross"
            continue
        for marker, project in HEADINGS.items():
            if marker in low and "stress-test questions" in low:
                current = project
                counters[current] = 0
                break
        match = re.match(r"\s*(\d+)\.\s*[â€œ\"“]?(.*?)[â€\"”]?\s*$", raw)
        if not match or not current:
            continue
        question = match.group(2).strip().strip("â€œâ€“”\"")
        if not question:
            continue
        if current == "cross":
            prefix, _, question = question.partition(":")
            project = "bvsc" if "bvsc" in prefix.lower() else "bfsc" if "bfsc" in prefix.lower() else "btech-dairy"
        else:
            project = current
        counters[current] = counters.get(current, 0) + 1
        rows.append((project, counters[current], question))
    return rows


def ask(project: str, question: str) -> tuple[dict, float]:
    request = urllib.request.Request(
        f"{BASE}/api/chat", method="POST", headers={"Content-Type": "application/json"},
        data=json.dumps({"projectId": project, "question": question, "uiLanguage": "en"}).encode(),
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=150) as response:
        return json.loads(response.read().decode()), time.time() - started


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--project", choices=["bvsc", "bfsc", "btech-dairy"])
    parser.add_argument("--cases", help="comma-separated section-local question numbers")
    args = parser.parse_args()
    selected = {int(v) for v in args.cases.split(",")} if args.cases else None
    rows = [row for row in parse(args.input) if (not args.project or row[0] == args.project)]
    if selected:
        rows = [row for row in rows if row[1] in selected]
    failed = 0
    for project, index, question in rows:
        print(f"\n{'=' * 88}\n{project} CASE {index}\nQ: {question}", flush=True)
        try:
            data, elapsed = ask(project, question)
            failed += data.get("source") == "provider-unavailable"
            print(f"SOURCE: {data.get('source')} MODEL: {data.get('model')} TIME: {elapsed:.1f}s")
            print(f"PAGES: {data.get('pages')}\nA: {data.get('answer')}", flush=True)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR: {exc!r}", flush=True)
    print(f"\nEXECUTION: {len(rows) - failed}/{len(rows)} returned answers (semantic review still required)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
