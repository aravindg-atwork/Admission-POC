"""Structured admission-policy evaluation with explicit rule precedence.

Rules decide one independent dimension at a time (entrance exam, marks, age,
documents, quota).  A higher-specificity rule replaces a general rule only in
the same dimension, so an NRI-abroad NEET exception cannot accidentally erase
the marks or age requirements.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Callable
import re

from . import eligibility


@dataclass(frozen=True)
class Facts:
    project_id: str
    text: str
    category: str | None
    subject_percent: float | None
    nri_family: bool
    xii_location: str | None
    entrance_status: str | None
    age_status: str | None
    ncl_status: str | None
    cvc_status: str | None
    asks_eligibility: bool


@dataclass(frozen=True)
class Decision:
    rule_id: str
    dimension: str
    priority: int
    outcome: str
    explanation: str
    pages: tuple[int, ...]
    remaining: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rule:
    rule_id: str
    dimension: str
    priority: int
    projects: frozenset[str]
    applies: Callable[[Facts], bool]
    decide: Callable[[Facts], Decision]


@dataclass
class Evaluation:
    facts: Facts
    decisions: dict[str, Decision] = field(default_factory=dict)

    @property
    def pages(self) -> list[int]:
        return sorted({page for decision in self.decisions.values() for page in decision.pages})


_NRI_RE = re.compile(r"\b(nri|non[ -]?resident indian|fn|foreign national|pio|oci)\b", re.I)
_ABROAD_RE = re.compile(
    r"\b(abroad|outside india|u\.?s\.?a\.?|united states|foreign school|foreign board)\b", re.I
)
_XII_ABROAD_RE = re.compile(
    r"\b(?:completed|finished|passed|studied|did)\b.{0,35}"
    r"\b(?:12th|xii|high school|school|abroad|outside india|u\.?s\.?a\.?|united states)\b|"
    r"\b(?:12th|xii|high school)\b.{0,35}\b(?:abroad|outside india|u\.?s\.?a\.?|united states)\b",
    re.I,
)
_INDIA_RE = re.compile(
    r"\b(?:class\s+)?(?:12(?:th)?|xii|high school|qualifying examination)\b.{0,45}\bin india\b|"
    r"\b(?:completed|finished|passed|studied)\b.{0,35}\bin india\b",
    re.I,
)
_NEET_RE = re.compile(r"\bneet(?:-ug)?(?:-?2026)?\b", re.I)
_NEGATIVE_EXAM_RE = re.compile(
    r"\b(?:did not|didn't|have not|haven't|never|not)\b.{0,28}"
    r"\b(?:appear(?:ed)?|write|wrote|take|took|attempt(?:ed)?|complete(?:d)?)\b|"
    r"\b(?:without|no)\s+neet\b",
    re.I,
)
_POSITIVE_EXAM_RE = re.compile(
    r"\b(?:qualified|cleared|passed|appeared(?:\s+for)?|wrote|took)\b.{0,24}\bneet\b",
    re.I,
)
_ASKS_ELIGIBILITY_RE = re.compile(r"\b(eligible|eligibility|can i apply|can i get|admission)\b", re.I)
_DOB_RE = re.compile(
    r"\b(?:born\s+(?:on\s+)?|date of birth(?:\s+is)?\s*)"
    r"(?:(\d{1,2})[/-](\d{1,2})[/-](\d{4})|(\d{1,2})\s+"
    r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4}))",
    re.I,
)
_TURN_17_RE = re.compile(
    r"\b(?:turn|will\s+(?:be|complete))\s+17\b.{0,24}\b"
    r"(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"(?:\s+(?:(\d{1,2})(?!\d)(?:,?\s+(\d{4}))?|(\d{4})))?", re.I,
)
_MONTHS = {name: number for number, name in enumerate(
    "january february march april may june july august september october november december".split(), 1
)}
_NCL_RE = re.compile(r"\b(?:ncl|non[ -]?creamy layer)\b", re.I)
_NCL_MISSING_RE = re.compile(
    r"\b(?:not ready|pending|expired|not available|do not have|don't have|without|missing)\b", re.I
)
_CVC_RE = re.compile(r"\b(?:cvc|caste validity(?: certificate)?)\b", re.I)
_CVC_PENDING_RE = re.compile(r"\b(?:pending|not ready|applied|application|proposal|receipt|proof)\b", re.I)


def _age_status(text: str) -> str | None:
    """Compare only an explicitly stated date with the fixed 2026 cutoff."""
    match = _DOB_RE.search(text)
    if match:
        if match.group(1):
            day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        else:
            day, month, year = int(match.group(4)), _MONTHS[match.group(5).lower()], int(match.group(6))
        try:
            born = date(year, month, day)
        except ValueError:
            return None
        return "satisfied" if born <= date(2010, 1, 1) else "not_eligible"
    match = _TURN_17_RE.search(text)
    if match:
        month = _MONTHS[match.group(1).lower()]
        year = int(match.group(3) or match.group(4) or 2026)
        day = int(match.group(2) or 1)
        try:
            birthday = date(year, month, day)
        except ValueError:
            return None
        return "satisfied" if birthday <= date(2026, 12, 31) else "not_eligible"
    return None


def extract_facts(project_id: str, text: str) -> Facts:
    low = text.lower()
    base = eligibility.extract(text)
    nri_family = bool(_NRI_RE.search(text))
    xii_location = None
    if nri_family and _ABROAD_RE.search(text) and _XII_ABROAD_RE.search(text):
        xii_location = "abroad"
    elif nri_family and _INDIA_RE.search(text):
        xii_location = "india"

    entrance_status = None
    if _NEET_RE.search(text):
        if _NEGATIVE_EXAM_RE.search(text):
            entrance_status = "not_appeared"
        elif _POSITIVE_EXAM_RE.search(text):
            entrance_status = "appeared"

    ncl_status = None
    if _NCL_RE.search(text):
        ncl_status = "missing_or_invalid" if _NCL_MISSING_RE.search(text) else "mentioned"
    cvc_status = None
    if _CVC_RE.search(text):
        cvc_status = "pending" if _CVC_PENDING_RE.search(text) else "mentioned"

    return Facts(
        project_id=project_id,
        text=text,
        category=base.get("category"),
        subject_percent=base.get("subject_percent"),
        nri_family=nri_family,
        xii_location=xii_location,
        entrance_status=entrance_status,
        age_status=_age_status(text),
        ncl_status=ncl_status,
        cvc_status=cvc_status,
        asks_eligibility=bool(_ASKS_ELIGIBILITY_RE.search(text)),
    )


def _nri_abroad_neet(facts: Facts) -> Decision:
    return Decision(
        rule_id="bvsc.nri_abroad.neet_exempt",
        dimension="entrance_exam",
        priority=100,
        outcome="exempt",
        explanation=(
            "The B.V.Sc. NRI/FN/PIO/OCI rule exempts a candidate who passed "
            "XII or an equivalent examination abroad from NEET-UG-2026."
        ),
        pages=(20, 21),
        remaining=(
            "at least 50% in Physics, Chemistry, Biology or Biotechnology and English taken together",
            "17 years of age by 31 December 2026",
            "valid NRI/FN/PIO/OCI status and required documents",
        ),
    )


def _nri_india_neet(facts: Facts) -> Decision:
    return Decision(
        rule_id="bvsc.nri_india.neet_required",
        dimension="entrance_exam",
        priority=100,
        outcome="not_eligible",
        explanation=(
            "A B.V.Sc. NRI/FN/PIO/OCI candidate who passed XII or an equivalent "
            "examination in India must have appeared for NEET-UG-2026."
        ),
        pages=(20, 21),
    )


def _general_missing_neet(facts: Facts) -> Decision:
    return Decision(
        rule_id="bvsc.general.neet_required",
        dimension="entrance_exam",
        priority=10,
        outcome="not_eligible",
        explanation="The general B.V.Sc. admission route requires NEET-UG-2026.",
        pages=(4,),
    )


def _nri_marks(facts: Facts) -> Decision:
    assert facts.subject_percent is not None
    meets = facts.subject_percent >= 50
    return Decision(
        rule_id="bvsc.nri_abroad.marks_50",
        dimension="qualifying_marks",
        priority=100,
        outcome="satisfied" if meets else "not_eligible",
        explanation=(
            f"Your stated {facts.subject_percent:g}% "
            f"{'meets' if meets else 'is below'} the 50% Physics, Chemistry, Biology or "
            "Biotechnology and English requirement for this quota."
        ),
        pages=(20, 21),
    )


def _age_decision(facts: Facts) -> Decision:
    meets = facts.age_status == "satisfied"
    return Decision(
        rule_id=f"{facts.project_id}.age.cutoff_2026", dimension="age", priority=90,
        outcome="satisfied" if meets else "not_eligible",
        explanation=(
            "Your stated date satisfies the requirement to be 17 by 31 December 2026 "
            "(born on or before 1 January 2010)." if meets else
            "Your stated date does not satisfy the requirement to be 17 by 31 December 2026 "
            "(born on or before 1 January 2010)."
        ),
        pages=(eligibility.RULES[facts.project_id]["page"],),
    )


def _nri_reserved_threshold(facts: Facts) -> Decision:
    return Decision(
        rule_id="bvsc.nri.category_no_marks_relaxation", dimension="category", priority=100,
        outcome="no_relaxation",
        explanation=("The NRI/FN/PIO/OCI academic rule remains 50%; a reserved category "
                     "does not lower this special-quota threshold."), pages=(20, 21),
    )


def _missing_ncl(facts: Facts) -> Decision:
    return Decision(
        rule_id=f"{facts.project_id}.obc.ncl_required", dimension="reservation_documents", priority=90,
        outcome="reservation_not_established",
        explanation=("A missing, pending, or expired NCL certificate does not establish an OBC "
                     "reservation claim. It does not by itself decide eligibility in another valid category."),
        pages=(),
    )


def _pending_cvc(facts: Facts) -> Decision:
    return Decision(
        rule_id=f"{facts.project_id}.reserved.cvc_pending", dimension="caste_validity_document", priority=90,
        outcome="provisional_only",
        explanation=("Proof that a caste-validity proposal is pending may be a provisional document route, "
                     "but it is not the final Caste Validity Certificate and the programme-specific deadline still applies."),
        pages=(),
    )


RULES = (
    Rule(
        "bvsc.nri_abroad.neet_exempt", "entrance_exam", 100, frozenset({"bvsc"}),
        lambda f: f.nri_family and f.xii_location == "abroad" and f.entrance_status == "not_appeared",
        _nri_abroad_neet,
    ),
    Rule(
        "bvsc.nri_india.neet_required", "entrance_exam", 100, frozenset({"bvsc"}),
        lambda f: f.nri_family and f.xii_location == "india" and f.entrance_status == "not_appeared",
        _nri_india_neet,
    ),
    Rule(
        "bvsc.general.neet_required", "entrance_exam", 10, frozenset({"bvsc"}),
        lambda f: f.entrance_status == "not_appeared",
        _general_missing_neet,
    ),
    Rule(
        "bvsc.nri_abroad.marks_50", "qualifying_marks", 100, frozenset({"bvsc"}),
        lambda f: f.nri_family and f.xii_location == "abroad" and f.subject_percent is not None,
        _nri_marks,
    ),
    Rule("programme.age.cutoff_2026", "age", 90, frozenset(eligibility.RULES),
         lambda f: f.age_status is not None, _age_decision),
    Rule("bvsc.nri.category_no_marks_relaxation", "category", 100, frozenset({"bvsc"}),
         lambda f: f.nri_family and f.category == "reserved", _nri_reserved_threshold),
    Rule("programme.obc.ncl_required", "reservation_documents", 90, frozenset(eligibility.RULES),
         lambda f: f.category == "reserved" and f.ncl_status == "missing_or_invalid", _missing_ncl),
    Rule("programme.reserved.cvc_pending", "caste_validity_document", 90,
         frozenset(eligibility.RULES),
         lambda f: f.category == "reserved" and f.cvc_status == "pending", _pending_cvc),
)


def evaluate(project_id: str, text: str) -> Evaluation:
    facts = extract_facts(project_id, text)
    evaluation = Evaluation(facts=facts)
    for rule in RULES:
        if project_id not in rule.projects or not rule.applies(facts):
            continue
        decision = rule.decide(facts)
        current = evaluation.decisions.get(rule.dimension)
        if current is None or decision.priority > current.priority:
            evaluation.decisions[rule.dimension] = decision
    return evaluation


def admission_reply(evaluation: Evaluation) -> dict | None:
    """Render only complete, high-confidence decisions during migration."""
    decision = evaluation.decisions.get("entrance_exam")
    if not decision or decision.priority < 100:
        return None
    if decision.outcome == "exempt":
        marks = evaluation.decisions.get("qualifying_marks")
        age = evaluation.decisions.get("age")
        category = evaluation.decisions.get("category")
        documents = [evaluation.decisions[key] for key in
                     ("reservation_documents", "caste_validity_document") if key in evaluation.decisions]
        failed = [item for item in (marks, age) if item and item.outcome == "not_eligible"]
        if failed:
            failures = " ".join(item.explanation for item in failed)
            answer = (
                f"No, not on the facts stated. {decision.explanation} "
                f"However, another mandatory condition fails: {failures} "
                "The NEET exemption removes only the entrance-exam condition; it does not waive "
                "the qualifying-marks, age, status, or document requirements."
            )
        else:
            remaining = [item for item in decision.remaining if not marks or not item.startswith("at least 50%")]
            if age:
                remaining = [item for item in remaining if not item.startswith("17 years")]
            satisfied = f" {marks.explanation}" if marks else ""
            satisfied += f" {age.explanation}" if age else ""
            caveats = " " + " ".join(item.explanation for item in ([category] if category else []) + documents) \
                if category or documents else ""
            answer = (
                f"Your lack of NEET does not by itself make you ineligible. {decision.explanation}{satisfied} "
                f"Final eligibility still requires {'; '.join(remaining)}. MAFSU also states that "
                "there are no seats for an NRI-sponsored candidate; you must qualify in "
                f"an actual NRI/FN/PIO/OCI category.{caveats}"
            )
    else:
        answer = (
            f"No. {decision.explanation} The NEET exemption applies only when XII or the "
            "equivalent examination was completed abroad; it does not apply to XII completed in India."
        )
    return {
        "answer": answer,
        "source": "structured-policy",
        "model": "policy-engine",
        "pages": evaluation.pages,
        "policyDecisions": [
            {
                "ruleId": item.rule_id,
                "dimension": item.dimension,
                "outcome": item.outcome,
                "priority": item.priority,
                "pages": list(item.pages),
            }
            for item in evaluation.decisions.values()
            if item.priority >= 90
        ],
    }
