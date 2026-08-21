"""Promotion gate for the first 23 natural paragraph questions in the supplied set."""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# Each tuple is (required token groups, forbidden tokens). One token from every
# required group must occur. These assert decisions, not exact prose.
CHECKS = [
    (("48",), ("47.5",), ("ncl", "non-creamy"), ("unreserved", "general")),
    (("not eligible", "cannot apply"), ("50%",), ("cannot compensate", "compulsory")),
    (("exempt",), ("abroad", "usa"), ("50%",), ("17",), ("documents", "nri/fn/pio/oci")),
    (("neet",), ("india", "maharashtra"), ("required", "must have appeared")),
    (("state quota",), ("not",), ("regional",)),
    (("depends", "cannot determine"), ("preference", "round"), ("current", "present", "first seat")),
    (("deficient",), ("re-upload", "upload correct"), ("reject", "failure")),
    (("b.f.sc",), ("44%", "44"), ("40%", "40"), ("mht-cet",), ("neet", "does not affect")),
    (("not eligible", "cannot"), ("50%",), ("weightage", "merit")),
    (("12",), ("10",), ("2",), ("20",), ("corrected", "98")),
    (("46",), ("40",), ("ncl",), ("female",), ("unreserved", "open")),
    (("cannot", "no"), ("main", "income"), ("7/12", "land")),
    (("preference",), ("again", "next round"), ("depends", "allotment")),
    (("separate", "both"), ("icar",), ("state merit", "mafsu merit"), ("vacant", "remain")),
    (("no", "not eligible"), ("mathematics", "maths"), ("pcm",)),
    (("pcm",), ("mht-cet",), ("not", "cannot")),
    (("management",), ("private",), ("not", "cannot"), ("university quota", "constituent")),
    (("mafsu", "university"), ("not direct", "cannot directly", "does not allot directly"), ("allot", "register")),
    (("43",), ("40",), ("ncl",), ("female", "horizontal"), ("cannot claim", "not eligible for agriculturist")),
    (("does not apply", "exception"), ("permanently disabled",), ("five", "5-year")),
    (("b.v.sc",), ("not eligible", "no"), ("b.f.sc",), ("eligible", "meet"), ("fisherman",), ("12",)),
    (("b.v.sc",), ("not eligible", "no"), ("b.f.sc",), ("b.tech",), ("pcb",), ("pcm",)),
    (("b.v.sc",), ("not",), ("b.f.sc",), ("b.tech",), ("pcb",), ("pcm",)),
]


def questions(path: Path) -> list[str]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("> "):
            rows.append(line[2:].strip().strip("“”\""))
    return rows[:23]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--base", default="http://127.0.0.1:8100")
    args = parser.parse_args()
    rows = questions(args.input)
    if len(rows) != 23:
        print(f"Expected 23 questions, found {len(rows)}")
        return 2
    failed = 0
    for index, question in enumerate(rows, 1):
        project = "bvsc" if index <= 7 or index >= 21 else "bfsc" if index <= 14 else "btech-dairy"
        state = {"programme": project} if index <= 20 else {}
        body = json.dumps({
            "question": question, "uiLanguage": "en", "projectId": project,
            "conversationState": state,
        }).encode("utf-8")
        request = urllib.request.Request(
            args.base.rstrip("/") + "/api/chat", data=body, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
            answer = (result.get("answer") or "").lower().replace("-", " ")
            required = CHECKS[index - 1]
            missing = [
                group for group in required
                if not any(token.replace("-", " ") in answer for token in group)
            ]
            ok = not missing and result.get("source") not in {
                "provider-unavailable", "validation-blocked", "no-context",
                "programme-clarify", "language-preference",
            }
            failed += not ok
            print(f"{'PASS' if ok else 'FAIL'} {index:02} {project:12} [{result.get('source')}] missing={missing}")
            if not ok:
                print(result.get("answer"))
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {index:02} {project:12} ERROR {exc!r}")
    print(f"\nPARAGRAPH PROMOTION GATE: {23 - failed}/23 passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
