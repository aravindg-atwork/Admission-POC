"""
Indic text-to-speech microservice for the AI Admission Assistant.

Wraps AI4Bharat's indic-parler-tts (HuggingFace, 0.9B params) behind a small HTTP
API. .NET Framework 4.5 can't load HuggingFace models in-process, and even the pure
Python backend on this dev machine can't - the model's compiled dependencies
(torch) hit the same Application Control policy that blocked the embedding service
until it was containerized. So this runs in Docker, exactly like embedding-service,
and the backend calls it over HTTP.

Only reachable from the backend (POST /api/tts proxies here) - the outer API key
gate on /api/tts is what protects this, so this service has no auth of its own.
"""

import io
import os
import re

import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from transformers import AutoTokenizer

MODEL_NAME = os.environ.get("TTS_MODEL", "ai4bharat/indic-parler-tts")
DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"
# indic-parler-tts is a gated HF model - requires accepting the license on
# huggingface.co while logged in, then a personal access token here. Read from
# the environment only, never hard-coded (same pattern as SARVAM_API_KEY).
HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")

app = FastAPI(title="Admission Assistant Indic TTS Service")

print(f"[indic-tts] loading {MODEL_NAME} on {DEVICE} ...")
from parler_tts import ParlerTTSForConditionalGeneration  # noqa: E402 - after torch/device setup

model = ParlerTTSForConditionalGeneration.from_pretrained(MODEL_NAME, token=HF_TOKEN).to(DEVICE)
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, token=HF_TOKEN)
description_tokenizer = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path, token=HF_TOKEN)
print("[indic-tts] model loaded")

# One recommended FEMALE voice per language, per the model card (Divya, Sunita,
# Jaya, Mary are all listed as the recommended female speakers). The gender is
# stated explicitly in the description, not just implied by name, because
# Parler-TTS draws from a distribution around the named speaker and an explicit
# description keeps that distribution consistently female across generations.
VOICE_DESCRIPTIONS = {
    "hi": "Divya, a female speaker, talks in a clear, warm, moderate pace voice with very close recording and almost no background noise.",
    "hi-IN": "Divya, a female speaker, talks in a clear, warm, moderate pace voice with very close recording and almost no background noise.",
    "mr": "Sunita, a female speaker, talks in a clear, warm, moderate pace voice with very close recording and almost no background noise.",
    "mr-IN": "Sunita, a female speaker, talks in a clear, warm, moderate pace voice with very close recording and almost no background noise.",
    "ta": "Jaya, a female speaker, talks in a clear, warm, moderate pace voice with very close recording and almost no background noise.",
    "ta-IN": "Jaya, a female speaker, talks in a clear, warm, moderate pace voice with very close recording and almost no background noise.",
    "en": "Mary, a female speaker, talks in a clear, warm, moderate pace voice with very close recording and almost no background noise.",
    "en-IN": "Mary, a female speaker, talks in a clear, warm, moderate pace voice with very close recording and almost no background noise.",
}
DEFAULT_DESCRIPTION = VOICE_DESCRIPTIONS["en"]

# Keep spoken answers to a length this hardware can synthesize well within the
# backend's proxy timeout. Measured on this CPU-only dev machine: ~400 chars of
# English took over 2 minutes - far past reasonable. 220 chars (roughly 1-2
# sentences) reliably finishes in well under a minute. A GPU host can raise this.
MAX_CHARS = int(os.environ.get("TTS_MAX_CHARS", "220"))
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s")


def _truncate_at_sentence(text, max_chars):
    """Cut at the last sentence boundary within max_chars, not mid-word/mid-sentence -
    a clipped sentence sounds broken read aloud, a shorter-but-complete one doesn't."""
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    boundaries = list(_SENTENCE_END.finditer(window))
    if boundaries:
        return window[:boundaries[-1].start() + 1].strip()
    return window.strip()  # no sentence boundary found - fall back to a hard cut


class TtsRequest(BaseModel):
    text: str
    language: str = "en"


@app.post("/tts")
def tts(request: TtsRequest):
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required.")
    text = _truncate_at_sentence(text, MAX_CHARS)

    description = VOICE_DESCRIPTIONS.get(request.language, DEFAULT_DESCRIPTION)

    description_ids = description_tokenizer(description, return_tensors="pt").to(DEVICE)
    prompt_ids = tokenizer(text, return_tensors="pt").to(DEVICE)

    with torch.no_grad():
        generation = model.generate(
            input_ids=description_ids.input_ids,
            attention_mask=description_ids.attention_mask,
            prompt_input_ids=prompt_ids.input_ids,
            prompt_attention_mask=prompt_ids.attention_mask,
        )

    audio = generation.cpu().numpy().squeeze()
    buf = io.BytesIO()
    sf.write(buf, audio, model.config.sampling_rate, format="WAV")
    return Response(content=buf.getvalue(), media_type="audio/wav")


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "device": DEVICE}
