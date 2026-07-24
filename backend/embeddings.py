"""Client for the Dockerized embedding service (nomic-embed-text).

.NET/host Python can't run the embedding model in-process here, so it lives in a
container and we call it over HTTP - the same shape as any hosted embeddings API.
"""

import json
import urllib.request

from . import config


def embed(texts):
    payload = json.dumps({"texts": list(texts)}).encode("utf-8")
    req = urllib.request.Request(
        config.EMBEDDING_URL,
        data=payload,
        headers={"Content-Type": "application/json", "X-API-Key": config.EMBEDDING_API_KEY},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))["embeddings"]
