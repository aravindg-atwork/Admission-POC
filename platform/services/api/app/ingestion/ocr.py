"""Prospectus extraction via Mistral OCR, as an alternative to pypdf.

Why this exists
---------------
pypdf's layout mode reconstructs a table by guessing at whitespace, and on
these fee grids it loses the association between a label and its figures.
The B.V.Sc. fee page came out as:

    i. a) For Maharashtra State 68860/- Total : Candidate 69410/- 47400/-

- three different figures, one detached label, and no way to tell which
column any of them belongs to. Several of the worst bugs in this project
trace back to that: a Ph.D. reservation fee reported as its unreserved fee,
and figures quoted confidently under the wrong heading. No amount of
retrieval tuning fixes a chunk whose numbers have already lost their labels.

Mistral OCR returns the same page as a markdown table:

    |  1 | Registration Fee | 1500 | 1500 | 1500 | 2200 | 1500 |
    |  2 | Tuition Fee      | 27500 | 27500 | 27500 | 41250 | 0 |

Every figure keeps its row label and its column header, which is what makes
a chunk answerable rather than merely on-topic.

Deliberately opt-in and reversible
----------------------------------
config.OCR_ENABLED chooses the extractor; pdf.extract_pages remains the
default and the fallback. OCR is a paid network call over a whole document,
so an ingest must not become un-runnable when the key is missing, the
service is down, or a page comes back empty - any of those falls straight
back to pypdf for that document, and ingest continues.
"""

import base64
import json
import urllib.error
import urllib.request

from ..settings import get_settings

_settings = get_settings()

# Pages an OCR response must at least produce before it is believed. A
# response that parses but returns almost nothing is worse than a pypdf
# extraction, because it silently indexes an empty corpus.
_MIN_PAGES = 3


def available():
    return bool(_settings.ocr_enabled and _settings.mistral_api_key)


def extract_pages(pdf_path):
    """[{page, text}] in the same shape pdf.extract_pages returns, or None.

    None means "use the normal extractor" - the caller is expected to fall
    back rather than fail, so a missing key or a bad day at the OCR service
    degrades ingest quality instead of blocking it entirely.
    """
    if not available():
        return None
    try:
        payload = json.dumps({
            "model": _settings.ocr_model,
            "document": {
                "type": "document_url",
                "document_url": "data:application/pdf;base64,"
                                + base64.b64encode(pdf_path.read_bytes()).decode("ascii"),
            },
        }).encode("utf-8")
        req = urllib.request.Request(
            _settings.mistral_url.rstrip("/") + "/ocr", data=payload, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_settings.mistral_api_key}",
                "User-Agent": "AdmissionAssistant/1.0",
            })
        with urllib.request.urlopen(req, timeout=_settings.ocr_timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"[ocr] HTTP {exc.code}: {exc.read().decode()[:200]}")
        return None
    except Exception as exc:  # noqa: BLE001 - ingest must survive this
        print(f"[ocr] failed for {pdf_path.name}: {exc!r}")
        return None

    pages = []
    for index, page in enumerate(data.get("pages") or [], start=1):
        text = (page.get("markdown") or "").strip()
        if text:
            # OCR numbers its own pages; trust its index when present so a
            # citation still points where a reader would look.
            pages.append({"page": page.get("index", index - 1) + 1
                          if isinstance(page.get("index"), int) else index,
                          "text": text})
    if len(pages) < _MIN_PAGES:
        print(f"[ocr] only {len(pages)} usable pages for {pdf_path.name} - using pypdf instead")
        return None
    return pages
