"""GET /healthz - unauthenticated liveness probe.

Separate from the admin console's health strip (admin_routes._check_health),
and deliberately so. That one is authenticated and pings every upstream with a
2s timeout, which is exactly right for a dashboard a human is reading and
exactly wrong for something a service supervisor polls on a timer:

  - Behind the admin token, nothing outside the console can watch the process.
    A Windows service wrapper cannot hold a credential just to ask "are you
    alive?", so today nothing does.

  - Depending on upstreams, it goes red whenever Mistral or the BGE-M3 service
    is down - while this process is perfectly healthy. A supervisor reading
    that would restart a working server on a loop, and restarting cannot fix
    somebody else's outage.

So this answers one question - can THIS process serve requests - and answers it
with no outbound call at all. The check is the project registry, because
without it every request 500s no matter which upstreams are up; that is a real
"restart me" condition, which an upstream outage is not.

Readiness (can it actually produce an answer right now) is a different question
with a different correct response, and the console already covers it.
"""

import time

from ..storage import projects

_STARTED_AT = time.time()


def build_health():
    """Return (status_code, payload). Pure - no I/O beyond a local file read."""
    try:
        count = len(projects.list_projects())
    except Exception as exc:  # noqa: BLE001 - any failure here means "cannot serve"
        return 503, {"status": "unhealthy",
                     "reason": "project registry unreadable",
                     "detail": str(exc),
                     "uptimeSeconds": round(time.time() - _STARTED_AT, 1)}

    return 200, {"status": "ok",
                 "projects": count,
                 "uptimeSeconds": round(time.time() - _STARTED_AT, 1)}


def handle_healthz(handler):
    status, payload = build_health()
    handler._json(status, payload)
