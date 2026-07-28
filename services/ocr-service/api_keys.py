"""
API key management for the OCR microservice.

Keys are stored in a JSON file mounted at /data/api-keys.json (or the path
set in API_KEYS_PATH). Each key has a label, an active flag, and a creation
timestamp, and can be revoked independently so different consumers (or
different environments) each hold their own key without sharing one secret.

Same pattern as the embedding-service's api_keys.py for consistency.
"""

import json
import secrets
import os
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("OCR_DATA_DIR", "/data"))
KEYS_PATH = Path(os.environ.get("API_KEYS_PATH", str(DATA_DIR / "api-keys.json")))


def _load():
    if KEYS_PATH.exists():
        try:
            return json.loads(KEYS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save(keys):
    KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEYS_PATH.write_text(json.dumps(keys, indent=2), encoding="utf-8")


def create_key(label=""):
    keys = _load()
    entry = {
        "id": secrets.token_hex(8),
        "key": "ocr_" + secrets.token_urlsafe(24),
        "label": label or "",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    keys.append(entry)
    _save(keys)
    return entry


def is_key_active(raw_key):
    if not raw_key:
        return False
    return any(k["key"] == raw_key and k.get("active", False) for k in _load())


def list_keys():
    return _load()


def set_active(key_id, active):
    keys = _load()
    for k in keys:
        if k["id"] == key_id:
            k["active"] = active
            _save(keys)
            return k
    return None


def delete_key(key_id):
    keys = _load()
    new_keys = [k for k in keys if k["id"] != key_id]
    if len(new_keys) == len(keys):
        return False
    _save(new_keys)
    return True

