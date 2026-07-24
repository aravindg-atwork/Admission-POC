/**
 * Runs in the PAGE's own JS context (manifest "world": "MAIN"), not the
 * isolated content-script world - this is required to patch window.fetch /
 * XMLHttpRequest so it sees the same responses the page's own React code
 * does. content.js (isolated world) can't touch window.fetch directly since
 * it runs in a separate JS realm from the page.
 *
 * OrderAssist's proposal page loads its data via React Router's loader,
 * which does `axios.get('/view_proposal/<id>.json')` before rendering
 * (see AuthLayoutService.js's authLayoutLoader). That response already has
 * exactly what we need to match against the Drive catalogue -
 * proposal_items[].product_name - as real structured data, not scraped
 * text. Reading the network response here is far more robust than a CSS
 * selector: it survives redesigns as long as the API contract doesn't
 * change, and needs no per-deployment configuration at all.
 */

(function () {
  const PROPOSAL_JSON_RE = /\/view_proposal\/\d+\.json(?:\?|$)/;

  // DOM-based markers (not JS globals) so the popup's diagnostic - which
  // reads via the isolated world, a separate JS realm from this MAIN-world
  // script - can still confirm this ran and see what it last captured. The
  // DOM itself is shared across worlds even though JS variables aren't.
  document.documentElement.dataset.oaInterceptorLoaded = "1";

  function extractQuotationText(data) {
    const items = data?.proposal_items || [];
    const productLine = items
      .map((item) => (item.quantity ? `${item.product_name} x${item.quantity}` : item.product_name))
      .filter(Boolean)
      .join(", ");
    const customerName = data?.proposal?.customer_name || "";
    return [customerName, productLine].filter(Boolean).join(" - ");
  }

  function publish(data) {
    const quotationText = extractQuotationText(data);
    document.documentElement.dataset.oaLastCapturedRaw = JSON.stringify(data).slice(0, 300);
    if (!quotationText) return;
    // A DOM attribute, not window.postMessage: content.js runs later
    // (document_idle vs. this script's document_start) and reads this
    // directly whenever it needs it, so there's no race to miss.
    document.documentElement.dataset.oaLastCapturedText = quotationText;
  }

  // fetch()
  const originalFetch = window.fetch;
  window.fetch = function (...args) {
    const url = typeof args[0] === "string" ? args[0] : args[0]?.url;
    const result = originalFetch.apply(this, args);
    if (url && PROPOSAL_JSON_RE.test(url)) {
      result.then((res) => res.clone().json()).then(publish).catch(() => {});
    }
    return result;
  };

  // XMLHttpRequest (axios can use either adapter depending on environment)
  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__oaAssistantUrl = url;
    return originalOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    if (this.__oaAssistantUrl && PROPOSAL_JSON_RE.test(this.__oaAssistantUrl)) {
      this.addEventListener("load", () => {
        try { publish(JSON.parse(this.responseText)); } catch { /* not JSON or not our shape */ }
      });
    }
    return originalSend.apply(this, args);
  };
})();
