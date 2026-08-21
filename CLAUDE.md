# Working notes for this repo

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
