# MAFSU MITRA widget — developer handoff

Version: Beta, 21 August 2026  
Integration target: existing MAFSU WebForms / HTML / jQuery website  
Frontend owner after handoff: MAFSU website developer  
Backend owner: MAFSU MITRA API team

## 1. What is included

| File | Purpose |
|---|---|
| `index.html` | Standalone working demo and the canonical widget markup |
| `mafsu-admissions-widget.css` | Fully namespaced widget styles |
| `mafsu-admissions-widget.js` | jQuery chat, guided options, health, programme, language and microphone behaviour |
| `MitraProxy.ashx` | Isolated ASP.NET relay for UAT; no IIS ARR or web.config edit |
| `MAFSU_LOGO.jpg` | Official logo displayed in the widget header |
| `README.md` | Short integration notes |
| `MAFSU_DEVELOPER_HANDOFF.md` | Complete integration and API contract |

The package does not require React, a bundler, npm, or changes to the existing
WebForms application. All widget CSS classes begin with `mafsu-chat` to reduce
collisions with the MAFSU website.

## 2. Production integration

1. Copy the CSS, JavaScript, logo and `MitraProxy.ashx` into the MAFSU test-site folders.
2. Copy only the `<div id="mafsu-admissions-widget">...</div>` block from
   `index.html` into the shared WebForms `.Master` page immediately before
   `</body>`.
3. Add the CSS link in `<head>`.
4. Load jQuery first, then load `mafsu-admissions-widget.js` near `</body>`.
5. Ensure the widget exists only once on a page.

Example paths—the MAFSU developer may change them:

```html
<link rel="stylesheet" href="/assets/mafsu-mitra/mafsu-admissions-widget.css">

<!-- Widget markup copied from index.html goes here. -->

<script src="/Scripts/jquery-3.7.1.min.js"></script>
<script src="/assets/mafsu-mitra/mafsu-admissions-widget.js"></script>
```

The current JavaScript uses delegated jQuery events, `$.ajax`, `.prop()` and
`.data()`. jQuery 3.7.1 is recommended. If the website already supplies jQuery,
do not load a second copy.

## 3. Required API arrangement

The official MAFSU site is expected to use HTTPS. It must not call the current
plain-HTTP IP directly because browsers block HTTPS-to-HTTP mixed content.

The preferred production arrangement is a same-origin reverse proxy:

```text
Student browser
    -> https://admissions.mafsu.ac.in/test_site/MitraProxy.ashx?endpoint=chat
    -> isolated ASP.NET handler
    -> MAFSU MITRA backend /api/chat
```

For isolated UAT, use the supplied handler URLs:

```html
<div id="mafsu-admissions-widget"
     class="mafsu-chat"
     data-api-base=""
     data-chat-url="/test_site/MitraProxy.ashx?endpoint=chat"
     data-health-url="/test_site/MitraProxy.ashx?endpoint=healthz"
     data-default-language="en">
```

Before deployment, the MAFSU developer must give the backend team the final
HTTPS origin/domain. The backend CORS allow-list and reverse proxy will then be
configured for that exact origin. Do not place an API secret in the HTML or
JavaScript; anything shipped to a browser is public.

### Code-only UAT relay — recommended

Upload `MitraProxy.ashx` into the physical `/test_site/` folder. It has a fixed
upstream and forwards only `GET healthz` and `POST chat`; it cannot proxy an
arbitrary URL or any admin endpoint. No IIS Manager, ARR installation, root
route or `web.config` edit is required. Rollback is deleting this one file.

Before adding the widget, open:

```text
https://admissions.mafsu.ac.in/test_site/MitraProxy.ashx?endpoint=healthz
```

It must return 200 JSON. A 404 means the handler was not uploaded; a 502 means
the IIS server cannot reach the MITRA host. Only after this check passes should
the widget be added to one test page.

### Optional IIS ARR alternative — not required for UAT

If the IIS administrator later prefers native proxying, the test site is `https://admissions.mafsu.ac.in/test_site/dashboard/index.aspx`.
Install/enable **IIS URL Rewrite** and **Application Request Routing (ARR)**,
then have the IIS administrator enable proxying. Back up `test_site/web.config`
and merge this rule only into that test application's
`<system.webServer><rewrite><rules>` section:

```xml
<rule name="MAFSU MITRA Isolated UAT API" stopProcessing="true">
  <match url="^mitra/api/(chat|healthz)$" ignoreCase="true" />
  <action type="Rewrite"
          url="http://159.69.210.30/api/{R:1}"
          appendQueryString="true" />
</rule>
```

Only `chat` and `healthz` are proxied. Do **not** proxy `/api/admin/`.
Configure an ARR request timeout of at least 120 seconds. If IIS administrators
allow these server variables, forward the original values as
`X-Real-IP={REMOTE_ADDR}` and `X-Forwarded-Proto=https`; the backend uses the
real client IP for per-student rate limiting.

After the rule is installed, both checks must pass without redirects:

