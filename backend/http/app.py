"""HTTP server for the Admission Assistant backend.

Standard-library http.server only - no compiled dependencies, so it runs on the
Windows host under the machine's Application Control policy. Serves the React
frontend (static files) and the JSON API - see docs/ or the individual route
modules (chat_routes.py, admin_routes.py, static.py, ../orderassist/routes.py)
for the full route table; this file is just the Handler skeleton and dispatch.

Split from the original flat server.py during the 2026-08-13 re-architecture
(Phase 6): do_GET/do_POST/do_PATCH/do_DELETE keep their EXACT if/elif
conditions and order from before the split - only each branch's body
changed, from inline logic to a one-line call into the route module that
owns that concern. Core HTTP plumbing (_send/_json/_admin_ok/_read_json)
stays here since every route module needs it via the shared `self`.
"""

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import admin_routes, chat_routes, static, trace_routes
from .. import config, prospectus_watch
from ..orderassist import routes as orderassist_routes
from ..storage import apikeys, projects


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

    def do_GET(self):
        m_stats = re.match(r"^/admin/projects/([^/]+)/stats$", self.path)
        m_flagged = re.match(r"^/admin/projects/([^/]+)/flagged$", self.path)
        m_review_log = re.match(r"^/admin/projects/([^/]+)/review-log$", self.path)
        m_review_summary = re.match(r"^/admin/projects/([^/]+)/review-summary$", self.path)
        m_suggestions = re.match(r"^/admin/projects/([^/]+)/suggestions$", self.path)

        if self.path == "/" or self.path.startswith("/?") or self.path == "/index.html":
            static.serve_index(self)
        elif self.path == "/admin" or self.path.startswith("/admin?"):
            static.serve_static(self, "admin.html")
        elif self.path == "/admin/keys":
            admin_routes.handle_keys_list(self)
        elif self.path == "/admin/learned-discriminators":
            admin_routes.handle_learned_discriminators_list(self)
        elif self.path == "/admin/projects":
            admin_routes.handle_projects_list(self)
        elif self.path == "/admin/extension-settings":
            orderassist_routes.handle_extension_settings_get(self)
        elif self.path == "/admin/prompts" or self.path.startswith("/admin/prompts?"):
            trace_routes.handle_prompts(self)
        elif self.path == "/admin/trace/stream" or self.path.startswith("/admin/trace/stream?"):
            trace_routes.handle_trace_stream(self)
        elif m_stats:
            admin_routes.handle_project_stats(self, m_stats.group(1))
        elif m_flagged:
            admin_routes.handle_project_flagged(self, m_flagged.group(1))
        elif m_review_log:
            admin_routes.handle_project_review_log(self, m_review_log.group(1))
        elif m_review_summary:
            admin_routes.handle_project_review_summary(self, m_review_summary.group(1))
        elif m_suggestions:
            admin_routes.handle_project_suggestions(self, m_suggestions.group(1))
        elif self.path.startswith("/api/") or self.path.startswith("/admin/keys/") \
                or self.path.startswith("/admin/projects/"):
            self._send(404, "Not found", "text/plain")
        else:
            static.serve_static(self, self.path.split("?")[0])

    def do_POST(self):
        m_ingest = re.match(r"^/admin/projects/([^/]+)/ingest$", self.path)
        m_clear = re.match(r"^/admin/projects/([^/]+)/cache/clear$", self.path)
        m_seed = re.match(r"^/admin/projects/([^/]+)/cache/seed$", self.path)
        m_watch_check = re.match(r"^/admin/projects/([^/]+)/watch/check$", self.path)
        m_suggestions_apply = re.match(r"^/admin/projects/([^/]+)/suggestions/apply$", self.path)

        if self.path == "/api/chat":
            chat_routes.handle_chat(self)
        elif self.path == "/api/feedback":
            chat_routes.handle_feedback(self)
        elif self.path == "/api/ingest":
            chat_routes.handle_ingest(self)
        elif self.path == "/api/tts":
            chat_routes.handle_tts(self)
        elif self.path == "/api/catalogue/match":
            orderassist_routes.handle_catalogue_match(self)
        elif self.path == "/api/catalogue/complementary":
            orderassist_routes.handle_catalogue_complementary(self)
        elif self.path == "/api/catalogue/note":
            orderassist_routes.handle_catalogue_note(self)
        # --- Extension endpoints ---
        elif self.path == "/api/extension/register":
            orderassist_routes.handle_extension_register(self)
        elif self.path == "/api/extension/report-config":
            orderassist_routes.handle_extension_report_config(self)
        elif self.path == "/api/extension/discover-folders":
            orderassist_routes.handle_extension_discover_folders(self)
        elif self.path == "/api/extension/config":
            orderassist_routes.handle_extension_config(self)
        elif self.path == "/admin/keys":
            admin_routes.handle_keys_create(self)
        elif self.path == "/admin/projects":
            admin_routes.handle_projects_create(self)
        elif m_ingest:
            admin_routes.handle_project_ingest(self, m_ingest.group(1))
        elif m_clear:
            admin_routes.handle_project_cache_clear(self, m_clear.group(1))
        elif m_seed:
            admin_routes.handle_project_cache_seed(self, m_seed.group(1))
        elif m_watch_check:
            admin_routes.handle_project_watch_check(self, m_watch_check.group(1))
        elif m_suggestions_apply:
            admin_routes.handle_project_suggestions_apply(self, m_suggestions_apply.group(1))
        else:
            self._send(404, "Not found", "text/plain")

    def do_PATCH(self):
        m_key = re.match(r"^/admin/keys/([^/]+)$", self.path)
        m_project = re.match(r"^/admin/projects/([^/]+)$", self.path)
        m_ext_settings = re.match(r"^/admin/extension-settings$", self.path)
        m_flag_resolve = re.match(r"^/admin/projects/([^/]+)/flagged/([^/]+)$", self.path)

        if m_key:
            admin_routes.handle_key_patch(self, m_key.group(1))
        elif m_ext_settings:
            orderassist_routes.handle_extension_settings_patch(self)
        elif m_flag_resolve:
            project_id, flag_id = m_flag_resolve.groups()
            admin_routes.handle_flag_resolve(self, project_id, flag_id)
        elif m_project:
            admin_routes.handle_project_patch(self, m_project.group(1))
        else:
            self._send(404, "Not found", "text/plain")

    def do_DELETE(self):
        m_key = re.match(r"^/admin/keys/([^/]+)$", self.path)
        m_project = re.match(r"^/admin/projects/([^/]+)$", self.path)
        m_learned = re.match(r"^/admin/learned-discriminators/([^/]+)$", self.path)

        if m_key:
            admin_routes.handle_key_delete(self, m_key.group(1))
        elif m_learned:
            admin_routes.handle_learned_discriminator_delete(self, m_learned.group(1))
        elif m_project:
            admin_routes.handle_project_delete(self, m_project.group(1))
        else:
            self._send(404, "Not found", "text/plain")

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
    # First run on a clean machine: create the default project. The
    # one-time flat-layout migration that used to run here was removed
    # 2026-08-13 (see git history) - it had been a no-op on every
    # deployment for 11 commits, and create() below writes a strictly
    # newer entry than the one that migration hand-built.
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
