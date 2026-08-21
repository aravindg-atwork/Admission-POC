"""Client for the self-hosted BGE-M3 embedding service - same account, same
endpoint, as backend/generation/embeddings.py. Ported as httpx instead of
urllib (this codebase's own HTTP client throughout, not a functional
change) but the endpoint SHAPE is preserved exactly, because that shape is
the hard-won part: this is POST /v1/embedding (singular), NOT the
OpenAI-standard /v1/embeddings, and the response is {"data": [[float,...],
...]} - raw vectors directly, not the OpenAI-shaped list of {"embedding":
[...]} objects a standards-compliant server would return. Confirmed
2026-08-11 against the live deployment (see the original module's own
comment) - not re-verified here, just carried forward.
"""

import httpx

from ..settings import get_settings

_settings = get_settings()


def embed(texts: list[str], timeout: float | None = None) -> list[list[float]]:
    """Embed a batch. Defaults to the generous ingest timeout - see
    embed_query for the short, request-path version.
    """
    if timeout is None:
        timeout = _settings.embedding_ingest_timeout
    resp = httpx.post(
        _settings.selfhosted_url.rstrip("/") + "/v1/embedding",
        json={"model": _settings.selfhosted_embedding_model, "input": texts},
        headers={"Authorization": f"Bearer {_settings.selfhosted_api_key}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["data"]


def embed_query(text: str) -> list[float]:
    """Embed ONE question on a student's request path, with a bounded wait -
    the short timeout is the obvious default here rather than something
    every call site has to remember to pass, same reasoning as the ported
    original.
    """
    return embed([text], timeout=_settings.embedding_query_timeout)[0]
