/**
 * Service worker: everything that needs Google auth or talks to the backend.
 * content.js never calls Google/the backend directly - it only extracts page
 * text and does the DOM injection, and asks this worker to do the rest via
 * chrome.runtime messages. Keeps the OAuth token and the backend API key out
 * of the page's own JS context.
 *
 * Zero-config design: the user only signs in with Google (Drive OAuth).
 * Everything else is auto-discovered:
 *   1. On install, calls /api/extension/register on the backend to get
 *      the API key + settings.
 *   2. Scans Drive root folders and sends them to the backend, which uses
 *      AI to pick the best catalogue folder.
 *   3. Auto-detects email compose areas (content.js) and send buttons.
 */

const DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files";
const DRIVE_FOLDER_ENDPOINT = "https://www.googleapis.com/drive/v3/files?q=";

async function getConfig() {
  const cfg = await chrome.storage.local.get([
    "backendUrl", "apiKey", "driveFolderId",
    "quotationTextSelector", "sendButtonSelector", "fileInputSelector",
    "matchThreshold",
    "ocrServiceUrl", "ocrApiKey",
    "injectNoteOnAttach", "injectNoteOnSkip",
  ]);
  return {
    backendUrl: cfg.backendUrl || "http://localhost:5050",
    apiKey: cfg.apiKey || "",
    driveFolderId: cfg.driveFolderId || "",
    quotationTextSelector: cfg.quotationTextSelector || "",
    sendButtonSelector: cfg.sendButtonSelector || "",
    fileInputSelector: cfg.fileInputSelector || "",
    matchThreshold: typeof cfg.matchThreshold === "number" ? cfg.matchThreshold : 0.55,
    ocrServiceUrl: cfg.ocrServiceUrl || "",
    ocrApiKey: cfg.ocrApiKey || "",
    injectNoteOnAttach: cfg.injectNoteOnAttach !== false, // default true
    injectNoteOnSkip: cfg.injectNoteOnSkip === true, // default false
  };
}

function getDriveToken(interactive) {
  return new Promise((resolve, reject) => {
    chrome.identity.getAuthToken({ interactive }, (token) => {
      if (chrome.runtime.lastError || !token) {
        reject(new Error(chrome.runtime.lastError?.message || "No Drive token - sign in required."));
        return;
      }
      resolve(token);
    });
  });
}

function clearDriveToken(token) {
  return new Promise((resolve) => {
    if (!token) { resolve(); return; }
    chrome.identity.removeCachedAuthToken({ token }, resolve);
  });
}

async function listCatalogue(folderId, token) {
  const q = encodeURIComponent(`'${folderId}' in parents and trashed = false`);
  const fields = encodeURIComponent("files(id,name,description,webViewLink)");
  const res = await fetch(`${DRIVE_FILES_URL}?q=${q}&fields=${fields}&pageSize=100`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json())?.error?.message || ""; } catch { /* not JSON */ }
    const err = new Error(`Drive list failed: ${res.status}${detail ? " - " + detail : ""}`);
    err.status = res.status;
    throw err;
  }
  const data = await res.json();
  return data.files || [];
}

// A half-finished sign-in can leave a stale/invalid token cached by Chrome,
// which then fails every real Drive call with 401/403 until it's cleared -
// looks identical to a real permissions problem otherwise. Clear it and force
// one genuinely fresh interactive sign-in before giving up.
async function listCatalogueWithRetry(folderId) {
  let token = await getDriveToken(true);
  try {
    return await listCatalogue(folderId, token);
  } catch (err) {
    if (err.status === 401 || err.status === 403) {
      await clearDriveToken(token);
      token = await getDriveToken(true);
      return await listCatalogue(folderId, token);
    }
    throw err;
  }
}

