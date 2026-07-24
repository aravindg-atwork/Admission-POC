"""RAG orchestration: retrieve prospectus context, route by language, generate.

Ties the pieces together the way a single question flows through the system:
embed the question, find the most relevant prospectus chunks, then ask the
language-appropriate model to answer using only those chunks.
"""

import hashlib
import json
import time
from datetime import datetime, timezone

from . import config, embeddings, faq, llm, projects, stats, transliterate, vectorstore
from .lang import detect_script

SYSTEM_PROMPT_BASE = (
    "You are a warm, knowledgeable admissions counselor for the B.V.Sc. & A.H. "
    "program, talking to a student directly - not reading them a document.\n\n"
    "RULES:\n"
    "- Answer the student's actual concern FIRST, in plain natural spoken sentences, "
    "the way a caring counselor would say it out loud. NEVER start a sentence with "
    "'It states that...', 'The prospectus says...', or 'According to page X...' - "
    "lead with the real answer and what it practically means for them.\n"
    "- Use ONLY the prospectus excerpts provided as your source of truth - never "
    "invent details. If something isn't covered, say so warmly and point them to "
    "what you can help with.\n"
    "- Mention the page reference only in passing, once, near the end of the "
    "relevant point (for example '...you'll find the details on page 9') - never "
    "as the subject of the sentence.\n"
    "- Write in plain spoken prose only. NEVER use markdown: no asterisks, no "
    "bullet points, no numbered lists, no bold, no headers. If there are several "
    "items, weave them into a natural sentence (\"you'll need three things: your "
    "mark sheet, an ID, and two photos\").\n"
    "- Keep it concise - a few sentences, not a document summary.\n\n"
    "Example of the tone to match:\n"
    "Student asks: \"When was the last day to submit documents?\"\n"
    "Good: \"The deadline officially closed on March 1st, but don't worry - you can "
    "still apply until March 15th if you pay a small late fee. I'd recommend "
    "submitting as soon as you can, though. You'll find the exact details on "
    "page 4.\"\n"
    "Bad (never do this): \"It states in the prospectus that the deadline is March "
    "1st. Page 4 mentions late submissions are accepted until March 15th with a "
    "fee.\"\n\n"
)

GREETING_PROMPT_BASE = (
    "You are a warm, friendly admissions counselor for the B.V.Sc. & A.H. program. "
    "The student is only greeting you, not asking a question yet. Reply warmly in one "
    "or two short spoken sentences and invite them to ask about eligibility, dates, "
    "fees, or documents. Plain prose only, no markdown, no asterisks or lists. "
)

SYSTEM_PROMPT = SYSTEM_PROMPT_BASE + llm.LANGUAGE_RULE
GREETING_PROMPT = GREETING_PROMPT_BASE + llm.LANGUAGE_RULE


def _apply_script_pref(text, language, script_pref):
    """Hinglish is a display-time transformation, not a generation-time one -
    asking the model to write Roman-script Hindi directly proved unreliable (see
    transliterate.py), so generation always stays native-script and this converts
    afterward, deterministically. Returns (display_text, speakable). No-op for
    anything that isn't a Devanagari answer under an explicit hinglish request.
    """
    if script_pref == "hinglish" and language == "devanagari":
        return transliterate.to_hinglish(text), False
    return text, True

# Exact-match greetings across the supported languages. Deliberately not length-based:
# a longer question in any script must never be mistaken for a greeting.
GREETINGS = {
    "hi", "hey", "hello", "yo", "hii", "hiya", "hey there",
    "thanks", "thank you", "thankyou", "ok", "okay", "bye", "goodbye",
    "namaste", "namaskar", "vanakkam", "vanakam",
    "வணக்கம்", "नमस्ते", "नमस्कार", "हाय", "हेलो",
}


def is_greeting(text):
    return text.lower().strip().strip("!.?,। ") in GREETINGS


def answer(project_id, question, script_pref="auto"):
    """Student -> intent -> FAQ cache -> RAG -> LLM -> answer.

    Returns {answer, pages, model, language, source, speakable}. `source` is
    'faq-cache' for an instant cache hit, otherwise 'rag'. Greetings short-circuit
    before any of it. `script_pref` ("auto" | "hinglish") is the user's explicit
    choice for Hindi output script - "hinglish" answers come back non-speakable
    since the TTS voice can't pronounce Romanized Hindi correctly. Every call is
    timed and recorded (counts/timing only, never question text) for that
    project's own dashboard and cost panel.
    """
    t0 = time.time()
    result = _answer(project_id, question, script_pref)
    stats.record(projects.stats_path(project_id), result["source"], result["model"],
                 result["language"], round((time.time() - t0) * 1000))
    return result


