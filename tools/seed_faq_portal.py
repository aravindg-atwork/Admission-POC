"""Seed the FAQ cache with procedural facts from the admissions PORTAL's own FAQ
page (https://admissions.mafsu.ac.in/mafsu_admission/dashboard/index.aspx), not
the prospectus PDF.

This is a genuinely different source from tools/seed_faq.py: the prospectus
covers eligibility/fees/dates, but the portal's own FAQ is where the actual
step-by-step "how do I use this website" procedure lives (registration, document
upload mechanics, password recovery, resubmission) - none of which the ingested
PDF describes in this much operational detail, so RAG over the prospectus alone
gave thin, generic answers to these questions (e.g. "What should be done before
submission of online application?" came back as two sentences instead of the
real multi-step checklist). Confirmed with a live before/after comparison against
the running app, not assumed.

English only, because that's the only language this content was provided in -
unlike tools/seed_faq.py's Hindi/Marathi entries (hand-written and cross-checked,
per that file's own docstring), a translation here would be this tool inventing
wording never verified against the source, exactly what that docstring warns
against. Add hi/mr versions later only if someone hand-writes and checks them
the same way.

No `pages` for any of these - this content lives on the portal, not in the
ingested prospectus, so there's no PDF page to cite. Same fact-then-code caching
mechanism as seed_faq.py otherwise: DETERMINISTIC (hand-written, not generated),
PERMANENT (seeded entries are exempt from pruning), FREE (skips the LLM call).

Usage:
  python tools/seed_faq_portal.py               # seed against the running backend
  python tools/seed_faq_portal.py --dry-run     # print the payload, seed nothing
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.environ.get("BACKEND_URL", "http://localhost:5050")
ADMIN = os.environ.get("ADMIN_TOKEN", "poc-admin-dev-token")
# This content is program-agnostic (portal login/upload/password mechanics
# are identical regardless of which degree course you're applying for), so
# it's meant to be seeded into every program's project, not just "default" -
# override via PROJECT_ID env var or --project.
PROJECT = os.environ.get("PROJECT_ID", "default")

# Each row: (question, answer) - rewritten into SYSTEM_PROMPT_BASE's style
# (lead with the answer, plain spoken prose, no markdown/bullets/numbered
# lists) from the portal FAQ's own step-by-step wording, not paraphrased
# loosely - every step from the source is preserved, just written as prose.
FACTS = [
    ("What should be done before submission of the online application?",
     "Before submitting the online application, log on to the university "
     "website (www.mafsu.ac.in), click the concerned degree course, and read "
     "the prospectus carefully to understand the eligibility conditions, "
     "reservation and weightage that apply to you - you can save or print it "
     "for reference. List out the documents and certificates you'll need for "
     "your candidature, then scan them carefully with clear, readable "
     "content; avoid scanning with a mobile camera, since it's your "
     "responsibility to scan documents correctly. If a document has two "
     "sides, or you need to upload more than one certificate in the same "
     "place (for example two 12th-standard mark sheets, or an affidavit "
     "alongside a Freedom Fighter certificate), combine them into a single "
     "PDF. Save each scanned file with a clear, descriptive name - like "
     "\"Agriculturist certificate\" or \"SSC mark sheet\" - so you upload the "
     "right document in the right place."),

    ("How do I register on the admissions portal?",
     "Click the concerned degree course on the admissions website, then "
     "click \"New User\" (as opposed to \"Registered User\", which is for "
     "someone already registered). Select the quota that applies to your "
     "candidature, then carefully fill in the mandatory fields - name, caste "
     "category, date of birth, mobile number, email, gender and so on - "
     "since every university notification is sent to the mobile number and "
     "email you enter here. Once payment is made, the details filled into "
     "the registration form can no longer be modified or edited."),

    # "Register"/"registration" genuinely means two different things in this
    # domain, both correct: the portal's account signup (above, BEFORE
    # applying) versus the prospectus's post-allotment academic registration
    # at the college with the Associate Dean (Part II SS2 - in-person only,
    # signed by student/counsellor/teachers, no in-absentia). A short "How to
    # Register?" doesn't say which one the student means. Before this entry,
    # a stale auto-cached answer to that exact bare phrasing (from an earlier
    # RAG generation, before this file existed) silently won on exact-text
    # match and only ever gave the academic-registration half - accurate on
    # its own, but a wrong answer for a student asking about the portal
    # signup, which is a much more common thing to ask "how do I register"
    # about. This disambiguates instead of picking a winner.
    ("How to Register?",
     "There are two different things called \"registration\" here. If you "
     "mean creating your account on the admissions portal, before applying: "
     "click the concerned degree course, then click \"New User\" (not "
     "\"Registered User\"), select your quota, and carefully fill in the "
     "mandatory fields - name, caste category, date of birth, mobile number, "
     "email, gender and so on - since every university notification goes to "
     "the mobile number and email you enter; once you make payment, these "
     "details can no longer be edited. If you mean the academic registration "
     "for your 1st professional year after being allotted a seat: you "
     "register in person with the Associate Dean at your allotted college, "
     "with your registration form signed by you, your counsellor and your "
     "teachers within the prescribed window - in-absentia registration is "
     "not allowed, and missing the deadline cancels your admission."),

    ("How do I fill up the online application form after registering?",
     "Log in as \"Registered User\" using the username and password you "
     "received after registration. Fill in all the required details and "
     "upload the relevant scanned documents in JPG or PDF format only. You "
     "can use the \"Back\" button to return to an earlier page and make "
     "changes - except to the registration page itself - any time before "
     "final submission, and you can complete the form in one sitting or "
     "across multiple sessions, any time up to the last date. Before "
     "submitting, refer to the document checklist to confirm everything "
     "required has been uploaded, and preview the filled form and documents "
     "for correctness and readability - only click \"submit\" once you're "
     "satisfied, since no changes are possible after that. You'll receive an "
     "SMS and email confirming successful submission; you can then print the "
     "submitted application for your records, and should note down your "
     "application number and password."),

    ("What precautions should be taken while uploading certificates or documents?",
     "Upload good-quality photographs or scans of your documents, and "
     "preview each one after uploading to check it's actually readable. Keep "
     "each scanned document under 5MB - if it's larger, reduce its size or "
     "save it as a PDF. Google Chrome or an up-to-date version of Internet "
     "Explorer (9 or later) works best for the portal. You can withdraw or "
     "re-upload a document any time before your final submission, but "
     "nothing can be edited or uploaded once the final submission is made."),

    ("How do I check, preview or print my submitted application form?",
     "After final submission, click \"Print Application\" to get a printout "
     "of the application form. Any time before the last date for "
     "submission, you can log back in as \"Registered User\" to view your "
     "submitted application again. If you notice incorrect entries or "
     "documents in what you submitted, you can submit a fresh new "
     "application before the last date - only your latest, fully-completed "
     "application is considered for the merit list if you submit more than "
     "one."),

    ("What should I do if I forgot my application password?",
     "Click the degree course you applied for, then click \"Registered "
     "User\" to reach the login page, and click \"Forgot Password\". Enter "
     "your application number and your registered mobile number, then click "
     "submit - your password will be sent to you by SMS on your registered "
     "mobile number and by email."),

    ("How do I know if my application was submitted properly?",
     "You'll receive an SMS and email confirming final submission of your "
     "application. You can also log in as \"Registered User\" with your "
     "user ID and password to check: if the form no longer shows \"Submit\" "
     "or \"Back\" buttons, it has been submitted successfully. If you see a "
     "blinking message at the top saying \"You are requested to submit the "
     "application\", it has not been finally submitted yet, and you should "
     "click submit."),

    ("What is the resubmission facility for the application?",
     "After the last date for submission, applications are scrutinized, and "
     "candidates whose documents are deficient or incorrect are listed on "
     "the website with an opportunity to upload the missing or corrected "
     "documents online before a separately notified date. It is the "
     "candidate's own responsibility to fix any such deficiency within that "
     "window."),

    ("How will I know about the merit list, option filling, allotment or reporting schedule?",
     "You should check the university website frequently for updates on the "
     "admission schedule, and you'll also receive an SMS and email at every "
     "step of the admission process, following the schedule in the "
     "admission programme."),

    ("When do I need to fill the option or preference form?",
     "You need to log in and submit the option (preference) form during "
     "every round of admission you want to be considered for - if you don't "
     "submit it for a given round, you won't be considered for admission in "
     "that round."),
]


def build_items():
    return [
        {"question": q, "answer": a, "pages": [], "tags": {"ui_language": "en"}}
        for q, a in FACTS
    ]


def req(method, path, headers=None, body=None, timeout=60):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--project", default=PROJECT,
                    help="Project id to seed into (default: %(default)s, or PROJECT_ID env var)")
    args = ap.parse_args()

    items = build_items()
    print(f"{len(FACTS)} portal-FAQ facts, English only = {len(items)} entries")

    if args.dry_run:
        print(json.dumps(items[:2], ensure_ascii=False, indent=2))
        return 0

    status, result = req("POST", f"/admin/projects/{args.project}/cache/seed",
                         {"X-Admin-Token": ADMIN}, {"items": items})
    if status != 200:
        print(f"FAILED: status={status} {result}")
        return 1
    print(f"Seeded {result.get('seeded')} entries into project {args.project!r}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
