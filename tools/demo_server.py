"""
Interactive dev server for the AI Admission Assistant POC control panel.

This dev machine's Application Control policy blocks freshly-built .NET binaries
(and FastAPI's compiled pydantic-core), so the real C# self-host can't run here.
This pure-stdlib server is the live stand-in: it serves the REAL Web project files
(Default.aspx chat widget, Admin.aspx console, their CSS/JS - directives stripped)
and mirrors the same behaviour the C# code implements:

  - API key store with generate / activate / deactivate / delete
  - /api/chat gated by an active X-API-Key (like ApiKeyAuthorizeAttribute)
  - /admin/keys/* gated by X-Admin-Token (like AdminController)
  - an auto-provisioned always-on key for the site's own chat widget, injected
    into Default.aspx (like Default.aspx.cs)

Backed by the proven pipeline: the Dockerized embedding-service + Ollama, reusing
the vector store already built from the real prospectus PDF.
"""

import json
import os
import re
import secrets
import threading
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB_ROOT = Path(r"C:\Users\Admin\Desktop\AI Assissant POC\src\AdmissionAssistant.Web")
STORE_PATH = Path(__file__).parent / "demo-vector-store.json"
KEYS_PATH = Path(__file__).parent / "demo-api-keys.json"

EMBEDDING_URL = "http://localhost:8000/embed"
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", "")
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.1"
ADMIN_TOKEN = "poc-admin-dev-token"
DEFAULT_KEY_LABEL = "admission-site"
TOP_K = 5
PORT = 5050

LANGUAGE_RULE = (
    "IMPORTANT: Reply in the SAME language and script the student used. If they wrote "
    "in Tamil, reply in natural Tamil; Hindi to Hindi; Marathi to Marathi; English to "
    "English. Write the way people actually speak that language, keeping common English "
    "loanwords they used (for example 'document', 'application', 'college') as-is in "
    "their script instead of forcing a formal translation. Never switch to a different "
    "language than the student used. Never answer a real question with only a greeting."
)

SYSTEM_PROMPT = (
    "You are a warm, friendly admissions assistant helping students with the "
    "B.V.Sc. & A.H. program. Talk naturally and kindly, like a helpful counselor "
    "who wants the student to feel at ease. When they ask about admissions, answer "
    "using ONLY the prospectus excerpts provided and never invent details. If the "
    "excerpts don't cover something, say so gently and point them to what you can help "
    "with. Weave page references into your answer naturally (for example, 'you'll find "
    "this on page 9') rather than listing them mechanically. Keep answers clear, "
    "encouraging, and easy for a nervous applicant to follow. " + LANGUAGE_RULE
)

GREETING_SYSTEM_PROMPT = (
    "You are a warm, friendly admissions assistant for the B.V.Sc. & A.H. program. "
    "The student is only greeting you, not asking a question yet. Reply warmly in one "
    "or two short sentences and invite them to ask about eligibility, dates, fees, or "
    "documents. " + LANGUAGE_RULE
)

# Exact-match greetings only, across the four supported languages. Deliberately NOT
# length-based: a longer question in any script must never be mistaken for a greeting
# (that bug greeted a real Tamil document question instead of answering it).
SMALL_TALK = {
    "hi", "hey", "hello", "yo", "hii", "hiya", "hey there",
    "thanks", "thank you", "thankyou", "ok", "okay", "bye", "goodbye",
    "namaste", "namaskar", "vanakkam", "vanakam",
    "वणक्कम्",       # வணக்கம் (Tamil)
    "नमस्ते",             # नमस्ते (Hindi)
    "नमस्कार",       # नमस्कार (Hindi/Marathi)
    "हाय", "हेलो",   # हाय / हेलो
}

STORE = json.loads(STORE_PATH.read_text())
print("Loaded", len(STORE), "chunks from", STORE_PATH)

_keys_lock = threading.Lock()


# --- API key store (mirrors AdmissionAssistant.Core.Security.ApiKeyStore) ---

def _load_keys():
    if not KEYS_PATH.exists():
        return []
    return json.loads(KEYS_PATH.read_text() or "[]")


def _save_keys(keys):
    KEYS_PATH.write_text(json.dumps(keys, indent=2))


def list_keys():
    with _keys_lock:
        return _load_keys()


