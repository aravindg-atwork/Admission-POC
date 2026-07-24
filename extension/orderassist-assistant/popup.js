const FIELDS = [
  "backendUrl", "apiKey", "driveFolderId",
  "quotationTextSelector", "sendButtonSelector", "fileInputSelector",
  "matchThreshold",
];

function setStatus(text, cls) {
  const el = document.getElementById("status");
  el.textContent = text;
  el.className = cls || "";
}

async function load() {
  const stored = await chrome.storage.local.get(FIELDS);
  for (const key of FIELDS) {
    const el = document.getElementById(key);
    if (el && stored[key]) el.value = stored[key];
  }
}

function extractFolderId(raw) {
  // Accept a pasted Drive URL (.../folders/<id>?usp=sharing) as well as a bare ID.
  const match = raw.match(/folders\/([a-zA-Z0-9_-]+)/);
  return match ? match[1] : raw;
}

async function save() {
  const values = {};
  for (const key of FIELDS) values[key] = document.getElementById(key).value.trim();
  values.driveFolderId = extractFolderId(values.driveFolderId);
  document.getElementById("driveFolderId").value = values.driveFolderId;
  const threshold = parseFloat(values.matchThreshold);
  values.matchThreshold = Number.isFinite(threshold) ? threshold : 0.55;
  document.getElementById("matchThreshold").value = values.matchThreshold;
  await chrome.storage.local.set(values);
  setStatus("Saved. Reload the OrderAssist tab for it to take effect.", "ok");
}

async function generateKey() {
  const backendUrl = document.getElementById("backendUrl").value.trim();
  const adminToken = document.getElementById("adminToken").value.trim();
  if (!backendUrl || !adminToken) { setStatus("Set Backend URL and admin token first.", "err"); return; }
  setStatus("Generating key…", "");
  try {
    const res = await fetch(`${backendUrl}/admin/keys`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Admin-Token": adminToken },
      body: JSON.stringify({ label: "orderassist-extension" }),
    });
    if (!res.ok) throw new Error(`Backend returned ${res.status} - check the admin token.`);
    const entry = await res.json();
    document.getElementById("apiKey").value = entry.key;
    document.getElementById("adminToken").value = "";
    await save();
    setStatus(`Generated and saved a real API key: ${entry.key}`, "ok");
  } catch (e) {
    setStatus(e.message, "err");
  }
}

async function testDrive() {
  setStatus("Checking Drive access…", "");
  const folderId = document.getElementById("driveFolderId").value.trim();
  if (!folderId) { setStatus("Set a Drive folder ID first.", "err"); return; }
  await save();
  const testText = document.getElementById("testQuotationText").value.trim() || "test connection";
  const result = await chrome.runtime.sendMessage({ type: "FIND_MATCH", quotationText: testText });
  if (!result?.ok) {
    setStatus(result?.error || "Could not reach Drive or the backend.", "err");
    return;
  }
  setStatus(`Connected - ${result.matches.length} catalogue item(s) ranked against "${testText}".`, "ok");
  const diag = document.getElementById("diag");
  diag.style.display = "block";
  if (result.matches.length === 0) {
    diag.textContent = "No files found in that Drive folder.";
    return;
  }
  diag.textContent = `Threshold: ${result.threshold} - a match needs to score at or above this to trigger the banner.\n\n` +
    result.matches
      .map((m, i) => `${i + 1}. ${m.name} - score ${m.score}${m.score >= result.threshold ? "  ✓ would trigger" : "  (below threshold)"}`)
      .join("\n");
}

// Runs INSIDE the target tab (isolated world, same as content.js) - must be
// fully self-contained, no references to anything outside its own body.
function diagnosticProbe(sendButtonSelector, fileInputSelector) {
  const root = document.documentElement.dataset;
  let sendCount = null;
  let sendError = null;
  try { sendCount = sendButtonSelector ? document.querySelectorAll(sendButtonSelector).length : null; }
  catch (e) { sendError = e.message; }

  let fileCount = null;
  let fileError = null;
  try { fileCount = fileInputSelector ? document.querySelectorAll(fileInputSelector).length : null; }
  catch (e) { fileError = e.message; }

  return {
    url: location.href,
    contentScriptLoaded: root.oaContentLoaded === "1",
    interceptorLoaded: root.oaInterceptorLoaded === "1",
    lastCapturedQuotationText: root.oaLastCapturedText || null,
    lastCapturedRaw: root.oaLastCapturedRaw || null,
    sendButtonSelector, sendButtonMatchCount: sendCount, sendButtonError: sendError,
    fileInputSelector, fileInputMatchCount: fileCount, fileInputError: fileError,
  };
}

function renderDiag(d) {
  const el = document.getElementById("diag");
  el.style.display = "block";
  if (d.error) { el.textContent = "Could not inspect this tab: " + d.error; return; }
  const lines = [
    `Extension version running: ${chrome.runtime.getManifest().version}`,
    `URL: ${d.url}`,
    `content.js loaded: ${d.contentScriptLoaded ? "yes" : "NO - extension isn't running here"}`,
    `interceptor.js loaded: ${d.interceptorLoaded ? "yes" : "NO - extension isn't running here"}`,
    `Last quotation text captured from API: ${d.lastCapturedQuotationText || "(none yet - did the page finish loading?)"}`,
    `Send button selector "${d.sendButtonSelector || "(not set)"}" matches: ${d.sendButtonError ? "ERROR: " + d.sendButtonError : d.sendButtonMatchCount}`,
    `File input selector "${d.fileInputSelector || "(not set)"}" matches: ${d.fileInputError ? "ERROR: " + d.fileInputError : (d.fileInputMatchCount ?? "(not set)")}`,
  ];
  if (d.lastCapturedRaw && !d.lastCapturedQuotationText) {
    lines.push(`Raw API response seen (first 300 chars): ${d.lastCapturedRaw}`);
  }
  el.textContent = lines.join("\n");
}

async function diagnose() {
  setStatus("Inspecting current tab…", "");
  await save(); // whatever's currently typed in the boxes, not whatever was last saved
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) { renderDiag({ error: "No active tab found." }); return; }

  const cfg = await chrome.storage.local.get(["sendButtonSelector", "fileInputSelector"]);
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: diagnosticProbe,
      args: [cfg.sendButtonSelector || "", cfg.fileInputSelector || ""],
    });
    renderDiag({ ...result, url: result.url || tab.url });
    setStatus("", "");
  } catch (e) {
    renderDiag({ error: `${e.message} (are you on the OrderAssist page? this can't inspect chrome:// or other extension pages)` });
    setStatus("", "");
  }
}

async function resetAuth() {
  setStatus("Clearing cached Google sign-in…", "");
  await chrome.runtime.sendMessage({ type: "RESET_AUTH" });
  setStatus("Cleared. Click \"Test Drive access\" now for a fully fresh sign-in.", "ok");
}

document.getElementById("save").addEventListener("click", save);
document.getElementById("testDrive").addEventListener("click", testDrive);
document.getElementById("diagnose").addEventListener("click", diagnose);
document.getElementById("generateKey").addEventListener("click", generateKey);
document.getElementById("resetAuth").addEventListener("click", resetAuth);
document.getElementById("version").textContent = "v" + chrome.runtime.getManifest().version;
load();
