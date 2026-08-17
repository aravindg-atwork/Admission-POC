# Frozen Model Stack & AWS Deployment

_AI Admission Assistant POC — locked configuration and production sizing._

## 1. Request flow (frozen)

```
Student question
   │
   ▼
Intent check ──► greeting? ──► short warm reply (no retrieval, no cache)
   │ (real question)
   ▼
Embed question once  (nomic-embed-text, Dockerized)
   │
   ▼
FAQ cache lookup ──► hit (cosine ≥ 0.88)? ──► return cached answer  (INSTANT, ~2s, no LLM)
   │ (miss)
   ▼
RAG search  (cosine over prospectus chunks, reuses the same embedding)
   │
   ▼
LLM generate ──► Sarvam AI cloud (sarvam-105b), if under the daily call cap
   │                (handles English AND Hindi/Marathi/Tamil - one strong model,
   │                 no per-language split needed)
   ▼ cap hit / cloud error
Local fallback (gemma2:2b via Ollama) ──► Answer  (+ page citations)
   │
   ▼
Auto-cache the answer → next similar ask is instant
   │
   ▼ (if voice reply requested)
Indic script? ──► AI4Bharat Indic-TTS (Dockerized)  │  Latin script ──► browser voice (instant)
```

## 2. Frozen models

| Role | Model | Where it runs | Why |
|------|-------|---------------|-----|
| Embeddings (RAG + FAQ match) | `nomic-embed-text-v1` | Docker (self-host) | Open, strong retrieval, one model for both search and cache matching |
| Chat — all languages, online | `sarvam-105b` (Sarvam AI) | **Cloud API** | One model strong at English AND Hindi/Marathi/Tamil: fast (~5-12s) AND high quality — the only way to get both on non-GPU hardware. Capped at `SARVAM_DAILY_LIMIT` (default 150) calls/day so the system can never drift into paid usage on its own. |
| Chat — offline / cap-exceeded fallback | `gemma2:2b` | Local Ollama | Single local model covers all languages when Sarvam is unavailable (lower quality, ~30-80s on CPU) |
| Global fallback | `llama3.1:8b` | Local Ollama | Used only if the configured local model is missing at request time |
| Voice output (TTS), Hindi/Marathi/Tamil | AI4Bharat `indic-parler-tts` (0.9B) | Docker (self-host) | Natural Indic voices (Divya/Sunita/Jaya); slow on CPU, so calls are async and fall back to the browser voice on error/timeout |
| Voice output (TTS), English | Browser Web Speech API | Client | Instant, no reason to wait on a model for English |
| Voice input (STT) | Browser Web Speech API (POC) | Client | Zero-setup; AI4Bharat ASR is a future upgrade if browser STT proves insufficient |

**`sarvam-30b` was retired by Sarvam on/before 2026-07-30** and now returns HTTP
400 on every call. That error is caught and falls back to `gemma2:2b` without
surfacing anything, so a stale `SARVAM_MODEL` doesn't look like an outage - it
quietly degrades every Hindi/Marathi answer to 2B-model quality. If Indic
answers ever regress for no obvious reason, check this first.

Everything above is config-driven (`backend/config.py` + env vars). Swapping any
model is a one-line change, no code edits. `SARVAM_API_KEY` is read from the
environment — never committed. The console's **Cost** tab shows live usage against
the daily cap and a per-agent breakdown (Sarvam cloud / local / free cache).

### Local open-source Sarvam model (2B)

Sarvam's open-source 2B model is **`sarvamai/sarvam-1`** on Hugging Face
(20+ Indian languages, incl. Hindi/Marathi/Tamil). It is **not** the same as the
cloud `sarvam-105b`; it is a much smaller, self-hostable model.

Local copy (already downloaded, verified intact):

| Item | Value |
|------|-------|
| Repo | `sarvamai/sarvam-1` |
| Location | `D:\models\sarvam-1` |
| Size | ~5.1 GB (2 `.safetensors` shards: 4,550 MB + 266 MB; 255 tensors) |
| Files | 12 (weights, config, tokenizer, index, license) |
| SHA | `e9607337286ddf496d4a2562b194e489dcf3feea` |

To re-download or update it later:

```bash
python -c "from huggingface_hub import snapshot_download; \
print(snapshot_download(repo_id='sarvamai/sarvam-1', local_dir='D:/models/sarvam-1'))"
```

To run it locally you'd need a transformer/inference runtime (e.g. `transformers`
+ `torch`, or `llama.cpp`/`Ollama` GGUF conversion) — see the "Chat" row in the
frozen-model table for how it fits the stack. This local copy is a ready-to-use
artifact for that, independent of the cloud API.

### Consolidated local model library (`D:\models`)

The `D:\models` folder is the single local model store, consolidating the
downloaded Sarvam models plus every model already present on this machine
(Ollama GGUF blobs and the Hugging Face embedding model). All are **copied**
(original caches untouched, so the running Ollama/embedding setup keeps working).

