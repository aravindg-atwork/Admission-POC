# Working notes for this repo

> **STOP - the live code is in `AI-Bot/`, not here.** `AI-Bot/` is its own git
> repo (github.com/bow-and-baan/AI-Bot) and is what production runs; work,
> commit and deploy from there, following `AI-Bot/DEPLOY.md` §4 and
> `AI-Bot/platform/CLAUDE.md`. The `platform/` folder beside this file is an
> August 2026 snapshot that production left behind long ago. On 2026-11-09
> files copied from it overwrote newer live files (restored before any
> rebuild). Never copy anything from this folder's `platform/` to the server.
> Someone else also deploys from their own machine, so `git fetch` in
> `AI-Bot/` and diff the live container's `app/` before every deploy.
> Everything below this box describes the old snapshot.

**`platform/` is the primary system.** It's what's live on the production
server's bare IP (`http://159.69.210.30/`, port 80) as of 2026-08-21. Its
own working-notes file, `platform/CLAUDE.md`, is the one to read for
day-to-day work — architecture, deployment, roadmap, everything.

For a human-facing overview of what's live, where, and how to reach the
admin console, see `GUIDE.md` in this same directory.

## The archived system

`archived/backend/` is the original proof-of-concept this project started
from. It is **not deleted and still fully working** — production keeps it
reachable at `http://159.69.210.30/legacy/` (proxied) and directly on the
host at port `5050`. It moved out of the repo root into `archived/` on
2026-08-21 alongside its own CLI runner (`archived/run_backend.py`) and
test suite (`archived/tools/`), once `platform/` took over the primary
port.

Its own working notes, unchanged apart from a translation note at the top
explaining the path shift, are at `archived/CLAUDE.md` — read that before
touching anything under `archived/backend/`.

`archived/legacy-docs/` holds older working files (scratch notes, a couple
of superseded document exports, a couple of backup dumps) kept for
reference rather than deleted — nothing in active use lives there.

## Companion files

- `HANDOFF.md` — machine-migration setup, gitignored data transfer. Not
  updated as part of the 2026-08-21 reorganization; treat anything it says
  about `backend/` living at the repo root as superseded by this file.
