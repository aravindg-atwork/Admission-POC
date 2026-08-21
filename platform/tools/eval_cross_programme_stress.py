"""Assertions for policy surfaces newly introduced by the 101-question stress set."""

import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8100"
CASES = [
    ("bvsc", "I completed high school in the USA and my subjects are not named exactly Physics, Chemistry, Biology like Indian boards. How will MAFSU check equivalence?", ("association of indian universities", "appropriate authority", "cannot invent"), ("one full year",)),
    ("bvsc", "I am an OCI candidate who studied abroad. Do I apply like NRI or through normal state quota?", ("4 march 2021", "native", "unreserved", "nri/fn/pio/oci"), ()),
    ("bvsc", "If NRI seats remain vacant, can a normal Maharashtra student apply for those seats in special round?", ("yes", "state merit", "rs. 5,000", "special fee"), ()),
    ("bvsc", "If I take a vacant NRI seat in special round, do I have to pay NRI fees for all years?", ("yes", "throughout"), ()),
    ("bvsc", "I got admission under NRI seat and now want to cancel. Will the special NRI fee be refunded?", ("no", "non-refundable"), ()),
    ("bvsc", "What is the difference between VCI quota and MAFSU University quota? Can I apply for both?", ("15%", "independent", "separate procedure", "mafsu"), ("have you appeared",)),
    ("bvsc", "If VCI seats stay vacant, will MAFSU students get those seats in later rounds?", ("state merit", "special round", "government"), ()),
    ("bfsc", "I am EWS but I uploaded only income certificate. Is that enough for EWS reservation?", ("no", "ews eligibility certificate"), ()),
    ("bfsc", "I am physically handicapped with 55% lower limb disability. Can I get admission in BFSc under PH quota?", ("no", "more than 50%"), ()),
    ("bfsc", "I have hearing disability. Can I apply under physically handicapped quota?", ("no", "shall not be admitted"), ("yes, you can",)),
    ("bfsc", "I am from Maharashtra and want only Nagpur College of Fishery Science. How many seats are there?", ("40", "32", "8"), ()),
    ("bfsc", "What is ICAR quota in BFSc and do I apply through MAFSU or through ICAR separately?", ("24", "8 per college", "independent", "icar"), ("have you appeared",)),
    ("bfsc", "I wrote MHT-CET but also CUET ICAR. Can I participate in both University quota and ICAR quota?", ("separate procedures", "mht-cet", "icar"), ("j&k",)),
    ("bfsc", "If ICAR seats remain vacant, will they come back to Maharashtra state merit list?", ("yes", "last", "state merit"), ()),
    ("bfsc", "I am from J&K. Do I need MHT-CET or ICAR-UG for the special quota?", ("not mht-cet", "icar-ug"), ()),
    ("bfsc", "I am NRI and want BFSc. Is there a separate NRI quota and how many seats are there?", ("yes", "10", "over and above"), ()),
    ("bfsc", "If NRI seats stay vacant, can a normal Maharashtra candidate take them in special round?", ("yes", "state merit", "5,000", "special"), ()),
    ("bfsc", "If I get vacant NRI seat in special round, do I have to pay the special dollar fee every semester?", ("yes", "3,000", "per semester", "throughout"), ()),
    ("btech-dairy", "I wrote PCB group in MHT-CET, not PCM. Can I still apply for Dairy Technology?", ("no", "pcm"), ("have you appeared",)),
    ("btech-dairy", "I am from another state and got 55% in 12th. Which entrance exam should I use for management quota?", ("first priority", "mht-cet", "cuet", "remaining"), ("should appear for cuet",)),
    ("btech-dairy", "I am NRI and want Dairy Technology. Is there a separate NRI quota?", ("yes", "10", "over and above"), ()),
    ("btech-dairy", "If I leave after first year with UG certificate, can I come back later and directly join third semester?", ("yes", "third semester", "parent institute", "deficit"), ()),
    ("btech-dairy", "Does Dairy Technology have internship or industrial training in final year?", ("yes", "in-plant", "eighth"), ()),
    ("bvsc", "I'm OBC, have 48% in PCB + English, qualified NEET, but my NCL expired and caste validity is pending. Can I still get reserved admission?", ("47.5", "ncl", "cvc", "50%"), ("reserved admission is confirmed",)),
    ("bfsc", "I am OBC, got 42% in PCB + English, 78 percentile in MHT-CET, my father is a fisherman and I also have NCC B certificate. Am I eligible and what will my corrected merit points be?", ("40%", "12", "2", "92"), ()),
    ("bfsc", "I'm general category with 49% in 12th but 99 percentile in MHT-CET and 12 fisherman weightage points. Can the high CET and weightage make me eligible?", ("no", "50%", "make you eligible"), ()),
    ("btech-dairy", "I am OBC female, got 43% in PCM + English, appeared for MHT-CET, my family owns farmland but farming is not our main income, and my NCL has expired. Am I eligible and which reservations can I actually claim?", ("43%", "40%", "ncl", "horizontal", "cannot claim agriculturist"), ("b.v.sc", "neet")),
    ("btech-dairy", "I am from Karnataka, got 60% in PCM, wrote CUET-ICAR but not Maharashtra CET. Can I take a management quota seat in a private MAFSU Dairy Technology college?", ("potentially", "remaining", "mht-cet", "cuet", "physics, chemistry, mathematics and english"), ()),
    ("bvsc", "I'm general category and got 49% in PCB + English but my NEET score is very good. Can NEET marks compensate for my 12th percentage?", ("no", "50%", "cannot compensate"), ("couldn't verify",)),
    ("bvsc", "I got 47.8% in PCB and English and I'm SC. I qualified NEET. Can I apply for veterinary?", ("yes", "47.5%", "reserved"), ("50.0%",)),
    ("bvsc", "I am outside Maharashtra. Can I get only management quota in private veterinary college or can I apply to constituent colleges also?", ("only", "management", "not constituent"), ("apply to both",)),
    ("bvsc", "I got a seat under OBC but my caste validity is not ready before reporting. Will my admission get cancelled or shifted to open category?", ("13 august 2026", "automatically", "unreserved"), ("will not be automatically",)),
    ("bvsc", "I uploaded my NEET marksheet but it is blurred. Will my application be rejected immediately or will MAFSU allow me to re-upload it?", ("deficient", "re-upload", "failure", "rejection"), ()),
    ("bvsc", "I got a seat in round 1 but I want another college. Do I have to fill preference again for round 2?", ("yes", "again", "depends"), ("don't need",)),
    ("bvsc", "I got Mumbai Veterinary College but I want Nagpur. If I participate in the next round, will I lose my current seat?", ("does not support", "depends", "final"), ("will not lose",)),
    ("bvsc", "My date of birth is 2 January 2010. I have good NEET marks. Can I still take admission?", ("no", "1 january 2010"), ("can still",)),
    ("bvsc", "I studied Biotechnology instead of Biology in 12th. Can I apply for BVSc?", ("accepted", "physics", "chemistry", "english"), ("missing two",)),
    ("bvsc", "I am NRI and completed my 12th in the USA. I did not write NEET. Am I eligible under NRI/FN/PIO/OCI quota?", ("exempt", "50%", "17"), ("mandatory requirement",)),
    ("bfsc", "I have 41% in PCB and English and belong to SC. Is that enough for BFSc?", ("yes", "40%"), ("couldn't verify",)),
    ("bfsc", "My parents own agricultural land. Can I claim agriculturist benefit and fisherman benefit together?", ("one 12-point category", "land ownership alone", "fishing"), ()),
    ("bfsc", "I have 7/12 extract and my father is a farmer. How many extra points will be added to my CET percentile?", ("12", "does not produce 24"), ()),
    ("bfsc", "I got 75 percentile in MHT-CET and 12 weightage points. Will my corrected points become 87?", ("yes", "75 + 12 = 87"), ("couldn't verify",)),
    ("bfsc", "I have caste certificate but no caste validity yet. Can I still submit application under OBC?", ("proof", "15 september 2026", "ncl"), ()),
    ("btech-dairy", "I am reserved category with 41% in PCM + English. Is that enough if I appeared for CET?", ("yes", "40%"), ("couldn't verify",)),
    ("btech-dairy", "I am OBC female. Can I claim both OBC reservation and female reservation?", ("yes", "horizontal", "ncl", "no ews certificate is required"), ("must submit an ews",)),
    ("btech-dairy", "My NCL is expired but caste certificate and caste validity are valid. Will I still get OBC benefit?", ("application", "1 april 2026", "unreserved"), ()),
    ("btech-dairy", "If I get an OBC seat and fail to submit caste validity before the deadline, will I lose admission completely?", ("12 august 2026", "automatically", "unreserved"), ("won't lose",)),
    ("btech-dairy", "Agricultural land is in my grandfather's name. Can I claim AG reservation?", ("paternal", "main-income", "agriculturist certificate"), ("economic holding",)),
    ("btech-dairy", "My father served only 3 years but became permanently disabled during service. Is the 5-year condition still compulsory?", ("does not apply", "permanently disabled"), ()),
    ("btech-dairy", "If I leave after second year with diploma, can I rejoin directly in fifth semester?", ("yes", "fifth semester", "deficit"), ()),
]


