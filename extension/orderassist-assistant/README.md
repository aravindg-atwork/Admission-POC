# OrderAssist Catalogue Assistant — POC

When a sales rep is about to send a proposal in OrderAssist, this extension
checks a Google Drive folder of brochures/templates, and if one matches,
offers to attach it before the existing Send button runs — so the email that
goes out (still sent by OrderAssist itself) carries both files.

## What's real vs. still a placeholder

This was built against OrderAssist's actual source
(`C:\Users\Admin\Desktop\orderassist`), not guessed:

- **Quotation content** (`interceptor.js`): OrderAssist's proposal page
  (`/view_proposal/:id`) loads its data via a React Router loader that calls
  `GET /view_proposal/<id>.json` (see
  `app/assets/javascripts/webpack/services/AuthLayoutService.js`), returning
  `{ proposal: {...}, proposal_items: [{ product_name, quantity, ... }] }`
  (shape confirmed from `ProposalShow.test.js`'s own mock data). `interceptor.js`
  runs in the page's own JS world and patches `fetch`/`XMLHttpRequest` to read
  that exact response — real structured data, not scraped text, and it
  survives redesigns as long as the API shape doesn't change. **No
  per-deployment configuration needed for this part.**
- **Send button** (`.btn-global.btn-add-roles`) and **attachment input**
  (`input[type="file"][accept=".pdf,.jpg,.jpeg"]`): both found in
  `SendEmailForm.js`. That file input is a real, already-shipped
  "Add Additional Attachments" feature — `SendProposal.js` posts to
  `/send_proposal/:id` with `additional_attachments[]` already in its
  multipart payload. The extension isn't hacking anything in; it's using a
  feature OrderAssist already built for this exact purpose. Only caveat:
  that input enforces PDF/JPEG under 2MB client-side, so catalogue brochures
  need to meet that.
- **Where it activates**: the manifest matches the OrderAssist origin
  (`https://app.orderassist.in/*`), not just the `/view_proposal/*` path.
  This has to be the whole origin, not the proposal path alone: OrderAssist
  is a SPA, so Chrome only ever injects a manifest-declared content script on
  a real top-level page load, never on the in-app `history.pushState`
  navigation that happens when a rep clicks into a quotation from a list. If
  `matches` were scoped to `/view_proposal/*` only, the script would stay
  uninjected for the rest of the tab's life whenever the session's first real
  page load landed somewhere else (a dashboard, a login page) - which is the
  common case. Matching the whole origin means it loads on whichever page the
  session actually starts on, then keeps running (via the fetch patch and a
  MutationObserver) across every subsequent in-app route change without
  needing to be re-injected. The tradeoff: pointing this at a different
  OrderAssist deployment (staging, a different customer's subdomain,
  localhost) now means editing this one pattern in `manifest.json` - it's no
  longer domain-agnostic the way path-only matching was intended to be.
- **Still needs you**: a real Google Cloud OAuth client for Drive access
  (`manifest.json`'s `oauth2.client_id` placeholder), and a real Drive folder
  ID of brochures. There's no way around that setup existing somewhere - it's
  a one-time step, not per-page config.

## Why screenshot/OCR isn't used here

The quotation content already exists as real JSON from OrderAssist's own
API — reading that is strictly more reliable than rendering a screenshot and
OCR'ing text back out of it. And OCR wouldn't solve attachment either: even
with perfect text recognition, attaching a file still requires finding the
real `<input type=file>` DOM element (which is what `content.js` does) or
faking a full OS-level drag-and-drop, neither of which "seeing" the page
gets you closer to.

## Setup

1. **Google Cloud OAuth client** (one-time, needs your Google account):
   [console.cloud.google.com](https://console.cloud.google.com/) → APIs &
   Services → Credentials → **Create OAuth client ID** → type **Chrome
   Extension** → app ID = this extension's ID (visible at
   `chrome://extensions` once loaded, with Developer mode on). Enable the
   **Google Drive API**, add `drive.readonly` scope on the consent screen.
   Paste the client ID into `manifest.json`, reload the unpacked extension.

2. **Popup config** (click the toolbar icon):
   - Backend URL (e.g. `http://localhost:5050`)
   - Backend API key (generate in the admin console's *URL Generator* tab)
   - Drive catalogue folder ID (paste the full Drive folder URL - the popup
     extracts the ID automatically)
   - Send button selector: `.btn-global.btn-add-roles`
   - Attachment file input selector: `input[type="file"][accept=".pdf,.jpg,.jpeg"]`
   - Quotation text selector: leave blank - not needed on the real page

## Loading it

`chrome://extensions` → **Developer mode** → **Load unpacked** → select this
folder.

## Testing without the real OrderAssist page

`test-page.html` is a static stand-in with the same class names (but no real
`/view_proposal/:id.json` call, so `interceptor.js` has nothing to catch
there) - it exercises the click-interception, matching, and DOM-injection
logic using the CSS-selector fallback instead. See the main conversation
history / ask again for the exact steps if needed.

## Status

The matching backend (`backend/catalogue.py` + `/api/catalogue/match`) is
tested end-to-end. The extension's OAuth, Drive listing/download, network
interception, and DOM-injection logic are all real, runnable code, verified
against OrderAssist's actual source. What's left is the one-time Google OAuth
setup and a real end-to-end run against the live app (I can't launch or
click through OrderAssist myself from here).
