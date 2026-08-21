# MITRA Review Console

The admin console is served at `/admin/` by the normal web image. It is not
linked from the student interface.

Set `ADMIN_API_KEY` in `services/api/.env` before starting the stack, then use
that value on the console login screen. The key is retained only in browser
`sessionStorage` and is cleared by **Lock** or when the tab session ends.

## Review workflow

1. Open a logged student conversation.
2. Select **Flag answer** on the exact assistant response.
3. Enter the corrected answer, prospectus page numbers, and reviewer notes.
4. Save and select **Test correction**. Publication is blocked when evidence
   pages do not exist, the answer is too short, or deterministic validation
   finds unsupported numbers or cross-programme leakage.
5. Select **Publish fix**. The exact programme/language/question answer becomes
   active immediately and its stale Redis answer is invalidated.
6. Select the review status chip later to reopen it. **Rollback** deactivates
   the override and invalidates its cache entry.

## Privacy and deployment

Email addresses, Indian mobile numbers, and Aadhaar-shaped identity numbers
are redacted before transcript storage. Answer delivery does not fail if the
logging database is unavailable.

Do not expose this console or its API over plain HTTP. The current public IP
demo has no TLS, so the admin console is intentionally validated locally only.
Deploy it on the real HTTPS MAFSU origin or behind an HTTPS VPN/access proxy.
