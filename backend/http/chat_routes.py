"""Admission-bot chat/feedback/ingest/tts route handlers - extracted from
server.py's do_POST during the 2026-08-13 re-architecture (Phase 6:
server.py -> http/ package split). Each handle_* function takes the live
`Handler` instance (`self`) exactly as it did inline in server.py. app.py's
do_POST keeps its exact if/elif conditions and order; only each branch's
body becomes a one-line call into this module.

_handle_ingest is called from both handle_ingest here (POST /api/ingest)
and admin_routes.handle_project_ingest (POST /admin/projects/:id/ingest) -
kept here since ingest is fundamentally an admission-bot/chat-domain
concern, imported by admin_routes rather than duplicated.
"""

import json
import re
import urllib.request

from .. import config, rag
from ..core import eligibility, programs, textclean
from ..generation import speech
from ..storage import apikeys, audiocache, faq, projects, reviewlog


# Allowed conversationState keys and how each is validated - the same
# pin-the-shape discipline `history` gets a few lines into handle_chat below
# (fixed key set, fixed value types, everything else silently dropped rather
# than trusted). This is client-supplied text/numbers that will eventually
# reach a guard's decision logic (P1), not just a prompt, so it gets the
# stricter treatment: unlike history's free-text `text[:1000]`, every field
# here is checked against a closed set or a numeric range, and anything that
# doesn't fit is dropped to None rather than passed through best-effort - a
# bad guess here is a wrong eligibility verdict, not a slightly-off prompt.
_CONVERSATION_PROGRAMMES = set(programs.PROGRAM_NAMES)
_CONVERSATION_CATEGORIES = {"reserved", "unreserved"}
_CONVERSATION_ENTRANCE_STATUSES = {"yes", "no", "pending"}


