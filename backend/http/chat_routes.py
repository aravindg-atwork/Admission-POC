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
from ..core import programs, textclean
from ..generation import speech
from ..storage import apikeys, audiocache, faq, projects


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

    # The widget generates its own trace id so it can subscribe to
    # /api/progress BEFORE asking, and watch the real pipeline run rather than
    # a timed animation. Ignored unless it looks exactly like uuid4().hex -
    # TraceCollector falls back to a server-generated id, which costs the
    # student their progress stream but never their answer.
    client_trace_id = body.get("traceId")
    try:
        result = rag.answer(project_id, question, script_pref, ui_language, history,
                            trace_id=client_trace_id if isinstance(client_trace_id, str) else None)
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
    faq_id = (body.get("faqId") or "").strip()
    if not faq_id or "liked" not in body:
        self._json(400, {"error": "faqId and liked are required."})
        return
    ok = faq.apply_feedback(projects.faq_path(project_id), projects.flagged_path(project_id),
                             faq_id, bool(body.get("liked")))
    if not ok:
        self._json(404, {"error": "Unknown faqId - it may already have been removed."})
        return
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
