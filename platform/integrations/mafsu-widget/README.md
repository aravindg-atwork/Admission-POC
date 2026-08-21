# MAFSU admissions floating widget

A standalone HTML/CSS/jQuery integration package for the existing MAFSU WebForms website. It does not require React and all widget selectors are prefixed with `mafsu-chat` to reduce collisions with the host site's CSS.

The student-facing name is **MAFSU MITRA (Beta)**. The visible beta notice is
intentional and must remain in the production embed until the University signs
off on removing it.

## Files to hand over

- `mafsu-admissions-widget.css` — copy to the site's CSS/static folder.
- `mafsu-admissions-widget.js` — copy to the site's JavaScript/static folder.
- Copy the `<div id="mafsu-admissions-widget">…</div>` block from `index.html` immediately before the WebForms master page's closing `</body>` tag.
- Add the stylesheet in `<head>` and load the script after jQuery, near the closing `</body>` tag.

The included `index.html` is a working standalone visual demo. It loads jQuery 3.7.1 itself. On the real website, remove that CDN tag when the site already loads a compatible jQuery version.

## API configuration

Set `data-api-base` on the root element:

```html
<div id="mafsu-admissions-widget"
     class="mafsu-chat"
     data-api-base="https://admissions-api.mafsu.in"
     data-default-language="en">
```

The preferred production arrangement is a same-origin reverse proxy and an empty `data-api-base`, so requests go to `/api/chat` on the MAFSU website domain. This avoids mixed-content and CORS failures. Do not embed the current plain-HTTP IP endpoint into an HTTPS MAFSU page; browsers will block it.

Expected request:

```json
{
  "question": "Am I eligible for B.F.Sc.?",
  "uiLanguage": "en",
  "projectId": "bvsc",
  "conversationState": {}
}
```

The initially supplied `projectId` is only a safe API default. An explicitly named programme in the student's question is auto-detected by the server, and the widget updates its programme badge from the returned `projectId`.

## WebForms integration notes

- Place the widget markup in the `.Master` file to make it available throughout the site.
- Keep only one element with `id="mafsu-admissions-widget"` per page.
- If the site uses an older jQuery, test `$.ajax`, delegated `.on()`, and `.prop()` support. jQuery 1.7+ contains the APIs used here; jQuery 3.7.1 is recommended.
- Permit the API origin in Content Security Policy (`connect-src`) when it is not same-origin.
- The backend must allow the real MAFSU site origin in CORS until the same-origin proxy is installed.
- The widget stores only current-page conversation state in memory. Refreshing the page clears it; this is intentional for the demo and avoids storing student data in the browser.
- Voice input uses the browser's Web Speech API. It requires a supported browser,
  microphone permission, and normally an HTTPS origin. Unsupported browsers
  retain typed input and show the microphone control as unavailable.
- Fresh programme-dependent questions such as "What are the fees?" are answered
  only after the student chooses B.V.Sc., B.F.Sc., or B.Tech Dairy. An explicitly
  named programme still routes automatically.
- Long assistant replies scroll to the beginning of the new response so the
  student can read from its first line; student messages and loading indicators
  continue to scroll to the latest position.

## Current product limitation

Explicit programme names auto-route correctly. General 10-turn reference resolution (for phrases such as “does that also apply?”), ambiguous-programme disambiguation, and multi-programme comparison are still part of roadmap item 7 and should not be represented as complete in the production sign-off.
