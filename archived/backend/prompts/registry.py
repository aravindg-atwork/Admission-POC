"""Manifest of every admission-bot LLM prompt, read by GET /admin/prompts
(see http/trace_routes.py) - "the prompt a agent is using to answer any
question as master prompt" (Request 3.1 of the 2026-08-13 plan).

Deliberately admission-bot-only: OrderAssist's own 2 prompts live in
orderassist/prompts.py, out of scope here, matching the isolation decision
made when OrderAssist was split out (Phase 5 of the same re-architecture).

Each entry's `text` is exactly what actually gets sent to the LLM - the
BASE constant + llm.LANGUAGE_RULE where the real call site appends it (see
each constant's own definition in system.py), never a hand-summarized
version. `template=True` entries still contain a literal "{program}"
placeholder; list_prompts(project_id=...) renders it via
rag.helpers._program_name so what's shown is byte-for-byte what a real
request for that project would see.
"""

from . import system

_PROMPTS = [
    {
        "id": "system_prompt_base",
        "name": "Main answer prompt",
        "usedBy": "Single-question answers (rag/answer.py's generic RAG path)",
        "template": True,
        "text": system.SYSTEM_PROMPT_BASE,
    },
    {
        "id": "greeting_prompt_base",
        "name": "Greeting prompt",
        "usedBy": "Greeting short-circuit (rag/guards.py's _greeting_guard)",
        "template": True,
        "text": system.GREETING_PROMPT_BASE,
    },
    {
        "id": "payment_system_prompt",
        "name": "Payment de-escalation prompt",
        "usedBy": "Payment-problem questions (intent.is_payment_issue)",
        "template": False,
        "text": system.PAYMENT_SYSTEM_PROMPT,
    },
    {
        "id": "verified_fact_system",
        "name": "Verified-fact phrasing prompt",
        "usedBy": "tablelookup.py resolved an exact table cell - phrase-only, no raw excerpts",
        "template": False,
        "text": system._VERIFIED_FACT_SYSTEM,
    },
    {
        "id": "comparison_system_prompt",
        "name": "Cross-program comparison prompt",
        "usedBy": "Questions spanning several programs (rag/comparison.py)",
        "template": False,
        "text": system._COMPARISON_SYSTEM_PROMPT,
    },
    {
        "id": "orchestrator_system_prompt",
        "name": "Multi-part orchestration prompt",
        "usedBy": "Genuinely multi-part questions (rag/orchestrator.py)",
        "template": True,
        "text": system._ORCHESTRATOR_SYSTEM_PROMPT,
    },
    {
        "id": "validate_system",
        "name": "Validator prompt",
        "usedBy": "Bounded post-generation PASS/FAIL check (rag/validate.py)",
        "template": False,
        "text": system._VALIDATE_SYSTEM,
    },
]


def list_prompts(project_id=None):
    """Returns the manifest, with {program} placeholders rendered when
    project_id is given - see module docstring for why this renders rather
    than just documents the placeholder.
    """
    if project_id is None:
        return [dict(p) for p in _PROMPTS]

    from ..rag.helpers import _program_name
    program = _program_name(project_id)
    rendered = []
    for p in _PROMPTS:
        entry = dict(p)
        if entry["template"]:
            entry["text"] = entry["text"].format(program=program)
        rendered.append(entry)
    return rendered
