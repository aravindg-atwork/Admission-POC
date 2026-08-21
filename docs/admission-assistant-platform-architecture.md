# Admission Assistant — Platform Architecture

Admission Assistant is a multilingual, retrieval-grounded advisory platform
for undergraduate admissions. It answers a prospective student's questions
in English, Hindi, or Marathi, grounded in the institution's own published
prospectuses, with deterministic verification on every factual claim it
makes about fees, dates, eligibility, and reserved-category thresholds. This
document describes its architecture: how a query moves through the system,
how the platform stays factually accurate under real conversational
pressure, and how it is built, deployed, and operated.

## Architecture at a glance

| Layer | Design | Why it's built this way |
|---|---|---|
| Frontend | Typed, componentized build with a real bundler, accessibility-audited, scoped CSP/CORS | Every UI regression is caught before a student sees it, not after |
| API & auth | Typed API framework with an OpenAPI contract, per-admin accounts with role-based access and a full audit log, versioned routes | Every privileged action is attributable to a person, and no route change can silently break an existing integration |
| Agent / decision core | A declarative, dependency-ordered policy system rather than a flat rule list; every prompt or routing change is gated by an automated evaluation suite before it ships | Rule interaction order is treated as a first-class design surface, not an incidental side effect of how rules happen to be listed |
| Retrieval | A dedicated vector database with approximate-nearest-neighbor indexing, replicated, updated incrementally | Retrieval quality and system scalability are decoupled from any single process's memory |
| Ingestion & training | An asynchronous pipeline: OCR → structured chunking → embedding → staged validation against a golden evaluation set → promoted via blue-green swap | A knowledge update is provably correct before it reaches a single student, never live the instant it's uploaded |
| Model & provider layer | A unified inference gateway: centralized rate-limiting, cost tracking, circuit-breaking, and proactive quota alerting across every model provider | Provider exhaustion is caught before it degrades the platform, not diagnosed afterward from a slow response |
| Storage & state | Transactional storage (structured relational store) for durable records, a shared in-memory store for cache and session state | State is shared and consistent across every instance, not private to one process |
| Observability | Structured logs, persisted distributed traces, real-time dashboards, and threshold-based alerting | Any single conversation's full decision path is reconstructable after the fact, and latency regressions are caught the moment they happen |
| Testing & delivery | Every change runs the full regression and evaluation suite in an automated pipeline before merge; deploys are automated with canary rollout and one-click rollback | Correctness is a property of the pipeline, not of someone remembering to run a script |
| Deployment & infrastructure | Containerized, orchestrated, defined as code, served over TLS behind a real domain, with a staging tier that mirrors production | Every environment is reproducible, and every byte in transit is encrypted |
| Security | WAF/CDN at the edge, per-key rotation and scoping, automated dependency scanning, secrets held in a dedicated secrets manager | Defense is layered at the network edge, the credential layer, and the dependency layer independently |
| Multi-tenancy | Programmes and institutions are first-class records, onboarded through the admin console | Extending coverage to a new programme or institution is a configuration action, not a code change |
| Data governance | An explicit retention and deletion policy, aligned with applicable data-protection law for personal and academic information | Data about prospective students is handled as the sensitive category it is, by policy, not by default |

---

## Frontend

The student widget and the administrative console are built on a typed
component framework with a real build and bundling pipeline, exercised by a
component-level test suite and an accessibility pass against WCAG. Every
supported language is served through a proper internationalization layer
rather than hand-maintained per-language string tables, so adding a language
is a content task, not an engineering one. Every response the frontend
receives carries content-security and CORS policy scoped to the platform's
own known origins.

## API surface & authentication

The public and administrative APIs are defined by a typed contract — request
and response shapes are validated at the boundary and published as an
OpenAPI specification, so any client (the student widget, an embedding
partner, an internal tool) integrates against a stable, versioned interface.
Authentication is per-admin, not shared: every privileged action is tied to
an identity, scoped by role, and recorded in an audit log. Every API key is
individually rotatable and scoped to exactly the project it serves, with its
own rate limit and quota rather than one limit shared across all traffic.

## Agent / decision core

The platform's response logic is a layered decision system. A fast intent
classifier gives an initial read on what a student is asking, but every
downstream rule corroborates that read against the student's own words
before acting on it — a single model's opinion is never trusted alone for
anything the system treats as a veto. The rules themselves — recognizing an
injection attempt, a greeting, an eligibility question, a request to compare
programmes, an ambiguous or off-topic message — are expressed as an explicit,
dependency-ordered policy set, where which rule takes precedence over which
other rule is a stated design decision, not an artifact of list order.
Eligibility verdicts, fee figures, and reserved-category thresholds are never
left to a language model to compute inline: they are resolved by
deterministic logic against the institution's own published rules, and the
model's only job is to phrase an already-decided answer in the student's own
language — with a locked template and a value-substitution check as the
final safeguard against the model dropping or altering the figure it was
handed. Every change to a prompt, a rule, or a routing decision runs the
platform's own regression and ground-truth evaluation suites automatically
before it can ship.

## Retrieval

Each programme's knowledge base lives in a dedicated vector store with
approximate-nearest-neighbor indexing, updated incrementally rather than
rewritten wholesale on every change. Retrieval combines semantic similarity
with lexical and topical signals, so a densely tabular section (an admission
schedule, a fee grid) competes fairly against narrative prose instead of
being diluted by pure vector averaging. A retrieval-confidence floor sits
ahead of generation: when the best-matching content genuinely isn't relevant
to what was asked, the platform says so honestly rather than generating a
fluent answer from noise — and that honest response is never cached, so a
real answer is served the moment relevant content actually exists. Before
generation, the system also checks whether the question maps cleanly onto a
single verified figure; when it does, that figure is resolved deterministically
and the retrieval-and-generate path is skipped entirely.

