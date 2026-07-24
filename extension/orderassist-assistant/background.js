/**
 * Service worker: everything that needs Google auth or talks to the backend.
 * content.js never calls Google/the backend directly - it only extracts page
 * text and does the DOM injection, and asks this worker to do the rest via
 * chrome.runtime messages. Keeps the OAuth token and the backend API key out
 * of the page's own JS context.
 */

const DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files";

async function getConfig() {
  const cfg = await chrome.storage.local.get([
    "backendUrl", "apiKey", "driveFolderId",
    "quotationTextSelector", "sendButtonSelector", "fileInputSelector",
    "matchThreshold",
  ]);
  return {
    backendUrl: cfg.backendUrl || "http://localhost:5050",
    apiKey: cfg.apiKey || "",
    driveFolderId: cfg.driveFolderId || "",
    quotationTextSelector: cfg.quotationTextSelector || "",
    sendButtonSelector: cfg.sendButtonSelector || "",
    fileInputSelector: cfg.fileInputSelector || "",
    matchThreshold: typeof cfg.matchThreshold === "number" ? cfg.matchThreshold : 0.55,
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
  const fields = encodeURIComponent("files(id,name,description)");
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
  const res = await fetch(`${DRIVE_FILES_URL}/${fileId}?alt=media`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Drive download failed: ${res.status}`);
  const blob = await res.blob();
  // Drive doesn't return a filename on the media download - fetch metadata separately.
  const metaRes = await fetch(`${DRIVE_FILES_URL}/${fileId}?fields=name,mimeType`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const meta = metaRes.ok ? await metaRes.json() : {};
  return { blob, name: meta.name || "attachment", mimeType: meta.mimeType || blob.type };
}

async function matchCatalogue(cfg, quotationText, items) {
  const res = await fetch(`${cfg.backendUrl}/api/catalogue/match`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": cfg.apiKey },
    body: JSON.stringify({ quotationText, items }),
  });
  if (!res.ok) throw new Error(`Catalogue match failed: ${res.status}`);
  const data = await res.json();
  return data.matches || [];
}

async function findBestMatch(quotationText) {
  const cfg = await getConfig();
  if (!cfg.apiKey) throw new Error("No backend API key configured - set one in the extension popup.");
  if (!cfg.driveFolderId) throw new Error("No Drive catalogue folder configured - set one in the extension popup.");

  const files = await listCatalogueWithRetry(cfg.driveFolderId);
  if (files.length === 0) return { matches: [], threshold: cfg.matchThreshold };

  const items = files.map((f) => ({ id: f.id, name: f.name, description: f.description || "" }));
  const matches = await matchCatalogue(cfg, quotationText, items);
  return { matches, threshold: cfg.matchThreshold };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "FIND_MATCH") {
    findBestMatch(msg.quotationText)
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true; // async response
  }
  if (msg.type === "DOWNLOAD_MATCH") {
    getDriveToken(false)
      .then((token) => downloadDriveFile(msg.fileId, token))
      .then((file) => sendResponse({ ok: true, ...file }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  if (msg.type === "RESET_AUTH") {
    chrome.identity.clearAllCachedAuthTokens(() => sendResponse({ ok: true }));
    return true;
  }
  return false;
});
