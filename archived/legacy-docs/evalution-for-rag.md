# Production RAG Evaluation & Root-Cause Analysis

You are acting as a **Senior RAG Engineer, LLM Evaluation Engineer, and Retrieval Systems Debugger**.

I already have a working RAG application. Do **not** immediately rewrite or replace the architecture.

Your first task is to inspect, instrument, evaluate, and diagnose the existing implementation.

## Current Environment

The application is hosted on a Hetzner CX53-class server with approximately:

* 32 GB RAM
* ~300 GB storage
* Linux
* Local/self-hosted AI infrastructure

Knowledge base:

* 3 PDF documents
* Approximately 60–70 pages each
* Roughly 180–210 pages total

The system already uses RAG and may contain:

* PDF parsing
* Chunking
* Embeddings
* Vector retrieval
* Qdrant or another vector database
* Reranking
* Query rewriting
* Prompt engineering
* PET
* ReAct
* Least-to-Most prompting
* Other retrieval/reasoning techniques

## Main Problem

The system is inconsistent.

A question may:

1. return the correct answer,
2. then return an incorrect answer,
3. then fail to retrieve the correct information,
4. even when the exact same question is asked again.

I need to determine **exactly where this instability originates**.

Do not assume the LLM is the problem.

Evaluate the entire pipeline.

---

# PHASE 1 — DISCOVER THE CURRENT ARCHITECTURE

Inspect the repository and identify the actual RAG flow.

Document:

```text
User Question
    ↓
Query Processing
    ↓
Query Rewriting / Expansion
    ↓
Embedding
    ↓
Vector / Keyword Retrieval
    ↓
Fusion
    ↓
Reranking
    ↓
Context Construction
    ↓
Prompt
    ↓
LLM
    ↓
Final Answer
```

Modify this diagram according to what the application actually does.

Identify:

* PDF parsing library
* embedding model
* embedding dimensions
* vector database
* vector distance metric
* chunking strategy
* chunk size
* chunk overlap
* metadata stored per chunk
* retrieval algorithm
* top-k
* score thresholds
* BM25/keyword search if present
* hybrid retrieval if present
* fusion algorithm if present
* reranker model
* reranker top-k
* query rewriting
* query expansion
* conversation-history handling
* final LLM
* model parameters
* temperature
* top_p
* max tokens
* system prompt
* RAG prompt
* context construction logic
* context token limits
* duplicate-removal logic
* document/version filtering

Do not change anything yet.

Produce a concise description of the existing architecture first.

---

# PHASE 2 — VERIFY PDF INGESTION

The source documents are PDFs, so verify that the information entering the RAG system is actually correct.

For each PDF inspect:

* extracted text
* headings
* paragraphs
* tables
* bullet points
* page boundaries
* headers
* footers
* page numbers
* multi-column layouts
* repeated content
* broken characters
* missing text
* merged rows
* incorrectly extracted tables

Randomly compare extracted content against the original PDF.

Pay special attention to:

* eligibility
* percentages
* dates
* fees
* course names
* category information
* seat counts
* requirements
* tables
* exceptions
* footnotes

Flag cases where visually structured information became corrupted during extraction.

Example:

Original:

```text
Course     Category     Minimum Marks
BVSc       General      50%
BVSc       SC/ST        40%
```

Bad extraction:

```text
Course Category Minimum BVSc General
BVSc SC/ST 50% 40%
```

Report these as ingestion failures.

---

# PHASE 3 — EVALUATE CHUNK QUALITY

Inspect the chunks stored in the retrieval system.

Determine whether chunks preserve semantic meaning.

Look for:

* sentences cut in half
* headings separated from content
* tables split incorrectly
* requirements separated from their course name
* percentages separated from categories
* information spread across unrelated chunks
* extremely small chunks
* extremely large chunks
* duplicated chunks
* chunks containing multiple unrelated sections

Evaluate whether chunks include enough contextual metadata.

Preferred structure:

```text
Document: <document>
Page: <page>
Section: <section>
Subsection: <subsection>

<actual content>
```

Determine whether the current system would benefit from:

* heading-aware chunking
* semantic chunking
* recursive chunking
* parent-child retrieval
* table-aware chunking

Do not automatically change the chunking strategy.

First provide evidence showing whether chunking is actually causing failures.

---

# PHASE 4 — BUILD A GOLDEN EVALUATION DATASET

