"""Automated prospectus refresh: detect when a project's live source page/PDF
changes, and re-run the extract/chunk/embed pipeline without anyone manually
downloading a new PDF and re-uploading it through the admin console.

Firecrawl (https://firecrawl.dev, self-hostable) does exactly one job here:
scrape the project's configured source URL and report whether its content
differs from the last time it was scraped (its `changeTracking` format). It is
deliberately NOT used to parse the prospectus itself - pdf.py's extraction is
tuned hard against this specific document's table layouts (see its docstring),
and handing that job to a generic web-to-markdown converter would throw that
tuning away. So on a detected change this module just downloads the PDF bytes
directly, same as the manual upload path, and calls rag.ingest() unchanged.

Untested against a real Firecrawl endpoint (no key was available while writing
this) - the response shape below (`data.changeTracking.changeStatus`) matches
Firecrawl's documented v1 /scrape API as of this writing, but confirm it
against a real response before relying on this in production, since an API
change would silently degrade to "unknown" status rather than crash (see
check_and_refresh's use of .get() throughout).
"""

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import config, rag
from .storage import atomic, projects


def _post(url, payload, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {config.FIRECRAWL_API_KEY}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download(url):
    # Some admission sites block requests with no browser-like UA - matches
    # what a real visitor's browser sends rather than Python's default
    # urllib UA, which a subset of sites reject outright.
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=config.PROSPECTUS_WATCH_TIMEOUT) as resp:
        return resp.read()


def _load_state(project_id):
    path = projects.watch_state_path(project_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _save_state(project_id, state):
    atomic.write_json(projects.watch_state_path(project_id), state, indent=2)


def check_and_refresh(project_id):
    """Check this project's configured source URL and re-ingest on change.

    Always returns a dict, never raises - both the manual admin "Check now"
    trigger and the unattended background loop (check_all) need a failed
    check to come back as data, not an exception. The background loop in
    particular must not let one project's bad URL or a Firecrawl outage take
    down the check for every other project.
    """
    entry = projects.get(project_id) or {}
    url = (entry.get("prospectus_url") or "").strip()
    now = datetime.now(timezone.utc).isoformat()

    if not url:
        return {"checked": False, "reason": "no source URL configured"}
    if not config.FIRECRAWL_API_KEY:
        return {"checked": False, "reason": "FIRECRAWL_API_KEY not set"}

    state = _load_state(project_id)
    try:
        result = _post(config.FIRECRAWL_URL + "/v1/scrape",
                        {"url": url, "formats": ["changeTracking"]},
                        config.PROSPECTUS_WATCH_TIMEOUT)
    except (urllib.error.URLError, OSError) as exc:
        state.update({"lastCheckedAt": now, "lastError": str(exc)})
        _save_state(project_id, state)
        return {"checked": True, "changed": False, "error": str(exc)}

    tracking = (result.get("data") or {}).get("changeTracking") or {}
    status = tracking.get("changeStatus", "unknown")  # new | same | changed | removed
    state.update({"lastCheckedAt": now, "lastStatus": status, "lastError": None})

    if status not in ("new", "changed"):
        _save_state(project_id, state)
        return {"checked": True, "changed": False, "status": status}

    try:
        pdf_bytes = _download(url)
    except (urllib.error.URLError, OSError) as exc:
        state["lastError"] = f"detected {status!r} but download failed: {exc}"
        _save_state(project_id, state)
        return {"checked": True, "changed": True, "status": status, "error": str(exc)}

    saved = projects.prospectus_path(project_id)
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_bytes(pdf_bytes)
    ingest_result = rag.ingest(project_id, saved)

    state.update({"lastRefreshedAt": now, "lastIngest": ingest_result, "lastError": None})
    _save_state(project_id, state)
    return {"checked": True, "changed": True, "status": status, "ingest": ingest_result}


def check_all():
    """Run check_and_refresh for every project with the watcher switched on.

    One project's failure (bad URL, Firecrawl down) must not stop the rest -
    each project's prospectus is independent, same as the rest of the
    multi-tenant pipeline (see projects.py).
    """
    results = {}
    for entry in projects.list_projects():
        if not entry.get("watch_enabled"):
            continue
        project_id = entry["id"]
        try:
            results[project_id] = check_and_refresh(project_id)
        except Exception as exc:  # noqa: BLE001 - isolate one project's bug from the rest
            print(f"[prospectus_watch] {project_id} failed: {exc!r}")
            results[project_id] = {"checked": True, "error": str(exc)}
    return results
