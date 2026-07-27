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
    # Generous: the service runs the model on CPU, and an ingest batch of full
    # table pages (several KB each) is far slower than a single short query.
    # 120s was enough for prose-sized chunks but timed out once whole tables
    # started being embedded as single chunks.
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))["embeddings"]
