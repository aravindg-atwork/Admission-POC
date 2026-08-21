"""OrderAssist route handlers - extracted from server.py's do_GET/do_POST/
do_PATCH during the 2026-08-13 re-architecture (Request 1b: isolate
OrderAssist, an unrelated sales-proposal/catalogue-matching feature, from
the admission-bot code it was previously interleaved with). Each function
takes the live `Handler` instance (`self`) exactly as it did inline in
server.py - same `self._read_json()`/`self._json()`/`self.headers` calls,
same behavior, just moved. server.py's do_GET/do_POST/do_PATCH keep their
exact if/elif conditions and order; only the body of each OrderAssist
branch becomes a one-line call into this module.
"""

from . import catalogue, extension_settings
from ..generation import llm
from ..storage import apikeys, projects, stats


def handle_extension_settings_get(self):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    self._json(200, extension_settings.get_settings())


def handle_catalogue_match(self):
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


def handle_catalogue_complementary(self):
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


def handle_catalogue_note(self):
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


def handle_extension_register(self):
    body = self._read_json()
    try:
         registration = extension_settings.get_registration()
         if not registration.get("driveFolderId"):
             registration["autoDiscoverFolders"] = True
         self._json(200, registration)
    except Exception as exc:
         self._json(500, {"error": str(exc)})


def handle_extension_report_config(self):
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


def handle_extension_discover_folders(self):
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


def handle_extension_config(self):
    try:
         settings = extension_settings.get_settings()
         self._json(200, {"settings": settings})
    except Exception as exc:
         self._json(500, {"error": str(exc)})


def handle_extension_settings_patch(self):
    if not self._admin_ok():
        self._json(401, {"error": "Invalid admin token."})
        return
    body = self._read_json()
    try:
        updated = extension_settings.update_settings(body)
        self._json(200, updated)
    except Exception as exc:
        self._json(500, {"error": str(exc)})

