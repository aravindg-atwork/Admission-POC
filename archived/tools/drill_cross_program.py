"""Cross-program fact drill: audit live comparison answers against the PDFs.

Written after a real 2026-08-13 failure - an "admission fee for all courses"
answer reported the Ph.D. reservation fee as Rs. 25,110, a figure that occurs
nowhere in the Ph.D. prospectus (it is M.V.Sc./M.Tech's number, which was
sitting in the same combined context), and reported Rs. 30,310 as Ph.D.'s
UNRESERVED fee when that is actually its reservation fee. Five of the six
programs in that answer were correct, which is precisely what makes this
class of error dangerous: nothing about the reply looks wrong.

What it does, per question:
  1. asks a cross-program question through the live /api/chat
  2. splits the answer into per-program segments
  3. extracts every number stated in each segment
  4. checks each number against the FULL TEXT of that program's own PDF -
     not the retrieved excerpts, so this is an independent audit rather
     than a re-run of the same check the pipeline already applies

A number missing from the program's own document is a hard failure: the
assistant attributed a figure to a prospectus that does not contain it.

Deliberately NOT asserting the labels are right (that "unreserved" really is
the unreserved figure) - that needs semantic checking this harness cannot do
deterministically, and claiming otherwise would be the same overconfidence
being audited for. Every number is printed with its context so a human can
eyeball the labelling; see the REVIEW section in the output.

Run:  .venv-backend/bin/python3 tools/drill_cross_program.py
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.programs import PROGRAM_NAMES  # noqa: E402
from backend.storage import apikeys, projects  # noqa: E402
from backend import config  # noqa: E402

BASE = f"http://localhost:{config.PORT}"

QUESTIONS = [
    "what is the admission fee for all courses",
    "how many quotas are there for each course",
    "what is the minimum percentage needed for each course",
    "how many seats are there in each course",
    "which entrance exam does each course need",
]

# Numbers that are never program facts - years, and the small ordinals that
# show up in "1st year"/"10+2"/"Round 2" phrasing. Including them would bury
# every real finding under noise.
_IGNORE = {"2024", "2025", "2026", "2027", "10", "12", "2", "3", "4", "5", "1"}
_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")


def _pdf_text(project_id):
    from pypdf import PdfReader
    path = projects.prospectus_path(project_id)
    if not path.exists():
        return None
    out = []
    for page in PdfReader(str(path)).pages:
        try:
            out.append(page.extract_text(extraction_mode="layout") or "")
        except Exception:  # noqa: BLE001 - one unreadable page must not stop the audit
            continue
    # Strip separators so "49,910" in the answer matches "49910" in the PDF
    # and vice versa - the documents are inconsistent about this themselves
    # (M.Tech writes "Rs. 25,110/-" where M.V.Sc. writes "Rs. 25110/-").
    return re.sub(r"[,\s]", "", "".join(out))


def _segments(reply):
    marks = []
    for pid, name in PROGRAM_NAMES.items():
        head = name.split()[0]
        for m in re.finditer(re.escape(head), reply):
            marks.append((m.start(), pid))
    marks.sort()
    segs = {}
    for i, (start, pid) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(reply)
        segs.setdefault(pid, []).append(reply[start:end])
    return {pid: " ".join(parts) for pid, parts in segs.items()}


def _ask(question, key):
    body = json.dumps({"question": question, "uiLanguage": "en"}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/chat", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": key})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())


def main():
    keys = [k for k in apikeys.list_keys(config.DEFAULT_PROJECT_ID) if k.get("active")]
    if not keys:
        print("No active key for the default project.")
        return 1
    key = keys[0]["key"]

    pdf_cache = {}
    total_checked = total_bad = 0

    for question in QUESTIONS:
        print("=" * 78)
        print("Q:", question)
        try:
            data = _ask(question, key)
        except Exception as exc:  # noqa: BLE001
            print("   REQUEST FAILED:", repr(exc))
            continue
        reply = data.get("answerText") or ""
        print(f"   source={data.get('source')}  model={data.get('model')}")

        segs = _segments(reply)
        if not segs:
            print("   (no per-program segments found - not a comparison answer)")
            print("   ", reply[:200].replace("\n", " "))
            continue

        for pid, segment in sorted(segs.items()):
            if pid not in pdf_cache:
                pdf_cache[pid] = _pdf_text(pid)
            haystack = pdf_cache[pid]
            name = PROGRAM_NAMES[pid]
            if haystack is None:
                print(f"   {name}: NO PDF - skipped")
                continue
            numbers = {n.replace(",", "") for n in _NUMBER_RE.findall(segment)}
            numbers = {n for n in numbers if n not in _IGNORE and len(n) >= 2}
            missing = sorted(n for n in numbers if n not in haystack)
            total_checked += len(numbers)
            total_bad += len(missing)
            status = "FAIL" if missing else "ok"
            print(f"   [{status}] {name}: {len(numbers)} numbers checked"
                  + (f"  -> NOT IN ITS PDF: {', '.join(missing)}" if missing else ""))
            if missing:
                print(f"          segment: {' '.join(segment.split())[:220]}")

    print("=" * 78)
    print(f"TOTAL: {total_checked} numbers checked, {total_bad} not found in the "
          f"program's own PDF")
    print("REVIEW: this audits SOURCING only. A number that exists in the right "
          "PDF but under the wrong label (e.g. quoting a reservation fee as the "
          "unreserved one) still needs a human read of the segments above.")
    return 1 if total_bad else 0


if __name__ == "__main__":
    sys.exit(main())