| Model | Format | Location | Size |
|-------|--------|----------|------|
| sarvam-1 (2B, open-source) | safetensors | `D:\models\sarvam-1` | ~4.8 GB |
| sarvam-30b (retired cloud model) | safetensors (26 shards) | `D:\models\sarvam-30b` | ~119.8 GB |
| sarvam-1 GGUF Q4_K_M | GGUF (Ollama, QuantFactory) | `D:\models\sarvam-1-gguf-Q4_K_M` | ~1.5 GB |
| qwen2.5-coder:1.5b | GGUF (Ollama) | `D:\models\qwen2.5-coder-1.5b` | ~0.9 GB |
| qwen2.5-coder:7b | GGUF (Ollama) | `D:\models\qwen2.5-coder-7b` | ~4.4 GB |
| gemma2:2b | GGUF (Ollama) — the offline chat fallback | `D:\models\gemma2-2b` | ~1.5 GB |
| llama3.1:8b | GGUF (Ollama) — the global fallback | `D:\models\llama3.1-8b` | ~4.7 GB |
| llama3.2:3b | GGUF (Ollama) | `D:\models\llama3.2-3b` | ~1.9 GB |
| bge-small-en-v1.5 | safetensors (HF embedding) | `D:\models\bge-small-en-v1.5` | ~0.1 GB |

Total ~142.7 GB on `D:\`.

The `tools/copy_ollama_models.py` script reads each Ollama model's manifest,
prints the matching GGUF blob (the `application/vnd.ollama.image.model` layer)
into `D:\models\<name>\<name>.gguf`, and is safe to re-run (skips existing
destinations). The embedding model was copied straight from
`~/.cache/huggingface/hub/models--BAAI--bge-small-en-v1.5`.

No Phi model was found on this machine — the `phi`/`phi3` paths in
site-packages are `transformers` library source code, not model weights.

## 3. What has to be hosted

| Component | Resource profile |
|-----------|------------------|
| Python backend (stdlib HTTP) | Negligible — a few MB RAM, tiny CPU |
| Vector store / API keys / FAQ cache | JSON files on disk — negligible |
| Ollama + `llama3.2:3b` | ~4–6 GB RAM; **GPU strongly speeds this up** |
| Embedding service (torch + nomic) | ~2–4 GB RAM; GPU helps |
| AI4Bharat TTS | ~2–4 GB RAM; GPU helps |
| Sarvam (Indic chat) | External cloud — **zero server load** |

## 4. AWS options

### Option A — GPU box (recommended for fast English + local voice)
- **Instance:** `g4dn.xlarge` — 4 vCPU, 16 GB RAM, 1× NVIDIA T4 (16 GB VRAM)
- Runs Ollama (English), embeddings, and AI4Bharat TTS all GPU-accelerated → ~1–3 s LLM latency. Sarvam handles Indic via cloud.
- **Storage:** 50–100 GB gp3 EBS (models + Docker images)
- **Cost:** ~$0.53/hr on-demand ≈ **$380/mo** 24×7; far less with spot, scheduled stop/start, or a 1-yr reserved/savings plan
- **OS:** Ubuntu 22.04 + NVIDIA driver + Docker + Ollama

### Option B — CPU box (cheaper, slower; FAQ cache + Sarvam cover the slow cases)
- **Instance:** `c6i.2xlarge` — 8 vCPU, 16 GB RAM (bump to `4xlarge`/32 GB for headroom)
- Everything on CPU. English LLM ~10–30 s (newer/more cores than the dev laptop, but not GPU-fast). Repeated questions are instant via the FAQ cache; Hindi/Marathi are fast via Sarvam cloud.
- **Storage:** 30–50 GB gp3 EBS
- **Cost:** ~$0.34/hr ≈ **$245/mo** 24×7
- Good starting point for a low-traffic pilot.

### Option C — Thin server + all-cloud AI (cheapest box, pay-per-use AI)
- **Instance:** `t3.small` — 2 vCPU, 2 GB RAM
- Hosts only the Python backend + JSON stores. Route **all** chat to Sarvam (English too), use a cloud embeddings API, and Sarvam/Google for TTS. No GPU, no model management.
- **Cost:** ~**$15/mo** server + per-request API usage
- Simplest ops; scales cleanly; depends fully on cloud AI (and its free-tier/paid limits).

## 5. Production notes (any option)
- **HTTPS:** put the backend behind nginx or an ALB; TLS via ACM or Let's Encrypt. Never expose the raw HTTP port.
- **Process management:** backend as a `systemd` service or container; Ollama as a service; embedding + TTS as Docker containers (compose or ECS).
- **Persistence:** keep `data/` (vector store, `api-keys.json`, `faq-cache.json`) on an EBS volume; back it up.
- **Scaling out:** the backend is stateless and can sit behind an ALB with N instances — but the JSON stores must then move to shared storage (EFS) or a small managed DB (e.g. DynamoDB/RDS) so all instances see the same keys/cache.
- **Secrets:** `SARVAM_API_KEY`, `ADMIN_TOKEN`, and the embedding-service key via SSM Parameter Store or Secrets Manager, injected as env vars — not in the repo.
- **Prospectus updates:** re-run ingest (`POST /api/ingest`) whenever the prospectus PDF changes; the FAQ cache should be cleared on a prospectus change so stale cached answers don't linger.

## 6. Recommendation
Start on **Option B (CPU)** for the pilot — no GPU cost, and the FAQ cache plus
Sarvam-for-Indic already remove most of the slow paths. Move to **Option A (GPU)**
if English-question latency becomes a problem at real traffic, or to **Option C**
if you'd rather run a near-zero-ops box and send everything to Sarvam's cloud.
