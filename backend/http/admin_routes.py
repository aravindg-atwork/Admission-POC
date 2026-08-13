"""Admin console route handlers - extracted from server.py's do_GET/
do_POST/do_PATCH/do_DELETE during the 2026-08-13 re-architecture (Phase 6:
server.py -> http/ package split). Each handle_* function takes the live
`Handler` instance (`self`) exactly as it did inline in server.py - same
`self._read_json()`/`self._json()`/`self._admin_ok()` calls, same
behavior, just moved. app.py's do_GET/do_POST/do_PATCH/do_DELETE keep
their exact if/elif conditions and order; only each admin branch's body
becomes a one-line call into this module.

The helper functions below (_project_summary, _build_stats, etc.) were
Handler methods in server.py, called via self.X() from several route
bodies - none of them actually touch self.headers/self.wfile/etc, so they
move here as plain module functions instead, called directly rather than
through self, once their bodies are no longer nested inside the Handler
class.
"""

import json
import urllib.request

from .. import config, prospectus_watch
from ..generation import embeddings, llm
from ..storage import apikeys, faq, projects, reviewlog, selflearn, stats
from . import chat_routes


def _project_summary(p):
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
        "prospectusWatch": _prospectus_watch_summary(p),
        "totalQuestions": snap["totalQuestions"], "sarvamCalls": snap["sarvamCalls"],
        "localCalls": snap["localCalls"], "cacheHits": snap["cacheHits"],
        "activeKeys": sum(1 for k in keys if k["active"]), "totalKeys": len(keys),
    }


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


def _build_stats(project_id):
    snap = stats.snapshot(projects.stats_path(project_id))
    keys = apikeys.list_keys(project_id)
    p = projects.get(project_id) or {"id": project_id}
    return {**snap, "sarvam": llm.sarvam_usage(), "allowCloud": projects.allow_cloud(project_id),
            "activeKeys": sum(1 for k in keys if k["active"]), "totalKeys": len(keys),
            "health": _check_health(), "prospectusWatch": _prospectus_watch_summary(p)}


def _review_summary(project_id):
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


def _check_health():
    health = {}
    selfhosted_models = None
    needs_selfhosted = (config.EMBEDDING_PROVIDER == "selfhosted"
                         or config.CHAT_FALLBACK == "selfhosted")
    if needs_selfhosted:
        selfhosted_models = _selfhosted_model_status()

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
        available = _hetzner_model_available()
        if available is None:
            health["hetzner"] = "unreachable"
        elif config.HETZNER_MODEL not in available:
            health["hetzner"] = f"model not listed ({config.HETZNER_MODEL})"
        else:
            health["hetzner"] = "up"

    return health



def handle_keys_list(self):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    self._json(200, apikeys.list_keys())


def handle_learned_discriminators_list(self):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    # Global, not per-project - faq.py's discriminator vocabulary
    # (and its learned overlay) is itself module-level, shared
    # across every project's FAQ cache (see selflearn.py's module
    # docstring).
    self._json(200, faq.list_learned_discriminators())


def handle_projects_list(self):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    self._json(200, [_project_summary(p) for p in projects.list_projects()])


def handle_project_stats(self, project_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    if not projects.get(project_id):
        self._json(404, {"error": "Project not found."})
        return
    self._json(200, _build_stats(project_id))


def handle_project_flagged(self, project_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    if not projects.get(project_id):
        self._json(404, {"error": "Project not found."})
        return
    self._json(200, faq.load_flagged(projects.flagged_path(project_id)))


def handle_project_review_log(self, project_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    if not projects.get(project_id):
        self._json(404, {"error": "Project not found."})
        return
    self._json(200, list(reversed(reviewlog.load(projects.review_log_path(project_id)))))


def handle_project_review_summary(self, project_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    if not projects.get(project_id):
        self._json(404, {"error": "Project not found."})
        return
    self._json(200, _review_summary(project_id))


def handle_project_suggestions(self, project_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
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


def handle_keys_create(self):
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


def handle_projects_create(self):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    name = (self._read_json().get("name") or "").strip()
    entry = projects.create(name)
    self._json(200, _project_summary(entry))


def handle_project_ingest(self, project_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    if not projects.get(project_id):
        self._json(404, {"error": "Project not found."})
        return
    chat_routes._handle_ingest(self, project_id)


def handle_project_cache_clear(self, project_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    if not projects.get(project_id):
        self._json(404, {"error": "Project not found."})
        return
    faq.clear(projects.faq_path(project_id))
    self._json(200, {"cleared": True})


def handle_project_cache_seed(self, project_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
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


def handle_project_watch_check(self, project_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    if not projects.get(project_id):
        self._json(404, {"error": "Project not found."})
        return
    self._json(200, prospectus_watch.check_and_refresh(project_id))


def handle_project_suggestions_apply(self, project_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
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


def handle_key_patch(self, key_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    entry = apikeys.set_active(key_id, bool(self._read_json().get("active")))
    self._json(200 if entry else 404, entry or {"error": "Key not found."})


def handle_flag_resolve(self, project_id, flag_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
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


def handle_project_patch(self, project_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
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
    self._json(200, _project_summary(projects.get(project_id)))


def handle_key_delete(self, key_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    ok = apikeys.delete(key_id)
    self._json(200 if ok else 404, {"deleted": key_id} if ok else {"error": "Key not found."})


def handle_learned_discriminator_delete(self, entry_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    ok = faq.remove_learned_discriminator(entry_id)
    self._json(200 if ok else 404, {"deleted": entry_id} if ok else {"error": "Entry not found."})


def handle_project_delete(self, project_id):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    ok = projects.delete(project_id)
    self._json(200 if ok else 404, {"deleted": project_id} if ok else {"error": "Project not found."})
