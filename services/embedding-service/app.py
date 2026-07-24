"""
Embedding microservice for the AI Admission Assistant POC.

.NET Framework 4.5 has no supported way to run HuggingFace models in-process,
so embedding generation is isolated here and exposed over a small HTTP API
that the .NET backend (AdmissionAssistant.Core.Embeddings.NomicEmbeddingClient)
calls over HttpClient.

Access to /embed is gated by per-consumer API keys (api_keys.py) so multiple
web apps can each hold their own key and be revoked independently, without
sharing one secret or needing separate URLs per consumer. Manage keys at
/admin (protected by ADMIN_TOKEN).
"""

import os
import secrets
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

import api_keys

MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1")

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")
if not ADMIN_TOKEN:
    ADMIN_TOKEN = secrets.token_urlsafe(24)
    print(f"[embedding-service] ADMIN_TOKEN not set - generated one for this run: {ADMIN_TOKEN}")
    print("[embedding-service] Set ADMIN_TOKEN in the environment to keep it stable across restarts.")

app = FastAPI(title="Admission Assistant Embedding Service")
model = SentenceTransformer(MODEL_NAME, trust_remote_code=True)


def require_api_key(x_api_key: Optional[str] = Header(None)):
    if not x_api_key or not api_keys.is_key_active(x_api_key):
        raise HTTPException(status_code=401, detail="Missing or inactive API key.")


def require_admin(x_admin_token: Optional[str] = Header(None)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token.")


class EmbedRequest(BaseModel):
    texts: List[str]


class EmbedResponse(BaseModel):
    embeddings: List[List[float]]


@app.post("/embed", response_model=EmbedResponse, dependencies=[Depends(require_api_key)])
def embed(request: EmbedRequest) -> EmbedResponse:
    vectors = model.encode(request.texts, normalize_embeddings=True)
    return EmbedResponse(embeddings=[v.tolist() for v in vectors])


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME}


# --- Key management (admin only) ---

class CreateKeyRequest(BaseModel):
    label: str = ""


class SetActiveRequest(BaseModel):
    active: bool


@app.get("/admin/keys", dependencies=[Depends(require_admin)])
def admin_list_keys():
    return api_keys.list_keys()


@app.post("/admin/keys", dependencies=[Depends(require_admin)])
def admin_create_key(request: CreateKeyRequest):
    return api_keys.create_key(request.label)


@app.patch("/admin/keys/{key_id}", dependencies=[Depends(require_admin)])
def admin_set_active(key_id: str, request: SetActiveRequest):
    entry = api_keys.set_active(key_id, request.active)
    if entry is None:
        raise HTTPException(status_code=404, detail="Key not found.")
    return entry


@app.delete("/admin/keys/{key_id}", dependencies=[Depends(require_admin)])
def admin_delete_key(key_id: str):
    if not api_keys.delete_key(key_id):
        raise HTTPException(status_code=404, detail="Key not found.")
    return {"deleted": key_id}


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return (Path(__file__).parent / "admin.html").read_text()
