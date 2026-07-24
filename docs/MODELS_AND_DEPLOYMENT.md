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
FAQ cache lookup ──► hit (cosine ≥ 0.93)? ──► return cached answer  (INSTANT, ~2s, no LLM)
   │ (miss)
   ▼
RAG search  (cosine over prospectus chunks, reuses the same embedding)
   │
   ▼
Language router  (script detection: Latin vs Devanagari/Tamil)
   │                                   │
   ▼ English                           ▼ Hindi / Marathi / Tamil
llama3.2:3b (local Ollama)      Sarvam AI cloud (sarvam-m)
   │                                   │  (local gemma2:2b fallback if offline)
   ▼                                   ▼
                Answer  (+ page citations)
   │
   ▼
Auto-cache the answer  → next similar ask is instant
```

## 2. Frozen models

| Role | Model | Where it runs | Why |
|------|-------|---------------|-----|
| Embeddings (RAG + FAQ match) | `nomic-embed-text-v1` | Docker (self-host) | Open, strong retrieval, one model for both search and cache matching |
| English chat | `llama3.2:3b` | Local Ollama | Small, fast, good English on CPU |
| Hindi / Marathi / Tamil chat | `sarvam-m` (Sarvam AI) | **Cloud API** | Purpose-built for Indian languages: fast AND high quality — the only way to get both on non-GPU hardware |
| Indic offline fallback | `gemma2:2b` | Local Ollama | Keeps the system working without internet (lower quality) |
| Global fallback | `llama3.1:8b` | Local Ollama | Used only if a routed model is missing at request time |
| Voice output (TTS) | AI4Bharat Indic-TTS | Docker (self-host) | Natural Tamil/Hindi/Marathi; browser TTS is the placeholder until this lands |
| Voice input (STT) | Browser Web Speech API (POC) | Client | Zero-setup; AI4Bharat ASR is the production upgrade |

Everything above is config-driven (`backend/config.py` + env vars). Swapping any
model is a one-line change, no code edits. `SARVAM_API_KEY` is read from the
environment — never committed.

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
