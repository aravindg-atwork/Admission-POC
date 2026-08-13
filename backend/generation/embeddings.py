"""Client for the embedding backend - local nomic-embed-text or self-hosted BGE-M3.

.NET/host Python can't run the embedding model in-process here, so it lives behind
an HTTP API, whichever backend is configured (see config.EMBEDDING_PROVIDER).
"""

import json
import urllib.request

from .. import config


def _embed_local(texts):
    payload = json.dumps({"texts": list(texts)}).encode("utf-8")
    req = urllib.request.Request(
        config.EMBEDDING_URL,
        data=payload,
        headers={"Content-Type": "application/json", "X-API-Key": config.EMBEDDING_API_KEY},
        method="POST",
    )
    # Generous: the service runs the model on CPU, and an ingest batch of full
    # table pages (several KB each) is far slower than a single short query.
    # 120s was enough for prose-sized chunks but timed out once whole tables
    # started being embedded as single chunks.
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))["embeddings"]


def _embed_selfhosted(texts):
    """Confirmed 2026-08-11 against the live BGE-M3 deployment: the endpoint
    is POST /v1/embedding (singular), not the OpenAI-standard /v1/embeddings -
    the same style of deviation as this server's chat endpoint (POST
    /v1/chat, not /v1/chat/completions - see providers.SelfHostedProvider).
    The response is {"object", "model", "data": [[float, ...], ...], "usage"}
    - "data" holds raw 1024-dim vectors directly, NOT the OpenAI-shaped list
    of {"embedding": [...]} objects a standards-compliant server would return.
    """
    payload = json.dumps({"model": config.SELFHOSTED_EMBEDDING_MODEL, "input": list(texts)}).encode("utf-8")
    req = urllib.request.Request(
        config.SELFHOSTED_URL.rstrip("/") + "/v1/embedding",
        data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {config.SELFHOSTED_API_KEY}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["data"]


def embed(texts):
    if config.EMBEDDING_PROVIDER == "selfhosted":
        return _embed_selfhosted(texts)
    return _embed_local(texts)
