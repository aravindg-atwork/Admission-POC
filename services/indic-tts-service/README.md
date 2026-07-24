# Indic TTS service

Wraps [AI4Bharat's `indic-parler-tts`](https://huggingface.co/ai4bharat/indic-parler-tts)
(HuggingFace, 0.9B params) behind a tiny HTTP API, for natural Hindi/Marathi/Tamil
voice output. Runs in Docker for the same reason `embedding-service` does: this
dev machine's Application Control policy blocks freshly-installed compiled
Python dependencies (torch, etc.) on the host directly, but not inside a Linux
container.

Only reachable from the backend - `POST /api/tts` on the main backend proxies
here and is the thing actually protected by an API key. This service has no
auth of its own.

## Access (required once)

`ai4bharat/indic-parler-tts` is a **gated** HuggingFace model:

1. Log into huggingface.co, open [ai4bharat/indic-parler-tts](https://huggingface.co/ai4bharat/indic-parler-tts), click **"Agree and access repository"** (instant, no approval wait in practice).
2. Create a read token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
3. Pass it to the container as `HF_TOKEN` (never commit it - same pattern as `SARVAM_API_KEY`).

## Run

```
docker build -t admission-indic-tts .
docker volume create admission-tts-cache
docker run -d --name admission-indic-tts -p 8001:8001 \
  -v admission-tts-cache:/root/.cache/huggingface \
  -e HF_TOKEN=hf_xxx admission-indic-tts
```

**Use the volume mount.** Without it, the ~3.6GB model gets re-downloaded from
HuggingFace every time the container is recreated (e.g. after a code change +
rebuild) - the download lives in the container's writable layer, not the image.
With the named volume, only the very first run downloads anything; every
container recreated afterward reuses the cached weights and starts in seconds.

First request after startup is slow (model load into memory); subsequent
requests reuse the loaded model.

## API

`POST /tts`

```json
{ "text": "Your answer text here", "language": "hi" }
```

Returns `audio/wav` bytes. `language` is one of `hi`, `mr`, `ta`, `en` — each
maps to the model's recommended voice (Divya, Sunita, Jaya, Mary respectively).
Unknown languages fall back to the English voice.

`GET /health` — `{ "status": "ok", "model": "...", "device": "cpu"|"cuda:0" }`

## Notes

- **CPU-only inference is slow.** This machine has no GPU, so a sentence or two
  can take anywhere from several seconds to over a minute. The backend calls
  this asynchronously (chat text renders immediately; audio arrives after) and
  falls back to the browser's built-in voice if this service is slow, down, or
  errors.
- `TTS_MAX_CHARS` (env var, default 400) caps how much text is synthesized per
  call, since this is an autoregressive model - a multi-paragraph answer would
  take minutes.
- On a machine with an NVIDIA GPU, this runs meaningfully faster automatically
  (`torch.cuda.is_available()` picks it up) - see `docs/MODELS_AND_DEPLOYMENT.md`
  for AWS GPU sizing.
