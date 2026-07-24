"""RAG orchestration: retrieve prospectus context, route by language, generate.

Ties the pieces together the way a single question flows through the system:
embed the question, find the most relevant prospectus chunks, then ask the
language-appropriate model to answer using only those chunks.
"""

from . import config, embeddings, faq, llm, vectorstore
from .lang import detect_script

SYSTEM_PROMPT = (
    "You are a warm, friendly admissions assistant helping students with the "
    "B.V.Sc. & A.H. program. Talk naturally and kindly, like a helpful counselor. "
    "Answer using ONLY the prospectus excerpts provided and never invent details. "
    "If the excerpts don't cover something, say so gently and point them to what you "
    "can help with. Weave page references into your answer naturally (for example, "
    "'you'll find this on page 9') rather than listing them mechanically. Keep answers "
    "clear and encouraging. " + llm.LANGUAGE_RULE
)

GREETING_PROMPT = (
    "You are a warm, friendly admissions assistant for the B.V.Sc. & A.H. program. "
    "The student is only greeting you, not asking a question yet. Reply warmly in one "
    "or two short sentences and invite them to ask about eligibility, dates, fees, or "
    "documents. " + llm.LANGUAGE_RULE
)

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


def answer(question):
    """Student -> intent -> FAQ cache -> RAG -> LLM -> answer.

    Returns {answer, pages, model, language, source}. `source` is 'faq-cache' for an
    instant cache hit, otherwise 'rag'. Greetings short-circuit before any of it.
    """
    question = question.strip()
    language = detect_script(question)

    # Intent: greeting short-circuit (no retrieval, no cache).
    if is_greeting(question):
        reply, model = llm.generate(GREETING_PROMPT, question, question, timeout=120)
        return {"answer": reply, "pages": [], "model": model,
                "language": language, "source": "greeting"}

    # Embed once; the vector is reused for both the FAQ lookup and RAG retrieval.
    query_vector = embeddings.embed([question])[0]

    # FAQ cache: instant answer for a question we've seen or seeded before.
    hit = faq.match(query_vector)
    if hit:
        return {"answer": hit["answer"], "pages": hit["pages"], "model": "faq-cache",
                "language": language, "source": "faq-cache"}

    # RAG: retrieve prospectus context, then the language-routed LLM.
    store = vectorstore.load()
    top = vectorstore.search(store, query_vector, config.TOP_K)
    context = "\n\n".join("[Page {}] {}".format(e["page"], e["text"]) for e in top)
    user_prompt = "Prospectus excerpts:\n" + context + "\n\nQuestion: " + question
    reply, model = llm.generate(SYSTEM_PROMPT, user_prompt, question)
    pages = sorted({e["page"] for e in top})

    # Auto-cache so the next similar ask is instant.
    if config.FAQ_AUTOCACHE:
        faq.add(question, reply, pages, query_vector)

    return {"answer": reply, "pages": pages, "model": model,
            "language": language, "source": "rag"}


def ingest(pdf_path):
    """Extract, chunk, embed and store a prospectus PDF. Returns counts."""
    from . import pdf as pdf_module

    pages = pdf_module.extract_pages(pdf_path)
    chunks = pdf_module.chunk_pages(pages)

    vectors = []
    batch = 32
    for i in range(0, len(chunks), batch):
        vectors.extend(embeddings.embed([c["text"] for c in chunks[i:i + batch]]))

    store = [{"page": c["page"], "text": c["text"], "vector": v} for c, v in zip(chunks, vectors)]
    vectorstore.save(store)
    return {"pagesProcessed": len(pages), "chunksIndexed": len(chunks)}
