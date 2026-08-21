"""User-supplied B.Tech. Dairy promotion gate: 24 multi-rule scenarios."""

import argparse
import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8100"
QUESTIONS = [
    "I am from Maharashtra, General category, and got 49% in Physics, Chemistry, Mathematics and English together in 12th. I appeared for MHT-CET 2026 and got a very good percentile. Can I still get admission to B.Tech Dairy Technology?",
    "I belong to OBC and have 42% in Physics, Chemistry, Mathematics and English together. I appeared for MHT-CET 2026. Am I eligible for B.Tech Dairy Technology, and does the 50% minimum apply to me?",
    "I have 65% in PCM and English in 12th but I did not appear for MHT-CET 2026. Can I take admission based only on my 12th marks?",
    "I studied Physics, Chemistry and Biology in 12th but did not have Mathematics. Can I apply for B.Tech Dairy Technology through MHT-CET?",
    "My date of birth is 2 January 2010. I satisfy the academic requirements and have appeared for MHT-CET. Am I eligible for admission in 2026-27?",
    "I was born on 1 January 2010. Am I old enough to apply for B.Tech Dairy Technology this year?",
    "I want B.Tech Dairy Technology but don't know which MAFSU colleges offer it. What are all the government/constituent and private affiliated colleges, and how many seats does each have?",
    "I want only a constituent MAFSU college. Between Warud and Udgir, how many University quota and ICAR quota seats are available in each?",
    "I didn't get a seat in Warud. Can I try for Udgir, and if I still don't get either, what private Dairy Technology colleges under MAFSU can I consider?",
    "I am from Karnataka, not Maharashtra. I got 55% in 12th. Can I apply to the MAFSU constituent Dairy Technology colleges at Warud or Udgir, or am I eligible only for private colleges?",
    "I am an outside-Maharashtra candidate. Can I get a University quota seat in a private Dairy Technology college, or am I restricted to Management quota?",
    "I am OBC and have my caste certificate, but my caste validity certificate hasn't arrived yet. I have the receipt showing that I applied for caste validity. Can I still apply under OBC?",
    "I got an OBC reserved seat in the first round, but my caste validity certificate is still pending. What is the last date to submit it, and what happens if I miss that deadline?",
    "I applied as OBC but couldn't submit my caste validity certificate and didn't get a seat in the first round. Will I be completely removed from admission, or can I participate as an Unreserved candidate?",
    "I am OBC and have a valid caste certificate and caste validity certificate, but my Non-Creamy Layer certificate is old. Can I still claim OBC reservation?",
    "My OBC Non-Creamy Layer certificate was issued before 1 April 2026 but is still valid on the last date for submitting the application. Will MAFSU accept it?",
    "I am an OBC female candidate. Do I get both OBC reservation and the 30% female reservation, or do I have to choose only one?",
    "If there aren't enough female OBC candidates to fill the female seats, what happens to those seats? Do they remain vacant or go to male OBC candidates?",
    "My parents own agricultural land, but our family's main income comes from my father's private job rather than farming. Can I claim the Agriculturist reservation?",
    "The agricultural land is in my paternal grandfather's name, not my father's name. Can I still claim the Agriculturist quota, and what certificate do I need?",
    "My father served in the Indian Army for 4 years and then retired normally. Can I claim the Defence Personnel reservation?",
    "My father served in the Army for only 3 years but was permanently disabled during service. Does the normal 5-year active-service requirement still apply to me?",
    "If I join B.Tech Dairy Technology and leave after completing the first year, will I get anything, or will that year be wasted? Can I return later and continue the degree?",
    "If I complete two years of B.Tech Dairy Technology and then leave, what qualification will I receive? If I return later, which semester can I join?",
]

CHECKS = {
    1: (("49", "50", "not"), ("eligible because",)),
    2: (("42", "40", "meet"), ("50% minimum applies",)),
    3: (("not", "mht-cet"), ("based only",)),
    4: (("mathematics", "not"), ("biology instead",)),
    5: (("not eligible", "1 january 2010"), ()),
    6: (("yes", "1 january 2010"), ("not old enough",)),
    7: (("warud", "udgir", "malkapur", "gandheli", "beed", "40"), ()),
    8: (("warud", "34", "6", "udgir", "33", "7"), ()),
    9: (("udgir", "malkapur", "gandheli", "beed"), ()),
    10: (("not eligible for warud or udgir", "management-quota", "private"), ()),
    11: (("management quota", "not", "university quota"), ()),
    12: (("yes", "proof", "12 august 2026"), ()),
    13: (("12 august 2026", "automatically", "unreserved"), ()),
    14: (("not completely removed", "unreserved", "12 august 2026"), ()),
    15: (("1 april 2026", "valid", "application"), ()),
    16: (("yes", "valid", "application"), ("rejected",)),
    17: (("both", "30%", "horizontal"), ("choose only",)),
    18: (("do not remain vacant", "male", "same category", "second round"), ()),
    19: (("no", "main source", "cultivation"), ()),
    20: (("yes", "paternal grandfather", "agriculturist certificate"), ()),
    21: (("no", "five years"), ()),
    22: (("does not apply", "permanently disabled"), ()),
    23: (("not automatically wasted", "certificate", "40 credits", "10 week", "third semester"), ()),
    24: (("diploma", "80 credits", "10 week", "fifth semester"), ()),
}


def ask(question: str) -> tuple[dict, float]:
    request = urllib.request.Request(
        f"{BASE}/api/chat", method="POST", headers={"Content-Type": "application/json"},
        data=json.dumps({"projectId": "btech-dairy", "question": question, "uiLanguage": "en"}).encode(),
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=150) as response:
        return json.loads(response.read().decode()), time.time() - started


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases")
    args = parser.parse_args()
    selected = {int(v) for v in args.cases.split(",")} if args.cases else set(range(1, 25))
    failed = 0
    for index, question in enumerate(QUESTIONS, 1):
        if index not in selected:
            continue
        print(f"\n{'=' * 88}\nCASE {index}\nQ: {question}", flush=True)
        try:
            data, elapsed = ask(question)
            answer = (data.get("answer") or "").lower().replace("-", " ")
            required, forbidden = CHECKS[index]
            missing = [value for value in required if value.replace("-", " ") not in answer]
            present = [value for value in forbidden if value.replace("-", " ") in answer]
            passed = data.get("source") != "provider-unavailable" and not missing and not present
            print(f"SOURCE: {data.get('source')} MODEL: {data.get('model')} TIME: {elapsed:.1f}s")
            print(f"PAGES: {data.get('pages')}\nA: {data.get('answer')}")
            print(f"ASSERT: {'PASS' if passed else 'FAIL'} missing={missing} forbidden={present}")
            failed += not passed
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR: {exc!r}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
