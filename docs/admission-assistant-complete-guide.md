# AI Admission Assistant — The Complete Guide

*A plain-language reference to what this project is, how it works, what it
costs, and where it currently falls short. Written for anyone — technical
or not — who needs the full picture in one place.*

---

## 1. What this project actually is

At its core, this is an AI chat assistant that answers a prospective
student's questions about university admission — instantly, in their own
language, at any hour, without waiting for a human counselor to be
available.

A student can type (or speak) something like *"What percentage do I need
in 12th to get into the veterinary course?"* or *"मला किती फी भरावी
लागेल?"* (Marathi for "how much fee do I need to pay?"), and get a direct,
specific answer — not a canned FAQ entry, not a link to a 60-page PDF they
have to read themselves, but a real answer to the real question, pulled
from the university's own official prospectus.

**The full intended scope of the project — what it's meant to cover, not
just what exists today:**

- Every undergraduate programme the university offers (currently three:
  a veterinary degree, a fisheries science degree, and a dairy technology
  degree — more can be added over time).
- Three languages: English, Hindi, and Marathi — because a real prospective
  student population in Maharashtra is not English-only, and forcing
  everyone through English is itself a barrier.
- Every kind of question a student or parent actually asks during
  admission season: eligibility ("do I qualify?"), fees, important dates,
  required documents, hostel availability, reservation categories, how the
  application process works, what happens if you miss a deadline, and so on.
- A way to ask by typing OR by speaking (voice input), because not every
  student is equally comfortable typing long questions, especially in a
  second language.
- An admin side, for the university's own staff: upload a new prospectus
  when it changes, see what students are actually asking, spot questions
  the system answered badly, and fix them.
- Grounded answers only. The assistant is not supposed to "know things" the
  way a general chatbot does — every factual answer is meant to trace back
  to an actual sentence in the actual prospectus document, not the AI's
  general knowledge or a guess.

That's the target. Section 6 is honest about how much of that is actually
built today versus still in progress.

---

## 2. How it actually works, explained simply

Forget the technical name for a moment ("RAG" — Retrieval-Augmented
Generation) and think of it like this:

Imagine hiring a very well-read assistant who has read the *entire*
prospectus booklet cover to cover and can instantly flip to the exact
paragraph that answers whatever you just asked — then explain that
paragraph to you in plain spoken language instead of reading the official
wording aloud.

That's four separate jobs happening behind the scenes every time a student
asks something:

1. **Understand the question.** What language is it in? What is it
   actually asking — a fee amount? An eligibility check? Is it even an
   admission question at all, or someone asking something unrelated?

2. **Find the right paragraph(s).** The entire prospectus has already been
   broken into small chunks and turned into a searchable index (more on
   this in Section 4 — this is the "embedding" step). The system searches
   that index for the pieces most likely to contain the answer — similar
   to how a library catalogue finds the right shelf, except this one
   understands *meaning*, not just matching exact words.

3. **Write the answer.** A language model (the "AI" most people picture
   when they hear "ChatGPT") reads the found paragraphs and writes a
   natural, direct answer — the way a knowledgeable person would explain
   it to a nervous 17-year-old and their parent, not the way a legal
   document is written.

4. **Double-check the number.** For the highest-stakes facts — a fee
   figure, a percentage requirement — the system doesn't trust the AI to
   read the number off a table correctly (AI models are measurably bad at
   reading dense tables reliably). Instead, plain computer code picks the
   exact number out of the table, and the AI's only job is to phrase that
   already-correct number into a natural sentence. This single design
   choice is the biggest reason this system gives fewer wrong numbers than
   a general-purpose chatbot would.

---

## 3. The two "brains" this system runs on, and what each one actually costs

There are two *separate* AI models doing two *separate* jobs. Mixing them
up is the most common source of confusion when people ask "what does the
AI cost," so they're kept clearly apart here.

### 3a. The "answering" brain — the language model

This is the one that reads the found paragraphs and writes the actual
reply a student sees. **Currently: Mistral**, a French AI company, on
their **free tier**.

**What "free tier" actually means here:** Mistral's free plan (called
"Experiment") gives roughly **1 billion tokens per month**, across all
their models, at zero cost, no credit card required. A "token" is roughly
¾ of an English word — so 1 billion tokens is an enormous amount of text,
far more than this project's current traffic uses. The catch: the free
tier comes with rate limits (how many requests per minute/second) tight
enough that under real concurrent load — many students asking at once
during peak admission days — requests start failing or queueing, which is
why this project has already been hit by this in testing (documented
separately as a real, reproduced incident, not a hypothetical risk).

**If this project moved to Mistral's paid tier** (needed for reliable
production use, not just occasional testing), current pricing works out
to roughly:

