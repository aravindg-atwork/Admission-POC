# AI Admission Assistant — POC

RAG-based chat/voice assistant that answers admission questions from the
prospectus PDF, with page-number citations. Built to slot alongside the
existing admission system, which runs **.NET Framework 4.5 / ASP.NET WebForms**.

## Why the architecture looks like this

.NET Framework 4.5 (2012) predates .NET Standard, so most modern AI/ML
libraries — the Anthropic SDK, ONNX Runtime, HuggingFace `transformers` —
don't target it. Rather than fight the framework, each piece is placed where
it actually works, and the boundaries between them are plain HTTP:

- **`src/AdmissionAssistant.Web`** — ASP.NET WebForms (`Default.aspx`, the
  chat UI shell) + Web API 2 controllers, all .NET Framework 4.5. This is
  the part that can later be merged into the real admission codebase.
- **`src/AdmissionAssistant.Core`** — class library with the actual pipeline
  logic: PDF parsing (iTextSharp), chunking, cosine-similarity vector search,
  and thin `HttpClient` wrappers for the embedding service and Claude.
- **`services/embedding-service`** — a small Python/FastAPI service wrapping
  the open-source `nomic-ai/nomic-embed-text-v1` model via
  `sentence-transformers`. .NET 4.5 can't load this model in-process, so it's
  isolated here and called over `POST /embed`, the same way it would call
  any other embeddings API.
- **`data/vector-store`** — embeddings persisted as a single JSON file,
  loaded into memory and searched with cosine similarity in C#. At POC scale
  (one prospectus, a few hundred chunks) this is fast enough and needs no
  extra infrastructure to deploy.

Claude is called directly via `HttpClient` against the Messages API
(`AdmissionAssistant.Core/Llm/ClaudeChatClient.cs`) since no official
Anthropic SDK targets .NET Framework 4.5.

## Which LLM

Default is **Ollama running an open-source model locally** — no API key, no
billing, which is what "no paid APIs" for a POC actually means. Ollama
exposes a REST API on `localhost:11434`, so `OllamaChatClient.cs` is just
another `HttpClient` call, same shape as the Claude client.

```
ChatProvider   = Ollama   (default) | Claude
OllamaBaseUrl  = http://localhost:11434
OllamaModel    = llama3.1
```

Install [Ollama](https://ollama.com), then:

```
ollama pull llama3.1
```

`llama3.1:8b` needs ~8 GB RAM; if that's tight, `ollama pull llama3.2:3b` and
set `OllamaModel` to `llama3.2` instead — smaller and faster, somewhat less
capable. Llama 3.1 officially supports Hindi; Tamil quality is unverified —
test it early in the Day 2 multilingual pass, since the original pipeline
already has a "Translate (if needed)" step as a fallback if a language
doesn't hold up well.

`ClaudeChatClient` is left wired in behind the same `IChatClient` interface
for later, once there's a production budget — flip `ChatProvider` to
`Claude` and set `ClaudeApiKey` to switch, no code changes.

## Local vs. remote toggle

The Web API controllers never call the pipeline pieces directly — they go
through `IAssistantService` (`AdmissionAssistant.Core/Rag/IAssistantService.cs`),
and `Web.config` decides which implementation gets built:

```xml
<add key="AssistantMode" value="Local" />   <!-- or "Remote" -->
<add key="RemoteAssistantServiceUrl" value="http://localhost:9000" />
```

- **`Local`** (default) — `LocalAssistantService` runs chunking, retrieval,
  and prompting in-process, right here in C# you can step through. This is
  the mode for learning how the pipeline actually works and for the code
  that eventually merges into the real WebForms app.
- **`Remote`** — `RemoteAssistantService` forwards the whole request to an
  external base URL's `/api/chat` and `/api/ingest`, using the exact same
  JSON contract this app's own controllers expose. Any service that speaks
  that contract — a fuller standalone Python/Node implementation, someone
  else's microservice — can be swapped in by changing one config value, no
  controller or Web project changes required.

Both modes are wired through `AdmissionAssistant.Web/Config/AssistantServiceFactory.cs`.

## Embedding-service API keys

`embedding-service` gates `/embed` behind per-consumer API keys instead of
one shared secret, so any consuming app can be individually deactivated
without touching the others. Generate and toggle keys at
`http://localhost:8000/admin` (see
`services/embedding-service/README.md#managing-api-keys`). The key for this
WebForms app goes in `Web.config` as `EmbeddingServiceApiKey`.

## Data flow

```
Admin uploads prospectus.pdf
  -> POST /api/ingest (IngestController)
  -> ProspectusPdfReader (iTextSharp, page-aware)
  -> TextChunker (sliding window, keeps page number per chunk)
  -> embedding-service /embed  (per chunk)
  -> JsonVectorStore.Save()  -> data/vector-store/vector-store.json

Student asks a question
  -> POST /api/chat (ChatController)
  -> embedding-service /embed  (question)
  -> JsonVectorStore.Search()  (cosine similarity, top-K chunks)
  -> ClaudeChatClient.AskAsync()  (context + citation-instructed system prompt)
  -> answer + page references  -> chat.js renders it
```

## Project layout

```
AdmissionAssistantPOC.sln
src/
  AdmissionAssistant.Core/     class library (net45) — pipeline logic
  AdmissionAssistant.Web/      WebForms + Web API 2 (net45) — UI + endpoints
services/
  embedding-service/           Python FastAPI — nomic-embed-text
data/
  prospectus/                  uploaded PDF(s)
  vector-store/                vector-store.json
```

## Running it

**Core library** — builds with the plain `dotnet` CLI, verified on this
machine:

```
cd src/AdmissionAssistant.Core
dotnet build
```

**Web project** — this is a classic ASP.NET Web Application project
(WebForms + Web API 2). It needs **Visual Studio 2022 with the "ASP.NET and
web development" workload** to restore packages, build, and run via IIS
Express — this dev machine has neither VS nor IIS Express installed, so the
`.csproj` is authored to the standard VS template shape but hasn't been
build-verified here. Open `AdmissionAssistantPOC.sln` in VS, let it restore
NuGet packages, and press F5.

**Embedding service**:

```
cd services/embedding-service
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Before running the Web project, set `ClaudeApiKey` in
`src/AdmissionAssistant.Web/Web.config` (`<appSettings>`).

## Status

Day 1 foundation (architecture + project setup) is in place. Ingestion
pipeline and RAG service have working code but haven't been exercised
end-to-end yet — that's the next step, once a real prospectus PDF and a
Claude API key are available to test against.

Voice (STT/TTS) is deferred to Day 2 per the original plan.
