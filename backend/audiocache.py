"""Persistent cache for generated Indic TTS audio, keyed by (language, text).

Indic TTS runs a 0.9B model on CPU and measured 166-252s for one sentence on
this host - far too slow to regenerate on every request. The TTS call is
deterministic (no sampling involved), so identical (language, text) always
produces the same audio: this is a pure win, not an approximation. Cache once,
serve instantly forever after.

That "identical text" case is not rare, it is the common one by construction:

  - Every FAQ cache hit (see faq.py) serves the exact same answer text to every
    student who asks a matching question, for as long as that entry lives -
    permanently for a seeded entry. The first student to request audio for it
    pays the full generation cost; every student after gets it instantly.
  - Any two fresh RAG answers that happen to land on the same wording (a common
    short fact stated the same way twice) benefit too, for free.

Stored as individual .wav files rather than folded into faq.py's JSON store:
audio is ~0.4-0.5MB per sentence, and that store keeps its entire parsed
contents in memory for every match() scan (see faq._load) - stuffing base64
audio into entries never read by matching would bloat the one code path that
runs on nearly every request, for data it never needs.

One cache directory per project (see projects.tts_cache_dir), same convention
as the vector store and FAQ cache.
"""

import hashlib


def _key(language, text):
    # sha256 rather than a weaker hash: this is a lookup key, not a checksum
    # for corruption detection, but the input space (every distinct answer
    # sentence in three languages) is large enough that collision resistance
    # is worth the negligible extra cost. Truncated to 24 hex chars - still far
    # more collision-resistant than this cache will ever need entries for.
    return hashlib.sha256(f"{language}\n{text}".encode("utf-8")).hexdigest()[:24]


def path_for(cache_dir, language, text):
    return cache_dir / f"{_key(language, text)}.wav"


def get(cache_dir, language, text):
    """Cached audio bytes for this exact (language, text), or None."""
    path = path_for(cache_dir, language, text)
    return path.read_bytes() if path.exists() else None


def put(cache_dir, language, text, audio_bytes):
    """Store audio for later reuse. Best-effort: a write failure (e.g. disk
    full) should not turn an already-successful TTS generation into an error
    response - callers should catch and log rather than propagate.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    path_for(cache_dir, language, text).write_bytes(audio_bytes)
