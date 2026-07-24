/**
 * Runs on the OrderAssist quotation page (isolated world - separate JS realm
 * from the page's own scripts). Intercepts the Send click, asks the
 * background worker whether a Drive catalogue item matches this quotation,
 * and - if the user agrees - injects that file into the page's own
 * attachment input before letting the original Send action continue. This
 * never touches OrderAssist's backend: it only adds a file to a form field
 * that's already there, then lets OrderAssist's existing send logic run.
 *
 * The quotation text itself comes from interceptor.js (runs in the page's
 * own world, reads the real /view_proposal/:id.json API response). It's read
 * straight off a DOM attribute (document.documentElement.dataset) rather than
 * caught via a live window.postMessage listener - interceptor.js runs at
 * document_start and can fire long before this script (document_idle) has
 * even attached a listener, so a live-only postMessage catch can silently
 * miss it. A DOM attribute has no such race: it's just read whenever needed,
 * however long ago it was set. A CSS selector is kept only as a fallback for
 * pages where that interception doesn't apply at all.
 *
 * If no Send button selector is configured in the popup, this script does
 * nothing at all - fails open, never blocks a real send.
 */

const BYPASS_FLAG = "oaAssistantBypass";
const boundButtons = new WeakSet();

function getLastQuotationText() {
  return (document.documentElement.dataset.oaLastCapturedText || "").trim();
}

function getConfig() {
  return chrome.storage.local.get([
    "quotationTextSelector", "sendButtonSelector", "fileInputSelector",
  ]);
}

function findBanner() {
  return document.getElementById("oa-assistant-host");
}

function removeBanner() {
  const host = findBanner();
  if (host) host.remove();
}

function showBanner({ match, onAttach, onSkip, onCancel }) {
  removeBanner();
  const host = document.createElement("div");
  host.id = "oa-assistant-host";
  host.style.cssText = "position:fixed;top:20px;right:20px;z-index:2147483647;";
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: "open" });

  root.innerHTML = `
    <style>
      .card { font: 14px/1.4 -apple-system, Segoe UI, Arial, sans-serif; background:#fff;
        border:1px solid #d8dee5; border-radius:12px; box-shadow:0 8px 28px rgba(0,0,0,.18);
        padding:16px; width:300px; color:#1a1f27; }
      .title { font-weight:600; margin-bottom:4px; }
      .sub { color:#5b6572; font-size:12.5px; margin-bottom:10px; }
      .match { background:#f3f6f4; border:1px solid #e1e7e3; border-radius:8px; padding:8px 10px;
        font-size:13px; margin-bottom:12px; }
      .match b { display:block; }
      .row { display:flex; gap:8px; }
      button { font:inherit; font-size:13px; font-weight:500; padding:8px 10px; border-radius:8px;
        border:1px solid #d8dee5; background:#f3f4f6; cursor:pointer; flex:1; }
      button.primary { background:#1a7f4e; border-color:#1a7f4e; color:#fff; }
      button.text { border:none; background:none; color:#5b6572; flex:0; }
    </style>
    <div class="card">
      <div class="title">Matching brochure found</div>
      <div class="sub">This quotation looks like it matches a catalogue item.</div>
      <div class="match"><b>${match.name}</b>${Math.round(match.score * 100)}% match</div>
      <div class="row">
        <button class="text" id="oa-cancel">Cancel</button>
        <button id="oa-skip">Send without it</button>
        <button class="primary" id="oa-attach">Attach &amp; send</button>
      </div>
    </div>
  `;

  root.getElementById("oa-attach").addEventListener("click", () => { removeBanner(); onAttach(); });
  root.getElementById("oa-skip").addEventListener("click", () => { removeBanner(); onSkip(); });
  root.getElementById("oa-cancel").addEventListener("click", () => { removeBanner(); onCancel(); });
}

function resendClick(button) {
  button.dataset[BYPASS_FLAG] = "1";
  button.click();
}

async function injectFileIntoInput(fileInput, file) {
  const dt = new DataTransfer();
  // Keep whatever the user already attached (e.g. the quotation PDF itself).
  for (const existing of fileInput.files || []) dt.items.add(existing);
  dt.items.add(file);
  fileInput.files = dt.files;
  fileInput.dispatchEvent(new Event("change", { bubbles: true }));
  fileInput.dispatchEvent(new Event("input", { bubbles: true }));
}

