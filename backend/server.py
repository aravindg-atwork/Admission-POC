"""HTTP server for the Admission Assistant backend.

Standard-library http.server only - no compiled dependencies, so it runs on the
Windows host under the machine's Application Control policy. Serves the React
frontend (static files) and the JSON API:

  POST /api/chat            X-API-Key gated - ask a question
  POST /api/ingest          X-API-Key gated - upload a prospectus PDF (multipart)
  POST /api/tts             X-API-Key gated - proxy to the Indic TTS service
  GET/POST/PATCH/DELETE /admin/keys[/id]   X-Admin-Token gated - manage keys
"""

import json
import re
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import apikeys, config, rag


def _read_multipart_file(body, content_type):
    """Minimal multipart/form-data parser: returns the first file's raw bytes."""
    m = re.search(r"boundary=(.+)$", content_type)
    if not m:
        return None
    boundary = ("--" + m.group(1).strip('"')).encode()
    parts = body.split(boundary)
    for part in parts:
        if b"Content-Disposition" in part and b"filename=" in part:
            header_end = part.find(b"\r\n\r\n")
            if header_end == -1:
                continue
            data = part[header_end + 4:]
            return data.rstrip(b"\r\n")
    return None


class Handler(BaseHTTPRequestHandler):
    # --- response helpers ---
    def _send(self, status, body, content_type):
        body_bytes = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        try:
            self.wfile.write(body_bytes)
        except (BrokenPipeError, ConnectionAbortedError):
            pass  # client closed the connection; nothing to do

    def _json(self, status, obj):
        self._send(status, json.dumps(obj), "application/json")

    def _admin_ok(self):
        return self.headers.get("X-Admin-Token") == config.ADMIN_TOKEN

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _read_json(self):
        raw = self._read_body()
        return json.loads(raw or b"{}")

    # --- static frontend ---
    _CONTENT_TYPES = {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".woff2": "font/woff2",
    }

    def _serve_static(self, rel_path):
        rel_path = rel_path.lstrip("/") or "index.html"
        target = (config.STATIC_DIR / rel_path).resolve()
        # Prevent path traversal outside the static dir.
        if config.STATIC_DIR.resolve() not in target.parents and target != config.STATIC_DIR.resolve():
            self._send(403, "Forbidden", "text/plain")
            return
        if not target.is_file():
            # SPA fallback: unknown non-API paths serve index.html
            target = config.STATIC_DIR / "index.html"
            if not target.is_file():
                self._send(404, "Not found", "text/plain")
                return
        ctype = self._CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    # --- routes ---
    def do_GET(self):
        if self.path == "/admin" or self.path.startswith("/admin?"):
            self._serve_static("admin.html")
        elif self.path == "/admin/keys":
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            self._json(200, apikeys.list_keys())
        elif self.path.startswith("/api/") or self.path.startswith("/admin/keys/"):
            self._send(404, "Not found", "text/plain")
        else:
            self._serve_static(self.path.split("?")[0])

    def do_POST(self):
        if self.path == "/api/chat":
            if not apikeys.is_active(self.headers.get("X-API-Key")):
                self._json(401, {"error": "Missing or inactive API key."})
                return
            question = (self._read_json().get("question") or "").strip()
            if not question:
                self._json(400, {"error": "Question is required."})
                return
            try:
                result = rag.answer(question)
                self._json(200, {
                    "answerText": result["answer"],
                    "pageReferences": result["pages"],
                    "model": result["model"],
                    "language": result["language"],
                    "source": result["source"],
                })
            except Exception as exc:  # noqa: BLE001 - surface any pipeline error to the client
                self._json(500, {"error": str(exc)})

        elif self.path == "/api/ingest":
            if not apikeys.is_active(self.headers.get("X-API-Key")):
                self._json(401, {"error": "Missing or inactive API key."})
                return
            body = self._read_body()
            file_bytes = _read_multipart_file(body, self.headers.get("Content-Type", ""))
            if not file_bytes:
                self._json(400, {"error": "Expected a PDF file in multipart/form-data."})
                return
            config.PROSPECTUS_DIR.mkdir(parents=True, exist_ok=True)
            saved = config.PROSPECTUS_DIR / "prospectus.pdf"
            saved.write_bytes(file_bytes)
            try:
                self._json(200, rag.ingest(saved))
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})

        elif self.path == "/api/tts":
            if not apikeys.is_active(self.headers.get("X-API-Key")):
                self._json(401, {"error": "Missing or inactive API key."})
                return
            self._proxy_tts()

        elif self.path == "/admin/keys":
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            label = (self._read_json().get("label") or "").strip()
            self._json(200, apikeys.create(label))

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
        entry = apikeys.set_active(m.group(1), bool(self._read_json().get("active")))
        self._json(200 if entry else 404, entry or {"error": "Key not found."})

    def do_DELETE(self):
        m = re.match(r"^/admin/keys/([^/]+)$", self.path)
        if not m:
            self._send(404, "Not found", "text/plain")
            return
        if not self._admin_ok():
            self._json(401, {"error": "Invalid admin token."})
            return
        ok = apikeys.delete(m.group(1))
        self._json(200 if ok else 404, {"deleted": m.group(1)} if ok else {"error": "Key not found."})

    def _proxy_tts(self):
        """Forward a {text, language} body to the Dockerized Indic TTS service."""
        body = self._read_body()
        try:
            req = urllib.request.Request(
                config.TTS_URL, data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                audio = resp.read()
                self._send(200, audio, resp.headers.get("Content-Type", "audio/wav"))
        except Exception:  # noqa: BLE001 - TTS service optional / may be offline
            self._json(503, {"error": "TTS service unavailable."})

    def log_message(self, fmt, *args):
        print("[backend]", fmt % args)


def serve():
    apikeys.get_or_create_default()
    httpd = ThreadingHTTPServer(("0.0.0.0", config.PORT), Handler)
    print("Admission Assistant backend running:")
    print("  Chat    : http://localhost:{}/".format(config.PORT))
    print("  Console : http://localhost:{}/admin  (admin token: {})".format(config.PORT, config.ADMIN_TOKEN))
    primary = ("Sarvam:" + config.SARVAM_MODEL) if config.SARVAM_API_KEY else "(no Sarvam key)"
    print("  Models  : online={}  offline={}".format(primary, config.MODEL_LOCAL))
    httpd.serve_forever()