def _sanitize_percent(value):
    """A percentage the client claims was already extracted this
    conversation - only trusted in the same range eligibility.py itself
    would accept (0-100), and only as a real number. Anything else (a
    string, a bool, NaN, out of range) comes back None rather than a
    half-trusted guess, since P1 will feed this straight into the same
    threshold comparison eligibility.evaluate() does for the current
    message.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or not (0 <= value <= 100):  # value != value -> NaN
        return None
    return float(value)


def _sanitize_conversation_state(raw):
    """Validate the client's conversationState onto the fixed shape
    ctx.conversationState carries (see rag/answer.py's _build_context) -
    {programme, intent, category, subjectPercent, overallPercent,
    entranceExamStatus}, every value either the right primitive or None.

    Unconditionally returns a dict with exactly these six keys (never a
    subset, never extra ones), so every reader downstream - today just this
    module echoing nothing back, from P1 onward every guard that touches
    ctx.conversationState - can assume the shape without a KeyError guard at
    every call site, the same convention `history`'s per-turn
    {role, text} shape already gives its readers.

    Not yet acted on by anything (P0 scope - see _build_context's docstring
    on ctx.conversationState): this only pins the shape crossing the network
    boundary so P1 can start reading it immediately without redoing this
    validation pass itself.
    """
    if not isinstance(raw, dict):
        return {"programme": None, "intent": None, "category": None,
                "subjectPercent": None, "overallPercent": None,
                "entranceExamStatus": None}
    programme = raw.get("programme")
    if programme not in _CONVERSATION_PROGRAMMES:
        programme = None
    intent = raw.get("intent")
    # No fixed intent vocabulary exists yet (P1 defines it) - capped the same
    # way history's per-turn text is capped, so an oversized or malformed
    # value can't bloat a future prompt, without pretending to validate
    # against a set that doesn't exist yet.
    intent = intent.strip()[:100] if isinstance(intent, str) and intent.strip() else None
    category = raw.get("category")
    if category not in _CONVERSATION_CATEGORIES:
        category = None
    entrance_status = raw.get("entranceExamStatus")
    if entrance_status not in _CONVERSATION_ENTRANCE_STATUSES:
        entrance_status = None
    return {
        "programme": programme,
        "intent": intent,
        "category": category,
        "subjectPercent": _sanitize_percent(raw.get("subjectPercent")),
        "overallPercent": _sanitize_percent(raw.get("overallPercent")),
        "entranceExamStatus": entrance_status,
    }


def _read_multipart_file(body, content_type):
    """Minimal multipart/form-data parser: returns the first file's raw bytes."""
    m = re.search(r"boundary=(.+)$", content_type)
    if not m:
        return None
    boundary = ("--" + m.group(1).strip('"')).encode()
    parts = body.split(boundary)
    for part in parts:
        if b"Content-Disposition" in part and b"filename=" in part:
            header_end = part.find(b"\r\n\r\n")
            if header_end == -1:
                continue
            data = part[header_end + 4:]
            return data.rstrip(b"\r\n")
    return None



def handle_chat(self):
    project_id = apikeys.resolve_active(self.headers.get("X-API-Key"))
    if not project_id:
        self._json(401, {"error": "Missing or inactive API key."})
        return
    body = self._read_json()
    question = (body.get("question") or "").strip()
    if not question:
        self._json(400, {"error": "Question is required."})
        return
    script_pref = "native" if body.get("scriptPreference") == "native" else "auto"
    ui_language = body.get("uiLanguage") if body.get("uiLanguage") in ("en", "hi", "mr", "ta") else None

    # Resolve a TYPED answer to the program-clarification question (see
    # rag/guards.py's _program_clarify_guard). The widget's chips already
    # resubmit the ORIGINAL question under the picked program's key, but a
    # student who types the program name instead of clicking used to send a
    # brand-new, context-free message. Reproduced from a real session:
    # "what all course can I apply for if my score is 60%" got the
    # clarification, the student typed "btech", and because that message
    # carries no question of its own the backend answered the only thing it
    # could - a whole-program overview - instead of the eligibility question
    # actually being asked. Rewriting to the original question here makes
    # typing exactly equivalent to clicking the chip, rather than adding
    # general conversation memory, which would change what the FAQ cache is
    # keyed on and is a far larger behavioral change than this fixes.
    # Scoped hard: fires only when the previous turn was genuinely a
    # clarification AND this message is nothing but a program name (see
    # programs.is_bare_program_reply - "btech dairy fees" is left alone).
    # Prior turns, used by the intent router to resolve a follow-up into a
    # standalone question (see rag/router.py). Sanitized and capped here
    # rather than trusted as sent: this is client-supplied text that ends up
    # inside a model prompt, so the shape is pinned to {role, text}, the role
    # to two known values, and the volume to something a prompt can hold.
    history = []
    for turn in (body.get("history") or [])[-12:]:
        if not isinstance(turn, dict):
            continue
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        role = "user" if turn.get("role") == "user" else "assistant"
        history.append({"role": role, "text": text[:1000]})

    # Client-accumulated slot-filling profile for this conversation (see
    # rag/answer.py's ctx.conversationState and this file's
    # _sanitize_conversation_state docstring for the shape/validation
    # discipline). Threaded onto ctx below via rag.answer()'s new
    # conversation_state kwarg - not read by any guard yet (P0 scope), but
    # already validated at the boundary so P1 doesn't have to.
    conversation_state = _sanitize_conversation_state(body.get("conversationState"))

    pending = body.get("pendingClarification") or {}
    original_question = (pending.get("originalQuestion") or "").strip()
    if original_question and programs.is_bare_program_reply(question):
        named = programs.detect_program(question)
        if named:
            # Same retarget the clicked chip performs, and the same one
            # _program_redirect_guard already does internally via
            # ctx.reanswer() - answer from that program's own project.
            project_id = named
            question = original_question

    # Same idea, for _percentage_clarify_guard's "is that your overall score
    # or those subjects?" (see core/eligibility.py's is_bare_scope_reply /
    # apply_percentage_scope docstrings for why this needs its own splice
    # rather than reusing router history: a live test showed a bare "overall"
    # reply losing the original question's programme AND percentage and
    # fanning out across all three programmes instead of answering the one
    # actually asked about). Distinguished from the program-clarify case
    # above by pendingClarification.kind, which the widget sets from which
    # field the previous response carried (clarifyOptions vs scopeOptions) -
    # both branches are mutually exclusive since a single turn only ever
    # asks one clarifying question.
    if pending.get("kind") == "percentage" and original_question:
        scope = eligibility.is_bare_scope_reply(question)
        if scope:
            question = eligibility.apply_percentage_scope(original_question, scope)

    # The widget generates its own trace id so it can subscribe to
    # /api/progress BEFORE asking, and watch the real pipeline run rather than
    # a timed animation. Ignored unless it looks exactly like uuid4().hex -
    # TraceCollector falls back to a server-generated id, which costs the
    # student their progress stream but never their answer.
    client_trace_id = body.get("traceId")
    try:
        result = rag.answer(project_id, question, script_pref, ui_language, history,
                            trace_id=client_trace_id if isinstance(client_trace_id, str) else None,
                            conversation_state=conversation_state)
        payload = {
            "answerText": result["answer"],
            "pageReferences": result["pages"],
            "model": result["model"],
            "language": result["language"],
            "source": result["source"],
            "speakable": result["speakable"],
            # Lets the console line this answer up with its own trace card
            # instead of guessing which of the live feed's cards was this
            # request (see the Playground inspector).
            "traceId": result.get("traceId"),
        }
        if result.get("clarifyOptions"):
            payload["clarifyOptions"] = result["clarifyOptions"]
        if result.get("scopeOptions"):
            payload["scopeOptions"] = result["scopeOptions"]
        # Topic-menu chips (see guards.py's _topic_menu_guard) - unlike
        # clarifyOptions/scopeOptions above, a click here resubmits a
        # complete, self-sufficient question of its own, so there is no
        # matching carryQuestion/pendingClarification wiring needed for it.
        if result.get("topicOptions"):
            payload["topicOptions"] = result["topicOptions"]
        # Guided-eligibility-interview chips (see guards.py's
        # _eligibility_interview_ask) - interviewField names which
        # conversationState slot a click should set (see static/app.js's
        # pickInterview) before resubmitting carryQuestion below.
        if result.get("interviewOptions"):
            payload["interviewOptions"] = result["interviewOptions"]
            payload["interviewField"] = result.get("interviewField")
        # The client-accumulated slot-filling profile this turn's guard
        # decided to seed/update (see rag/helpers.py's resolve_conversation_slot
        # and guards.py's _slot_update) - e.g. the programme an eligibility
        # interview just confirmed, or the "resolved" marker a completed
        # verdict leaves behind for one more turn so a same-topic swap like
        # "what about SC?" still has something to swap. A plain patch, never
        # a full replacement - see _slot_update's docstring on why a field
        # this turn doesn't know about is OMITTED rather than sent as null.
        if result.get("slotUpdate"):
            payload["slotUpdate"] = result["slotUpdate"]
        # Both guard-supplied (see guards.py's carryQuestion comments) so the
        # widget can arm its NEXT pendingClarification from server-known
        # state instead of its own last-typed message, which is wrong the
        # moment two clarifications chain (percentage, then still-unknown
        # programme) - see this file's pendingClarification handling above.
        if result.get("carryQuestion"):
            payload["carryQuestion"] = result["carryQuestion"]
        if result.get("answeredForProgram"):
            payload["answeredForProgram"] = {
                "projectId": result["answeredForProgram"],
                "label": programs.PROGRAM_NAMES.get(result["answeredForProgram"], ""),
            }
        # Already {projectId, label} dicts from rag._answer_comparison,
        # unlike answeredForProgram above (a bare id server.py wraps) -
        # a comparison answer names several programs, not one.
        if result.get("comparedPrograms"):
            payload["comparedPrograms"] = result["comparedPrograms"]
        # Only present for answers that actually went through the FAQ
        # cache (rag/faq-cache/payment-issue/verified-fact) - a
        # clarify-program prompt, greeting or guard refusal has
        # nothing for a like/dislike to target, so /api/feedback has
        # no id to act on and the frontend shows no buttons for those.
        if result.get("faqId"):
            payload["faqId"] = result["faqId"]
        self._json(200, payload)
    except Exception as exc:
        self._json(500, {"error": str(exc)})


def handle_feedback(self):
    project_id = apikeys.resolve_active(self.headers.get("X-API-Key"))
    if not project_id:
        self._json(401, {"error": "Missing or inactive API key."})
        return
    body = self._read_json()
    if "liked" not in body:
        self._json(400, {"error": "faqId or traceId, and liked, are required."})
        return
    faq_id = (body.get("faqId") or "").strip()
    if faq_id:
        ok = faq.apply_feedback(projects.faq_path(project_id), projects.flagged_path(project_id),
                                 faq_id, bool(body.get("liked")))
        if not ok:
            self._json(404, {"error": "Unknown faqId - it may already have been removed."})
            return
        self._json(200, {"ok": True})
        return
    # Guard-served answers (eligibility verdicts, the guided interview,
    # comparisons, clarifications...) never get a faqId - they run BEFORE
    # the FAQ cache and are deliberately never cached themselves (an
    # eligibility verdict depends on per-conversation state, so it must
    # always be recomputed, never served stale - see rag/guards.py's module
    # docstring). Without this fallback, "no faqId" silently meant "no
    # feedback buttons at all" for a large and growing share of real
    # conversations - reported live 2026-08-19. There is no cache entry to
    # update here, so this just records the event the same shape reviewlog
    # already uses for the system's OWN self-detected near-misses (kind,
    # reason/source, small discriminator fields, never question/answer
    # text) - a STUDENT dislike on a guard answer is exactly the same kind
    # of signal, just triggered by the student instead of a validation
    # check.
    trace_id = (body.get("traceId") or "").strip()
    if not trace_id:
        self._json(400, {"error": "faqId or traceId, and liked, are required."})
        return
    source = body.get("source")
    reviewlog.append(projects.review_log_path(project_id), {
        "kind": "student_feedback",
        "source": source if isinstance(source, str) else None,
        "liked": bool(body.get("liked")),
        "traceId": trace_id,
    })
    self._json(200, {"ok": True})


def handle_ingest(self):
    project_id = apikeys.resolve_active(self.headers.get("X-API-Key"))
    if not project_id:
        self._json(401, {"error": "Missing or inactive API key."})
        return
    _handle_ingest(self, project_id)


def handle_tts(self):
    # resolve_active (not just is_active): the audio cache is per-
    # project, same as the FAQ/vector stores, so the project_id is
    # needed here now, not just an active/inactive check.
    project_id = apikeys.resolve_active(self.headers.get("X-API-Key"))
    if not project_id:
        self._json(401, {"error": "Missing or inactive API key."})
        return
    _proxy_tts(self, project_id)



def _handle_ingest(self, project_id):
    body = self._read_body()
    file_bytes = _read_multipart_file(body, self.headers.get("Content-Type", ""))
    if not file_bytes:
        self._json(400, {"error": "Expected a PDF file in multipart/form-data."})
        return
    saved = projects.prospectus_path(project_id)
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_bytes(file_bytes)
    try:
        self._json(200, rag.ingest(project_id, saved))
    except Exception as exc:
        self._json(500, {"error": str(exc)})


def _proxy_tts(self, project_id):
    try:
        payload = self._read_json()
        text = textclean.clean_for_speech(payload.get("text") or "")
        language = payload.get("language") or ""
        cache_dir = projects.tts_cache_dir(project_id)

        # The generation call is what takes 166-252s on this host - a cache
        # hit skips it entirely and returns in the time it takes to read a
        # small file off disk. Same (language, text) always means the same
        # audio (the TTS call has no sampling step), so this is exact reuse,
        # not an approximation.
        cached = audiocache.get(cache_dir, language, text)
        if cached is not None:
            self._send(200, cached, "audio/wav")
            return

        payload["text"] = text
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(config.TTS_URL, data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=config.TTS_TIMEOUT) as resp:
            audio = resp.read()
            content_type = resp.headers.get("Content-Type", "audio/wav")
        try:
            audiocache.put(cache_dir, language, text, audio)
        except OSError as exc:
            # A cache-write failure (disk full, permissions) must not turn a
            # successful generation into an error response - the audio is
            # already in hand and the student should still get it. Next
            # request just regenerates instead of finding a cache hit.
            print(f"[tts] cache write failed (serving anyway): {exc!r}")
        self._send(200, audio, content_type)
    except Exception as exc:
        # Logged, not swallowed: this returned a bare 503 for every cause,
        # and the UI treats 503 as "fall back to the device voice" - so a
        # timeout on a working service was indistinguishable from the
        # service being down, and the Indic voice silently never played.
        print(f"[tts] proxy to {config.TTS_URL} failed: {exc!r}")
        self._json(503, {"error": "TTS service unavailable."})


def handle_stt(self):
    """POST /api/stt - raw audio in, transcript out.

    Takes the audio body directly rather than multipart: the browser sends
    one MediaRecorder blob and nothing else, so a parser here would only be
    ceremony. The language hint rides in a header for the same reason.

    Returns 200 with {"text": null} rather than an error when transcription
    fails, because the caller's fallback is "let them type" - an error
    status would surface as a broken page for something that is merely a
    degraded convenience.
    """
    project_id = apikeys.resolve_active(self.headers.get("X-API-Key"))
    if not project_id:
        self._json(401, {"error": "Missing or inactive API key."})
        return
    audio = self._read_body()
    if not audio:
        self._json(400, {"error": "Audio body is required."})
        return
    language = self.headers.get("X-Audio-Language") or None
    if language not in ("hi", "mr", "en", "ta", None):
        language = None
    content_type = self.headers.get("Content-Type") or "audio/webm"
    text = speech.transcribe(audio, content_type, language)
    self._json(200, {"text": text})
