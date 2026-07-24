"""HTTP server for the Admission Assistant backend.

Standard-library http.server only - no compiled dependencies, so it runs on the
Windows host under the machine's Application Control policy. Serves the React
frontend (static files) and the JSON API:

  POST /api/chat                         X-API-Key gated - ask a question
  POST /api/ingest                       X-API-Key gated - upload a prospectus PDF (multipart)
  POST /api/tts                          X-API-Key gated - proxy to the Indic TTS service
  POST /api/catalogue/match              X-API-Key gated - rank catalogue items against quotation text
  GET/POST        /admin/projects[/id]   X-Admin-Token gated - manage projects
  PATCH           /admin/projects/id     X-Admin-Token gated - update project settings (e.g. allow_cloud)
  DELETE          /admin/projects/id     X-Admin-Token gated - delete a project
  GET             /admin/projects/id/stats   X-Admin-Token gated - dashboard/cost metrics + health
  POST            /admin/projects/id/ingest  X-Admin-Token gated - upload a prospectus PDF (multipart)
  POST            /admin/projects/id/cache/clear  X-Admin-Token gated - clear that project's FAQ cache
  GET/POST/PATCH/DELETE /admin/keys[/id] X-Admin-Token gated - manage keys

Every key belongs to exactly one project; /api/chat and /api/ingest resolve
which project's pipeline to run from the key, so different projects never
share a prospectus, vector store, or cost numbers.
"""

import json
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import apikeys, catalogue, config, faq, llm, projects, rag, stats, textclean