async function handleSendClick(event, cfg) {
  const button = event.currentTarget;
  console.log("[OA] Send button click intercepted", button);
  if (button.dataset[BYPASS_FLAG]) {
    delete button.dataset[BYPASS_FLAG];
    console.log("[OA] this is our own re-dispatched click - letting it through");
    return; // let this one through, it's our own re-dispatched click
  }

  let quotationText = getLastQuotationText();
  if (!quotationText && cfg.quotationTextSelector) {
    const textEl = document.querySelector(cfg.quotationTextSelector);
    quotationText = (textEl?.innerText || textEl?.value || "").trim();
  }
  console.log("[OA] quotationText:", JSON.stringify(quotationText));
  if (!quotationText) {
    console.log("[OA] no quotation text at all - letting the click through unmodified");
    return; // nothing to match against - don't block sending
  }

  event.preventDefault();
  event.stopImmediatePropagation();
  console.log("[OA] blocked the original click, asking background for a match…");

  let result;
  try {
    result = await chrome.runtime.sendMessage({ type: "FIND_MATCH", quotationText });
    console.log("[OA] FIND_MATCH result:", result);
  } catch (e) {
    console.log("[OA] FIND_MATCH threw, failing open:", e);
    resendClick(button); // extension error - fail open, let the send through
    return;
  }
  if (!result?.ok || !result.matches?.length || result.matches[0].score < result.threshold) {
    console.log("[OA] no confident match - sending normally, no banner");
    resendClick(button); // no confident match - send as normal, no nagging
    return;
  }
  console.log("[OA] confident match found, showing banner:", result.matches[0]);

  const match = result.matches[0];
  showBanner({
    match,
    onCancel: () => {}, // user cancelled - do nothing, don't send
    onSkip: () => resendClick(button),
    onAttach: async () => {
      const fileInput = cfg.fileInputSelector ? document.querySelector(cfg.fileInputSelector) : null;
      if (!fileInput) {
        // No attach input found on this page - can't inject. Download it for
        // manual attach instead of silently dropping the recommendation.
        const dl = await chrome.runtime.sendMessage({ type: "DOWNLOAD_MATCH", fileId: match.id });
        if (dl?.ok) {
          const url = URL.createObjectURL(dl.blob);
          const a = document.createElement("a");
          a.href = url; a.download = dl.name; a.click();
          URL.revokeObjectURL(url);
        }
        resendClick(button);
        return;
      }
      const dl = await chrome.runtime.sendMessage({ type: "DOWNLOAD_MATCH", fileId: match.id });
      if (dl?.ok) {
        const file = new File([dl.blob], dl.name, { type: dl.mimeType });
        await injectFileIntoInput(fileInput, file);
      }
      resendClick(button);
    },
  });
}

function bindSendButton(cfg) {
  if (!cfg.sendButtonSelector) return;
  const found = document.querySelectorAll(cfg.sendButtonSelector);
  let newlyBound = 0;
  found.forEach((button) => {
    if (boundButtons.has(button)) return;
    boundButtons.add(button);
    newlyBound += 1;
    button.addEventListener("click", (e) => handleSendClick(e, cfg), { capture: true });
  });
  if (newlyBound > 0) {
    console.log(`[OA] bound click listener to ${newlyBound} new button(s) (${found.length} total match the selector right now)`);
  }
}

(async function init() {
  // DOM-based marker (not a JS global) so the popup's diagnostic can confirm
  // this script actually ran, regardless of which JS "world" reads it from.
  document.documentElement.dataset.oaContentLoaded = "1";

  const cfg = await getConfig();
  if (!cfg.sendButtonSelector) return; // not configured - stay inactive

  bindSendButton(cfg);
  // OrderAssist is presumably a SPA - the Send button may render after this
  // script runs, or re-render on navigation. Keep watching for it.
  const observer = new MutationObserver(() => bindSendButton(cfg));
  observer.observe(document.body, { childList: true, subtree: true });
})();
