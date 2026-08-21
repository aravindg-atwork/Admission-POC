"""User-supplied B.F.Sc. promotion gate: 17 multi-rule scenarios."""

import argparse
import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8100"
QUESTIONS = [
    "I am OBC from Maharashtra and got 43% in Physics, Chemistry, Biology and English together in 12th. I appeared for MHT-CET 2026. Am I eligible for B.F.Sc., and what documents do I need to claim OBC reservation?",
    "I got 55% in PCB and English in 12th but I did not appear for MHT-CET 2026. Can I still apply for B.F.Sc. based on my 12th marks?",
    "I have 48% in PCB and English and I belong to General category, but my MHT-CET percentile is good. Can I get admission or is 50% in 12th compulsory?",
    "I am SC and have 41% in PCB and English. I appeared for MHT-CET 2026. Am I eligible for B.F.Sc., or do I also need 50% in 12th?",
    "I am 16 years old now and my 17th birthday is on 20 December 2026. Can I apply for B.F.Sc. admission this year?",
    "My date of birth is 10 January 2010. I have good MHT-CET marks and meet the 12th eligibility. Am I eligible for B.F.Sc. 2026-27?",
    "I got 82 percentile in PCB in MHT-CET. My parents are farmers and we have agricultural land. Will I get any extra points in the B.F.Sc. merit list, and how will my final merit score be calculated?",
    "My father is a fisherman and fishing is his main source of income. I got 70 percentile in MHT-CET. Is there any benefit or extra weightage for fishermen's children, and which certificate should I submit?",
    "I studied Fresh Water Fish Culture as a vocational subject in 11th and 12th. Will I get additional marks for B.F.Sc. admission? Will those marks be added to my MHT-CET percentile?",
    "I have an NCC B certificate and also participated in sports. Can I claim weightage for both, and what is the maximum additional weightage I can get?",
    "I am an OBC female candidate. Will I get both OBC reservation and female reservation for B.F.Sc., or can I claim only one of them?",
    "I am OBC and have a caste certificate, but my Non-Creamy Layer certificate has expired. Can I still apply under OBC and submit a new NCL certificate later?",
    "I have applied for my caste validity certificate but haven't received it yet. Can I apply for B.F.Sc. under reserved category with proof that I have submitted the caste validity application?",
    "I got a B.F.Sc. seat under OBC in the first round, but my caste validity certificate is still pending. How long do I have to submit it, and what happens to my admission if I don't submit it?",
    "How many B.F.Sc. colleges are there under MAFSU? I want Nagpur as my first preference, but if I don't get Nagpur can I choose Udgir or Morshi?",
    "How many B.F.Sc. seats are available in Nagpur, Udgir and Morshi, and how many of those seats are under University quota and ICAR quota?",
    "I want admission through ICAR quota. Do I have to apply through the MAFSU admission process or does ICAR conduct separate admission for those seats?",
]

CHECKS = {
    1: (("43%", "40%", "mht-cet", "caste certificate", "caste validity", "non-creamy"), ("not eligible",)),
    2: (("not", "mht-cet"), ("eligible based",)),
    3: (("48%", "50%", "cannot compensate"), ()),
    4: (("41.0%", "40.0%", "meet"), ("need 50%",)),
    5: (("yes", "31 december 2026"), ("not eligible", "no.")),
    6: (("no", "1 january 2010"), ("eligible for b.f.sc",)),
    7: (("12", "82 + 12 = 94", "20"), ()),
    8: (("12", "70 + 12 = 82", "fisherman"), ()),
    9: (("10", "mht-cet", "20"), ("no additional",)),
    10: (("2", "4 additional", "20"), ()),
    11: (("both", "30%", "horizontal", "obc"), ("only one",)),
    12: (("1 april 2026", "application", "unreserved"), ("submit later" ,)),
    13: (("proof", "15 september 2026", "unreserved"), ()),
    14: (("15 september 2026", "automatically cancels", "second round"), ()),
    15: (("three", "nagpur", "udgir", "morshi"), ()),
    16: (("40", "32", "8", "120", "96", "24"), ()),
    17: (("separate", "independent", "icar"), ("apply through mafsu",)),
}


def ask(question: str) -> tuple[dict, float]:
    # The API asks which programme a question is about when the client sends
    # no selected programme (the P0 ambiguous-programme guard). The real widget
    # sets conversationState.programme when a student picks a course, so a suite
    # that omits it is not simulating a student - it was silently scoring
    # `programme-clarify` as a miss on every question that names no programme.
    request = urllib.request.Request(
        f"{BASE}/api/chat", method="POST", headers={"Content-Type": "application/json"},
        data=json.dumps({"projectId": "bfsc", "question": question, "uiLanguage": "en",
                         "conversationState": {"programme": "bfsc"}}).encode(),
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=150) as response:
        return json.loads(response.read().decode()), time.time() - started


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases")
    args = parser.parse_args()
    selected = {int(v) for v in args.cases.split(",")} if args.cases else set(range(1, 18))
    failed = 0
    for index, question in enumerate(QUESTIONS, 1):
        if index not in selected:
            continue
        print(f"\n{'=' * 88}\nCASE {index}\nQ: {question}", flush=True)
        try:
            data, elapsed = ask(question)
            print(f"SOURCE: {data.get('source')} MODEL: {data.get('model')} TIME: {elapsed:.1f}s")
            print(f"PAGES: {data.get('pages')}\nA: {data.get('answer')}", flush=True)
            answer = data.get("answer", "").lower()
            required, forbidden = CHECKS[index]
            missing = [value for value in required if value not in answer]
            present = [value for value in forbidden if value in answer]
            passed = data.get("source") != "provider-unavailable" and not missing and not present
            print(f"ASSERT: {'PASS' if passed else 'FAIL'} missing={missing} forbidden={present}")
            failed += not passed
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR: {exc!r}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
