"""Live Hindi/Marathi promotion gate across all three programmes."""

import json
import sys
import urllib.request


BASE = "http://127.0.0.1:8100"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CASES = (
    ("hi", "bvsc", "mujhe batao, I am NRI, completed 12th in USA with 55% PCBE and did not take NEET. Am I eligible?", ("50%", "17", "NEET")),
    ("mr", "bvsc", "mala he kalaycha ahe: I am NRI, completed 12th in USA with 45% PCBE and did not take NEET. Am I eligible?", ("45%", "50%", "NEET")),
    ("hi", "bfsc", "mujhe batao, how many B.F.Sc. seats are in Nagpur and how many are University and ICAR quota?", ("40", "32", "8")),
    ("mr", "bfsc", "How many B.F.Sc. seats are in Nagpur and how many are University and ICAR quota? mala kiti ahe", ("40", "32", "8")),
    ("hi", "btech-dairy", "mujhe batao, for Dairy management quota which gets first priority: MHT-CET or CUET ICAR-UG?", ("MHT-CET", "CUET")),
    ("mr", "btech-dairy", "mala kay mahit pahije: for Dairy management quota which gets first priority, MHT-CET or CUET ICAR-UG?", ("MHT-CET", "CUET")),
)


def ask(language: str, project: str, question: str) -> dict:
    body = json.dumps({"projectId": project, "question": question, "uiLanguage": language}).encode()
    request = urllib.request.Request(
        f"{BASE}/api/chat", data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode())


def has_devanagari(text: str) -> bool:
    return any("\u0900" <= char <= "\u097f" for char in text)


def main() -> int:
    passed = 0
    for index, (expected_language, project, question, required) in enumerate(CASES, 1):
        result = ask(expected_language, project, question)
        answer = result.get("answer", "")
        missing = [token for token in required if token not in answer]
        ok = (
            result.get("language") == expected_language
            and has_devanagari(answer)
            and not missing
            and result.get("source") not in {"provider-unavailable", "validation-blocked", "no-context"}
        )
        passed += int(ok)
        print(
            f"{'PASS' if ok else 'FAIL'} {index:02d} {project:12s} {expected_language} "
            f"source={result.get('source')} cache={result.get('cacheHit')} missing={missing}\n{answer}\n"
        )
    print(f"MULTILINGUAL PROMOTION GATE: {passed}/{len(CASES)} passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
