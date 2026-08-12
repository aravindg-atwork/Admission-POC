"""HTTP server for the Admission Assistant backend.

Standard-library http.server only - no compiled dependencies, so it runs on the
Windows host under the machine's Application Control policy. Serves the React
frontend (static files) and the JSON API:

  POST /api/chat                         X-API-Key gated - ask a question
  POST /api/feedback                     X-API-Key gated - like/dislike a specific answered response
  POST /api/ingest                       X-API-Key gated - upload a prospectus PDF (multipart)
  POST /api/tts                          X-API-Key gated - proxy to the Indic TTS service
  POST /api/catalogue/match              X-API-Key gated - rank catalogue items against quotation text
  POST /api/catalogue/complementary      X-API-Key gated - LLM cross-sell suggestions (non-blocking follow-up)
  POST /api/catalogue/note               X-API-Key gated - generate an email note for matched item(s)
  GET/POST        /admin/projects[/id]   X-Admin-Token gated - manage projects
  PATCH           /admin/projects/id     X-Admin-Token gated - update project settings (allow_cloud, prospectus_url, watch_enabled)
  DELETE          /admin/projects/id     X-Admin-Token gated - delete a project
  GET             /admin/projects/id/stats   X-Admin-Token gated - dashboard/cost metrics + health
  GET             /admin/projects/id/flagged X-Admin-Token gated - disliked answers pulled from cache, for review
  PATCH           /admin/projects/id/flagged/flagId  X-Admin-Token gated - resolve a flagged dislike (dismissed/corrected/rule-changed)
  GET             /admin/projects/id/review-log      X-Admin-Token gated - the system's OWN self-detected near-misses (validation flags/regenerations)
  GET             /admin/projects/id/review-summary  X-Admin-Token gated - aggregate counts over flagged + review-log
  GET             /admin/projects/id/suggestions      X-Admin-Token gated - detected patterns, split safe-to-automate vs propose-only
  POST            /admin/projects/id/suggestions/apply X-Admin-Token gated - apply a safe-to-automate discriminator synonym
  GET             /admin/learned-discriminators        X-Admin-Token gated - audit list of applied learned overlay entries (global)
  DELETE          /admin/learned-discriminators/id     X-Admin-Token gated - revert one learned overlay entry
  POST            /admin/projects/id/ingest  X-Admin-Token gated - upload a prospectus PDF (multipart)
  POST            /admin/projects/id/cache/clear  X-Admin-Token gated - clear that project's FAQ cache
  POST            /admin/projects/id/cache/seed   X-Admin-Token gated - bulk-load curated Q&A into that cache
  POST            /admin/projects/id/watch/check  X-Admin-Token gated - check the configured source URL now, re-ingest if changed
  GET/POST/PATCH/DELETE /admin/keys[/id] X-Admin-Token gated - manage keys

Every key belongs to exactly one project; /api/chat and /api/ingest resolve
which project's pipeline to run from the key, so different projects never
share a prospectus, vector store, or cost numbers.
"""

import json
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import (apikeys, audiocache, catalogue, config, embeddings,
               extension_settings, faq, llm, programs, projects,
               prospectus_watch, rag, reviewlog, selflearn, stats, textclean)

