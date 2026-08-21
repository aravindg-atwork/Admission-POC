"""User-supplied B.V.Sc. promotion gate: multi-rule admissions scenarios."""

import json
import argparse
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8100"
sys.stdout.reconfigure(encoding="utf-8")

QUESTIONS = [
    "I am OBC from Maharashtra and I got 48% in Physics, Chemistry, Biology and English together in 12th. I have also qualified NEET-UG 2026. Am I eligible for B.V.Sc. admission in MAFSU, and do I need an NCL certificate for OBC reservation?",
    "I belong to the General category and have 49.6% in PCB and English together, but I got a good NEET-UG 2026 score. Can my NEET marks compensate for my 12th percentage, or am I not eligible for B.V.Sc.?",
    "I am from Maharashtra, but I completed my 12th from a school outside Maharashtra. My father has a Maharashtra domicile certificate and has been living in Maharashtra for several years. Can I apply for MAFSU B.V.Sc., and will I be considered under regional quota or state quota?",
    "I am from Madhya Pradesh and completed my 10th and 12th there. I qualified NEET-UG 2026 and want to study B.V.Sc. in Maharashtra. Can I apply to Nagpur Veterinary College, or am I only eligible for management quota seats in MAFSU-affiliated private colleges?",
    "I have qualified NEET and I meet the 12th percentage requirement, but I will turn 17 only in February 2027. Can I still take admission for the 2026-27 B.V.Sc. batch?",
    "I am OBC and have my caste certificate, but my Non-Creamy Layer certificate is not ready yet. Can I submit the B.V.Sc. application now and upload the NCL certificate later? What happens if I cannot submit it before document verification?",
    "I accidentally uploaded a blurred 12th marksheet while filling my B.V.Sc. application. Will my application be rejected immediately, or will MAFSU give me another chance to upload the correct document?",
    "My name appeared in the provisional merit list, but my category or marks are shown incorrectly. How can I raise a grievance, how much do I need to pay, and can I upload a new certificate while submitting the grievance?",
    "I got a seat in the first admission round, but it is not my preferred veterinary college. If I want a better college in the next round, do I need to fill the preference form again? What happens to my current allotted seat?",
    "I have been allotted a B.V.Sc. seat through MAFSU. What exactly do I need to do after allotment? Do I have to personally visit the college, and should I carry original documents or are photocopies enough?",
    "I am from Pune district and want admission to Mumbai Veterinary College. Since MAFSU has regional and state quotas, can I still select Mumbai as my preference, or am I restricted to the veterinary college belonging to my region?",
    "I am from another state and want a management quota seat in a private veterinary college affiliated with MAFSU. Do I have to approach the private college directly, or will MAFSU allot the management quota seat? Is NEET compulsory for management quota too?",
    "I took admission in a B.V.Sc. college through MAFSU but now I have received admission somewhere else and want to cancel my seat. How do I cancel my admission, and how much of my fees will be refunded if I cancel 10 days after classes start?",
    "I am a female OBC candidate from Maharashtra. Is there a separate reservation for female students in addition to OBC reservation? How will my seat be considered under the University quota?",
    "I studied Physics, Chemistry and Biotechnology in 12th instead of Biology. I have English as a subject and have qualified NEET-UG 2026. Can I still apply for B.V.Sc. & A.H. at MAFSU?",
    "I wanna apply for BVSC NRI abroad quota and I have not completed any entrance like NEET exams. I am eligible for this quota, right? I completed my 12th in the USA.",
    "I am an NRI candidate, but I completed my 12th in India and did not appear for NEET-UG-2026. Does the NRI quota exempt me from NEET?",
    "I completed XII abroad and have not appeared for NEET. Does that alone confirm I am eligible for the B.V.Sc. NRI/FN/PIO/OCI quota?",
]

