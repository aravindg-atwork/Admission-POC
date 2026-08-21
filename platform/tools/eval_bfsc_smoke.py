"""Initial B.F.Sc. post-ingestion correctness gate."""

import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8100"
CASES = [
    ("application fee", "What is the application fee for B.F.Sc.?", [("1000",), ("700",)], ["62635"]),
    ("admission fee", "What is the first year admission fee for B.F.Sc.?", [("40610", "40,610")], ["62635", "62,635"]),
    ("unreserved marks", "What percentage is required for unreserved B.F.Sc. candidates?", [("50",)], ["47.5"]),
    ("reserved marks", "What percentage is required for reserved B.F.Sc. candidates?", [("40",)], ["47.5"]),
    ("subjects", "Which subjects are required in 12th for B.F.Sc.?", [("biology",)], ["mathematics"]),
    ("entrance", "Which entrance examination is required for B.F.Sc.?", [("mht-cet", "mht cet")], ["neet"]),
    ("duration", "How long is the B.F.Sc. course?", [("four-year", "four year", "4 years", "eight semesters")], []),
    ("personal reserved", "I am reserved, scored 41% in Physics, Chemistry, Biology and English together, and appeared for MHT-CET 2026. Do I meet the B.F.Sc. marks requirement?", [("meet", "eligible"), ("40",)], ["47.5", "neet"]),
]


def ask(question: str) -> dict:
    request = urllib.request.Request(
        f"{BASE}/api/chat", method="POST", headers={"Content-Type": "application/json"},
        data=json.dumps({"projectId": "bfsc", "question": question, "uiLanguage": "en"}).encode(),
    )
    with urllib.request.urlopen(request, timeout=150) as response:
        return json.loads(response.read().decode())


def main() -> int:
    failed = 0
    for label, question, groups, forbidden in CASES:
        try:
            data = ask(question)
            answer = (data.get("answer") or "").lower().replace("-", " ").replace(",", "")
            missing = [group for group in groups if not any(term.replace("-", " ") in answer for term in group)]
            present = [term for term in forbidden if term in answer]
            ok = not missing and not present and data.get("source") != "provider-unavailable"
            failed += not ok
            print(f"{'PASS' if ok else 'FAIL'}  {label:22} [{data.get('source')}] {data.get('answer')}")
            if not ok:
                print(f"      missing={missing} forbidden={present}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {label:22} ERROR {exc!r}")
    print(f"\nB.F.Sc. SMOKE GATE: {len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