Create an evaluation dataset from the actual PDFs.

Target:

**50–100 questions minimum.**

Questions must represent multiple difficulty levels.

## Category A — Direct factual questions

Examples:

```text
What is the application fee?
What is the minimum age?
When is the last date?
```

## Category B — Terminology variation

Ask the same fact differently.

Example:

```text
What is the minimum percentage for BVSc?

How much marks do I need for BVSc?

BVSc minimum marks?

What percentage is needed to apply for veterinary admission?
```

## Category C — Multi-hop questions

Questions requiring information from multiple sections/chunks.

## Category D — Numerical questions

Include:

* percentages
* dates
* fees
* age
* seat counts
* marks

## Category E — Document-conflict questions

Where multiple PDFs contain similar or conflicting information.

## Category F — Unanswerable questions

Questions whose answers do NOT exist in the PDFs.

The correct system behavior should be refusal to invent an answer.

For every evaluation item store:

```json
{
  "id": "eval_001",
  "question": "...",
  "expected_answer": "...",
  "expected_document": "...",
  "expected_page": 0,
  "expected_section": "...",
  "expected_chunk_ids": [],
  "question_type": "factual",
  "answerable": true
}
```

Where exact expected chunk IDs can be established, include them.

---

# PHASE 5 — RETRIEVAL EVALUATION

Evaluate retrieval separately from answer generation.

This is extremely important.

For every evaluation question record:

```text
Question

Expected document
Expected page
Expected chunk

Top-1 retrieval
Top-3 retrieval
Top-5 retrieval
Top-10 retrieval

Retrieval scores
```

Calculate:

```text
Recall@1
Recall@3
Recall@5
Recall@10

MRR
Hit Rate
```

The primary question is:

> Did the retriever actually find the chunk containing the answer?

Do not judge the LLM yet.

Target for this small knowledge base:

```text
Recall@5  >= 95%
Recall@10 >= 98%
```

If retrieval cannot reach these levels, diagnose retrieval before changing prompts.

---

# PHASE 6 — SAME-QUESTION CONSISTENCY TEST

This is one of the most important evaluations.

For every golden question, run the **exact same question multiple times**.

Start with:

```text
10 runs per question
```

For difficult/failing questions use:

```text
20 runs
```

Record for every run:

```text
question
rewritten_query
expanded_queries

dense_results
dense_scores

keyword_results
keyword_scores

fusion_results

reranker_input
reranker_scores
reranker_output

final_chunk_ids

final_context_hash

LLM parameters

answer
```

Then compare runs.

Determine the FIRST stage where outputs diverge.

Example:

```text
RUN 1

Question
   ↓
Query rewrite A
   ↓
Chunks 12, 15, 19
   ↓
Reranker
   ↓
Chunks 12, 19, 15
   ↓
Correct answer


RUN 2

Same Question
   ↓
Query rewrite B
   ↓
Chunks 31, 42, 12
   ↓
Reranker
   ↓
Chunks 31, 42
   ↓
Wrong answer
```

Diagnosis:

```text
Instability originates in query rewriting/retrieval.
```

Alternatively:

```text
RUN 1 and RUN 2

Same query
Same retrieved chunks
Same reranker order
Same final context

BUT

Different answers
```

Diagnosis:

```text
Instability originates in generation.
```

This distinction MUST be measured.

---

# PHASE 7 — QUERY REWRITING ABLATION

If query rewriting exists, evaluate:

```text
A. Original query only

B. Rewritten query only

C. Original + rewritten query
```

Compare Recall@5 and Recall@10.

Check whether rewriting removes important lexical information such as:

```text
BVSc
NEET
SC/ST
course codes
percentages
dates
abbreviations
specific terminology
```

Never assume rewriting improves retrieval.

If the original query performs better, report it.

---

# PHASE 8 — DENSE VS KEYWORD VS HYBRID

If possible, evaluate independently:

```text
Dense retrieval only

BM25/keyword only

Hybrid retrieval
```

Then compare:

```text
Recall@1
Recall@3
Recall@5
Recall@10
MRR
```

Pay particular attention to queries containing:

* course names
* abbreviations
* percentages
* dates
* numbers
* categories
* codes
* exact terminology

Determine whether hybrid retrieval provides measurable improvement.

Do not recommend hybrid retrieval simply because it is considered best practice.

Prove whether it improves this dataset.

---