# Injected into index.html so the first-party chat widget authenticates without the
# key being hard-coded in client files.
_KEY_SNIPPET = '<script>window.ADMISSION_API_KEY="{}";</script>'


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
    def _serve_index(self):
        target = config.STATIC_DIR / "index.html"
        if not target.is_file():
            self._send(404, "Not found", "text/plain")
            return
        html = target.read_text(encoding="utf-8")
        key = apikeys.get_or_create_default(config.DEFAULT_PROJECT_ID)["key"]
        html = html.replace("</head>", _KEY_SNIPPET.format(key) + "</head>", 1)
        self._send(200, html, "text/html; charset=utf-8")

    def do_GET(self):
        m_stats = re.match(r"^/admin/projects/([^/]+)/stats$", self.path)

        if self.path == "/" or self.path.startswith("/?") or self.path == "/index.html":
            self._serve_index()
        elif self.path == "/admin" or self.path.startswith("/admin?"):
            self._serve_static("admin.html")
        elif self.path == "/admin/keys":
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            self._json(200, apikeys.list_keys())
        elif self.path == "/admin/projects":
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            self._json(200, [self._project_summary(p) for p in projects.list_projects()])
        elif m_stats:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            project_id = m_stats.group(1)
            if not projects.get(project_id):
                self._json(404, {"error": "Project not found."})
                return
            self._json(200, self._build_stats(project_id))
        elif self.path.startswith("/api/") or self.path.startswith("/admin/keys/") \
                or self.path.startswith("/admin/projects/"):
            self._send(404, "Not found", "text/plain")
        else:
            self._serve_static(self.path.split("?")[0])

    def do_POST(self):
        m_ingest = re.match(r"^/admin/projects/([^/]+)/ingest$", self.path)
        m_clear = re.match(r"^/admin/projects/([^/]+)/cache/clear$", self.path)

        if self.path == "/api/chat":
            project_id = apikeys.resolve_active(self.headers.get("X-API-Key"))
            if not project_id:
                self._json(401, {"error": "Missing or inactive API key."})
                return
            body = self._read_json()
            question = (body.get("question") or "").strip()
            if not question:
                self._json(400, {"error": "Question is required."})
                return
            # "hinglish" is the only non-default value: Hindi answered in Roman
            # script instead of Devanagari, an explicit user choice (see rag.py).
            script_pref = "hinglish" if body.get("scriptPreference") == "hinglish" else "auto"
            try:
                result = rag.answer(project_id, question, script_pref)
                self._json(200, {
                    "answerText": result["answer"],
                    "pageReferences": result["pages"],
                    "model": result["model"],
                    "language": result["language"],
                    "source": result["source"],
                    "speakable": result["speakable"],
                })
            except Exception as exc:  # noqa: BLE001 - surface any pipeline error to the client
                self._json(500, {"error": str(exc)})

        elif self.path == "/api/ingest":
            project_id = apikeys.resolve_active(self.headers.get("X-API-Key"))
            if not project_id:
                self._json(401, {"error": "Missing or inactive API key."})
                return
            self._handle_ingest(project_id)

        elif self.path == "/api/tts":
            if not apikeys.is_active(self.headers.get("X-API-Key")):
                self._json(401, {"error": "Missing or inactive API key."})
                return
            self._proxy_tts()

        elif self.path == "/api/catalogue/match":
            if not apikeys.is_active(self.headers.get("X-API-Key")):
                self._json(401, {"error": "Missing or inactive API key."})
                return
            body = self._read_json()
            quotation_text = (body.get("quotationText") or "").strip()
            items = body.get("items") or []
            if not quotation_text or not items:
                self._json(400, {"error": "quotationText and items are required."})
                return
            try:
                self._json(200, {"matches": catalogue.match(quotation_text, items)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})

        elif self.path == "/admin/keys":
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            body = self._read_json()
            label = (body.get("label") or "").strip()
            project_id = body.get("project_id") or config.DEFAULT_PROJECT_ID
            if not projects.get(project_id):
                self._json(404, {"error": "Project not found."})
                return
            self._json(200, apikeys.create(label, project_id))

        elif self.path == "/admin/projects":
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            name = (self._read_json().get("name") or "").strip()
            entry = projects.create(name)
            self._json(200, self._project_summary(entry))

        elif m_ingest:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            project_id = m_ingest.group(1)
            if not projects.get(project_id):
                self._json(404, {"error": "Project not found."})
                return
            self._handle_ingest(project_id)

        elif m_clear:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            project_id = m_clear.group(1)
            if not projects.get(project_id):
                self._json(404, {"error": "Project not found."})
                return
            faq.clear(projects.faq_path(project_id))
            self._json(200, {"cleared": True})

        else:
            self._send(404, "Not found", "text/plain")

    def do_PATCH(self):
        m_key = re.match(r"^/admin/keys/([^/]+)$", self.path)
        m_project = re.match(r"^/admin/projects/([^/]+)$", self.path)

        if m_key:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            entry = apikeys.set_active(m_key.group(1), bool(self._read_json().get("active")))
            self._json(200 if entry else 404, entry or {"error": "Key not found."})
        elif m_project:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            project_id = m_project.group(1)
            if not projects.get(project_id):
                self._json(404, {"error": "Project not found."})
                return
            body = self._read_json()
            if "allow_cloud" in body:
                projects.set_allow_cloud(project_id, bool(body["allow_cloud"]))
            self._json(200, self._project_summary(projects.get(project_id)))
        else:
            self._send(404, "Not found", "text/plain")

    def do_DELETE(self):
        m_key = re.match(r"^/admin/keys/([^/]+)$", self.path)
        m_project = re.match(r"^/admin/projects/([^/]+)$", self.path)

        if m_key:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            ok = apikeys.delete(m_key.group(1))
            self._json(200 if ok else 404, {"deleted": m_key.group(1)} if ok else {"error": "Key not found."})
        elif m_project:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            ok = projects.delete(m_project.group(1))
            self._json(200 if ok else 404, {"deleted": m_project.group(1)} if ok else {"error": "Project not found."})
        else:
            self._send(404, "Not found", "text/plain")

    def _handle_ingest(self, project_id):
        """Save an uploaded prospectus PDF and run rag.ingest() for a project.
        Shared by the API-key-gated /api/ingest and the admin-token-gated
        /admin/projects/:id/ingest (the console's drag-a-PDF-onto-a-project flow)."""
        body = self._read_body()
        file_bytes = _read_multipart_file(body, self.headers.get("Content-Type", ""))
        if not file_bytes:
            self._json(400, {"error": "Expected a PDF file in multipart/form-data."})
            return
        saved = projects.prospectus_path(project_id)
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(file_bytes)
        try:
            self._json(200, rag.ingest(project_id, saved))
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": str(exc)})

    def _project_summary(self, p):
        """Projects-rail payload: prospectus/embedding status and a compact
        cost/usage snapshot per project, without needing to open it."""
        project_id = p["id"]
        manifest = {}
        mpath = projects.manifest_path(project_id)
        if mpath.exists():
            try:
                manifest = json.loads(mpath.read_text(encoding="utf-8"))
            except ValueError:
                manifest = {}
        snap = stats.snapshot(projects.stats_path(project_id))
        keys = apikeys.list_keys(project_id)
        return {
            "id": project_id,
            "name": p["name"],
            "createdAt": p["created_at"],
            "allowCloud": projects.allow_cloud(project_id),
            "prospectus": {
                "embedded": bool(manifest),
                "chunksIndexed": manifest.get("chunksIndexed"),
                "pagesProcessed": manifest.get("pagesProcessed"),
                "embeddedAt": manifest.get("embeddedAt"),
            },
            "totalQuestions": snap["totalQuestions"],
            "sarvamCalls": snap["sarvamCalls"],
            "localCalls": snap["localCalls"],
            "cacheHits": snap["cacheHits"],
            "activeKeys": sum(1 for k in keys if k["active"]),
            "totalKeys": len(keys),
        }

    def _build_stats(self, project_id):
        """Dashboard + Cost panel payload for one project: usage snapshot, the
        (account-wide) Sarvam cap, live health, key count. Health checks hit the
        embedding service and Ollama (cheap, local, shared across projects) but
        never Sarvam - pinging a paid endpoint just to render a dashboard would
        burn against the daily cap for nothing."""
        snap = stats.snapshot(projects.stats_path(project_id))
        keys = apikeys.list_keys(project_id)
        return {
            **snap,
            "sarvam": llm.sarvam_usage(),
            "allowCloud": projects.allow_cloud(project_id),
            "activeKeys": sum(1 for k in keys if k["active"]),
            "totalKeys": len(keys),
            "health": self._check_health(),
        }

    @staticmethod
    def _check_health():
        health = {}
        try:
            urllib.request.urlopen(config.EMBEDDING_URL.rsplit("/embed", 1)[0] + "/health", timeout=2)
            health["embedding"] = "up"
        except Exception:  # noqa: BLE001
            health["embedding"] = "down"
        try:
            urllib.request.urlopen(config.OLLAMA_URL.rstrip("/") + "/api/tags", timeout=2)
            health["ollama"] = "up"
        except Exception:  # noqa: BLE001
            health["ollama"] = "down"
        health["sarvam"] = "configured" if config.SARVAM_API_KEY else "not configured"
        return health

    def _proxy_tts(self):
        """Forward a {text, language} body to the Dockerized Indic TTS service,
        after stripping markdown noise so the voice doesn't read out asterisks
        and bullet dashes."""
        try:
            payload = self._read_json()
            payload["text"] = textclean.clean_for_speech(payload.get("text") or "")
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                config.TTS_URL, data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                audio = resp.read()
                self._send(200, audio, resp.headers.get("Content-Type", "audio/wav"))
        except Exception:  # noqa: BLE001 - TTS service optional / may be offline
            self._json(503, {"error": "TTS service unavailable."})

    def log_message(self, fmt, *args):
        print("[backend]", fmt % args)


def serve():
    projects.migrate_legacy_if_needed()
    if not projects.list_projects():
        projects.create("Admission Assistant", config.DEFAULT_PROJECT_ID)
    apikeys.get_or_create_default(config.DEFAULT_PROJECT_ID)

    httpd = ThreadingHTTPServer(("0.0.0.0", config.PORT), Handler)
    print("Admission Assistant backend running:")
    print("  Chat    : http://localhost:{}/".format(config.PORT))
    print("  Console : http://localhost:{}/admin  (admin token: {})".format(config.PORT, config.ADMIN_TOKEN))
    primary = ("Sarvam:" + config.SARVAM_MODEL) if config.SARVAM_API_KEY else "(no Sarvam key)"
    print("  Models  : online={}  offline={}".format(primary, config.MODEL_LOCAL))
    httpd.serve_forever()