def create_key(label):
    with _keys_lock:
        keys = _load_keys()
        entry = {
            "id": secrets.token_hex(6),
            "key": "aas_" + secrets.token_urlsafe(32),
            "label": label or "unlabeled",
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        keys.append(entry)
        _save_keys(keys)
        return entry


def set_active(key_id, active):
    with _keys_lock:
        keys = _load_keys()
        for entry in keys:
            if entry["id"] == key_id:
                entry["active"] = active
                _save_keys(keys)
                return entry
        return None


def delete_key(key_id):
    with _keys_lock:
        keys = _load_keys()
        remaining = [k for k in keys if k["id"] != key_id]
        if len(remaining) == len(keys):
            return False
        _save_keys(remaining)
        return True


def is_key_active(key_value):
    if not key_value:
        return False
    with _keys_lock:
        return any(k["key"] == key_value and k["active"] for k in _load_keys())


def get_or_create_default():
    with _keys_lock:
        keys = _load_keys()
        for entry in keys:
            if entry["label"] == DEFAULT_KEY_LABEL:
                return entry
        entry = {
            "id": secrets.token_hex(6),
            "key": "aas_" + secrets.token_urlsafe(32),
            "label": DEFAULT_KEY_LABEL,
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        keys.append(entry)
        _save_keys(keys)
        return entry


# --- Pipeline ---

def post_json(url, payload, headers=None, timeout=280):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def embed(texts):
    result = post_json(EMBEDDING_URL, {"texts": texts}, {"X-API-Key": EMBEDDING_API_KEY})
    return result["embeddings"]


def cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def is_small_talk(text):
    cleaned = text.lower().strip().strip("!.?,। ")
    return cleaned in SMALL_TALK


def answer_question(question):
    if is_small_talk(question):
        payload = {
            "model": OLLAMA_MODEL,
            "stream": False,
            "messages": [
                {"role": "system", "content": GREETING_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
        }
        result = post_json(OLLAMA_URL, payload)
        return result["message"]["content"], []

    q_vector = embed([question])[0]
    scored = sorted(STORE, key=lambda e: cosine_similarity(q_vector, e["vector"]), reverse=True)
    top = scored[:TOP_K]
    context = "\n\n".join("[Page {}] {}".format(e["page"], e["text"]) for e in top)

    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Prospectus excerpts:\n" + context + "\n\nQuestion: " + question},
        ],
    }
    result = post_json(OLLAMA_URL, payload)
    return result["message"]["content"], sorted(set(e["page"] for e in top))


# --- HTTP handler ---

def read_web_file(*parts):
    return (WEB_ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def strip_aspx_directive(raw):
    return re.sub(r"^<%@.*?%>\s*", "", raw, flags=re.DOTALL)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type):
        body_bytes = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj), "application/json")

    def _admin_ok(self):
        return self.headers.get("X-Admin-Token") == ADMIN_TOKEN

    def do_GET(self):
        if self.path in ("/", "/Default.aspx"):
            html = strip_aspx_directive(read_web_file("Default.aspx"))
            key = get_or_create_default()["key"]
            html = html.replace("<%= DefaultApiKey %>", key)
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path in ("/Admin.aspx", "/admin"):
            html = strip_aspx_directive(read_web_file("Admin.aspx"))
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path == "/Content/site.css":
            self._send(200, read_web_file("Content", "site.css"), "text/css")
        elif self.path == "/Content/admin.css":
            self._send(200, read_web_file("Content", "admin.css"), "text/css")
        elif self.path == "/Scripts/chat.js":
            self._send(200, read_web_file("Scripts", "chat.js"), "application/javascript")
        elif self.path == "/Scripts/admin.js":
            self._send(200, read_web_file("Scripts", "admin.js"), "application/javascript")
        elif self.path == "/admin/keys":
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            self._json(200, list_keys())
        else:
            self._send(404, "Not found", "text/plain")

    def do_POST(self):
        if self.path == "/api/chat":
            if not is_key_active(self.headers.get("X-API-Key")):
                self._json(401, {"error": "Missing or inactive API key."})
                return
            body = self._read_json()
            question = (body.get("question") or "").strip()
            if not question:
                self._json(400, {"error": "Question is required."})
                return
            try:
                answer_text, pages = answer_question(question)
                self._json(200, {"answerText": answer_text, "pageReferences": pages})
            except Exception as exc:
                self._json(500, {"error": str(exc)})
        elif self.path == "/admin/keys":
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            body = self._read_json()
            self._json(200, create_key((body.get("label") or "").strip()))
        else:
            self._send(404, "Not found", "text/plain")

    def do_PATCH(self):
        m = re.match(r"^/admin/keys/([^/]+)$", self.path)
        if not m:
            self._send(404, "Not found", "text/plain")
            return
        if not self._admin_ok():
            self._json(401, {"error": "Invalid admin token."})
            return
        body = self._read_json()
        entry = set_active(m.group(1), bool(body.get("active")))
        self._json(200 if entry else 404, entry or {"error": "Key not found."})

    def do_DELETE(self):
        m = re.match(r"^/admin/keys/([^/]+)$", self.path)
        if not m:
            self._send(404, "Not found", "text/plain")
            return
        if not self._admin_ok():
            self._json(401, {"error": "Invalid admin token."})
            return
        ok = delete_key(m.group(1))
        self._json(200 if ok else 404, {"deleted": m.group(1)} if ok else {"error": "Key not found."})

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def log_message(self, fmt, *args):
        print("[demo_server]", fmt % args)


if __name__ == "__main__":
    get_or_create_default()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("Admission Assistant demo running:")
    print("  Chat widget : http://localhost:{}/".format(PORT))
    print("  Console     : http://localhost:{}/admin  (admin token: {})".format(PORT, ADMIN_TOKEN))
    server.serve_forever()