def main() -> int:
    failed = 0
    for index, (project, question, required, forbidden) in enumerate(CASES, 1):
        # The API asks which programme a question is about when the client sends
        # no selected programme (the P0 ambiguous-programme guard). The real widget
        # sets conversationState.programme when a student picks a course, so a suite
        # that omits it is not simulating a student - it was silently scoring
        # `programme-clarify` as a miss on every question that names no programme.
        request = urllib.request.Request(
            f"{BASE}/api/chat", method="POST", headers={"Content-Type": "application/json"},
            data=json.dumps({"projectId": project, "question": question, "uiLanguage": "en",
                             "conversationState": {"programme": project}}).encode(),
        )
        try:
            with urllib.request.urlopen(request, timeout=150) as response:
                data = json.loads(response.read().decode())
            answer = (data.get("answer") or "").lower().replace("-", " ")
            missing = [v for v in required if v.replace("-", " ") not in answer]
            present = [v for v in forbidden if v.replace("-", " ") in answer]
            ok = not missing and not present and data.get("source") != "provider-unavailable"
            failed += not ok
            print(f"{'PASS' if ok else 'FAIL'} {index:02} {project:12} [{data.get('source')}] {data.get('answer')}")
            if not ok:
                print(f"    missing={missing} forbidden={present}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {index:02} {project:12} ERROR {exc!r}")
    print(f"\nCROSS-PROGRAMME STRESS DELTA: {len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