def _answer(project_id, question, script_pref):
    question = question.strip()
    language = detect_script(question)
    cloud_ok = projects.allow_cloud(project_id)

    # Intent: greeting short-circuit (no retrieval, no cache).
    if is_greeting(question):
        reply, model = llm.generate(GREETING_PROMPT, question, question, timeout=120, allow_cloud=cloud_ok)
        display, speakable = _apply_script_pref(reply, language, script_pref)
        return {"answer": display, "pages": [], "model": model, "language": language,
                "source": "greeting", "speakable": speakable}

    # Embed once; the vector is reused for both the FAQ lookup and RAG retrieval.
    query_vector = embeddings.embed([question])[0]

    # FAQ cache: instant answer for a question we've seen or seeded before. Cached
    # text is always native-script; script_pref is applied below regardless of
    # whether the answer came from cache or fresh generation.
    hit = faq.match(projects.faq_path(project_id), query_vector)
    if hit:
        display, speakable = _apply_script_pref(hit["answer"], language, script_pref)
        return {"answer": display, "pages": hit["pages"], "model": "faq-cache",
                "language": language, "source": "faq-cache", "speakable": speakable}

    # RAG: retrieve prospectus context, then the language-routed LLM. Retrieval uses
    # an English-translated version of non-English questions - the prospectus is
    # predominantly English text, and the embedding model doesn't align Hindi/Tamil
    # with English closely enough for the original-language vector to reliably find
    # the right chunks (verified: a Hindi fee question missed chunks an equivalent
    # English one found). The FAQ-cache vector above stays untranslated on purpose,
    # so cache matching stays consistent with how earlier entries were embedded.
    retrieval_vector = query_vector
    if language != "latin":
        translated = llm.translate_to_english(question)
        if translated and translated != question:
            retrieval_vector = embeddings.embed([translated])[0]

    store = vectorstore.load(projects.store_path(project_id))
    top = vectorstore.search(store, retrieval_vector, config.TOP_K)

    if not top:
        # No prospectus uploaded for this project yet. An empty excerpts block was
        # tested and found to NOT reliably stop the model from hallucinating a
        # confident-sounding made-up answer (e.g. inventing a specific fee amount)
        # despite the "never invent details" rule - so this makes the no-data case
        # explicit and unambiguous instead, which the model does follow reliably.
        # Not cached: the real answer should appear the moment a prospectus is
        # uploaded, not stay stuck on this message.
        no_data_prompt = (
            "There are NO prospectus excerpts available - none have been uploaded yet "
            "for this project. Do not answer using any outside knowledge or make up "
            "specifics. Instead, warmly and briefly tell the student the prospectus "
            "isn't loaded yet and you can't answer specific questions until it is.\n\n"
            "Question: " + question
        )
        reply, model = llm.generate(SYSTEM_PROMPT, no_data_prompt, question, allow_cloud=cloud_ok)
        display, speakable = _apply_script_pref(reply, language, script_pref)
        return {"answer": display, "pages": [], "model": model, "language": language,
                "source": "no-context", "speakable": speakable}

    context = "\n\n".join("[Page {}] {}".format(e["page"], e["text"]) for e in top)
    user_prompt = "Prospectus excerpts:\n" + context + "\n\nQuestion: " + question
    reply, model = llm.generate(SYSTEM_PROMPT, user_prompt, question, allow_cloud=cloud_ok)
    pages = sorted({e["page"] for e in top})

    # Auto-cache the native-script answer so the next similar ask is instant,
    # regardless of which script_pref that later ask uses.
    if config.FAQ_AUTOCACHE:
        faq.add(projects.faq_path(project_id), question, reply, pages, query_vector)

    display, speakable = _apply_script_pref(reply, language, script_pref)
    return {"answer": display, "pages": pages, "model": model, "language": language,
            "source": "rag", "speakable": speakable}


def ingest(project_id, pdf_path):
    """Extract, chunk, embed and store a prospectus PDF for a project.

    Skips re-embedding entirely when the PDF is byte-identical to what's
    already indexed for this project (tracked via a content hash in
    manifest.json) - re-uploading the same prospectus, or restarting the
    pipeline against unchanged data, costs nothing. Returns counts plus
    `skipped: True` when the skip path was taken.
    """
    from . import pdf as pdf_module

    pdf_bytes = pdf_path.read_bytes()
    content_hash = hashlib.sha256(pdf_bytes).hexdigest()

    manifest_path = projects.manifest_path(project_id)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("hash") == content_hash:
            return {"pagesProcessed": manifest["pagesProcessed"],
                     "chunksIndexed": manifest["chunksIndexed"], "skipped": True}

    pages = pdf_module.extract_pages(pdf_path)
    chunks = pdf_module.chunk_pages(pages)

    vectors = []
    batch = 32
    for i in range(0, len(chunks), batch):
        vectors.extend(embeddings.embed([c["text"] for c in chunks[i:i + batch]]))

    store = [{"page": c["page"], "text": c["text"], "vector": v} for c, v in zip(chunks, vectors)]
    vectorstore.save(projects.store_path(project_id), store)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "hash": content_hash, "pagesProcessed": len(pages), "chunksIndexed": len(chunks),
        "embeddedAt": datetime.now(timezone.utc).isoformat(),
    }), encoding="utf-8")

    return {"pagesProcessed": len(pages), "chunksIndexed": len(chunks), "skipped": False}