async function downloadDriveFile(fileId, token) {
  // Drive doesn't return a filename on the media download - metadata needs a
  // separate call. That call doesn't depend on the content download (or vice
  // versa), so fetch both at once instead of waiting on one before starting
  // the other.
  const [res, metaRes] = await Promise.all([
    fetch(`${DRIVE_FILES_URL}/${fileId}?alt=media`, { headers: { Authorization: `Bearer ${token}` } }),
    fetch(`${DRIVE_FILES_URL}/${fileId}?fields=name,mimeType`, { headers: { Authorization: `Bearer ${token}` } }),
  ]);
  if (!res.ok) throw new Error(`Drive download failed: ${res.status}`);
  const blob = await res.blob();
  const meta = metaRes.ok ? await metaRes.json() : {};
  return { blob, name: meta.name || "attachment", mimeType: meta.mimeType || blob.type };
}

async function matchCatalogue(cfg, quotationText, quotationLines, items) {
  const res = await fetch(`${cfg.backendUrl}/api/catalogue/match`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": cfg.apiKey },
    body: JSON.stringify({ quotationText, quotationLines, items, threshold: cfg.matchThreshold }),
  });
  if (!res.ok) throw new Error(`Catalogue match failed: ${res.status}`);
  const data = await res.json();
  return data.matches || [];
}

// Simple in-memory OCR text cache keyed by file ID.
// Persisted across service-worker restarts via chrome.storage.session.
const ocrCache = new Map();

async function getOcrTextCache() {
  const stored = await chrome.storage.session.get("ocrTextCache");
  if (stored.ocrTextCache) {
    for (const [k, v] of Object.entries(stored.ocrTextCache)) ocrCache.set(k, v);
  }
}

async function saveOcrTextCache() {
  const obj = {};
  for (const [k, v] of ocrCache.entries()) obj[k] = v;
  // Keep the last 200 entries to avoid bloating storage.
  const entries = Object.entries(obj);
  if (entries.length > 200) {
    const trimmed = Object.fromEntries(entries.slice(-200));
    await chrome.storage.session.set({ ocrTextCache: trimmed });
  } else {
    await chrome.storage.session.set({ ocrTextCache: obj });
  }
}

async function ocrFile(cfg, fileId, fileName) {
  if (!cfg.ocrServiceUrl) return ""; // OCR not configured
  const cached = ocrCache.get(fileId);
  if (cached) return cached;

  try {
    // Download the file from Drive first
    const token = await getDriveToken(false);
    const dl = await downloadDriveFile(fileId, token);
    
    // Send to OCR service
    const formData = new FormData();
    formData.append("file", dl.blob, dl.name);
    const res = await fetch(cfg.ocrServiceUrl, {
      method: "POST",
      headers: { "X-API-Key": cfg.ocrApiKey || "" },
      body: formData,
    });
    if (!res.ok) {
      console.log("[OA] OCR failed for", fileName, res.status);
      return "";
    }
    const data = await res.json();
    const text = data.text || "";
    if (text) {
      ocrCache.set(fileId, text);
      await saveOcrTextCache();
    }
    return text;
  } catch (e) {
    console.log("[OA] OCR error for", fileName, e.message);
    return "";
  }
}

async function findBestMatch(quotationText, quotationLines) {
  const cfg = await getConfig();
  if (!cfg.apiKey) throw new Error("No backend API key configured - set one in the extension popup.");
  if (!cfg.driveFolderId) throw new Error("No Drive catalogue folder configured - set one in the extension popup.");

  const files = await listCatalogueWithRetry(cfg.driveFolderId);
  if (files.length === 0) return { matches: [], threshold: cfg.matchThreshold };

  // Load OCR text cache from session storage
  await getOcrTextCache();

  // Build items with OCR text (lazy: OCR each file once, cache forever)
  const items = [];
  for (const f of files) {
    const item = { id: f.id, name: f.name, description: f.description || "", webViewLink: f.webViewLink || "" };
    const ocrText = await ocrFile(cfg, f.id, f.name);
    if (ocrText) item.ocr_text = ocrText.slice(0, 2000);
    items.push(item);
  }

  // quotationLines (one entry per distinct product on the quotation) lets the
  // backend match each product independently and return several brochures
  // instead of only ever the single best match for the whole quotation.
  const matches = await matchCatalogue(cfg, quotationText, quotationLines, items);
  // `items` is returned too so a follow-up complementary-suggestion call
  // (see findComplementary) can reuse it instead of re-listing and re-OCRing
  // the whole Drive folder a second time just to ask a slower question about
  // the same catalogue.
  return { matches, threshold: cfg.matchThreshold, items };
}

