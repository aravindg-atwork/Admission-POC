# Embedding service

Wraps the open-source `nomic-ai/nomic-embed-text-v1` model (via HuggingFace
`sentence-transformers`) behind a tiny HTTP API, since .NET Framework 4.5
can't load HuggingFace models in-process.

## Run

```
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

## API

`POST /embed` — requires header `X-API-Key: <an active key>`

```json
{ "texts": ["some prospectus chunk text"] }
```

```json
{ "embeddings": [[0.01, -0.02, "..."]] }
```

`GET /health` — returns `{ "status": "ok", "model": "..." }`, no key required.

## Managing API keys

Every consumer of `/embed` (the WebForms app, or any other web app later)
gets its own key, so any one of them can be revoked without touching the
others. Keys are stored in `api_keys.json` (gitignored) next to `app.py`.

On startup, if `ADMIN_TOKEN` isn't set in the environment, one is generated
and printed to the console — set it explicitly to keep it stable across
restarts:

```
set ADMIN_TOKEN=your-own-secret
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/admin`, paste the admin token in, and:

- generate a new key with a label (e.g. `admission-webforms`)
- deactivate/reactivate any key without deleting it
- delete a key entirely

Whatever key you generate for the WebForms app goes into
`src/AdmissionAssistant.Web/Web.config` as `EmbeddingServiceApiKey`.

Admin endpoints (`/admin/*`) require header `X-Admin-Token: <ADMIN_TOKEN>`
instead of an API key — they manage keys, they aren't gated by one.
