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
  POST            /admin/projects/id/cache/seed   X-Admin-Token gated - bulk-load curated Q&A into that cache
  GET/POST/PATCH/DELETE /admin/keys[/id] X-Admin-Token gated - manage keys

Every key belongs to exactly one project; /api/chat and /api/ingest resolve
which project's pipeline to run from the key, so different projects never
share a prospectus, vector store, or cost numbers.
"""

import concurrent.futures
import json
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import (apikeys, catalogue, config, embeddings, extension_settings, faq,
               llm, projects, rag, stats, textclean)

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
        # The browser extension calls this API cross-origin (chrome-extension://...)
        # from its background service worker. No cookies/credentials are ever
        # used here (auth is the X-API-Key/X-Admin-Token header instead), so a
        # wildcard is safe and means the extension needs no special permission
        # grant just to reach its own backend - it works the same way any
        # normal CORS-enabled API would for any caller.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body_bytes)
        except (BrokenPipeError, ConnectionAbortedError):
            pass  # client closed the connection; nothing to do

    def do_OPTIONS(self):
        # CORS preflight: the browser sends this before any POST/PATCH/DELETE
        # with a JSON body or custom header, and won't proceed to the real
        # request unless it gets an explicit yes here.
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key, X-Admin-Token")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

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
        if config.STATIC_DIR.resolve() not in target.parents and target != config.STATIC_DIR.resolve():
            self._send(403, "Forbidden", "text/plain")
            return
        if not target.is_file():
            target = config.STATIC_DIR / "index.html"
            if not target.is_file():
                self._send(404, "Not found", "text/plain")
                return
        ctype = self._CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

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
        elif self.path == "/admin/extension-settings":
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            self._json(200, extension_settings.get_settings())
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
        m_seed = re.match(r"^/admin/projects/([^/]+)/cache/seed$", self.path)

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
            script_pref = "native" if body.get("scriptPreference") == "native" else "auto"
            ui_language = body.get("uiLanguage") if body.get("uiLanguage") in ("en", "hi", "mr", "ta") else None
            try:
                result = rag.answer(project_id, question, script_pref, ui_language)
                self._json(200, {
                    "answerText": result["answer"],
                    "pageReferences": result["pages"],
                    "model": result["model"],
                    "language": result["language"],
                    "source": result["source"],
                    "speakable": result["speakable"],
                })
            except Exception as exc:
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
            quotation_lines = [
                line.strip() for line in (body.get("quotationLines") or []) if line and line.strip()
            ]
            items = body.get("items") or []
            threshold = body.get("threshold")
            threshold = threshold if isinstance(threshold, (int, float)) else 0.55
            if not quotation_text or not items:
                self._json(400, {"error": "quotationText and items are required."})
                return
            try:
                # The semantic match (embedding call) and the complementary
                # suggestion (LLM call) are independent - the latter no longer
                # waits on the former's result to know what to exclude, it
                # dedupes against it afterwards instead. That lets both I/O-bound
                # calls run concurrently instead of back-to-back, since a rep is
                # sitting there waiting on this response before Send goes through.
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    if quotation_lines:
                        match_future = pool.submit(
                            catalogue.match_lines, quotation_lines, items, threshold=threshold)
                    else:
                        match_future = pool.submit(catalogue.match, quotation_text, items)
                    complementary_future = pool.submit(
                        catalogue.suggest_complementary, quotation_text, items, set())

                    matches = match_future.result()
                    complementary = complementary_future.result()

                existing_ids = {m["id"] for m in matches}
                matches += [c for c in complementary if c["id"] not in existing_ids]
                self._json(200, {"matches": matches})
            except Exception as exc:
                self._json(500, {"error": str(exc)})

        elif self.path == "/api/catalogue/note":
            if not apikeys.is_active(self.headers.get("X-API-Key")):
                self._json(401, {"error": "Missing or inactive API key."})
                return
            body = self._read_json()
            quotation_text = (body.get("quotationText") or "").strip()
            matched_items = body.get("matchedItems") or []
            if not matched_items:
                single = body.get("matchedItem") or {}
                matched_items = [single] if single.get("name") else []
            if not quotation_text or not matched_items:
                self._json(400, {"error": "quotationText and matchedItems are required."})
                return
            try:
                note, model = catalogue.generate_note(quotation_text, matched_items)
                self._json(200, {"note": note, "model": model})
            except Exception as exc:
                self._json(500, {"error": str(exc)})

        # --- Extension endpoints ---
        elif self.path == "/api/extension/register":
            body = self._read_json()
            try:
                 registration = extension_settings.get_registration()
                 if not registration.get("driveFolderId"):
                     registration["autoDiscoverFolders"] = True
                 self._json(200, registration)
            except Exception as exc:
                 self._json(500, {"error": str(exc)})

        elif self.path == "/api/extension/report-config":
            # Lets an install report back a Drive folder ID it discovered on
            # its own (see discoverDriveFolders in background.js), so it
            # becomes the durable default for every future /register call -
            # this install's next service-worker restart included - instead
            # of forcing a fresh Drive rescan every time. Deliberately scoped
            # to just driveFolderId: everything else in extension settings is
            # admin-controlled (via /admin/extension-settings) and shouldn't
            # be overwritable by any regular API key holder.
            if not apikeys.is_active(self.headers.get("X-API-Key")):
                self._json(401, {"error": "Missing or inactive API key."})
                return
            body = self._read_json()
            drive_folder_id = (body.get("driveFolderId") or "").strip()
            if drive_folder_id:
                extension_settings.update_settings({"driveFolderId": drive_folder_id})
            self._json(200, {"ok": True})

        elif self.path == "/api/extension/discover-folders":
            body = self._read_json()
            folders = body.get("folders", [])
            if not folders:
                self._json(200, {"folderId": "", "hint": "No catalogue folder found. Create one named 'Catalogue' or 'Brochures'."})
                return
            try:
                folder_lines = "\n".join(f"- ID: {f['id']}  Name: {f.get('name','')}" for f in folders)
                prompt = ("You are setting up a sales brochure matching system. "
                    "The user's Google Drive has these folders that may contain product brochures/catalogues:\n"
                    f"{folder_lines}\n\n"
                    "Pick the one most likely to contain product brochures or marketing catalogues "
                    "for a sales quotation system. Reply with ONLY the folder ID, nothing else.")
                answer, _ = llm.generate("Select best catalogue folder. Reply ONLY with folder ID.", prompt, "", timeout=30, allow_cloud=True)
                best_id = answer.strip().strip('"\'').strip()
                if any(f.get("id") == best_id for f in folders):
                    folder = next(f for f in folders if f["id"] == best_id)
                    self._json(200, {"folderId": best_id, "folderName": folder.get("name", "")})
                else:
                    heuristic = max(folders, key=lambda f: sum(w in (f.get("name","")+" "+f.get("description","")).lower() for w in ["catalogue","catalog","brochure","product","template","flyer","brochures"]))
                    self._json(200, {"folderId": heuristic["id"], "folderName": heuristic.get("name", "")})
            except Exception:
                heuristic = max(folders, key=lambda f: sum(w in (f.get("name","")+" "+f.get("description","")).lower() for w in ["catalogue","catalog","brochure","product","template","flyer","brochures"]))
                self._json(200, {"folderId": heuristic["id"], "folderName": heuristic.get("name", "")})

        elif self.path == "/api/extension/config":
            try:
                 settings = extension_settings.get_settings()
                 self._json(200, {"settings": settings})
            except Exception as exc:
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

        elif m_seed:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            project_id = m_seed.group(1)
            if not projects.get(project_id):
                self._json(404, {"error": "Project not found."})
                return
            items = self._read_json().get("items") or []
            if not isinstance(items, list) or not items:
                self._json(400, {"error": "Expected a non-empty 'items' list."})
                return
            try:
                count = faq.seed(projects.faq_path(project_id), items, embeddings.embed)
                self._json(200, {"seeded": count})
            except Exception as exc:
                self._json(500, {"error": str(exc)})

        else:
            self._send(404, "Not found", "text/plain")

    def do_PATCH(self):
        m_key = re.match(r"^/admin/keys/([^/]+)$", self.path)
        m_project = re.match(r"^/admin/projects/([^/]+)$", self.path)
        m_ext_settings = re.match(r"^/admin/extension-settings$", self.path)

        if m_key:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            entry = apikeys.set_active(m_key.group(1), bool(self._read_json().get("active")))
            self._json(200 if entry else 404, entry or {"error": "Key not found."})
        elif m_ext_settings:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            body = self._read_json()
            try:
                updated = extension_settings.update_settings(body)
                self._json(200, updated)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
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
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _project_summary(self, p):
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
            "id": project_id, "name": p["name"], "createdAt": p["created_at"],
            "allowCloud": projects.allow_cloud(project_id),
            "prospectus": {
                "embedded": bool(manifest), "chunksIndexed": manifest.get("chunksIndexed"),
                "pagesProcessed": manifest.get("pagesProcessed"), "embeddedAt": manifest.get("embeddedAt"),
            },
            "totalQuestions": snap["totalQuestions"], "sarvamCalls": snap["sarvamCalls"],
            "localCalls": snap["localCalls"], "cacheHits": snap["cacheHits"],
            "activeKeys": sum(1 for k in keys if k["active"]), "totalKeys": len(keys),
        }

    def _build_stats(self, project_id):
        snap = stats.snapshot(projects.stats_path(project_id))
        keys = apikeys.list_keys(project_id)
        return {**snap, "sarvam": llm.sarvam_usage(), "allowCloud": projects.allow_cloud(project_id),
                "activeKeys": sum(1 for k in keys if k["active"]), "totalKeys": len(keys), "health": self._check_health()}

    @staticmethod
    def _check_health():
        health = {}
        try:
            urllib.request.urlopen(config.EMBEDDING_URL.rsplit("/embed", 1)[0] + "/health", timeout=2)
            health["embedding"] = "up"
        except Exception:
            health["embedding"] = "down"
        try:
            urllib.request.urlopen(config.OLLAMA_URL.rstrip("/") + "/api/tags", timeout=2)
            health["ollama"] = "up"
        except Exception:
            health["ollama"] = "down"
        health["sarvam"] = "configured" if config.SARVAM_API_KEY else "not configured"
        return health

    def _proxy_tts(self):
        try:
            payload = self._read_json()
            payload["text"] = textclean.clean_for_speech(payload.get("text") or "")
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(config.TTS_URL, data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=config.TTS_TIMEOUT) as resp:
                audio = resp.read()
                self._send(200, audio, resp.headers.get("Content-Type", "audio/wav"))
        except Exception as exc:
            # Logged, not swallowed: this returned a bare 503 for every cause,
            # and the UI treats 503 as "fall back to the device voice" - so a
            # timeout on a working service was indistinguishable from the
            # service being down, and the Indic voice silently never played.
            print(f"[tts] proxy to {config.TTS_URL} failed: {exc!r}")
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
