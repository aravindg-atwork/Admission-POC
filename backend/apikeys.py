
"""API key store: generate / activate / deactivate / delete.

Every consumer (the admission site's own widget, the browser extension, any
integration) holds its own key, so any one can be revoked without touching the
others. Backed by a single JSON file - enough at POC scale. Each key belongs
to exactly one project; resolve_active() is how /api/chat and /api/ingest
figure out which project's pipeline a request is for.
"""

import json
import secrets
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()


def _load():
    if not config.KEYS_PATH.exists():
        return []
    return json.loads(config.KEYS_PATH.read_text(encoding="utf-8") or "[]")


def _save(keys):
    config.KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.KEYS_PATH.write_text(json.dumps(keys, indent=2), encoding="utf-8")


def _new_entry(label, project_id):
    return {
        "id": secrets.token_hex(6),
        "key": "aas_" + secrets.token_urlsafe(32),
        "label": label or "unlabeled",
        "project_id": project_id,
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def list_keys(project_id=None):
    with _lock:
        keys = _load()
        return keys if project_id is None else [k for k in keys if k.get("project_id") == project_id]


def create(label, project_id):
    with _lock:
        keys = _load()
        entry = _new_entry(label, project_id)
        keys.append(entry)
        _save(keys)
        return entry


def set_project(key_id, project_id):
    with _lock:
        keys = _load()
        for entry in keys:
            if entry["id"] == key_id:
                entry["project_id"] = project_id
                _save(keys)
                return entry
        return None


def set_active(key_id, active):
    with _lock:
        keys = _load()
        for entry in keys:
            if entry["id"] == key_id:
                entry["active"] = active
                _save(keys)
                return entry
        return None


def delete(key_id):
    with _lock:
        keys = _load()
        remaining = [k for k in keys if k["id"] != key_id]
        if len(remaining) == len(keys):
            return False
        _save(remaining)
        return True


def is_active(key_value):
    if not key_value:
        return False
    with _lock:
        return any(k["key"] == key_value and k["active"] for k in _load())


def resolve_active(key_value):
    """Return the project_id an active key belongs to, or None."""
    if not key_value:
        return None
    with _lock:
        for k in _load():
            if k["key"] == key_value and k["active"]:
                return k.get("project_id")
    return None


def get_or_create_default(project_id):
    with _lock:
        keys = _load()
        for entry in keys:
            if entry["label"] == config.DEFAULT_KEY_LABEL and entry.get("project_id") == project_id:
                return entry
        entry = _new_entry(config.DEFAULT_KEY_LABEL, project_id)
        keys.append(entry)
        _save(keys)
        return entry
