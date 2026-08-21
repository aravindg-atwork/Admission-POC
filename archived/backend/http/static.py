"""Static frontend serving - extracted from server.py during the
2026-08-13 re-architecture (Phase 6: server.py -> http/ package split).
serve_static/serve_index take the live `Handler` instance (`self`) and use
its `self._send(...)` exactly as they did inline in server.py, just moved
out of the Handler class.
"""

import json

from .. import config
from ..core import programs
from ..storage import apikeys, projects


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


_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}


def serve_static(self, rel_path):
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
    ctype = _CONTENT_TYPES.get(target.suffix, "application/octet-stream")
    self._send(200, target.read_bytes(), ctype)


def serve_index(self):
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
