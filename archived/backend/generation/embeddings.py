"""Client for the embedding backend - local nomic-embed-text or self-hosted BGE-M3.

.NET/host Python can't run the embedding model in-process here, so it lives behind
an HTTP API, whichever backend is configured (see config.EMBEDDING_PROVIDER).
"""

import json
import urllib.request

from .. import config


def _embed_local(texts, timeout):
    payload = json.dumps({"texts": list(texts)}).encode("utf-8")
    req = urllib.request.Request(
        config.EMBEDDING_URL,
        data=payload,
        headers={"Content-Type": "application/json", "X-API-Key": config.EMBEDDING_API_KEY},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))["embeddings"]


def _embed_selfhosted(texts, timeout):
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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["data"]


def embed(texts, timeout=None):
    """Embed a batch. Defaults to the generous ingest timeout.

    The default is the SLOW one deliberately: an existing batch caller that is
    not updated keeps working, whereas defaulting to the short query timeout
    would make ingest start failing on large table chunks with no obvious
    cause. Request-path callers should use embed_query instead of passing a
    timeout by hand.
    """
    if timeout is None:
        timeout = config.EMBEDDING_INGEST_TIMEOUT
    if config.EMBEDDING_PROVIDER == "selfhosted":
        return _embed_selfhosted(texts, timeout)
    return _embed_local(texts, timeout)


def embed_query(text):
    """Embed ONE question on a student's request path, with a bounded wait.

    Exists so the short timeout is the obvious thing to reach for rather than
    something each call site has to remember to pass. Every caller in rag/ is
    on the request path and should use this; ingest and seeding are the only
    legitimate users of the batch form above.
    """
    return embed([text], timeout=config.EMBEDDING_QUERY_TIMEOUT)[0]
