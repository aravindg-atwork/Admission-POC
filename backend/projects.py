"""Project registry: one isolated pipeline (prospectus, vector store, FAQ
cache, stats) per project.

A "project" is the unit the console's project nav operates on - dropping the
Admission Assistant agent onto a project gives it its own prospectus and its
own cost/usage numbers, so exploring multiple use cases in this POC never
quietly shares state between them. Backed by a flat JSON registry plus one
directory per project - same pattern as apikeys.py, just one level up.
"""

import json
import secrets
import shutil
import threading
from datetime import datetime, timezone

from . import apikeys, config

_lock = threading.Lock()


def _load():
    if not config.PROJECTS_REGISTRY_PATH.exists():
        return []
    return json.loads(config.PROJECTS_REGISTRY_PATH.read_text(encoding="utf-8") or "[]")


def _save(projects):
    config.PROJECTS_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.PROJECTS_REGISTRY_PATH.write_text(json.dumps(projects, indent=2), encoding="utf-8")


def _dir(project_id):
    return config.PROJECTS_DIR / project_id


def prospectus_path(project_id):
    return _dir(project_id) / "prospectus.pdf"


def store_path(project_id):
    return _dir(project_id) / "vector-store.json"


def faq_path(project_id):
    return _dir(project_id) / "faq-cache.json"


def stats_path(project_id):
    return _dir(project_id) / "stats.json"


def manifest_path(project_id):
    return _dir(project_id) / "manifest.json"


def tts_cache_dir(project_id):
    return _dir(project_id) / "tts-cache"


def list_projects():
    with _lock:
        return _load()


def get(project_id):
    for p in _load():
        if p["id"] == project_id:
            return p
    return None


def create(name, project_id=None):
    with _lock:
        projects = _load()
        entry = {
            "id": project_id or secrets.token_hex(6),
            "name": name or "Untitled project",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "allow_cloud": True,
        }
        projects.append(entry)
        _save(projects)
        _dir(entry["id"]).mkdir(parents=True, exist_ok=True)
        return entry


def allow_cloud(project_id):
    """Whether this project may use the Sarvam cloud model at all.

    Defaults to True (existing behavior) for projects created before this
    setting existed. When False, the project always answers with the local
    model, regardless of the Sarvam key or the account-wide daily cap.
    """
    entry = get(project_id)
    return bool(entry.get("allow_cloud", True)) if entry else True


def set_allow_cloud(project_id, value):
    with _lock:
        projects = _load()
        for entry in projects:
            if entry["id"] == project_id:
                entry["allow_cloud"] = bool(value)
                _save(projects)
                return entry
        return None


def delete(project_id):
    with _lock:
        projects = _load()
        remaining = [p for p in projects if p["id"] != project_id]
        if len(remaining) == len(projects):
            return False
        _save(remaining)
        shutil.rmtree(_dir(project_id), ignore_errors=True)
        for key in apikeys.list_keys():
            if key.get("project_id") == project_id:
                apikeys.delete(key["id"])
        return True


def migrate_legacy_if_needed():
    """One-time move of the old flat single-tenant data files into
    data/projects/default/, the first time this runs after upgrading.

    Runs before anything else touches project data. Safe to call every
    startup - it's a no-op once data/projects.json exists.
    """
    if config.PROJECTS_REGISTRY_PATH.exists():
        return

    with _lock:
        if config.PROJECTS_REGISTRY_PATH.exists():  # re-check under lock
            return
        entry = {
            "id": config.DEFAULT_PROJECT_ID,
            "name": "Admission Assistant",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "allow_cloud": True,
        }
        _save([entry])
        _dir(entry["id"]).mkdir(parents=True, exist_ok=True)

    legacy_prospectus = config.LEGACY_PROSPECTUS_DIR / "prospectus.pdf"
    if legacy_prospectus.exists():
        shutil.move(str(legacy_prospectus), str(prospectus_path(config.DEFAULT_PROJECT_ID)))
    if config.LEGACY_STORE_PATH.exists():
        shutil.move(str(config.LEGACY_STORE_PATH), str(store_path(config.DEFAULT_PROJECT_ID)))
    if config.LEGACY_FAQ_PATH.exists():
        shutil.move(str(config.LEGACY_FAQ_PATH), str(faq_path(config.DEFAULT_PROJECT_ID)))
    if config.LEGACY_STATS_PATH.exists():
        shutil.move(str(config.LEGACY_STATS_PATH), str(stats_path(config.DEFAULT_PROJECT_ID)))

    for key in apikeys.list_keys():
        if not key.get("project_id"):
            apikeys.set_project(key["id"], config.DEFAULT_PROJECT_ID)