# Each inner tuple is an OR-group; every group must be represented.
CHECKS = [
    ([('47.5',), ('non-creamy', 'ncl'), ('meet',)], []),
    ([('not eligible',), ('cannot make up', 'cannot compensate', "can't compensate")], ['you are eligible']),
    ([('30% state quota', 'state quota'), ('not the 70%', 'not regional', 'only for the 30%')], []),
    ([('management quota',), ('private veterinary',), ('not at nagpur', 'not eligible for nagpur', 'not eligible for the university quota')], []),
    ([('cannot', 'no,'), ('31 december 2026',)], []),
    ([('non-creamy', 'ncl'), ('unreserved',), ('reject',)], []),
    ([('resubmission', 'upload the correct', 'upload only the indicated'), ('risk', 'reject')], []),
    ([('rs. 200', 'rs.200', '₹200'), ('no documents', 'cannot upload', 'no additional documents'), ('grievance',)], []),
    ([('every admission round', 'every round'), ('cannot change college', 'depends on the quota round')], []),
    ([('personally visit',), ('original documents',), ('self-attested photocopies',)], []),
    ([('mumbai',), ('regional quota', 'region quota'), ('state quota',)], []),
    ([('mafsu will allot', 'mafsu fills'), ('neet-ug-2026',), ('do not approach', "don't approach", 'do not seek direct')], []),
    ([('associate dean', 'principal'), ('80%',), ('10 days', 'ten days', '15 days or less')], []),
    ([('30%',), ('female',), ('obc',)], []),
    ([('biotechnology',), ('cannot confirm full eligibility', 'must also meet'), ('percentage',)], ['you satisfy both']),
    ([('exempt',), ('abroad', 'usa'), ('50%',), ('17',), ('nri/fn/pio/oci',)], ['not eligible because you did not appear']),
    ([('must have appeared',), ('india',), ('only', 'applies only')], ['you are exempt from neet']),
    ([('does not by itself',), ('50%',), ('17',), ('documents', 'status')], ['final eligibility is confirmed']),
]


def ask(question: str) -> tuple[dict, float]:
    # The API asks which programme a question is about when the client sends
    # no selected programme (the P0 ambiguous-programme guard). The real widget
    # sets conversationState.programme when a student picks a course, so a suite
    # that omits it is not simulating a student - it was silently scoring
    # `programme-clarify` as a miss on every question that names no programme.
    request = urllib.request.Request(
        f"{BASE}/api/chat",
        data=json.dumps({"projectId": "bvsc", "question": question, "uiLanguage": "en",
                         "conversationState": {"programme": "bvsc"}}).encode(),
        method="POST", headers={"Content-Type": "application/json"},
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=150) as response:
        return json.loads(response.read().decode()), time.time() - started


def norm(text: str) -> str:
    return text.lower().replace("-", " ").replace("–", " ").replace("—", " ")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", help="comma-separated 1-based case numbers")
    args = parser.parse_args()
    selected = {int(value) for value in args.cases.split(",")} if args.cases else set(range(1, len(QUESTIONS) + 1))
    failed = 0
    for index, question in enumerate(QUESTIONS, 1):
        if index not in selected:
            continue
        print(f"\n{'=' * 88}\nCASE {index}\nQ: {question}", flush=True)
        try:
            data, elapsed = ask(question)
            print(f"SOURCE: {data.get('source')}  MODEL: {data.get('model')}  TIME: {elapsed:.1f}s")
            print(f"PAGES: {data.get('pages')}\nA: {data.get('answer')}", flush=True)
            answer = norm(data.get("answer") or "")
            groups, forbidden = CHECKS[index - 1]
            missing = [group for group in groups if not any(norm(term) in answer for term in group)]
            present = [term for term in forbidden if norm(term) in answer]
            passed = not missing and not present and data.get("source") != "provider-unavailable"
            failed += not passed
            print(f"VERDICT: {'PASS' if passed else 'FAIL'}"
                  + (f"  missing={missing} forbidden={present}" if not passed else ""), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc!r}", flush=True)
            failed += 1
    print(f"\nPROMOTION GATE: {len(selected) - failed}/{len(selected)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