| Model | Cost per 1 million words of input | Cost per 1 million words of output |
|---|---|---|
| Mistral Small | ~$0.15 (≈ ₹14) | ~$0.60 (≈ ₹57) |

(1 USD ≈ ₹95.7 as of mid-August 2026.)

**How that compares to ChatGPT / GPT-5** (OpenAI's current flagship,
widely considered a stronger, more reliable reasoning model — the AI most
non-technical people mean when they say "ChatGPT"). As of August 2026,
OpenAI prices the GPT-5 family in three speed/quality tiers:

| Tier | Cost per 1M input tokens | Cost per 1M output tokens | In INR (input/output) |
|---|---|---|---|
| Luna (fastest, cheapest) | $0.20 | $1.20 | ≈ ₹19 / ₹115 |
| Terra (mid) | $2.00 | $12.00 | ≈ ₹191 / ₹1,148 |
| Sol (flagship, most capable) | $5.00 | $30.00 | ≈ ₹479 / ₹2,871 |

**On paper, GPT-5's flagship tier looks 30-50× more expensive per token
than Mistral.** But that comparison is misleading for THIS project
specifically, and here's the actual number that matters:

### The real question isn't "which is cheaper per token" — it's "what does an entire admission season actually cost"

This project's own measurements (from real testing) show a typical
question-and-answer round trip uses about **5,000 input tokens** (the
retrieved paragraphs plus instructions) and **~300 output tokens** (the
actual reply). Admission-related questions are heavily concentrated in a
short window — realistically **about two months a year**, around results
announcement through admission close. Outside that window, traffic is
close to zero.

Assume, illustratively, **5,000 total questions** across that two-month
season (a reasonable planning estimate, not a guaranteed number — the real
figure should be checked against actual usage once the system has run a
full season):

| Provider / tier | Estimated total cost for the ENTIRE 2-month season |
|---|---|
| Mistral Small (paid) | ≈ **₹445** |
| GPT-5 Luna | ≈ **₹651** |
| GPT-5 Terra | ≈ **₹6,509** |
| GPT-5 Sol (flagship) | ≈ **₹16,275** |

**This is the actual argument for "pay-as-you-go, and pay for quality":**
because real total volume is low and concentrated into a short burst, even
the *most expensive* GPT-5 tier costs on the order of a few thousand to
~₹16,000 rupees for the *entire admission season* — not per month, not
per day, the whole season. That is a genuinely small absolute number for
an institution to weigh against fewer wrong answers, better handling of
oddly-phrased questions, and less risk of the "confidently wrong" failure
mode described in Section 5. A flat monthly subscription, by contrast,
would mean paying for 12 months of capacity to cover 2 months of real use
— pay-as-you-go pricing is structurally the right fit for this traffic
shape, regardless of which provider is chosen.

*(Caveat, stated honestly: these are illustrative estimates built from
this project's own measured per-question token usage and a reasonable
assumed volume — not a quote, and not a guarantee. Before committing a
real budget, the same math should be re-run against actual logged usage
from a live season.)*

### 3b. The "understanding meaning" brain — the embedding model

This is the second, separate AI, called **BGE-M3**, and it does a
completely different job from the answering model above: it's the one
that makes the "find the right paragraph" step in Section 2 actually work.

**In plain terms**: an embedding model reads a sentence and converts it
into a long list of numbers that represents its *meaning* — not the exact
words. This is what lets the system correctly match a student asking
*"how much does the hostel cost"* against a prospectus paragraph headed
*"Hostel Fees"* even though the wording doesn't match exactly, and — this
is the important part for this project — it's *multilingual by design*.
BGE-M3 was specifically chosen because it understands over 100 languages
well enough to match a Hindi or Marathi question directly against English
prospectus content, without needing a separate translation step just to
search.

**The critical cost difference from Section 3a: BGE-M3 is free, open-source
software, run on the university's own server** — it is not rented per-use
from a company the way Mistral or GPT-5 are. There is no per-question,
per-token bill for this half of the system at all. The only cost is the
electricity/server capacity to keep it running, which is a fixed
infrastructure cost, not a usage-based one. This matters for the overall
cost story: the expensive, metered part of this system is *only* the
answering model in Section 3a — the "understanding" half is essentially
free to operate at any volume.

---

## 4. Current limitations — stated honestly

No AI system like this is perfect, and pretending otherwise would be
dishonest. Here are the real, current limitations:

**Hallucination.** This is the technical term for an AI model stating
something confidently that isn't actually correct — the AI equivalent of
a student guessing on an exam but writing the answer as if certain of it.
This is a real, inherent risk of every language model, including GPT-5 and
Mistral both. This project reduces that risk significantly for the
numbers that matter most (fees, eligibility percentages) by never letting
the AI pick those numbers itself — see Section 2, step 4 — but that
safety net doesn't cover every kind of question. A free-form answer about,
say, the admission process or a document requirement still carries some
residual risk of the AI phrasing something slightly wrong, which is why
this project also runs an automated accuracy check on generated answers
(catching numbers that don't appear anywhere in the source material) as a
second line of defense — though that check itself isn't applied uniformly
to every language yet (see below).

**Language reliability gaps.** Occasionally, an English question has come
back answered in Hindi, or vice versa, when the system didn't have a
strong enough signal about which language to reply in. This has a known,
partially-applied fix, but hasn't been proven bug-free across every
scenario.

**Accuracy checking is stronger for English than for Hindi/Marathi.** The
automated "does this answer contain a number that isn't actually in the
source" check currently only runs its full strength on English answers —
Hindi and Marathi answers get a lighter check, because the stronger check
hasn't been verified to work reliably across scripts yet.

**A parallel, in-progress rebuild currently covers less than the live
system.** This project has an original, currently-live version, and a
newer rebuild in progress (built with a cleaner underlying architecture).
As of this writing, the newer rebuild only has data for one of the three
degree programmes loaded, has no Hindi/Marathi support wired in yet, and
is missing some of the live system's guided-conversation features (like
asking a student one clarifying question at a time when their eligibility
question is missing information, instead of guessing). None of this
affects the currently-live system, which still covers all three
programmes and all three languages — it's specifically a limitation of
the newer version still being finished.

---

## 5. Why paying for GPT-5 quality might be worth it

Given Section 3a's actual math — a full admission season costing on the
order of a few thousand to ~₹16,000 rupees even at GPT-5's flagship
pricing — the usual objection to "just use the better, more expensive
model" (that it would be unaffordable at scale) doesn't really apply here,
*because this system's real-world usage pattern is a short, low-volume
burst, not constant year-round traffic*. The models that make GPT-5
expensive per token are priced for companies running millions of requests
a day, continuously, all year. That is not this project's shape of usage
at all.

Given that, the practical tradeoff is genuinely simple: a materially
stronger model that handles oddly-phrased questions better and hallucinates
less, for what amounts to pocket change across an entire season, versus
staying on a free tier that has already, in real testing, hit rate-limit
problems under concurrent load. The free tier's risk isn't really "will it
cost too much" — it's "will it stay reliably usable when many students ask
at once during the two weeks after results are announced," which is
exactly when reliability matters most.

---

## 6. Infrastructure built for a two-month spike, not year-round load

Two specific pieces of infrastructure exist (or are planned) specifically
because of this bursty traffic shape, and they matter as much to cost as
the model choice does:

**Load balancing** — in plain terms, running several copies of the
"answering engine" side by side and spreading incoming questions across
them, the way a ticket counter opens more windows when the queue gets
long. The key second half of this: those extra copies can be shut back
down when the queue is short, so the system isn't paying to keep ten
counters staffed during the ten quiet months. This is specifically suited
to a system that's busy for two months and quiet for ten.

**Caching** — remembering the answer to a question that's already been
asked and answered, so the *next* student who asks something close enough
to the same question gets an instant, free answer instead of the system
re-doing the full "search the prospectus, ask the AI" process from
scratch. Admission questions are highly repetitive by nature — hundreds of
students asking essentially "what's the fee" or "am I eligible" in
slightly different wording — which makes caching one of the single
biggest cost and speed levers available: fewer paid AI calls, and
near-instant replies for the questions asked most often.

Together, these two mean the system's real running cost scales with
*actual, current demand*, not with a guessed year-round capacity number —
which is the right shape for a workload that spikes hard for two months
and then goes quiet.

---

## 7. Summary

This is a multilingual, grounded AI admissions assistant meant to cover
every programme, every common question type, and both typed and spoken
input — built on two separate AI components: a paid, metered
"answering" model (currently Mistral, free tier; GPT-5 is a viable,
genuinely affordable upgrade given how low actual total-season volume is)
and a free, self-hosted "understanding meaning" model (BGE-M3) that makes
multilingual search possible at no per-question cost. Its real limitations
are the ordinary ones any AI system has — occasional hallucination,
language-reliability edge cases — mitigated deliberately wherever the
stakes are highest (money, eligibility), and openly acknowledged wherever
they aren't yet. And its infrastructure is deliberately shaped around the
fact that this system is genuinely busy for about two months a year, and
should be built, staffed, and billed accordingly — not provisioned as if
it needed to handle admissions-season traffic in July.