```text
GET  https://admissions.mafsu.ac.in/test_site/mitra/api/healthz -> 200 JSON
POST https://admissions.mafsu.ac.in/test_site/mitra/api/chat    -> 200 JSON
```

The UAT widget must keep `data-api-base="/test_site/mitra"`. A 404 from the
isolated health URL means the proxy rule is not installed yet. Rollback is to
remove this one rule or restore the backed-up test-site `web.config`.
After acceptance, restrict the MITRA host firewall so public port 80 accepts
connections only from the MAFSU IIS server's egress IP.


## 4. Live endpoints

### GET `/api/healthz`

Purpose: availability check for the launcher status dot.

Successful response:

```json
{
  "status": "ok",
  "uptimeSeconds": 125.4
}
```

The widget checks this endpoint when loaded and every 30 seconds. The dot is:

- amber while checking;
- green only after a successful health response;
- red when the API is unreachable.

This is an availability indicator, not a guarantee that an external model
provider will answer every generation request.

### POST `/api/chat`

Content type: `application/json; charset=utf-8`

Request:

```json
{
  "question": "I have 48% and qualified NEET. Can I apply for B.V.Sc.?",
  "uiLanguage": "en",
  "projectId": "bvsc",
  "conversationState": {},
  "sessionId": null
}
```

Request fields:

| Field | Allowed value | Notes |
|---|---|---|
| `question` | Non-empty string, maximum 1200 characters | Student's current message |
| `uiLanguage` | `en`, `hi`, or `mr` | Requested response language |
| `projectId` | `bvsc`, `bfsc`, or `btech-dairy` | Current programme; explicit names in the question may override it |
| `conversationState` | JSON object, maximum 32 keys / 8 KiB | Guided interview state returned by earlier responses |
| `sessionId` | `null` or returned session identifier | Allows server-side transcript grouping |

Representative response:

```json
{
  "answer": "Yes—based on the details shared so far...",
  "source": "eligibility",
  "interviewField": null,
  "interviewOptions": [],
  "carryQuestion": null,
  "slotUpdate": {
    "programme": "bvsc"
  },
  "language": "en",
  "cacheHit": false,
  "projectId": "bvsc",
  "sessionId": "generated-session-id",
  "messageId": 123,
  "admissionYear": "2026-27",
  "decisionState": "eligible_so_far",
  "sourceTrace": {
    "programme": "bvsc",
    "admissionYear": "2026-27"
  }
}
```

Response-handling rules:

1. Render `answer` as text, never as HTML.
2. Treat returned `projectId` as authoritative and synchronize the visible
   programme selector.
3. Merge `slotUpdate` into the current `conversationState`.
4. Store the returned `sessionId` and send it with the next question.
5. Render `interviewOptions` as buttons. When a button is clicked, store its
   value using `interviewField` as the key and resend `carryQuestion`.
6. The response carries no prospectus page list, model id or policy rule ids.
   These exist server-side for review and evaluation, and are deliberately
   not part of a student-facing reply - do not display or reintroduce them.
7. Disable composer and programme controls while a request is in progress to
   prevent duplicate submissions.
8. The `EN / हिं / मर` buttons switch the whole interface, not only the answer
   language: labels, placeholder, safety notice, FAQ list and the question each
   shortcut sends. The greeting card beside the launcher is the one exception -
   it stays in English by design, because it appears before a visitor has
   chosen a language, and its own text names हिंदी and मराठी.

The supplied jQuery file already implements these rules.

### Direct HTTPS mode (once MITRA has its own domain)

When MITRA is reachable at its own HTTPS hostname, `MitraProxy.ashx` is no
longer required. Point the widget at the domain and drop in the site key:

```html
<div id="mafsu-admissions-widget" class="mafsu-chat"
     data-chat-url="https://mitra.mafsu.ac.in/api/chat"
     data-health-url="https://mitra.mafsu.ac.in/api/healthz"
     data-site-key="THE-KEY-WE-ISSUE">
```

No server-side change is needed - no ARR, no `web.config`, no handler. Two
things we need from you first: the exact origin(s) to allowlist, and whether
the site sends a `Content-Security-Policy` (if it does, add the MITRA host to
`connect-src` or the browser blocks the call regardless of the key).

The site key is **publishable**. It is visible in the page source by design: it
identifies the site, it does not authenticate it. The origin allowlist and the
per-client rate limit are what protect the endpoint, so there is no need to
hide the key or route it through a server. Keep `MitraProxy.ashx` in the
package as a fallback for the case where a proxy or CSP policy blocks direct
calls.

## 5. Programme and follow-up behaviour

- If a student explicitly names one programme, the backend routes to it and
  the selector follows the response.
- If a fresh programme-dependent question is ambiguous, the backend may return
  the three programme choices.
- Manual programme changes and **New chat** must clear previous guided state.
- Do not guess a state field from an option label or value. Always use the
  response's `interviewField`.
