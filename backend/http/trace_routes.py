"""New in Request 3 (2026-08-13 re-architecture): the live agent-
observability endpoints - GET /admin/prompts (the master system prompts,
byte-for-byte what's actually sent to the LLM) and GET /admin/trace/stream
(a live Server-Sent Events feed of every real /api/chat request's full
step-by-step trace, system-wide, not just one admin's own test messages).

Both are genuinely new endpoints, added only after the rest of the
2026-08-13 re-architecture (Phases 1-6) was fully split and verified - see
that plan's explicit "server.py's route surface must stay byte-identical
through the reorg; only Phase 9 adds new endpoints" constraint.
"""

import json
import queue
from urllib.parse import parse_qs, urlparse

from .. import config
from ..prompts import registry
from ..trace import hub


def handle_prompts(self):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    query = parse_qs(urlparse(self.path).query)
    project_id = (query.get("projectId") or [None])[0]
    self._json(200, {"prompts": registry.list_prompts(project_id)})


def handle_trace_stream(self):
    """SSE stream. Auth travels as a URL query param (?token=...), not a
    header - EventSource (the browser API this is built for) cannot set
    custom headers on its request, so the header-based X-Admin-Token check
    every other admin route uses doesn't apply here. Owner-confirmed
    tradeoff (see the 2026-08-13 plan): reuses the same static
    config.ADMIN_TOKEN rather than minting a short-lived signed token,
    matching this POC's existing single-shared-token posture.
    """
    query = parse_qs(urlparse(self.path).query)
    token = (query.get("token") or [""])[0]
    if token != config.ADMIN_TOKEN:
        self._json(401, {"error": "Invalid admin token."})
        return

    # Not self._send() - that helper always sets Content-Length and writes
    # the whole body once, which is exactly wrong for a long-lived stream.
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.send_header("Cache-Control", "no-cache")
    self.send_header("Connection", "keep-alive")
    self.send_header("Access-Control-Allow-Origin", "*")
    self.end_headers()

    q = hub.subscribe()
    try:
        while True:
            try:
                event = q.get(timeout=15)
                payload = f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                # Heartbeat - keeps intermediary proxies/browsers from
                # timing out an idle connection. An SSE comment line (":"
                # prefix), not a real event - EventSource's onmessage
                # never fires for it.
                payload = ": ping\n\n"
            self.wfile.write(payload.encode("utf-8"))
            self.wfile.flush()
    except (BrokenPipeError, ConnectionAbortedError):
        pass  # admin closed the tab; nothing to do
    finally:
        hub.unsubscribe(q)