async function findComplementary(cfg, quotationText, items, existingIds) {
  const res = await fetch(`${cfg.backendUrl}/api/catalogue/complementary`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": cfg.apiKey },
    body: JSON.stringify({ quotationText, items, existingIds }),
  });
  if (!res.ok) throw new Error(`Complementary suggestion failed: ${res.status}`);
  const data = await res.json();
  return data.matches || [];
}

async function generateNote(cfg, quotationText, matchedItems) {
  const res = await fetch(`${cfg.backendUrl}/api/catalogue/note`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": cfg.apiKey },
    body: JSON.stringify({ quotationText, matchedItems }),
  });
  if (!res.ok) throw new Error(`Note generation failed: ${res.status}`);
  const data = await res.json();
  return data.note || "";
}

/**
 * Auto-register with the backend: fetch backend URL from storage (fallback
 * localhost:5050), call /api/extension/register, and store the returned config.
 * If the backend also returns autoDiscoverFolders:true and no driveFolderId is
 * set yet, trigger Drive folder discovery.
 */
async function registerWithBackend(customBackendUrl) {
  const stored = await chrome.storage.local.get(["backendUrl", "driveFolderId"]);
  const backendUrl = customBackendUrl || stored.backendUrl || "http://localhost:5050";

  try {
    const res = await fetch(`${backendUrl}/api/extension/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!res.ok) throw new Error(`Backend returned ${res.status}`);
    const config = await res.json();

    // driveFolderId is discovered client-side (discoverDriveFolders), not
    // admin-set, so the backend only has one once some install has reported
    // it back (see reportDiscoveredFolder). MV3 service workers restart
    // constantly (idle timeout, first click waking it back up, etc.) and
    // this function runs unconditionally on every restart - blindly
    // overwriting with the backend's usually-empty value would wipe out a
    // folder this install already found, forcing a fresh ~10s Drive rescan
    // on every cold start. Keep whatever's already known locally instead.
    const driveFolderId = config.driveFolderId || stored.driveFolderId || "";

    // Merge returned config into storage
    await chrome.storage.local.set({
      backendUrl,
      apiKey: config.apiKey || "",
      driveFolderId,
      quotationTextSelector: config.quotationTextSelector || "",
      sendButtonSelector: config.sendButtonSelector || "",
      fileInputSelector: config.fileInputSelector || "",
      matchThreshold: typeof config.matchThreshold === "number" ? config.matchThreshold : 0.55,
      ocrServiceUrl: config.ocrServiceUrl || "",
      ocrApiKey: config.ocrApiKey || "",
      injectNoteOnAttach: config.injectNoteOnAttach !== false,
      injectNoteOnSkip: config.injectNoteOnSkip === true,
    });

    // If the backend has nothing on file yet and we don't already know one
    // locally either, kick off Drive folder scanning.
    if (config.autoDiscoverFolders && !driveFolderId) {
      discoverDriveFolders(backendUrl).catch((e) =>
        console.log("[OA] Drive folder discovery failed:", e.message)
      );
    } else if (driveFolderId && !config.driveFolderId) {
      // We know it locally but the backend doesn't yet (e.g. first
      // registration after this install discovered it) - report it back so
      // every future registration, from this install or any other, already
      // has it and never needs to re-scan.
      reportDiscoveredFolder(backendUrl, config.apiKey || "", driveFolderId).catch((e) =>
        console.log("[OA] failed to report discovered folder to backend:", e.message)
      );
    }

    return { ok: true, config };
  } catch (e) {
    console.log("[OA] registerWithBackend failed:", e.message);
    return { ok: false, error: e.message };
  }
}

async function reportDiscoveredFolder(backendUrl, apiKey, driveFolderId) {
  if (!apiKey) return;
  await fetch(`${backendUrl}/api/extension/report-config`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
    body: JSON.stringify({ driveFolderId }),
  });
}

/**
 * Scan all root folders in the user's Drive, send them to the backend for
 * AI-powered selection of the best catalogue folder, then store the result.
 */
async function discoverDriveFolders(backendUrl) {
  const token = await getDriveToken(true);
  
  // List root folders (not in any folder = root)
  const q = encodeURIComponent(
    "mimeType='application/vnd.google-apps.folder' and trashed=false and 'root' in parents"
  );
  const fields = encodeURIComponent("files(id,name,description,createdTime)");
  const res = await fetch(
    `${DRIVE_FILES_URL}?q=${q}&fields=${fields}&pageSize=100`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok) throw new Error(`Drive list folders failed: ${res.status}`);
  const data = await res.json();
  const folders = data.files || [];
  
  if (folders.length === 0) {
    console.log("[OA] No root folders found in Drive");
    return { ok: false, error: "No folders found" };
  }
  
  // Send folders to backend for AI selection
  const discoverRes = await fetch(`${backendUrl}/api/extension/discover-folders`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folders }),
  });
  if (!discoverRes.ok) throw new Error(`Discover failed: ${discoverRes.status}`);
  const result = await discoverRes.json();
  
  if (result.folderId) {
    await chrome.storage.local.set({ driveFolderId: result.folderId });
    console.log("[OA] Auto-discovered Drive catalogue folder:", result.folderName || result.folderId);
    // Persist it to the backend too, so every future registration (this
    // install's next service-worker restart, or any other rep's install)
    // gets it directly instead of each one independently re-scanning Drive.
    const { apiKey } = await chrome.storage.local.get(["apiKey"]);
    reportDiscoveredFolder(backendUrl, apiKey, result.folderId).catch((e) =>
      console.log("[OA] failed to report discovered folder to backend:", e.message)
    );
    return { ok: true, folderId: result.folderId, folderName: result.folderName };
  }
  
  // No folder found - store the hint for the popup to show
  await chrome.storage.local.set({ driveDiscoveryHint: result.hint || "" });
  return { ok: false, error: result.hint || "No suitable folder found" };
}

/**
 * Get the current registration status for the popup.
 */
async function getRegistrationStatus() {
  const stored = await chrome.storage.local.get([
    "backendUrl", "apiKey", "driveFolderId",
    "sendButtonSelector", "driveDiscoveryHint",
  ]);
  return {
    backendUrl: stored.backendUrl || "",
    hasApiKey: !!stored.apiKey,
    hasDriveFolder: !!stored.driveFolderId,
    driveFolderId: stored.driveFolderId || "",
    sendButtonSelector: stored.sendButtonSelector || "",
    driveDiscoveryHint: stored.driveDiscoveryHint || "",
  };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "REGISTER_EXTENSION") {
    registerWithBackend(msg.backendUrl)
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  if (msg.type === "REGISTRATION_STATUS") {
    getRegistrationStatus()
      .then((status) => sendResponse({ ok: true, ...status }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  if (msg.type === "DISCOVER_DRIVE_FOLDERS") {
    getConfig()
      .then((cfg) => discoverDriveFolders(cfg.backendUrl))
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  if (msg.type === "FIND_MATCH") {
    findBestMatch(msg.quotationText, msg.quotationLines)
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  if (msg.type === "DOWNLOAD_MATCH") {
    getDriveToken(false)
      .then((token) => downloadDriveFile(msg.fileId, token))
      .then((file) => sendResponse({ ok: true, ...file }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  if (msg.type === "FIND_COMPLEMENTARY") {
    getConfig()
      .then((cfg) => findComplementary(cfg, msg.quotationText, msg.items, msg.existingIds))
      .then((matches) => sendResponse({ ok: true, matches }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  if (msg.type === "GENERATE_NOTE") {
    getConfig()
      .then((cfg) => generateNote(cfg, msg.quotationText, msg.matchedItems))
      .then((note) => sendResponse({ ok: true, note }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  if (msg.type === "RESET_AUTH") {
    chrome.identity.clearAllCachedAuthTokens(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg.type === "SET_CONFIG") {
    chrome.storage.local.set(msg.values, () => {
      sendResponse({ ok: true });
    });
    return true;
  }
  return false;
});

// Auto-register on service worker startup (fires on extension load/update)
registerWithBackend().catch((e) => console.log("[OA] initial register failed:", e.message));