# Injected into index.html so the first-party chat widget authenticates without the
# key being hard-coded in client files.
_KEY_SNIPPET = '<script>window.ADMISSION_API_KEY="{}";</script>'
# Every program's own widget key, so the frontend can switch context when a
# student picks a program off the clarification prompt (see rag.py's
# needs_program_clarification path) - a plain resubmit under the right key,
# not a server-side router, since these are already client-embedded widget
# keys and not treated as secrets (same trust level as ADMISSION_API_KEY
# above). Built fresh per request rather than cached: cheap (six dict lookups
# plus get_or_create_default, which is itself already cached), and always
# reflects whatever projects currently exist.
_PROGRAMS_SNIPPET = '<script>window.MAFSU_PROGRAMS={};</script>'


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
        program_list = [
            {"projectId": pid, "label": name,
             "apiKey": apikeys.get_or_create_default(pid)["key"]}
            for pid, name in programs.PROGRAM_NAMES.items()
            if projects.get(pid)
        ]
        snippets = (_KEY_SNIPPET.format(key)
                    + _PROGRAMS_SNIPPET.format(json.dumps(program_list)))
        html = html.replace("</head>", snippets + "</head>", 1)
        self._send(200, html, "text/html; charset=utf-8")

    def do_GET(self):
        m_stats = re.match(r"^/admin/projects/([^/]+)/stats$", self.path)
        m_flagged = re.match(r"^/admin/projects/([^/]+)/flagged$", self.path)
        m_review_log = re.match(r"^/admin/projects/([^/]+)/review-log$", self.path)
        m_review_summary = re.match(r"^/admin/projects/([^/]+)/review-summary$", self.path)
        m_suggestions = re.match(r"^/admin/projects/([^/]+)/suggestions$", self.path)

        if self.path == "/" or self.path.startswith("/?") or self.path == "/index.html":
            self._serve_index()
        elif self.path == "/admin" or self.path.startswith("/admin?"):
            self._serve_static("admin.html")
        elif self.path == "/admin/keys":
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            self._json(200, apikeys.list_keys())
        elif self.path == "/admin/learned-discriminators":
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            # Global, not per-project - faq.py's discriminator vocabulary
            # (and its learned overlay) is itself module-level, shared
            # across every project's FAQ cache (see selflearn.py's module
            # docstring).
            self._json(200, faq.list_learned_discriminators())
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
        elif m_flagged:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            project_id = m_flagged.group(1)
            if not projects.get(project_id):
                self._json(404, {"error": "Project not found."})
                return
            self._json(200, faq.load_flagged(projects.flagged_path(project_id)))
        elif m_review_log:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            project_id = m_review_log.group(1)
            if not projects.get(project_id):
                self._json(404, {"error": "Project not found."})
                return
            self._json(200, list(reversed(reviewlog.load(projects.review_log_path(project_id)))))
        elif m_review_summary:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            project_id = m_review_summary.group(1)
            if not projects.get(project_id):
                self._json(404, {"error": "Project not found."})
                return
            self._json(200, self._review_summary(project_id))
        elif m_suggestions:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            project_id = m_suggestions.group(1)
            if not projects.get(project_id):
                self._json(404, {"error": "Project not found."})
                return
            patterns = selflearn.detect_recurring_patterns(faq.load_flagged(projects.flagged_path(project_id)))
            safe, propose = [], []
            for p in patterns:
                if selflearn.classify(p) == selflearn.SAFE_TO_AUTOMATE:
                    safe.append({"signature": list(p["signature"]), "count": p["count"],
                                 "sampleQuestions": [e.get("question", "") for e in p["entries"][:5]]})
                else:
                    propose.append(selflearn.propose(p))
            self._json(200, {"safeToAutomate": safe, "proposeOnly": propose})
        elif self.path.startswith("/api/") or self.path.startswith("/admin/keys/") \
                or self.path.startswith("/admin/projects/"):
            self._send(404, "Not found", "text/plain")
        else:
            self._serve_static(self.path.split("?")[0])

    def do_POST(self):
        m_ingest = re.match(r"^/admin/projects/([^/]+)/ingest$", self.path)
        m_clear = re.match(r"^/admin/projects/([^/]+)/cache/clear$", self.path)
        m_seed = re.match(r"^/admin/projects/([^/]+)/cache/seed$", self.path)
        m_watch_check = re.match(r"^/admin/projects/([^/]+)/watch/check$", self.path)
        m_suggestions_apply = re.match(r"^/admin/projects/([^/]+)/suggestions/apply$", self.path)

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
                payload = {
                    "answerText": result["answer"],
                    "pageReferences": result["pages"],
                    "model": result["model"],
                    "language": result["language"],
                    "source": result["source"],
                    "speakable": result["speakable"],
                }
                if result.get("clarifyOptions"):
                    payload["clarifyOptions"] = result["clarifyOptions"]
                if result.get("answeredForProgram"):
                    payload["answeredForProgram"] = {
                        "projectId": result["answeredForProgram"],
                        "label": programs.PROGRAM_NAMES.get(result["answeredForProgram"], ""),
                    }
                # Already {projectId, label} dicts from rag._answer_comparison,
                # unlike answeredForProgram above (a bare id server.py wraps) -
                # a comparison answer names several programs, not one.
                if result.get("comparedPrograms"):
                    payload["comparedPrograms"] = result["comparedPrograms"]
                # Only present for answers that actually went through the FAQ
                # cache (rag/faq-cache/payment-issue/verified-fact) - a
                # clarify-program prompt, greeting or guard refusal has
                # nothing for a like/dislike to target, so /api/feedback has
                # no id to act on and the frontend shows no buttons for those.
                if result.get("faqId"):
                    payload["faqId"] = result["faqId"]
                self._json(200, payload)
            except Exception as exc:
                self._json(500, {"error": str(exc)})

        elif self.path == "/api/feedback":
            project_id = apikeys.resolve_active(self.headers.get("X-API-Key"))
            if not project_id:
                self._json(401, {"error": "Missing or inactive API key."})
                return
            body = self._read_json()
            faq_id = (body.get("faqId") or "").strip()
            if not faq_id or "liked" not in body:
                self._json(400, {"error": "faqId and liked are required."})
                return
            ok = faq.apply_feedback(projects.faq_path(project_id), projects.flagged_path(project_id),
                                     faq_id, bool(body.get("liked")))
            if not ok:
                self._json(404, {"error": "Unknown faqId - it may already have been removed."})
                return
            self._json(200, {"ok": True})

        elif self.path == "/api/ingest":
            project_id = apikeys.resolve_active(self.headers.get("X-API-Key"))
            if not project_id:
                self._json(401, {"error": "Missing or inactive API key."})
                return
            self._handle_ingest(project_id)

        elif self.path == "/api/tts":
            # resolve_active (not just is_active): the audio cache is per-
            # project, same as the FAQ/vector stores, so the project_id is
            # needed here now, not just an active/inactive check.
            project_id = apikeys.resolve_active(self.headers.get("X-API-Key"))
            if not project_id:
                self._json(401, {"error": "Missing or inactive API key."})
                return
            self._proxy_tts(project_id)

        elif self.path == "/api/catalogue/match":
            project_id = apikeys.resolve_active(self.headers.get("X-API-Key"))
            if not project_id:
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
                # Semantic match only (embedding call, ~100ms) - the complementary
                # suggestion used to run here too (an LLM call, several seconds,
                # worse on a Sarvam retry), but a rep is sitting there waiting on
                # this response before Send goes through, so it can't share the
                # blocking path. See /api/catalogue/complementary - it runs the
                # same suggestion after the banner is already showing instead.
                if quotation_lines:
                    matches = catalogue.match_lines(quotation_lines, items, threshold=threshold)
                else:
                    matches = catalogue.match(quotation_text, items)
                stats.record_catalogue(projects.stats_path(project_id), "match", True)
                self._json(200, {"matches": matches})
            except Exception as exc:
                stats.record_catalogue(projects.stats_path(project_id), "match", False, exc)
                self._json(500, {"error": str(exc)})

        elif self.path == "/api/catalogue/complementary":
            # Fired by the extension right after the match banner is already
            # showing (see content.js) - never on the blocking path a rep is
            # staring at. An LLM call, so failing closed (empty list) here is
            # fine; the rep already has their real matches either way.
            project_id = apikeys.resolve_active(self.headers.get("X-API-Key"))
            if not project_id:
                self._json(401, {"error": "Missing or inactive API key."})
                return
            body = self._read_json()
            quotation_text = (body.get("quotationText") or "").strip()
            items = body.get("items") or []
            existing_ids = set(body.get("existingIds") or [])
            if not quotation_text or not items:
                self._json(400, {"error": "quotationText and items are required."})
                return
            try:
                suggestions = catalogue.suggest_complementary(quotation_text, items, existing_ids)
                stats.record_catalogue(projects.stats_path(project_id), "complementary", True)
                self._json(200, {"matches": suggestions})
            except Exception as exc:
                stats.record_catalogue(projects.stats_path(project_id), "complementary", False, exc)
                self._json(500, {"error": str(exc)})

        elif self.path == "/api/catalogue/note":
            project_id = apikeys.resolve_active(self.headers.get("X-API-Key"))
            if not project_id:
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
                stats.record_catalogue(projects.stats_path(project_id), "note", True)
                self._json(200, {"note": note, "model": model})
            except Exception as exc:
                stats.record_catalogue(projects.stats_path(project_id), "note", False, exc)
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

        elif m_watch_check:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            project_id = m_watch_check.group(1)
            if not projects.get(project_id):
                self._json(404, {"error": "Project not found."})
                return
            self._json(200, prospectus_watch.check_and_refresh(project_id))
        elif m_suggestions_apply:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            project_id = m_suggestions_apply.group(1)
            if not projects.get(project_id):
                self._json(404, {"error": "Project not found."})
                return
            body = self._read_json()
            group, canonical, word = body.get("group"), body.get("canonical"), body.get("word")
            if not (group and canonical and word):
                self._json(400, {"error": "group, canonical, and word are all required."})
                return
            # A minimal re-derived pattern shape for the evidence string -
            # the admin console already showed the full pattern (count,
            # sample questions) before the admin chose to apply it, so only
            # the count needs to survive into the audit trail here.
            pseudo_pattern = {"signature": tuple((k, tuple(v)) for k, v in body.get("signature", [])),
                               "count": body.get("count", 0)}
            try:
                entry_id = selflearn.apply_safe(group, canonical, word, pseudo_pattern)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(200, {"id": entry_id})

        else:
            self._send(404, "Not found", "text/plain")

    def do_PATCH(self):
        m_key = re.match(r"^/admin/keys/([^/]+)$", self.path)
        m_project = re.match(r"^/admin/projects/([^/]+)$", self.path)
        m_ext_settings = re.match(r"^/admin/extension-settings$", self.path)
        m_flag_resolve = re.match(r"^/admin/projects/([^/]+)/flagged/([^/]+)$", self.path)

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
        elif m_flag_resolve:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            project_id, flag_id = m_flag_resolve.groups()
            if not projects.get(project_id):
                self._json(404, {"error": "Project not found."})
                return
            body = self._read_json()
            resolution = body.get("resolution", "")
            note = body.get("note", "")
            ok = faq.resolve_flag(projects.flagged_path(project_id), flag_id, resolution, note)
            if not ok:
                self._json(404, {"error": "Flag not found or invalid resolution."})
                return
            self._json(200, {"ok": True})
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
            if "prospectus_url" in body or "watch_enabled" in body:
                projects.set_prospectus_watch(
                    project_id,
                    url=body["prospectus_url"] if "prospectus_url" in body else None,
                    enabled=body["watch_enabled"] if "watch_enabled" in body else None,
                )
            self._json(200, self._project_summary(projects.get(project_id)))
        else:
            self._send(404, "Not found", "text/plain")

    def do_DELETE(self):
        m_key = re.match(r"^/admin/keys/([^/]+)$", self.path)
        m_project = re.match(r"^/admin/projects/([^/]+)$", self.path)
        m_learned = re.match(r"^/admin/learned-discriminators/([^/]+)$", self.path)

        if m_key:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            ok = apikeys.delete(m_key.group(1))
            self._json(200 if ok else 404, {"deleted": m_key.group(1)} if ok else {"error": "Key not found."})
        elif m_learned:
            if not self._admin_ok():
                self._json(401, {"error": "Invalid admin token."})
                return
            ok = faq.remove_learned_discriminator(m_learned.group(1))
            self._json(200 if ok else 404, {"deleted": m_learned.group(1)} if ok else {"error": "Entry not found."})
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
            "prospectusWatch": self._prospectus_watch_summary(p),
            "totalQuestions": snap["totalQuestions"], "sarvamCalls": snap["sarvamCalls"],
            "localCalls": snap["localCalls"], "cacheHits": snap["cacheHits"],
            "activeKeys": sum(1 for k in keys if k["active"]), "totalKeys": len(keys),
        }

    @staticmethod
    def _prospectus_watch_summary(p):
        project_id = p["id"]
        state = {}
        spath = projects.watch_state_path(project_id)
        if spath.exists():
            try:
                state = json.loads(spath.read_text(encoding="utf-8"))
            except ValueError:
                state = {}
        return {
            "url": p.get("prospectus_url", ""), "enabled": bool(p.get("watch_enabled")),
            "lastCheckedAt": state.get("lastCheckedAt"), "lastStatus": state.get("lastStatus"),
            "lastError": state.get("lastError"), "lastRefreshedAt": state.get("lastRefreshedAt"),
        }

    def _build_stats(self, project_id):
        snap = stats.snapshot(projects.stats_path(project_id))
        keys = apikeys.list_keys(project_id)
        p = projects.get(project_id) or {"id": project_id}
        return {**snap, "sarvam": llm.sarvam_usage(), "allowCloud": projects.allow_cloud(project_id),
                "activeKeys": sum(1 for k in keys if k["active"]), "totalKeys": len(keys),
                "health": self._check_health(), "prospectusWatch": self._prospectus_watch_summary(p)}

    def _review_summary(self, project_id):
        """Aggregate view over flagged (student dislikes) + review-log (the
        system's own self-detected near-misses) - computed fresh per
        request, same pattern as _build_stats/_check_health above (no
        scheduler, no background job; this is stdlib http.server and the
        underlying files are small). Feeds the admin console's Review tab
        and, longer-term, selflearn.detect_recurring_patterns.
        """
        flagged = faq.load_flagged(projects.flagged_path(project_id))
        log = reviewlog.load(projects.review_log_path(project_id))

        open_flags = [f for f in flagged if f.get("resolution", "open") == "open"]
        reason_counts = {}
        for entry in log:
            for reason in entry.get("reasons", []):
                # Only the reason KIND, not its detail (e.g. "unsupported_number:
                # 18000" -> "unsupported_number") - the detail is per-question and
                # not useful to aggregate; the kind is what selflearn groups on.
                kind = reason.split(":", 1)[0].strip()
                reason_counts[kind] = reason_counts.get(kind, 0) + 1

        return {
            "flaggedTotal": len(flagged),
            "flaggedOpen": len(open_flags),
            "reviewLogTotal": len(log),
            "reviewLogRegenerated": sum(1 for e in log if e.get("kind") == "validation_regenerated"),
            "reasonCounts": reason_counts,
        }

    @staticmethod
    def _selfhosted_model_status():
        """GET {SELFHOSTED_URL}/v1/models -> {model name: status}, or None on failure.

        Added 2026-08-12 after bge-m3 and glm-4-9b-chat went "running"->"stopped"
        mid-session with zero warning - discovered only when a live chat/embed
        request failed. This is the same endpoint used to diagnose that live,
        now surfaced in the admin health strip instead of requiring a manual
        curl after something already broke.
        """
        if not config.SELFHOSTED_URL:
            return None
        try:
            req = urllib.request.Request(
                config.SELFHOSTED_URL.rstrip("/") + "/v1/models",
                headers={"Authorization": f"Bearer {config.SELFHOSTED_API_KEY}"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return {m.get("name"): m.get("status") for m in data}
        except Exception:
            return None

    @staticmethod
    def _hetzner_model_available():
        """GET {HETZNER_URL}/models -> whether HETZNER_MODEL is in the list, or
        None on failure. Unlike SelfHostedProvider's server, Hetzner's /v1/models
        response has no per-model "status" (running/stopped) - it's a managed
        inference service, not a bare-metal box someone can unload a model
        from - so reachability plus the configured model id actually being
        listed is the whole check.
        """
        if not config.HETZNER_API_KEY:
            return None
        try:
            req = urllib.request.Request(
                config.HETZNER_URL.rstrip("/") + "/models",
                headers={"Authorization": f"Bearer {config.HETZNER_API_KEY}"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return {m.get("id") for m in data.get("data", [])}
        except Exception:
            return None

    @classmethod
    def _check_health(cls):
        health = {}
        selfhosted_models = None
        needs_selfhosted = (config.EMBEDDING_PROVIDER == "selfhosted"
                             or config.CHAT_FALLBACK == "selfhosted")
        if needs_selfhosted:
            selfhosted_models = cls._selfhosted_model_status()

        # Embeddings: check whichever backend is actually configured, not
        # always the local Docker service - EMBEDDING_PROVIDER=selfhosted
        # (the current default) routes embeddings through the self-hosted
        # server instead, and pinging the unused local service there just
        # produces a misleading "down" or a false "up" for a path nothing
        # actually calls.
        if config.EMBEDDING_PROVIDER == "selfhosted":
            if selfhosted_models is None:
                health["embedding"] = "unreachable"
            else:
                status = selfhosted_models.get(config.SELFHOSTED_EMBEDDING_MODEL)
                health["embedding"] = "up" if status == "running" else f"stopped ({config.SELFHOSTED_EMBEDDING_MODEL})"
        else:
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

        if config.CHAT_FALLBACK == "selfhosted":
            if selfhosted_models is None:
                health["selfhosted"] = "unreachable"
            else:
                needed = {config.SELFHOSTED_MODEL_EN, config.SELFHOSTED_MODEL_INTL}
                not_running = sorted(m for m in needed if selfhosted_models.get(m) != "running")
                health["selfhosted"] = "up" if not not_running else f"stopped ({', '.join(not_running)})"
        elif config.CHAT_FALLBACK == "hetzner":
            available = cls._hetzner_model_available()
            if available is None:
                health["hetzner"] = "unreachable"
            elif config.HETZNER_MODEL not in available:
                health["hetzner"] = f"model not listed ({config.HETZNER_MODEL})"
            else:
                health["hetzner"] = "up"

        return health

    def _proxy_tts(self, project_id):
        try:
            payload = self._read_json()
            text = textclean.clean_for_speech(payload.get("text") or "")
            language = payload.get("language") or ""
            cache_dir = projects.tts_cache_dir(project_id)

            # The generation call is what takes 166-252s on this host - a cache
            # hit skips it entirely and returns in the time it takes to read a
            # small file off disk. Same (language, text) always means the same
            # audio (the TTS call has no sampling step), so this is exact reuse,
            # not an approximation.
            cached = audiocache.get(cache_dir, language, text)
            if cached is not None:
                self._send(200, cached, "audio/wav")
                return

            payload["text"] = text
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(config.TTS_URL, data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=config.TTS_TIMEOUT) as resp:
                audio = resp.read()
                content_type = resp.headers.get("Content-Type", "audio/wav")
            try:
                audiocache.put(cache_dir, language, text, audio)
            except OSError as exc:
                # A cache-write failure (disk full, permissions) must not turn a
                # successful generation into an error response - the audio is
                # already in hand and the student should still get it. Next
                # request just regenerates instead of finding a cache hit.
                print(f"[tts] cache write failed (serving anyway): {exc!r}")
            self._send(200, audio, content_type)
        except Exception as exc:
            # Logged, not swallowed: this returned a bare 503 for every cause,
            # and the UI treats 503 as "fall back to the device voice" - so a
            # timeout on a working service was indistinguishable from the
            # service being down, and the Indic voice silently never played.
            print(f"[tts] proxy to {config.TTS_URL} failed: {exc!r}")
            self._json(503, {"error": "TTS service unavailable."})

    def log_message(self, fmt, *args):
        print("[backend]", fmt % args)


def _prospectus_watch_loop():
    """Background poll: re-check every watch-enabled project's source URL.

    Runs once immediately on startup (so a change that landed while the
    server was down is caught right away, not after a full interval), then
    on PROSPECTUS_WATCH_INTERVAL_HOURS. A daemon thread so it never blocks
    process shutdown; check_all() already isolates one project's failure
    from the rest, and this loop isolates one bad run from the next.
    """
    interval = max(1.0, config.PROSPECTUS_WATCH_INTERVAL_HOURS) * 3600
    while True:
        try:
            prospectus_watch.check_all()
        except Exception as exc:  # noqa: BLE001 - must not kill the loop
            print(f"[prospectus_watch] background loop error: {exc!r}")
        time.sleep(interval)


def serve():
    projects.migrate_legacy_if_needed()
    if not projects.list_projects():
        projects.create("Admission Assistant", config.DEFAULT_PROJECT_ID)
    apikeys.get_or_create_default(config.DEFAULT_PROJECT_ID)

    threading.Thread(target=_prospectus_watch_loop, daemon=True).start()

    httpd = ThreadingHTTPServer(("0.0.0.0", config.PORT), Handler)
    print("Admission Assistant backend running:")
    print("  Chat    : http://localhost:{}/".format(config.PORT))
    print("  Console : http://localhost:{}/admin  (admin token: {})".format(config.PORT, config.ADMIN_TOKEN))
    primary = ("Sarvam:" + config.SARVAM_MODEL) if config.SARVAM_API_KEY else "(no Sarvam key)"
    print("  Models  : online={}  offline={}".format(primary, config.MODEL_LOCAL))
    httpd.serve_forever()