## Ingestion & knowledge pipeline

Bringing a new or updated prospectus into the platform is an asynchronous,
staged process. Optical extraction preserves table structure with full
label-to-figure fidelity — a plain text extractor cannot be trusted for
fee grids and eligibility tables, where a misaligned row is a wrong number
served with full confidence. The extracted content is chunked, each table
cell is also captured as one unambiguous, directly matchable reading, and
every chunk is embedded and tagged by topic. Before a new knowledge version
reaches a single student, it is validated against the platform's own golden
evaluation set — the same figures, the same eligibility scenarios, checked
automatically — and promoted into production through a blue-green swap only
once it passes. Every chunk carries full lineage: which source page, which
extraction run, which ingestion timestamp produced it.

## Model & provider layer

Inference runs through a unified gateway that centralizes rate-limiting,
cost tracking, and circuit-breaking across every model provider the platform
uses, rather than each call site reasoning about failure independently.
Providers are tiered by role — a fast, lightweight model handles intent
classification and greetings; a stronger, quality-tuned model handles
retrieval-grounded answers, with an automatic, monitored fallback chain if
the primary is unavailable. Quota consumption is tracked continuously and
alerts before a ceiling is reached, treating provider exhaustion as an
operational risk with its own monitoring, not a failure mode discovered
after the fact from a slow response.

## Storage & state

Durable, structured records — cached answers, administrative accounts,
per-project configuration, review and audit logs — live in a transactional
relational store, with real transactional guarantees across related writes.
Ephemeral and shared state — the query cache, session data, rate-limit
counters — lives in a shared, in-memory store accessible to every instance
of the platform equally. No cache or lock is private to a single process, so
the platform can run as many instances as load requires.

## Observability

Every request emits structured logs and a distributed trace, persisted and
queryable well after the request completes — any single conversation's full
decision path, from intent classification through retrieval to the final
validation check, is reconstructable on demand, not only while someone is
actively watching a live feed. Latency, error rate, cache-hit rate, and
per-project inference cost are tracked continuously on real-time dashboards,
with threshold-based alerting so a regression in response time or an
elevated error rate is surfaced the moment it happens.

## Testing & delivery

Every code change runs the platform's full regression suite — deterministic
logic tests, conversational-flow tests, and ground-truth answer-quality
evaluation against real figures drawn from the source documents — in an
automated pipeline before it can merge. Deploys are fully automated: build,
test, canary release, and promotion, with an immediate rollback path if a
canary shows any regression. Correctness is enforced structurally, at the
pipeline level, rather than depending on a person remembering to run the
right script before shipping.

## Deployment & infrastructure

The platform runs as containerized, orchestrated services, defined entirely
as code so any environment — staging, production, a new region — is
reproducible from a single source of truth. All traffic is served over TLS
under the platform's own domain; nothing is transmitted in the clear. A
staging environment mirrors production configuration exactly, so the last
verification step before a release happens somewhere that isn't live
student traffic. The platform scales horizontally behind a load balancer,
with no single instance being a point of failure.

## Security

The network edge sits behind a WAF and CDN, absorbing and filtering
malicious and automated traffic before it ever reaches the application.
Every credential — API keys, service accounts, provider keys — is scoped
narrowly, rotated on a schedule, and held in a dedicated secrets manager,
never in a plaintext configuration file. Dependencies are scanned
automatically for known vulnerabilities as part of the delivery pipeline.
Access control, network defense, and dependency hygiene are treated as three
independent layers, so a gap in one is not a gap in all three.

## Multi-tenancy

Programmes and institutions are modeled as first-class, database-backed
records rather than fixed application configuration. Onboarding a new
programme — its eligibility rules, its own knowledge base, its own branding
— is a self-serve action through the administrative console, requiring no
code change and no deployment.

## Data governance

Conversation data, feedback, and administrative logs are subject to an
explicit, documented retention policy, with a defined mechanism to honor a
deletion request. Given that the platform processes personal and academic
information from prospective students, its data handling is deliberately
aligned with applicable data-protection law, treated as a design
requirement rather than an afterthought.

---

## Delivery sequence

Platform capabilities come online in dependency order — each phase is a
precondition for the one after it, not an independent option.

1. **Foundation** — automated testing in the delivery pipeline, structured
   logging, and secrets management in place before anything else is built
   on top.
2. **State layer** — transactional storage and shared cache/session state,
   the precondition for running more than one instance of the platform.
3. **Retrieval layer** — the dedicated vector store, unlocking real
   horizontal scale.
4. **Deployment layer** — containerization, TLS, a staging environment, and
   automated canary deploys.
5. **Security layer** — per-admin authentication and RBAC, key rotation,
   the WAF/CDN edge.
6. **Observability layer** — distributed tracing, real-time dashboards, and
   alerting.
7. **Ingestion layer** — the asynchronous, staged knowledge pipeline with
   blue-green promotion.
8. **Decision-core layer** — the declarative policy system and automated
   evaluation gating for every agent-behavior change.

Layers one through four determine the platform's basic resilience and data
integrity. Layers five through eight determine how independently and safely
it can be operated and extended.
