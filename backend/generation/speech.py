"""Speech-to-text via Mistral Voxtral.

Added 2026-08-14. The mic button previously relied entirely on the browser's
webkitSpeechRecognition, which is Chrome-only, silently absent in several
browsers, and sends audio to Google rather than to us - so a student on
Firefox or an in-app webview simply had no voice input at all.

Measured before wiring, on audio generated with the macOS Hindi voice:
English transcribes in 0.5s and Hindi in 1.2s. Hindi is close but not
exact - "बी.व्ही.एस्सी. ... शुल्क" came back as "बी भी एसी ... शुल्प",
garbling the acronym and one character. That is survivable here precisely
because the layers downstream are built for imperfect input: programme
aliases match on a normalized skeleton, marker matching carries
single-edit typo tolerance, and the intent router reads meaning rather than
tokens. It would NOT be survivable if a transcript were used verbatim as a
figure or a name.

Text-to-speech is deliberately NOT here. Mistral's voice catalogue is ten
voices, all en_us/en_gb - no Indic at all - so it cannot serve the case
that actually needs a server-side voice. English already has one in the
browser. See config.TTS_URL for the service that owns that job.
"""

import json
import urllib.error
import urllib.request
import uuid

from .. import config

# Anything larger is not a student asking a question - it is a mistake or an
# upload, and letting it through would spend a transcription call on it.
MAX_AUDIO_BYTES = 8 * 1024 * 1024


def _multipart(fields, filename, audio, content_type):
    boundary = "----b" + uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        if value is None:
            continue
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
            .encode("utf-8"))
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode("utf-8"))
    parts.append(audio)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def transcribe(audio, content_type="audio/webm", language=None):
    """Audio bytes -> text, or None on any failure.

    None rather than an exception, matching llm.generate_scoped's contract:
    a failed transcription must leave the student able to type, never break
    the page.
    """
    if not audio or len(audio) > MAX_AUDIO_BYTES or not config.MISTRAL_API_KEY:
        return None
    body, boundary = _multipart(
        {"model": config.STT_MODEL, "language": language},
        "audio", audio, content_type)
    req = urllib.request.Request(
        config.MISTRAL_URL.rstrip("/") + "/audio/transcriptions",
        data=body, method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {config.MISTRAL_API_KEY}",
            "User-Agent": "AdmissionAssistant/1.0",
        })
    try:
        with urllib.request.urlopen(req, timeout=config.STT_TIMEOUT) as resp:
            text = (json.loads(resp.read().decode("utf-8")) or {}).get("text")
    except urllib.error.HTTPError as exc:
        print(f"[stt] HTTP {exc.code}: {exc.read().decode()[:160]}")
        return None
    except Exception as exc:  # noqa: BLE001 - never break the request
        print(f"[stt] failed: {exc!r}")
        return None
    text = (text or "").strip()
    return text or None
