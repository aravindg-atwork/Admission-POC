# MAFSU Admission Assistant — Guide

One place to find what's live, where, and how to reach it. Deeper
technical notes live in `platform/CLAUDE.md` (primary system) and
`archived/CLAUDE.md` (archived system) — this file is the map, not the
manual.

## What's live right now (production: `159.69.210.30`)

| What | Where | Notes |
|---|---|---|
| Student chat (new system) | `http://159.69.210.30/` | Primary, port 80. B.V.Sc., B.F.Sc., B.Tech. (Dairy Technology). |
| New system's API | `http://159.69.210.30/api/...` | Same origin, proxied by nginx. |
| Old system (archived) | `http://159.69.210.30/legacy/` | Proxied through to the original POC, still running on the host at port `5050`. Kept reachable, not decommissioned. |
| Admin console | *not publicly reachable — see below* | Deliberately not exposed on plain HTTP. |

## Admin console access

The admin console reviews real conversations and lets an admin publish
corrected answers, so it is **not** exposed on the public port — this
whole site is still plain HTTP (no domain/TLS yet), and sending an admin
key or student transcripts over that would be readable by anyone on the
network path.

Instead it's bound only to the server's own loopback interface on port
`8443`. Reach it by tunneling in:

```bash
ssh -L 8443:127.0.0.1:8443 root@159.69.210.30
```

then, with that terminal still open, browse to:

```
http://127.0.0.1:8443/admin/
```

**Admin key** (send it as the `X-Admin-Key` header, or paste it into the
console's own login field):

```
d6a6c8a27fb8436a924cb6af0763d80b56e23f7b512dc015
```

> This key only protects something reachable through an SSH tunnel to a
> server you already control — real, but low-exposure. Treat it as a
> secret anyway (don't paste it into chat tools, tickets, or anywhere
> outside this repo). It lives in `/opt/admission-platform/infra/.env` on
> the server (`ADMIN_API_KEY=...`) if it ever needs to be looked up or
> rotated; rotating means changing it there and redeploying
> (`docker compose -f docker-compose.prod.yml up -d api web`).

## The two systems, in short

- **`platform/`** — the current, primary system. FastAPI + React +
  Postgres + Redis + Qdrant, all in Docker. Full working notes,
  roadmap, and decision history: `platform/CLAUDE.md`.
- **`archived/backend/`** — the original proof-of-concept this project
  started from. Plain-Python, no framework, still fully functional and
  still serving `/legacy/` in production. Working notes:
  `archived/CLAUDE.md`.

Both systems answer from the same three programmes' real prospectuses
(B.V.Sc. & A.H., B.F.Sc., B.Tech. Dairy Technology) — Maharashtra Animal
& Fishery Sciences University, three undergraduate admissions.

## Running things locally

**New system** (`platform/`):
```bash
cd platform/infra
docker compose up -d --build
curl http://127.0.0.1:8100/healthz
```
Frontend at `http://localhost:5180`. Details, including the SSH tunnel
needed for local embeddings, in `platform/CLAUDE.md`'s "How to run it"
and "CHECKPOINT" sections.

**Archived system** (`archived/backend/`):
```bat
.venv-backend\Scripts\python.exe archived\run_backend.py
```
Serves on `:5050` — student widget at `/`, its own operator console at
`/admin`. Details in `archived/CLAUDE.md`.

## Further reading

- `platform/CLAUDE.md` — the primary system's full working notes:
  architecture, deployment topology, roadmap, decision log.
- `archived/CLAUDE.md` — the archived system's full working notes,
  preserved as-is (guard logic, provider quirks, benchmark history).
- `docs/admission-assistant-platform-architecture.md` — standalone
  architecture writeup, written for a non-Claude, leadership audience.
- `docs/admission-assistant-complete-guide.md` — the full-scope
  explainer doc (scope, cost comparison, limitations) in plain language.
- `docs/admission-bot-end-to-end-system-flow.drawio.xml` — two-page
  diagram: query decision logic, and infrastructure/deployment.
