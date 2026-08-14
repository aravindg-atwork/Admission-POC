"""The 80-question admissions evaluation, as a runnable regression suite.

Why this exists alongside bench_answer_quality.py
-------------------------------------------------
bench_answer_quality.py checks FIGURES: it asserts a fee appears and another
programme's fee does not. That is necessary and it is not sufficient. On
2026-08-14 the unknown-programme refusal broke - "what is the fee for the MBA
programme" started returning the program-clarification instead of "we do not
run that course" - and the benchmark stayed green, because its expectation for
that case is `expect=[] forbid=[fees]` and a clarification prompt contains no
figures at all. A suite that can only see numbers cannot see a bot that has
stopped answering.

So the assertions here are about BEHAVIOUR as well as content:

  expect / forbid      as before - strings that must / must not appear
  no_clarify           the answer must not be a "which programme?" bounce.
                       Four evaluation questions were answered that way when
                       they were perfectly answerable (Q14, Q49, Q76, Q79).
  refuse               must say the programme is not covered AND must not
                       quote undergraduate figures at it. Section G asks about
                       M.V.Sc./Ph.D./M.Tech., retired from this deployment on
                       2026-08-14; Q71 answered an M.V.Sc. question using
                       B.V.Sc. migration rules, which is the exact failure.
  answered             must produce a real answer of some substance - catches
                       a question quietly degrading into a refusal, which is
                       how Q35 ("How do I apply for MAFSU admission?") failed.

Ground truth comes from the prospectus PDFs, with page numbers, never from a
previous answer of the assistant's - checking it against its own output only
establishes that it is consistent. Facts that could NOT be confirmed in the
source text (seat totals, the B.V.Sc. course length) are marked manual rather
than guessed: a suite that asserts something unverified is worse than one that
admits it does not know.

Usage:
    ADMIN_TOKEN=... .venv-backend/bin/python3 -u tools/eval_admissions.py
    ... --section C          run one section
    ... --show               print every answer, not just failures
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402
from backend.storage import apikeys  # noqa: E402

BASE = f"http://localhost:{config.PORT}"

# Verified from the 2026-27 prospectuses, with the page each came from.
#   B.V.Sc. & A.H.  50% / 47.50% reserved, PCB-or-Biotech + English   (p4)
#   B.F.Sc.         50% / 40%     reserved, PCB + English             (p10)
#   B.Tech. Dairy   50% / 40%     reserved, PCM + English             (p5)
# All three state the requirement on the subjects "taken together".
CLARIFY_MARKERS = ("which program", "which programme", "please pick one",
                   "ask again naming")
# Written one-per-line deliberately: the first version relied on implicit
# string concatenation across a line break and silently produced "not specify"
# instead of two separate markers, so a correct refusal ("the excerpts... do
# not mention any entrance examination for Ph.D.") was graded as a failure.
REFUSAL_MARKERS = (
    "only cover", "only covers", "does not specify", "doesn't specify",
    "do not specify", "not specified", "does not mention", "do not mention",
    "doesn't mention", "not covered", "only for the", "is only",
    "contact", "admission office", "admissions office", "cannot help",
    "can't help",
)
UG_FIGURES = ("62635", "62,635", "40610", "40,610", "47.50", "47.5")


def C(section, number, question, **kw):
    kw.setdefault("expect", [])
    kw.setdefault("forbid", [])
    return dict(section=section, n=number, q=question, **kw)


CASES = [
    # ---- A. Basic eligibility -------------------------------------------
    C("A", 1, "What is the eligibility criteria for B.V.Sc. & A.H. at MAFSU?",
      expect=["50"], forbid=["B.Tech", "Dairy"], answered=True, no_clarify=True),
    C("A", 2, "What percentage do I need in 12th to apply for B.V.Sc.?",
      expect=["50"], forbid=["40%"], no_clarify=True),
    C("A", 3, "Is NEET mandatory for B.V.Sc. admission at MAFSU?",
      expect=["NEET"], no_clarify=True),
    C("A", 4, "What entrance exam is required for B.F.Sc.?",
      expect=["MHT-CET", "MHT CET"], forbid=["NEET"], no_clarify=True),
    C("A", 5, "What is the minimum percentage required for B.F.Sc.?",
      expect=["50"], no_clarify=True),
    C("A", 6, "What subjects should I have studied in 12th for B.F.Sc.?",
      expect=["Biology"], forbid=["Mathematics"], no_clarify=True),
    C("A", 7, "What is the eligibility for B.Tech. Dairy Technology?",
      expect=["Mathematics"], forbid=["Biology"], no_clarify=True),
    C("A", 8, "Is Mathematics compulsory for B.Tech. Dairy Technology?",
      expect=["Yes", "compulsory", "required"], no_clarify=True),
    C("A", 9, "Which entrance exam is used for B.Tech. Dairy Technology admission?",
      expect=["MHT-CET", "MHT CET"], forbid=["NEET"], no_clarify=True),
    C("A", 10, "How long is the B.V.Sc. & A.H. course?", manual="duration not confirmed in source text"),
    C("A", 11, "How long is the B.F.Sc. course?",
      expect=["four year", "4 year", "eight semester", "8 semester"], no_clarify=True),
    C("A", 12, "How long is the B.Tech. Dairy Technology course?",
      expect=["four year", "4 year", "eight semester", "8 semester"], no_clarify=True),

    # ---- B. Student-style verdicts --------------------------------------
    C("B", 13, "I got 48% in PCB and English. Can I apply for veterinary at MAFSU "
                "if I belong to the reserved category?",
      expect=["47.5", "eligible"], forbid=["40%", "Dairy", "Mathematics"], no_clarify=True),
    C("B", 14, "I studied Physics, Chemistry, Biology and English but didn't have "
                "Mathematics. Which MAFSU courses can I apply for?",
      expect=["B.F.Sc", "BFSc", "Fishery"], no_clarify=True),
    C("B", 15, "I am from another state. Can I apply for MAFSU?", answered=True, no_clarify=True),
    C("B", 16, "I have PCB but not Biotechnology. Am I eligible for B.V.Sc.?",
      expect=["Biology"], no_clarify=True),
    C("B", 17, "I scored 49% in 12th. Am I eligible for B.F.Sc.?",
      # 49% stated as an AGGREGATE cannot answer a subject-combination rule:
      # asking which it is, is the correct behaviour here, not a failure.
      expect=["subject", "Physics", "overall", "aggregate"]),
    C("B", 18, "Can I apply for B.Tech. Dairy Technology with Biology instead of Mathematics?",
      expect=["No", "not"], forbid=["Yes,"], no_clarify=True),
    C("B", 19, "I didn't appear for MHT-CET. Can I still get admission to B.F.Sc.?",
      expect=["No", "must", "mandatory", "cannot"], forbid=["Yes, you can still"], no_clarify=True),
    C("B", 20, "Can I get B.V.Sc. admission without NEET if I have high 12th marks?",
      expect=["No", "cannot", "NEET"], no_clarify=True),
    C("B", 21, "Does MAFSU consider 12th marks or entrance-exam marks for admission?",
      answered=True, no_clarify=True),
    C("B", 22, "I am from the reserved category. What percentage do I need for B.V.Sc.?",
      expect=["47.5"], forbid=["40%"], no_clarify=True),
    C("B", 23, "What happens if my qualifying exam result is awaited when I apply?", answered=True),
    C("B", 24, "Can a student who passed 12th from another board apply to MAFSU?",
      answered=True, no_clarify=True),

    # ---- C. Multi-condition reasoning -----------------------------------
    C("C", 25, "I have 51% overall in 12th but only 45% in PCB and English. Am I "
                "eligible for B.V.Sc.?",
      expect=["not eligible"], forbid=["You are eligible"], no_clarify=True),
    C("C", 26, "I have 50% in PCB but I'm from the reserved category. Am I eligible?",
      manual="genuinely ambiguous which programme - clarification is defensible"),
    C("C", 27, "I am eligible for B.V.Sc. but my NEET score is low. Does MAFSU have "
                "any separate entrance examination?",
      expect=["No", "NEET"], no_clarify=True),
    C("C", 28, "If I qualify for NEET, does that automatically guarantee admission to MAFSU?",
      expect=["No", "not guarantee"], forbid=["40%"], no_clarify=True),
    C("C", 29, "Can I apply for both B.F.Sc. and B.Tech. Dairy Technology using the "
                "same MHT-CET score?", answered=True, no_clarify=True),
    C("C", 30, "What is the difference between the admission process for B.V.Sc. and "
                "B.F.Sc. at MAFSU?",
      expect=["NEET"], forbid=["Dairy Technology"], no_clarify=True),
    C("C", 31, "Which MAFSU undergraduate courses require NEET and which require MHT-CET?",
      expect=["NEET"], no_clarify=True),
    C("C", 32, "I studied PCB in 12th. Can you tell me all the MAFSU undergraduate "
                "courses for which I am eligible?",
      expect=["B.F.Sc", "BFSc", "Fishery"], forbid=["only"], no_clarify=True),
    C("C", 33, "I studied PCM. Which MAFSU courses can I apply for?",
      expect=["Dairy", "B.Tech"], forbid=["B.V.Sc"], no_clarify=True),
    C("C", 34, "What are the minimum marks and entrance exam requirements for all "
                "three undergraduate courses?",
      expect=["47.5"], no_clarify=True),

    # ---- D. Application process -----------------------------------------
    C("D", 35, "How do I apply for MAFSU admission?", answered=True, no_clarify=True,
      forbid=["can't help with that course", "only cover admissions"]),
    C("D", 36, "Where can I find the MAFSU prospectus?", answered=True, no_clarify=True,
      forbid=["can't help with that course", "only cover admissions"]),
    C("D", 37, "When does the MAFSU application form open?",
      forbid=["item 1", "the table", "Admission Programme table"], answered=True),
    C("D", 38, "What documents are required while applying?", answered=True, no_clarify=True),
    C("D", 39, "Can I edit my application after submitting it?", answered=True, no_clarify=True),
    C("D", 40, "What happens if I make a mistake in my application form?", answered=True),
    C("D", 41, "How do I pay the application fee?", expect=["1000", "1,000"], no_clarify=True),
    C("D", 42, "Can I apply for more than one course?", manual="prospectus wording unclear"),
    C("D", 43, "Is there a separate application form for B.V.Sc. and B.F.Sc.?", manual="unverified"),
    C("D", 44, "How can I check my application status?", answered=True),
    C("D", 45, "Where will MAFSU publish the merit list?", expect=["mafsu.ac.in", "website"]),
    C("D", 46, "How will I know if I have been selected?", answered=True),
    C("D", 47, "What happens after the merit list is published?", answered=True),
    C("D", 48, "What documents do I need during counselling/admission?", answered=True),

    # ---- E. Reservation --------------------------------------------------
    C("E", 49, "What is the reservation policy for MAFSU admission?", answered=True, no_clarify=True),
    C("E", 50, "What percentage is required for SC/ST/OBC candidates?",
      expect=["47.5"], forbid=["do not list", "does not list", "no separate"], no_clarify=True),
    C("E", 51, "What documents are required to claim reservation?",
      expect=["caste"], answered=True, no_clarify=True),
    C("E", 52, "Can I claim Maharashtra reservation if I studied outside Maharashtra?",
      answered=True, no_clarify=True),
    C("E", 53, "Is a caste certificate mandatory during admission?", answered=True, no_clarify=True),
    C("E", 54, "What is the eligibility percentage for reserved candidates in B.V.Sc.?",
      expect=["47.5"], forbid=["40%"], no_clarify=True),
    C("E", 55, "Are there seats reserved for EWS candidates?", expect=["EWS"], no_clarify=True),
    C("E", 56, "What are the rules for PwD candidates?", answered=True, no_clarify=True),
    C("E", 57, "Does MAFSU have a Maharashtra domicile requirement?", answered=True, no_clarify=True),

    # ---- F. Fees, colleges, seats ---------------------------------------
    C("F", 58, "What is the tuition fee for B.V.Sc. at MAFSU?",
      expect=["62635", "62,635"], forbid=["40610", "40,610"], no_clarify=True),
    C("F", 59, "How much does the complete B.V.Sc. course cost?", manual="total not confirmed in source"),
    C("F", 60, "What is the hostel fee at MAFSU?", answered=True),
    C("F", 61, "Is hostel accommodation compulsory?", answered=True),
    C("F", 62, "Which colleges under MAFSU offer B.V.Sc.?",
      expect=["Nagpur"], no_duplicates=True, no_clarify=True),
    C("F", 63, "Which MAFSU college is closest to Mumbai?", expect=["Mumbai"], no_clarify=True),
    C("F", 64, "Where is B.F.Sc. offered under MAFSU?",
      expect=["Fishery"], no_duplicates=True, no_clarify=True),
    C("F", 65, "Which colleges offer B.Tech. Dairy Technology?",
      expect=["Dairy"], no_duplicates=True, no_clarify=True),
    C("F", 66, "How many seats are available for B.V.Sc.?", answered=True),
    C("F", 67, "How many seats are available for B.F.Sc.?", answered=True),
    C("F", 68, "How many seats are available for B.Tech. Dairy Technology?", answered=True),

    # ---- G. Retired postgraduate programmes: the traps -------------------
    C("G", 69, "What are the eligibility requirements for M.V.Sc. admission?", refuse=True),
    C("G", 70, "What entrance examination is required for M.V.Sc.?", refuse=True),
    C("G", 71, "Can I apply for M.V.Sc. if my veterinary degree is from another university?",
      refuse=True, forbid=["Yes, you can apply for M.V.Sc"]),
    C("G", 72, "What are the eligibility requirements for Ph.D. admission at MAFSU?", refuse=True),
    C("G", 73, "What is the admission process for Ph.D. at MAFSU?", refuse=True),
    C("G", 74, "Is there an entrance examination for Ph.D. admission?", refuse=True),
    C("G", 75, "What subjects or specializations are available for Ph.D.?", refuse=True),
    C("G", 76, "What is the minimum percentage required for Ph.D. admission?", refuse=True),
    C("G", 77, "Can a candidate with a degree from another university apply for MAFSU Ph.D.?",
      refuse=True),
    C("G", 78, "What documents are required for Ph.D. admission?", refuse=True),
    C("G", 79, "What is the duration of the Ph.D. programme?", refuse=True),
    C("G", 80, "What is the eligibility for M.Tech. Dairy Technology?", refuse=True),
]

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def _norm(text):
    return re.sub(r"[,\s]", "", (text or "").translate(_DEVANAGARI_DIGITS)).lower()


def _duplicate_lines(text):
    lines = [l.strip() for l in (text or "").splitlines() if len(l.strip()) > 12]
    seen, dupes = set(), []
    for line in lines:
        if line in seen:
            dupes.append(line)
        seen.add(line)
    return dupes


def _ask(question, key, timeout=240):
    body = json.dumps({"question": question, "uiLanguage": "en"}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/chat", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": key})
    started = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode()), time.time() - started


def grade(case, answer):
    """Every reason this answer fails, or [] if it passes."""
    flat, low = _norm(answer), (answer or "").lower()
    problems = []

    if case.get("answered"):
        if any(m in low for m in CLARIFY_MARKERS) or "can't help with that course" in low:
            problems.append("declined a question that is in scope")
        elif len(low.split()) < 4:
            problems.append("no real answer")
    if case.get("no_clarify") and any(m in low for m in CLARIFY_MARKERS):
        problems.append("bounced back a 'which programme?' clarification")
    if case.get("refuse"):
        if not any(m in low for m in REFUSAL_MARKERS):
            problems.append("did NOT say the programme is uncovered")
        leaked = [f for f in UG_FIGURES if _norm(f) in flat]
        if leaked:
            problems.append(f"answered a retired PG question with UG figures: {leaked}")
    if case.get("no_duplicates"):
        dupes = _duplicate_lines(answer)
        if dupes:
            problems.append(f"duplicated list entry: {dupes[0][:44]!r}")

    expect = case.get("expect") or []
    if expect and all(_norm(e) not in flat for e in expect):
        problems.append(f"missing any of {expect}")
    present = [f for f in (case.get("forbid") or []) if _norm(f) in flat]
    if present:
        problems.append(f"contains forbidden {present}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--section", help="run only this section letter")
    ap.add_argument("--show", action="store_true", help="print every answer")
    args = ap.parse_args()

    keys = [k for k in apikeys.list_keys(config.DEFAULT_PROJECT_ID) if k.get("active")]
    if not keys:
        print("no active key on the default project")
        return 1
    key = keys[0]["key"]

    cases = [c for c in CASES if not args.section or c["section"] == args.section.upper()]
    passed = failed = 0
    manual, failures, slow = [], [], []
    total = 0.0

    for case in cases:
        if case.get("manual"):
            manual.append((case["n"], case["q"], case["manual"]))
            continue
        try:
            data, elapsed = _ask(case["q"], key)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            failures.append((case, [f"request failed: {exc!r}"], ""))
            print(f"  FAIL  Q{case['n']:<3} {case['q'][:52]:54} request failed")
            continue
        total += elapsed
        if elapsed > 15:
            slow.append((case["n"], elapsed))
        answer = data.get("answerText") or data.get("error") or ""
        problems = grade(case, answer)
        if problems:
            failed += 1
            failures.append((case, problems, answer))
            print(f"  FAIL  Q{case['n']:<3} {case['q'][:52]:54} {elapsed:5.1f}s  {problems[0][:46]}")
        else:
            passed += 1
            print(f"  ok    Q{case['n']:<3} {case['q'][:52]:54} {elapsed:5.1f}s")
        if args.show:
            print(f"        {answer[:300]}")

    graded = passed + failed
    print("\n" + "=" * 78)
    print(f"RESULT: {passed}/{graded} graded   ({len(manual)} manual)   "
          f"avg {total / max(graded, 1):.1f}s")
    if slow:
        print(f"\nSLOW (>15s): " + ", ".join(f"Q{n} {t:.0f}s" for n, t in slow))
    if failures:
        print("\nFAILURES:")
        for case, problems, answer in failures:
            print(f"\n  [{case['section']}] Q{case['n']}: {case['q']}")
            for problem in problems:
                print(f"      - {problem}")
            if answer:
                print(f"      got: {answer[:200].strip()}")
    if manual:
        print("\nMANUAL (not auto-graded - ground truth unconfirmed in the PDFs):")
        for number, question, why in manual:
            print(f"  Q{number}: {question[:60]}  [{why}]")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