# PHASE 9 — RERANKER ABLATION

Run the evaluation:

```text
WITHOUT reranking
```

and:

```text
WITH reranking
```

Measure:

```text
Retriever Recall@10

Reranker Recall@3
Reranker Recall@5
```

Identify cases where:

```text
retriever found correct chunk
```

but:

```text
reranker removed correct chunk
```

Produce examples.

If reranking decreases accuracy, report it clearly.

---

# PHASE 10 — CONTEXT CONSTRUCTION TEST

Inspect what is actually sent to the final LLM.

Determine whether:

* correct chunk was retrieved
* correct chunk survived reranking
* correct chunk was actually inserted into context
* context was truncated
* neighboring context was missing
* duplicate chunks consumed token budget
* conflicting documents were included
* metadata was removed
* page/source information was lost

Calculate a hash of the final context.

For repeated identical questions:

```text
same context hash
```

should mean the LLM received identical evidence.

This allows retrieval instability to be separated from generation instability.

---

# PHASE 11 — GENERATION CONSISTENCY

When identical context is provided, run the final LLM repeatedly.

Test:

```text
temperature = 0
temperature = 0.1
temperature = current production value
```

Keep context identical.

Measure:

```text
answer consistency
factual correctness
citation correctness
hallucination rate
```

Determine whether randomness is responsible for inconsistent answers.

For factual RAG, prioritize deterministic behavior over creativity.

---

# PHASE 12 — FAITHFULNESS / GROUNDEDNESS

For every generated answer determine:

### Context Precision

How much retrieved context is actually relevant?

### Context Recall

Did retrieval capture the information necessary to answer?

### Faithfulness

Is every factual statement supported by retrieved context?

### Answer Relevancy

Does the answer directly answer the question?

### Citation Correctness

Does the referenced PDF/page actually support the answer?

### Hallucination Rate

How frequently does the model invent unsupported information?

### Refusal Accuracy

For unanswerable questions, does the system correctly say the information is unavailable?

---

# PHASE 13 — CONFLICT DETECTION

Because multiple PDFs are used, detect situations where similar facts differ between documents.

Example:

```text
Document A:
Application fee = ₹800

Document B:
Application fee = ₹900

Document C:
Application fee = ₹1,000
```

Determine whether documents have metadata such as:

```text
academic_year
effective_date
document_version
document_type
priority
```

Evaluate whether retrieval is selecting outdated information.

Report all discovered conflicts.

Do NOT silently choose one value without explaining the authority/version logic.

---

# PHASE 14 — PARENT-CHILD RETRIEVAL EXPERIMENT

If chunk fragmentation is demonstrated, test parent-child retrieval as an experiment.

Example:

```text
Parent:
800–1500 tokens

Children:
150–300 tokens
```

Embed/search children.

When a child matches:

```text
child match
   ↓
retrieve parent
   ↓
send parent context to LLM
```

Compare against current retrieval.

Measure actual improvement before recommending adoption.

---

# PHASE 15 — ADVANCED PROMPTING ABLATION

The application may currently use:

* PET
* ReAct
* Least-to-Most
* query decomposition
* multi-step reasoning

Evaluate them separately.

Create:

```text
Baseline RAG

Baseline + PET

Baseline + ReAct

Baseline + Least-to-Most

Baseline + current complete pipeline
```

Measure whether each technique actually improves accuracy.

If a technique increases:

* latency
* instability
* hallucination
* retrieval variance

without measurable accuracy improvement, recommend removing it from the default RAG path.

Simple factual questions should not automatically invoke complex agent reasoning.

---

# PHASE 16 — FAILURE CLASSIFICATION

Every failed evaluation must be assigned a root cause.

Use categories:

```text
INGESTION_FAILURE
CHUNKING_FAILURE
QUERY_REWRITE_FAILURE
EMBEDDING_FAILURE
RETRIEVAL_FAILURE
FUSION_FAILURE
RERANKER_FAILURE
METADATA_FAILURE
DOCUMENT_VERSION_FAILURE
CONTEXT_CONSTRUCTION_FAILURE
CONTEXT_TRUNCATION
GENERATION_FAILURE
HALLUCINATION
CITATION_FAILURE
UNKNOWN
```

Do not simply report:

```text
Question failed.
```

Report:

```text
Question:
"What is ...?"

Expected:
"..."

Actual:
"..."

Correct source:
PDF 2, page 31

Retrieved:
PDF 1 page 18
PDF 3 page 42

Root cause:
RETRIEVAL_FAILURE

Explanation:
Correct chunk was not present in Top-10 retrieval.

Recommended fix:
...
```

---

# PHASE 17 — BUILD AN EVALUATION REPORT

Generate a report similar to:

```text
====================================
RAG EVALUATION REPORT
====================================

Questions Tested: 100
Runs Per Question: 10
Total Runs: 1000

RETRIEVAL

Recall@1:   XX%
Recall@3:   XX%
Recall@5:   XX%
Recall@10:  XX%

MRR:        X.XX


RERANKING

Correct chunk retained @3: XX%
Correct chunk retained @5: XX%


GENERATION

Answer Accuracy:       XX%
Faithfulness:          XX%
Answer Relevancy:      XX%
Citation Accuracy:     XX%
Hallucination Rate:    XX%
Refusal Accuracy:      XX%


CONSISTENCY

Same-question consistency: XX%

Retrieval consistency:     XX%
Reranker consistency:      XX%
Context consistency:       XX%
Generation consistency:    XX%


FAILURE DISTRIBUTION

Ingestion:              XX%
Chunking:               XX%
Query rewriting:        XX%
Retrieval:              XX%
Reranking:              XX%
Context construction:   XX%
Generation:             XX%
Hallucination:           XX%
Other:                   XX%
```

---

# PHASE 18 — PRODUCE A FAILURE TRACE

For every failed question generate a trace:

```text
QUESTION
↓
QUERY TRANSFORMATION
↓
DENSE SEARCH
↓
KEYWORD SEARCH
↓
FUSION
↓
RERANKER
↓
FINAL CHUNKS
↓
FINAL CONTEXT
↓
LLM
↓
ANSWER
↓
EXPECTED ANSWER
↓
FAILURE POINT
```

This should make debugging individual questions easy.

---

# PHASE 19 — RECOMMEND FIXES ONLY AFTER EVALUATION

Do NOT immediately rebuild the RAG system.

After collecting measurements, rank fixes:

```text
P0 — Critical
P1 — High
P2 — Medium
P3 — Optional optimization
```

For each recommendation provide:

```text
Problem
Evidence
Root cause
Recommended change
Expected improvement
Implementation effort
Risk
```

Example:

```text
P0

Problem:
Correct chunks frequently disappear after reranking.

Evidence:
Retriever Recall@10 = 98%
Reranker Recall@5 = 81%

Root Cause:
Reranker is eliminating relevant numerical/eligibility chunks.

Action:
Replace/tune reranker or increase reranker output.

Do NOT modify embeddings yet.
```

The recommendation must be evidence-driven.

---

# PHASE 20 — FINAL DECISION

At the end answer these questions clearly:

1. Is PDF extraction reliable?
2. Is chunking reliable?
3. Is the embedding model suitable?
4. Is dense retrieval reliable?
5. Is keyword retrieval needed?
6. Does hybrid retrieval improve results?
7. Is query rewriting helping or hurting?
8. Is reranking helping or hurting?
9. Is the correct context reaching the LLM?
10. Is the LLM hallucinating despite correct context?
11. Why does the same question sometimes succeed and sometimes fail?
12. Which component contributes the most failures?
13. Which advanced reasoning techniques should remain?
14. Which should be removed?
15. What is the smallest architecture change capable of achieving production-level reliability?

Most importantly:

> Identify the FIRST point in the pipeline where a successful run and a failed run diverge.

That is the primary root cause I want identified.

---

# IMPORTANT RULES

* Do not blindly rewrite the project.
* Do not assume more RAG complexity means better RAG.
* Do not change multiple components simultaneously.
* Establish a baseline first.
* Change one variable at a time.
* Preserve the existing production application while evaluating.
* Add instrumentation where required.
* Use deterministic evaluation.
* Save evaluation results so runs can be compared.
* Do not judge RAG quality using only final-answer quality.
* Retrieval and generation must be evaluated independently.
* Every optimization must demonstrate measurable improvement.
* Prefer simple architecture when accuracy is equivalent.
* Never hide failed tests.
* Do not claim an improvement without before/after metrics.

The final objective is not to create the most complicated RAG system.

The objective is to make the existing RAG system **accurate, measurable, reproducible, explainable, and consistent for the same question**.
