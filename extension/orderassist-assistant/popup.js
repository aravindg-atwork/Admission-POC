/**
 * Zero-config popup: status-only, Google sign-in, troubleshooting.
 *
 * The user does NOT configure backendUrl, apiKey, driveFolderId, selectors,
 * or any other settings here. All of that is auto-discovered by the
 * background worker through /api/extension/register.
 *
 * The ONLY field the user may set is the Backend URL (if it's not
 * localhost:5050), and Google sign-in for Drive access.
 */

function $(id) { return document.getElementById(id); }

function setDot(id, state) {
  const dot = $(id);
  if (!dot) return;
  dot.className = "dot " + (state || "gray");
}

function setDetail(id, text) {
  const el = $(id);
  if (el) el.textContent = text;
}

function setStatus(text, cls) {
  const el = $("status");
  if (!el) return;
  el.textContent = text;
  el.className = cls || "";
  if (cls) {
    el.style.display = "block";
  } else {
    el.style.display = "none";
  }
}

function showDiag(text) {
  const el = $("diag");
  if (el) { el.textContent = text; el.style.display = "block"; }
}

async function refreshStatus() {
  try {
    const result = await chrome.runtime.sendMessage({ type: "REGISTRATION_STATUS" });
    if (!result?.ok) {
      setDot("dot-backend", "red");
      setDetail("detail-backend", "Error contacting worker");
      return;
    }

    // Backend status
    if (result.hasApiKey) {
      setDot("dot-backend", "green");
      setDetail("detail-backend", "Connected to " + (result.backendUrl || "backend"));
    } else {
      setDot("dot-backend", "yellow");
      setDetail("detail-backend", "Not registered — enter URL and connect");
    }

    // Drive status
    if (result.hasDriveFolder) {
      setDot("dot-drive", "green");
      setDetail("detail-drive", "Signed in and authorized");
      setDot("dot-folder", "green");
      setDetail("detail-folder", result.driveFolderId ? "Folder selected" : "Auto-discovered");
    } else {
      // Check if we have any Google Drive OAuth token cached
      setDot("dot-drive", "yellow");
      setDetail("detail-drive", "Sign in with Google below");
      setDot("dot-folder", "gray");
      const hint = result.driveDiscoveryHint;
      setDetail("detail-folder", hint || "Sign in to find catalogue folder");
    }
  } catch (e) {
    console.log("[OA-POPUP] refreshStatus error:", e.message);
  }
}

async function handleConnectBackend() {
  const backendUrl = $("backendUrl").value.trim();
  if (!backendUrl) {
    setStatus("Enter a backend URL", "err");
    return;
  }
  setStatus("Connecting…", "info");
  try {
    const result = await chrome.runtime.sendMessage({
      type: "REGISTER_EXTENSION",
      backendUrl,
    });
    if (result?.ok) {
      setStatus("Connected and configured. Checking Drive…", "ok");
      await refreshStatus();
    } else {
      setStatus(result?.error || "Connection failed", "err");
    }
  } catch (e) {
    setStatus("Error: " + e.message, "err");
  }
}

async function handleSignIn() {
  setStatus("Signing in with Google…", "info");
  try {
    // Request Drive token interactively — this triggers the OAuth flow
    const token = await new Promise((resolve, reject) => {
      chrome.identity.getAuthToken({ interactive: true }, (token) => {
        if (chrome.runtime.lastError || !token) {
          reject(new Error(chrome.runtime.lastError?.message || "Sign-in cancelled"));
          return;
        }
        resolve(token);
      });
    });
    if (token) {
      setStatus("Signed in! Scanning Drive for catalogue folder…", "ok");
      await refreshStatus();
      // Trigger folder discovery
      const result = await chrome.runtime.sendMessage({ type: "DISCOVER_DRIVE_FOLDERS" });
      if (result?.ok) {
        setStatus("Found catalogue folder: " + (result.folderName || result.folderId), "ok");
      } else {
        setStatus(result?.error || "No catalogue folder found. Create one named 'Catalogue' or 'Brochures' and re-scan.", "err");
      }
      await refreshStatus();
    }
  } catch (e) {
    setStatus(e.message, "err");
  }
}

async function handleRescanDrive() {
  setStatus("Re-scanning Drive…", "info");
  try {
    const result = await chrome.runtime.sendMessage({ type: "DISCOVER_DRIVE_FOLDERS" });
    if (result?.ok) {
      setStatus("Found: " + (result.folderName || result.folderId), "ok");
    } else {
      setStatus(result?.error || "No catalogue folder found", "err");
    }
    await refreshStatus();
  } catch (e) {
    setStatus("Error: " + e.message, "err");
  }
}

async function handleResetAuth() {
  setStatus("Clearing Google sign-in…", "info");
  try {
    await chrome.runtime.sendMessage({ type: "RESET_AUTH" });
    setStatus("Signed out. Click 'Sign in with Google' to re-authenticate.", "ok");
    await refreshStatus();
  } catch (e) {
    setStatus("Error: " + e.message, "err");
  }
}

async function handleDiagnose() {
  setStatus("Inspecting current tab…", "info");
  showDiag("Probing…");
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) {
      showDiag("No active tab found.");
      setStatus("", "");
      return;
    }

    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const root = document.documentElement.dataset;
        return {
          url: location.href,
          contentLoaded: root.oaContentLoaded === "1",
          interceptorLoaded: root.oaInterceptorLoaded === "1",
          lastCapturedText: root.oaLastCapturedText || "(none)",
        };
      },
    });

    const lines = [
      `URL: ${result.url}`,
      `content.js loaded: ${result.contentLoaded ? "yes" : "NO"}`,
      `interceptor.js loaded: ${result.interceptorLoaded ? "yes" : "NO"}`,
      `Last quotation text: ${result.lastCapturedText}`,
    ];
    showDiag(lines.join("\n"));
    setStatus("", "");
  } catch (e) {
    showDiag("Diagnose error: " + e.message);
    setStatus("", "");
  }
}

// ---------- Init ----------
document.addEventListener("DOMContentLoaded", async () => {
  // Version
  const ver = $("version");
  if (ver) ver.textContent = "v" + (chrome.runtime.getManifest().version || "?");

  // Load stored backend URL
  const stored = await chrome.storage.local.get(["backendUrl"]);
  if (stored.backendUrl) {
    $("backendUrl").value = stored.backendUrl;
  }

  // Refresh status display
  await refreshStatus();

  // Wire up buttons
  $("connectBackend").addEventListener("click", handleConnectBackend);
  $("backendUrl").addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleConnectBackend();
  });
  $("signInBtn").addEventListener("click", handleSignIn);
  $("diagnoseBtn").addEventListener("click", handleDiagnose);
  $("rescanDriveBtn").addEventListener("click", handleRescanDrive);
  $("resetAuthBtn").addEventListener("click", handleResetAuth);

  // Troubleshoot collapsible
  const toggle = $("troubleshootToggle");
  const body = $("troubleshootBody");
  toggle.addEventListener("click", () => {
    body.classList.toggle("open");
    toggle.textContent = body.classList.contains("open") ? "▼ Troubleshoot" : "▶ Troubleshoot";
  });
});

