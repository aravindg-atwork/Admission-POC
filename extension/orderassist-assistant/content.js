/**
 * Runs on the OrderAssist quotation page (isolated world - separate JS realm
 * from the page's own scripts). Intercepts the Send click, asks the
 * background worker whether a Drive catalogue item matches this quotation,
 * and - if the user agrees - injects that file into the page's own
 * attachment input AND an AI-generated contextual note into the email body
 * before letting the original Send action continue. This never touches
 * OrderAssist's backend: it only adds items to existing form fields, then
 * lets OrderAssist's existing send logic run.
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
 * Auto-detect Email Body:
 * The extension never asks for an email compose-area selector. Instead it
 * probes the DOM for the most likely rich-text compose element at injection
 * time: [contenteditable="true"] divs, div[role="textbox"], .ql-editor,
 * .fr-view, or finally a <textarea> with significant area. This makes it a
 * true zero-config AI overlay - it works on any email compose area without
 * per-deployment setup.
 *
 * If no Send button selector is configured in the popup, this script does
 * nothing at all - fails open, never blocks a real send.
 */

const BYPASS_FLAG = "oaAssistantBypass";
const boundButtons = new WeakSet();
// The FIND_MATCH round trip takes a moment, and nothing visibly happens
// during it - a rep who doesn't see instant feedback will often click Send
// again. Without this guard, that second click starts a fully independent
// match/attach cycle in parallel with the first, which can end up
// dispatching two real sends. Tracks which buttons currently have a cycle
// in flight so extra clicks are swallowed instead.
const pendingButtons = new WeakSet();

function getLastQuotationText() {
  return (document.documentElement.dataset.oaLastCapturedText || "").trim();
}

