"""Deterministic student-safety controls and auditable response metadata."""

from datetime import date
import re

ADMISSION_YEAR = "2026-27"
_OTHER_YEAR = re.compile(r"\b(20\d{2})\s*[-/]\s*(\d{2,4})\b")
_AADHAAR = re.compile(r"(?<!\d)(?:\d[ -]?){11}\d(?!\d)")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{9}(?!\d)")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_APPLICATION_ID = re.compile(
    r"\b(?:(?:neet|cet|cuet)\s+(?:application\s+|registration\s+|roll\s+)?|(?:application|registration|roll)\s+)"
    r"(?:id|no\.?|number)\s*[:#-]?\s*(?=[A-Z0-9-]*\d)[A-Z0-9-]{7,}\b",
    re.I,
)
_DATE_2026 = re.compile(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+2026\b", re.I)
_MONTHS = {name.lower(): number for number, name in enumerate(("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}


def pii_types(text: str) -> list[str]:
    found = []
    for label, pattern in (("Aadhaar/identity number", _AADHAAR), ("phone number", _PHONE), ("email address", _EMAIL), ("exam/application identifier", _APPLICATION_ID)):
        if pattern.search(text):
            found.append(label)
    return found


def year_mismatch(text: str) -> str | None:
    for match in _OTHER_YEAR.finditer(text):
        start, raw_end = match.groups()
        end = raw_end if len(raw_end) == 4 else start[:2] + raw_end
        year = f"{start}-{end[-2:]}"
        if year != ADMISSION_YEAR:
            return year
    return None


def reconcile_state(text: str, state: dict) -> tuple[dict, dict]:
    """Apply explicit corrections; ordinary contradictions remain unresolved."""
    low = " ".join(text.lower().split())
    if not any(marker in low for marker in ("sorry", "correction", "actually", "i meant", "not general", "not obc", "not reserved")):
        return dict(state), {}
    updated, changes = dict(state), {}
    if re.search(r"\b(?:obc|sc|st|reserved)\b.*\bnot\s+(?:general|unreserved)\b|\bnot\s+(?:general|unreserved)\b.*\b(?:obc|sc|st|reserved)\b", low):
        changes["category"] = "reserved"
    elif re.search(r"\b(?:general|unreserved)\b.*\bnot\s+(?:obc|sc|st|reserved)\b|\bnot\s+(?:obc|sc|st|reserved)\b.*\b(?:general|unreserved)\b", low):
        changes["category"] = "unreserved"
    if re.search(r"\b(?:actually|correction|sorry|i meant)\b.*\b(?:qualified|passed)\b.*\bneet\b", low):
        changes["entranceExamStatus"] = "yes"
    elif re.search(r"\b(?:actually|correction|sorry|i meant)\b.*\b(?:did not|didn't|failed|not qualified)\b.*\bneet\b", low):
        changes["entranceExamStatus"] = "not_qualified"
    updated.update(changes)
    return updated, changes


def turn_facts(text: str, project_id: str) -> dict:
    """Persist only explicit facts for the programme's applicable exam."""
    low = text.lower()
    exam = "neet" if project_id == "bvsc" else "mht-cet|mht cet|cet"
    if not re.search(rf"\b(?:{exam})\b", low):
        return {}
    if re.search(r"\b(?:did not|didn't|never|have not|haven't)\b.{0,24}\b(?:appear|take|sit)\b", low):
        return {"entranceExamStatus": "no"}
    if project_id == "bvsc" and re.search(r"\b(?:failed|did not qualify|didn't qualify|not qualified)\b", low):
        return {"entranceExamStatus": "not_qualified"}
    if re.search(r"\b(?:appeared|qualified|percentile|score)\b", low):
        return {"entranceExamStatus": "yes"}
    return {}


def decision_state(result: dict) -> str:
    source, answer = str(result.get("source", "")), str(result.get("answer", "")).lower()
    if source in {"clarification", "clarify-percentage", "eligibility-interview", "programme-clarification", "state-contradiction", "malformed-input"}:
        return "needs_clarification"
    if source in {"low-confidence", "no-context", "provider-unavailable", "validation-blocked", "knowledge-boundary"}:
        return "cannot_confirm"
    if any(term in answer for term in ("document deficiency", "reservation claim", "expired ncl", "caste validity", "missing document")):
        return "document_issue"
    if any(term in answer for term in ("nri/fn/pio/oci", "management quota", "icar quota", "reserved category")):
        return "quota_specific"
    if source in {"eligibility", "verified-policy", "eligibility-rule"}:
        if re.search(r"(?:^|[.!:]\s)(?:no|not eligible|you do not|you cannot)\b", answer):
            return "not_eligible"
        if any(term in answer for term in ("eligible so far", "meet the", "can apply", "potentially eligible")):
            return "eligible_so_far"
    return "informational"


def _passed_deadlines(answer: str) -> list[str]:
    passed, today = [], date.today()
    for match in _DATE_2026.finditer(answer):
        day, month = match.groups()
        try:
            deadline = date(2026, _MONTHS[month.lower()], int(day))
        except ValueError:
            continue
        if deadline < today:
            passed.append(match.group(0))
    return list(dict.fromkeys(passed))


def finalize(question: str, project_id: str, result: dict) -> dict:
    result = dict(result)
    if project_id in {"bfsc", "btech-dairy"}:
        result["answer"] = re.sub(
            r"\b(?:clear|qualify(?: in)?)\s+MHT-CET(?:\s+2026)?\b",
            "have appeared for MHT-CET 2026",
            str(result.get("answer", "")), flags=re.I,
        )
    if project_id == "bfsc" and "neet" in question.lower() and "mht" in question.lower() and "does not affect" not in str(result.get("answer", "")).lower():
        result["answer"] += " Your NEET result does not affect regular B.F.Sc. eligibility; this route uses MHT-CET 2026 rather than NEET."
    pages = sorted({page for page in result.get("pages", []) if isinstance(page, int) and page > 0})
    result["pages"] = pages
    result["admissionYear"] = ADMISSION_YEAR
    result["decisionState"] = decision_state(result)
    result["sourceTrace"] = {
        "programme": project_id, "admissionYear": ADMISSION_YEAR, "pages": pages,
        "ruleIds": [item["ruleId"] for item in result.get("policyDecisions", []) if isinstance(item, dict) and item.get("ruleId")],
    }
    if result["decisionState"] == "cannot_confirm":
        result["fallbackReason"] = result.get("source")
    passed = _passed_deadlines(str(result.get("answer", "")))
    if passed and any(word in question.lower() for word in ("now", "today", "still", "can i", "what should", "how do")):
        result["answer"] += f"\n\nDate check: {', '.join(passed)} has already passed for the {ADMISSION_YEAR} admission cycle. Do not rely on that action as currently available; confirm whether the appropriate MAFSU admission authority has issued any later official notice."
    return result