- The client-provided state is convenience state only. It must never be used as
  authentication, identity, or proof of eligibility.

## 6. Speech: STT and TTS status

### Speech-to-text (microphone): implemented

The microphone uses the browser's Web Speech API:

```javascript
window.SpeechRecognition || window.webkitSpeechRecognition
```

It does not call the MAFSU backend and does not consume LLM/model quota. It
requires browser support, microphone permission and normally an HTTPS page.
Unsupported browsers retain normal typed input.

### Text-to-speech: no backend API exists today

There is currently no `/api/tts` endpoint. The MAFSU developer must not call or
advertise one. If a read-aloud button is desired without backend cost, use the
browser's `speechSynthesis` API:

```javascript
function readMitraAnswer(text, language) {
  if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) return false;
  window.speechSynthesis.cancel();
  var utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = language === "hi" ? "hi-IN" : language === "mr" ? "mr-IN" : "en-IN";
  window.speechSynthesis.speak(utterance);
  return true;
}
```

Available voice quality depends on the student's operating system/browser. A
server-side TTS endpoint can be designed later only after provider, cost,
consent, caching and audio-retention decisions are approved.

## 7. Errors the UI must handle

| HTTP/status | Meaning | Student-facing behaviour |
|---|---|---|
| `200` | Valid API response | Render the returned answer |
| `400` | Disallowed CORS/preflight or invalid boundary request | Do not expose raw server details |
| `413` | Request body exceeds 16 KiB | Ask the student to shorten the message |
| `422` | Invalid field, language, programme, state or question | Show a concise validation message |
| `429` | Per-client rate limit reached | Ask the student to wait and retry; respect `Retry-After` |
| `5xx` | Temporary backend/provider failure | Preserve the student's question and offer Retry |
| Network timeout | API unavailable | Turn the status dot red and offer Retry |

The current chat timeout is 90 seconds because provider fallback may take time.
Do not silently remove or lose a student's typed question after failure.

## 8. Security requirements for the website developer

- Use only the official HTTPS MAFSU domain in production.
- Prefer same-origin `/api/*` proxying.
- Never embed an admin key, provider key or API secret in HTML/JavaScript.
- Render all server/user strings with `.text()` or `textContent`, never `.html()`.
- Keep the admin console outside this widget and outside public routing.
- Do not persist marks, caste/category details, certificates or transcripts in
  `localStorage`, cookies, analytics events or browser logs.
- Do not send conversation contents to third-party analytics.
- Keep the 1200-character client limit; the server independently enforces it.
- Keep controls disabled during requests to prevent accidental request floods.
- If the site has a Content Security Policy, allow only required assets. For a
  same-origin proxy, `connect-src 'self'` is sufficient.
- Restrict `img-src` to the site's own static assets for the supplied logo.
- Test keyboard focus, Escape-to-close and mobile layout after placing the
  widget inside the real master page.

The backend already applies scoped CORS, request/state bounds, rate limiting,
prompt-injection checks, security headers and public admin isolation. Browser
controls complement these protections; they do not replace them.

## 9. Cache, capacity and load-balancing ownership

These are backend responsibilities and must not be reimplemented in jQuery.

- The API currently has an exact-answer Redis cache and returns `cacheHit`.
- Deterministic policy/eligibility guards run before unsafe cached overrides.
- The browser must not cache admission answers as authoritative data.
- Model free-tier quotas and provider throttling remain capacity risks.
- Before full public launch, the backend team will add measured cache hit-rate
  monitoring, provider circuit breakers/quotas, queue/back-pressure behaviour,
  concurrency tests and a reverse-proxy/load-balancing plan.
- Horizontal API replicas require shared Redis/Postgres/Qdrant and stateless
  request handling. Do not make the website depend on one server instance.

## 10. Acceptance checklist on the real MAFSU website

- [ ] Launcher opens and immediately focuses the text box.
- [ ] Health dot changes according to actual `/api/healthz` availability.
- [ ] `?` displays clickable FAQ questions.
- [ ] English, Hindi and Marathi buttons send the correct `uiLanguage`.
- [ ] Explicit B.V.Sc., B.F.Sc. and Dairy questions route correctly.
- [ ] Ambiguous fee/eligibility questions display programme choices.
- [ ] Guided option buttons continue the original question.
- [ ] Microphone gracefully disables when unsupported.
- [ ] Long answers remain positioned at the first line of the new response.
- [ ] Escape closes the panel and focus returns to the launcher.
- [ ] Mobile layout is usable at 320 px width and with the on-screen keyboard.
- [ ] No mixed-content, CORS or CSP errors appear in the browser console.
- [ ] `429`, timeout and offline states provide a retry path.
- [ ] The Beta and “verify final decisions with MAFSU” notices remain visible.

## 11. Backend contacts and change control

The website developer owns presentation and placement only. Any change to API
fields, admission rules, caching, prompts, security controls, admin review,
provider routing or model behaviour stays with the backend team. Coordinate API
changes before modifying the JavaScript contract.