// Per-product-line strings captured by interceptor.js, so a quotation with
// several distinct products can be matched against the catalogue line-by-line
// (see match_lines on the backend) instead of only ever as one merged blob.
function getLastQuotationLines() {
  try {
    const raw = document.documentElement.dataset.oaLastCapturedLines;
    const lines = raw ? JSON.parse(raw) : [];
    return Array.isArray(lines) ? lines.filter(Boolean) : [];
  } catch {
    return [];
  }
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function getConfig() {
  return chrome.storage.local.get([
    "quotationTextSelector", "sendButtonSelector", "fileInputSelector",
    "injectNoteOnAttach", "injectNoteOnSkip",
  ]);
}

function findBanner() {
  return document.getElementById("oa-assistant-host");
}

function removeBanner() {
  const host = findBanner();
  if (host) host.remove();
}

// Shown the instant a click is intercepted, before the FIND_MATCH round trip
// resolves, so there's immediate visible feedback instead of an apparent
// dead click - see the pendingButtons comment above for why that matters.
function showLoadingBanner() {
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
        padding:14px 16px; width:220px; color:#5b6572; display:flex; align-items:center; gap:10px; }
      .spinner { width:14px; height:14px; border:2px solid #d8dee5; border-top-color:#1a7f4e;
        border-radius:50%; animation:spin .6s linear infinite; flex-shrink:0; }
      @keyframes spin { to { transform:rotate(360deg); } }
    </style>
    <div class="card"><span class="spinner"></span>Checking catalogue…</div>
  `;
}

function showBanner({ matches, onAttach, onSkip, onCancel }) {
  removeBanner();
  const host = document.createElement("div");
  host.id = "oa-assistant-host";
  host.style.cssText = "position:fixed;top:20px;right:20px;z-index:2147483647;";
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: "open" });

  const many = matches.length > 1;
  // All start selected (matches prior "attach everything" behavior by
  // default) - unchecking lets the rep leave one out before attaching.
  const selected = new Set(matches.map((_, i) => i));
  const matchRows = matches
    .map((m, i) => {
      // Complementary suggestions (see catalogue.suggest_complementary on the
      // backend) carry a synthetic score, not a real similarity percentage -
      // label them by what they are instead of a misleading "50% match".
      const label = m.matchType === "complementary"
        ? "often paired with this order"
        : `${Math.round(m.score * 100)}% match`;
      const previewLink = m.webViewLink
        ? `<a href="${escapeHtml(m.webViewLink)}" target="_blank" rel="noopener noreferrer">Preview</a>`
        : "";
      return `
        <div class="match">
          <input type="checkbox" class="match-check" id="oa-check-${i}" data-idx="${i}" checked />
          <label for="oa-check-${i}"><b>${escapeHtml(m.name)}</b>${label}</label>
          ${previewLink}
        </div>`;
    })
    .join("");

  root.innerHTML = `
    <style>
      .card { font: 14px/1.4 -apple-system, Segoe UI, Arial, sans-serif; background:#fff;
        border:1px solid #d8dee5; border-radius:12px; box-shadow:0 8px 28px rgba(0,0,0,.18);
        padding:16px; width:300px; color:#1a1f27; }
      .title { font-weight:600; margin-bottom:4px; }
      .sub { color:#5b6572; font-size:12.5px; margin-bottom:10px; }
      .match { background:#f3f6f4; border:1px solid #e1e7e3; border-radius:8px; padding:8px 10px;
        font-size:13px; margin-bottom:6px; display:flex; align-items:center; gap:8px; }
      .match:last-of-type { margin-bottom:12px; }
      .match input[type="checkbox"] { flex-shrink:0; margin:0; }
      .match label { flex:1; min-width:0; cursor:pointer; }
      .match label b { display:block; }
      .match a { flex-shrink:0; color:#1a7f4e; font-size:12px; font-weight:600; text-decoration:none; }
      .match a:hover { text-decoration:underline; }
      .row { display:flex; gap:8px; }
      button { font:inherit; font-size:13px; font-weight:500; padding:8px 10px; border-radius:8px;
        border:1px solid #d8dee5; background:#f3f4f6; cursor:pointer; flex:1; }
      button.primary { background:#1a7f4e; border-color:#1a7f4e; color:#fff; }
      button.text { border:none; background:none; color:#5b6572; flex:0; }
      .spinner { display:inline-block; width:12px; height:12px; border:2px solid #fff;
        border-top-color:transparent; border-radius:50%; animation:spin .6s linear infinite;
        vertical-align:middle; margin-right:4px; }
      @keyframes spin { to { transform:rotate(360deg); } }
    </style>
    <div class="card">
      <div class="title">Matching brochure${many ? "s" : ""} found</div>
      <div class="sub">This quotation looks like it matches ${many ? "these catalogue items" : "a catalogue item"}${many ? " - pick which to attach" : ""}.</div>
      ${matchRows}
      <div class="row">
        <button class="text" id="oa-cancel">Cancel</button>
        <button id="oa-skip">Send without ${many ? "them" : "it"}</button>
        <button class="primary" id="oa-attach">Attach ${many ? "selected" : ""} &amp; send</button>
      </div>
    </div>
  `;

  root.addEventListener("change", (e) => {
    if (!e.target.classList.contains("match-check")) return;
    const idx = Number(e.target.dataset.idx);
    if (e.target.checked) selected.add(idx);
    else selected.delete(idx);
  });

  root.getElementById("oa-attach").addEventListener("click", () => {
    const chosen = matches.filter((_, i) => selected.has(i));
    removeBanner();
    onAttach(chosen);
  });
  root.getElementById("oa-skip").addEventListener("click", () => { removeBanner(); onSkip(); });
  root.getElementById("oa-cancel").addEventListener("click", () => { removeBanner(); onCancel(); });
}

// `button` is the node captured at the original click - if OrderAssist's SPA
// re-rendered the Send button while we awaited the match/attach/note round
// trip, that node may already be detached and clicking it would do nothing
// (the send would silently never happen). Re-query the live selector first.
// OrderAssist's own client-side validation (e.g. a required "To" field) can
// reject the resend and re-render the compose form from its own React
// state - which snaps a React-controlled rich-text body back to what React
// thinks it should contain, silently discarding whatever we injected via
// raw DOM. The plain file input isn't controlled the same way and survives
// that re-render, which is why the attachment sticks but the note vanishes.
// A single re-render doesn't seem to be the whole story - OrderAssist has
// been observed resetting the field again a couple of seconds after the
// first reset, presumably a second validation-error render pass. One
// delayed check isn't enough, so check repeatedly over a few seconds and
// re-inject each time it's missing (each fixed checkpoint, not an
// open-ended observer, so this can't turn into an infinite fight with
// React if something keeps clearing it).
function verifyNoteStuck(noteText) {
  if (!noteText) return;
  for (const delay of [600, 1500, 3000, 5000]) {
    setTimeout(() => {
      const bodyEl = autoDetectEmailBody();
      if (!bodyEl) return; // compose form is gone - either it sent, or navigated away, nothing to fix
      const currentText = bodyEl.value !== undefined ? bodyEl.value : (bodyEl.textContent || "");
      if (!currentText.includes(noteText.slice(0, 30))) {
        console.log(`[OA] note missing ${delay}ms after resend (native validation likely rejected the send) - re-injecting`);
        injectNoteIntoEmail(noteText);
      }
    }, delay);
  }
}

function resendClick(button, cfg) {
  pendingButtons.delete(button);
  const live = button.isConnected ? button : findSendButtons(cfg)[0];
  if (!live) {
    console.log("[OA] send button is gone and re-query found nothing - cannot resend");
    return;
  }
  live.dataset[BYPASS_FLAG] = "1";
  live.click();
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

/**
 * Auto-detect the email compose body element on the page.
 *
 * Strategy (in priority order):
 * 1. Largest [contenteditable="true"] div (rich text editors like Quill, TinyMCE, etc.)
 * 2. div[role="textbox"] (ARIA textbox pattern)
 * 3. .ql-editor (Quill.js specific)
 * 4. .fr-view (Froala editor specific)
 * 5. Largest <textarea> on the page
 * 6. Any input[type="text"] with significant size
 *
 * Returns the element or null.
 */
// Rich-text libraries (Draft.js, Slate, measurement mirrors, etc.) routinely
// keep extra contenteditable/textbox nodes in the DOM that are hidden or
// pushed off-screen rather than removed. getBoundingClientRect() still
// reports real, sometimes large, dimensions for those - which previously let
// them out-score the actual visible compose box and "successfully" receive a
// note nobody could ever see. Require an on-screen, visible rect for every
// candidate type, not just textareas.
function isVisibleForInjection(el) {
  if (el.offsetParent === null && getComputedStyle(el).position !== "fixed") return false;
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return false;
  if (rect.bottom <= 0 || rect.right <= 0) return false;
  if (rect.top >= window.innerHeight || rect.left >= window.innerWidth) return false;
  const style = getComputedStyle(el);
  return style.visibility !== "hidden" && style.display !== "none";
}

function autoDetectEmailBody() {
  const selectorsByPriority = [
    { selector: 'div[contenteditable="true"]', type: "contenteditable", priority: 0 },
    { selector: 'div[role="textbox"]', type: "textbox", priority: 1 },
    { selector: ".ql-editor", type: "quill", priority: 2 },
    { selector: ".fr-view", type: "froala", priority: 3 },
    { selector: "textarea", type: "textarea", priority: 4, minArea: 1000 },
  ];

  const candidates = [];
  for (const { selector, type, priority, minArea } of selectorsByPriority) {
    document.querySelectorAll(selector).forEach((el) => {
      if (!isVisibleForInjection(el)) return;
      const rect = el.getBoundingClientRect();
      const area = rect.width * rect.height;
      if (minArea && area < minArea) return;
      candidates.push({ el, area, type, priority });
    });
  }

  if (candidates.length === 0) return null;

  // Sort by priority first (lower number = higher priority), then by area descending
  candidates.sort((a, b) => a.priority - b.priority || b.area - a.area);
  return candidates[0].el;
}

/**
 * Inject a note into the email body without breaking existing content.
 *
 * For contenteditable divs: append a <br><br> + paragraph with the note.
 * For textareas/inputs: append \n\n + note.
 */
function injectNoteIntoEmail(noteText) {
  const bodyEl = autoDetectEmailBody();
  if (!bodyEl) {
    console.log("[OA] could not auto-detect email body element - note not injected");
    return false;
  }

  const isContentEditable = bodyEl.isContentEditable ||
    bodyEl.getAttribute("contenteditable") === "true" ||
    bodyEl.classList.contains("ql-editor") ||
    bodyEl.classList.contains("fr-view") ||
    bodyEl.getAttribute("role") === "textbox";

  if (isContentEditable) {
    // Rich text editor — append as HTML preserving existing content
    bodyEl.focus();
    // Move cursor to end
    const sel = window.getSelection();
    if (sel) {
      const range = document.createRange();
      range.selectNodeContents(bodyEl);
      range.collapse(false); // collapse to end
      sel.removeAllRanges();
      sel.addRange(range);
    }
    // Insert two line breaks + the note
    document.execCommand("insertHTML", false, `<br><br><p>${noteText}</p>`);
    console.log("[OA] note injected into contenteditable element");
    return true;
  }

  // Plain text input/textarea — append text
  const text = bodyEl.value || bodyEl.textContent || "";
  if (bodyEl.value !== undefined) {
    bodyEl.value = text + "\n\n" + noteText;
  } else {
    bodyEl.textContent = text + "\n\n" + noteText;
  }
  // Trigger change event so the framework picks it up
  bodyEl.dispatchEvent(new Event("input", { bubbles: true }));
  bodyEl.dispatchEvent(new Event("change", { bubbles: true }));
  console.log("[OA] note injected into textarea/input");
  return true;
}

async function handleSendClick(event, cfg) {
  const button = event.currentTarget;
  console.log("[OA] Send button click intercepted", button);
  if (button.dataset[BYPASS_FLAG]) {
    delete button.dataset[BYPASS_FLAG];
    console.log("[OA] this is our own re-dispatched click - letting it through");
    return; // let this one through, it's our own re-dispatched click
  }
  if (pendingButtons.has(button)) {
    console.log("[OA] a match request is already in flight for this button - ignoring extra click");
    event.preventDefault();
    event.stopImmediatePropagation();
    return;
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
  pendingButtons.add(button);
  showLoadingBanner();

  // One entry per distinct product line on the quotation, so a proposal
  // covering several products can be matched (and attached) against more
  // than one catalogue item instead of only ever the single best match.
  const quotationLines = getLastQuotationLines();

  let result;
  try {
    result = await chrome.runtime.sendMessage({ type: "FIND_MATCH", quotationText, quotationLines });
    console.log("[OA] FIND_MATCH result:", result);
  } catch (e) {
    console.log("[OA] FIND_MATCH threw, failing open:", e);
    removeBanner();
    resendClick(button, cfg); // extension error - fail open, let the send through
    return;
  }
  if (!result?.ok) {
    console.log("[OA] FIND_MATCH failed - sending normally, no banner:", result?.error);
    removeBanner();
    resendClick(button, cfg);
    return;
  }
  // Cap how many brochures we'll ever offer at once - a quotation with many
  // product lines shouldn't turn into an email with a dozen attachments.
  // Complementary suggestions carry a synthetic score (see
  // catalogue.suggest_complementary), already capped server-side to at most
  // 2 - the match threshold doesn't apply to them, they're kept unconditionally.
  const confidentMatches = (result.matches || [])
    .filter((m) => m.matchType === "complementary" || m.score >= result.threshold)
    .slice(0, 4);
  if (confidentMatches.length === 0) {
    console.log("[OA] no confident match - sending normally, no banner");
    removeBanner();
    resendClick(button, cfg); // no confident match - send as normal, no nagging
    return;
  }
  console.log("[OA] confident match(es) found, showing banner:", confidentMatches);

  showBanner({
    matches: confidentMatches,
    onCancel: () => { pendingButtons.delete(button); }, // user cancelled - do nothing, don't send
    onSkip: async () => {
      // Optionally inject a note on skip too (configurable)
      let noteText = "";
      if (cfg.injectNoteOnSkip) {
        try {
          const noteResult = await chrome.runtime.sendMessage({
            type: "GENERATE_NOTE",
            quotationText,
            matchedItems: confidentMatches.map((m) => ({ name: m.name, description: m.description || "" })),
          });
          if (noteResult?.ok && noteResult.note) {
            noteText = noteResult.note;
            injectNoteIntoEmail(noteText);
          }
        } catch (e) {
          console.log("[OA] note generation failed on skip, continuing:", e.message);
        }
      }
      resendClick(button, cfg);
      verifyNoteStuck(noteText);
    },
    onAttach: async (chosenMatches) => {
      // The banner lets the rep uncheck individual suggestions before
      // attaching - chosenMatches is whatever was still checked when they
      // clicked "Attach & send", not necessarily all of confidentMatches.
      if (chosenMatches.length === 0) {
        console.log("[OA] nothing selected in the banner - sending without attachments");
        resendClick(button, cfg);
        return;
      }

      // Note generation (an LLM call) and file downloads (Drive API calls)
      // are independent - kick both off together instead of waiting on the
      // note before even starting to download, so the two waits overlap
      // instead of stacking on top of each other.
      const notePromise = cfg.injectNoteOnAttach !== false
        ? chrome.runtime.sendMessage({
            type: "GENERATE_NOTE",
            quotationText,
            matchedItems: chosenMatches.map((m) => ({ name: m.name, description: m.description || "" })),
          }).catch((e) => {
            console.log("[OA] note generation failed, continuing with attach:", e.message);
            return null;
          })
        : Promise.resolve(null);

      const downloadsPromise = Promise.all(
        chosenMatches.map((match) => chrome.runtime.sendMessage({ type: "DOWNLOAD_MATCH", fileId: match.id }))
      );

      const [noteResult, downloads] = await Promise.all([notePromise, downloadsPromise]);

      let noteText = "";
      if (noteResult?.ok && noteResult.note) {
        noteText = noteResult.note;
        injectNoteIntoEmail(noteText);
      }

      // Injecting into the file input has to stay sequential - each
      // injection reads the input's current file list to preserve what's
      // already there, so doing it concurrently would race and drop files.
      // The slow part (downloading the bytes) already happened in parallel
      // above; this loop is just fast synchronous DOM work.
      const fileInput = findFileInput(cfg);
      for (const dl of downloads) {
        if (!dl?.ok) continue;
        if (fileInput) {
          const file = new File([dl.blob], dl.name, { type: dl.mimeType });
          await injectFileIntoInput(fileInput, file);
        } else {
          // No attach input found on this page - can't inject. Download it
          // for manual attach instead of silently dropping the recommendation.
          const url = URL.createObjectURL(dl.blob);
          const a = document.createElement("a");
          a.href = url; a.download = dl.name; a.click();
          URL.revokeObjectURL(url);
        }
      }
      resendClick(button, cfg);
      verifyNoteStuck(noteText);
    },
  });
}

const SEND_TEXT_RE = /\bsend\b/i;
const SUBMIT_TEXT_RE = /\bsubmit\b/i;
const NEGATIVE_TEXT_RE = /\b(cancel|draft|delete|close|back|discard)\b/i;

function visibleRect(el) {
  if (el.offsetParent === null && el !== document.body) return null;
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return null;
  return rect;
}

/**
 * DOM heuristic for the Send/Submit button, used whenever no admin-configured
 * selector is set (or the configured one no longer matches anything - e.g.
 * after a page redesign). Same idea as autoDetectEmailBody() below: scan for
 * plausible candidates and score them instead of requiring exact per-site
 * config.
 */
function autoDetectSendButton() {
  const candidates = [];
  document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"], a[class*="btn"]').forEach((el) => {
    if (el.disabled) return;
    if (!visibleRect(el)) return;
    const text = (el.innerText || el.value || el.getAttribute("aria-label") || "").trim();
    if (!text || NEGATIVE_TEXT_RE.test(text)) return;
    let score;
    if (SEND_TEXT_RE.test(text)) score = 10;
    else if (SUBMIT_TEXT_RE.test(text)) score = 5;
    else return; // doesn't look like a send/submit action at all
    score -= Math.min(text.length, 40) * 0.05; // prefer terse "Send" over a long sentence containing it
    if (/primary|btn-add-roles|btn-global/i.test(el.className)) score += 1;
    candidates.push({ el, score });
  });
  if (candidates.length === 0) return null;
  candidates.sort((a, b) => b.score - a.score);
  return candidates[0].el;
}

/**
 * DOM heuristic for the attachment file input, same fallback role as
 * autoDetectSendButton() above. File inputs are commonly visually hidden
 * (styled via a label/button), so - unlike the button heuristic - visibility
 * isn't required, just that it exists and isn't disabled.
 */
function autoDetectFileInput() {
  const inputs = Array.from(document.querySelectorAll('input[type="file"]')).filter((el) => !el.disabled);
  if (inputs.length === 0) return null;
  if (inputs.length === 1) return inputs[0];
  const scored = inputs.map((el) => {
    const accept = (el.getAttribute("accept") || "").toLowerCase();
    let score = 0;
    if (/pdf|jpg|jpeg|png|image|document/.test(accept)) score += 5;
    if (el.multiple) score += 1;
    return { el, score };
  });
  scored.sort((a, b) => b.score - a.score);
  return scored[0].el;
}

// Try the admin-configured selector first (it's cheap and exact when it's
// right); fall back to the DOM heuristic when it's unset or stops matching.
function findSendButtons(cfg) {
  if (cfg.sendButtonSelector) {
    const found = document.querySelectorAll(cfg.sendButtonSelector);
    if (found.length > 0) return Array.from(found);
  }
  const auto = autoDetectSendButton();
  return auto ? [auto] : [];
}

function findFileInput(cfg) {
  if (cfg.fileInputSelector) {
    const found = document.querySelector(cfg.fileInputSelector);
    if (found) return found;
  }
  return autoDetectFileInput();
}

function bindSendButton(cfg) {
  const found = findSendButtons(cfg);
  let newlyBound = 0;
  found.forEach((button) => {
    if (boundButtons.has(button)) return;
    boundButtons.add(button);
    newlyBound += 1;
    button.addEventListener("click", (e) => handleSendClick(e, cfg), { capture: true });
  });
  if (newlyBound > 0) {
    console.log(`[OA] bound click listener to ${newlyBound} new button(s) (${found.length} total found right now)`);
  }
}

(async function init() {
  // DOM-based marker (not a JS global) so the popup's diagnostic can confirm
  // this script actually ran, regardless of which JS "world" reads it from.
  document.documentElement.dataset.oaContentLoaded = "1";

  const cfg = await getConfig();

  bindSendButton(cfg);
  // OrderAssist is presumably a SPA - the Send button may render after this
  // script runs, or re-render on navigation. Keep watching for it.
  const observer = new MutationObserver(() => bindSendButton(cfg));
  observer.observe(document.body, { childList: true, subtree: true });
})();
