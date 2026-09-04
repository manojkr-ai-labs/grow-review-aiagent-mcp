# Deployment Plan — ReviewPulse on Railway

> Companion to [`architecture.md`](./architecture.md) and [`implementation-plan.md`](./implementation-plan.md).
>
> **Decision.** Host **both** the FastAPI console API and the Next.js operator UI on
> [Railway](https://railway.app), as two services in one project. The Gmail/Docs MCP server
> already runs on Railway (`mcp-gmail-google-docs-connect`); this plan adds the ReviewPulse
> app beside it, not a third platform.

This document is the ops contract for that deploy. It records what we will ship, what must
change in this repo first, and the order of work. It does **not** implement Dockerfiles or
Railway config yet.

---

## 1. Goal

A reachable operator console where an authorized person can:

1. Read the latest weekly pulse, themes, and scrubbed reviews.
2. Trigger a pipeline run (dry-run by default) and watch SSE logs.
3. Append / draft / send via the existing hosted MCP server.
4. Keep SQLite, embedding cache, publish-state, and `runs/<id>/` across restarts.

The weekly scheduler (Phase 6) is in scope as a **follow-on** on the same API service.
First go-live is **operator-triggered** from the console, with the clock wired after the
volume and auth are proven.

---

## 2. Target topology

Two Railway **services** from this repo, plus the existing MCP service (unchanged):

```
Browser
   │  HTTPS
   ▼
┌─────────────────────────────────┐
│  reviewpulse-web  (Next.js)     │  public: https://<web>.up.railway.app
│  root: web/                     │
│  rewrites /api/v1 → API         │
└──────────────┬──────────────────┘
               │  Railway private network
               │  http://reviewpulse-api.railway.internal:$PORT
               ▼
┌─────────────────────────────────┐
│  reviewpulse-api  (FastAPI)     │  not public (private networking only)
│  root: repo                     │
│  volume → data/ + runs/         │
│  uvicorn on 0.0.0.0:$PORT       │
└──────────────┬──────────────────┘
               │  HTTPS (existing)
               ▼
     mcp-gmail-google-docs-connect
     (already on Railway)
```

| Service | Repo root | Runtime | Public? |
| --- | --- | --- | --- |
| **reviewpulse-api** | repository root | Python 3.12, `reviewpulse serve` | No — private network only |
| **reviewpulse-web** | `web/` | Node 22, `next start` | Yes — the only browser URL |
| **MCP** (existing) | other repo | already deployed | Yes (bearer on `POST /mcp`) |

Keeping the API off the public internet is the v1 auth model: the browser only talks to
Next.js; Next.js proxies `/api/v1` (including SSE) to FastAPI. CORS stays unused for the
happy path.

---

## 3. Why both on Railway (not Vercel for the UI)

This is an operator console in front of a **long-running Python worker with a disk**, not a
public Next.js site with a tiny API.

| Constraint | Implication |
| --- | --- |
| SQLite, `data/cache/`, `data/publish-state.json`, `runs/` (F23) | Persistent volume on the API service. Serverless / ephemeral disks forget last week. |
| Cluster + MiniLM + Play fetch can run for minutes | A process that stays up; not a 10s serverless timeout. |
| Pipeline jobs + SSE live in the API process memory | One API replica. Restarting the API drops in-flight job logs. |
| Next rewrites `/api/v1` and `EventSource` tails `/pipeline/jobs/{id}/log` | Same-origin proxy on a long-lived Node server. Vercel rewrites buffer/timeout SSE. |
| MCP already on Railway | One vendor for secrets, private DNS, and logs. |

Vercel remains a later option if the UI becomes a public product that needs preview deploys
and a CDN. It is not the first deploy.

---

## 4. Current blockers (must fix before first deploy)

These are true of the tree **today**. The deploy will fail or be unsafe without the tasks
in §5.

| # | Blocker | Where | What happens on Railway today |
| --- | --- | --- | --- |
| B1 | `reviewpulse serve` **refuses** any host other than `127.0.0.1` / `localhost` / `::1` | `src/reviewpulse/cli.py` | Container health check never connects. Railway requires `0.0.0.0`. |
| B2 | Bind port ignores `PORT` | `cli.py`, `[console] api_port` | Railway injects `PORT` (often 8080). We still listen on 8000. |
| B3 | CORS allowlist is localhost-only | `src/reviewpulse/api/app.py` | Harmless if the API stays private and the UI uses rewrites. Required if SSE or the browser ever hits the API origin directly. |
| B4 | SSE log URL is baked to `http://127.0.0.1:8000` | `web/lib/api.ts` `jobLogUrl` | In the browser this ignores the Next rewrite and tries the operator's machine. Production must use a **relative** `/api/v1/.../log` (same origin as the UI). |
| B5 | `next start --port 3000` is hardcoded | `web/package.json` | Must listen on Railway's `PORT`. |
| B6 | Next rewrites read `REVIEWPULSE_API_ORIGIN` at **build** time | `web/next.config.ts` | Destination is serialized into the routes manifest. The internal API hostname must be a build-time env var (or we switch to a runtime rewrite). |
| B7 | `config/settings.toml` is gitignored | `.gitignore` | Image boots on `settings.example.toml` (`document_id = ""`, example recipient). Production TOML must live on the volume (or be generated at start). |
| B8 | **No auth product** | Phase 7 plan: local-only | A public Next URL is an open operator console: run pipeline, send email, patch settings. Gate the UI before sharing the link. |
| B9 | Hugging Face model download | `sentence-transformers/all-MiniLM-L6-v2` | First cluster on a cold volume hits huggingface.co. Cache the model on the volume (or bake it into the image). |
| B10 | One API replica / in-memory jobs | `api/jobs.py` | Horizontal scale of the API is forbidden in v1. Restart mid-run loses the SSE buffer (artifacts on disk still land). |

Local `127.0.0.1` behaviour must keep working. Deploy bind is opt-in via env, not a blanket
`0.0.0.0` default.

---

## 5. Code changes before first deploy

Do these in the repo, with tests, **then** create the Railway project. Order is the
suggested PR sequence.

### 5.1 API bind and `PORT` (B1, B2)

- Honor `PORT` when set (Railway contract).
- Allow `0.0.0.0` / `::` only when `REVIEWPULSE_BIND_ALL=1` (or `RAILWAY_ENVIRONMENT` is set).
- Keep the localhost refuse path for a naked `reviewpulse serve` on a laptop.
- Start command on Railway:

```text
REVIEWPULSE_BIND_ALL=1 reviewpulse serve --host 0.0.0.0 --port ${PORT:-8080}
```

CLI should treat `--port` and `PORT` as the same knob (`--port` wins if both exist).

### 5.2 CORS from env (B3)

```text
CORS_ORIGINS=https://<web>.up.railway.app,http://127.0.0.1:3000
```

Parse a comma-separated list; fall back to today's localhost pair. Needed for SSE if we
ever point `EventSource` at the API origin; cheap insurance even with private API.

### 5.3 Same-origin SSE (B4)

`jobLogUrl` must return `/api/v1/pipeline/jobs/{id}/log` in production so the browser
talks to the Next origin. Keep `NEXT_PUBLIC_API_ORIGIN` only as a **local** override for
`npm run dev` without the rewrite (optional). Playwright should cover relative EventSource.

### 5.4 Next listen port (B5)

```json
"start": "next start --hostname 0.0.0.0 --port ${PORT:-3000}"
```

Use a tiny `start` script if Windows npm does not expand `${PORT}` the same way — Railway
is Linux, so a `node`/`sh` wrapper is acceptable and clearer.

### 5.5 Rewrite destination (B6)

Set on the **web** service (available at `next build`):

```text
REVIEWPULSE_API_ORIGIN=http://reviewpulse-api.railway.internal:8080
```

Pin the API to **8080** (Railway default) so the rewrite host:port is stable across
redeploys. Document the pin in the API start command.

If Railway private DNS is not ready at first web build, temporarily use the API's public
`*.up.railway.app` URL at build time, then switch to internal and **rebuild** the web
service. Do not leave the API public once private networking works.

### 5.6 Operator gate (B8)

v1 is a shared secret, not a user database.

**Recommended:** HTTP Basic Auth (or a single bearer cookie) in Next.js **middleware** on
the web service. Env:

```text
CONSOLE_BASIC_USER=...
CONSOLE_BASIC_PASSWORD=...
```

The API stays private, so the password only protects the UI. Add a matching
`X-Reviewpulse-Cron-Key` (or Basic) later for the scheduler HTTP tick so cron is not an
unauthenticated `POST /pipeline/run`.

Until this lands, do not add a custom domain or share the Railway URL.

### 5.7 Volume-friendly paths (B7, B9)

Optional but cleaner than start-script symlinks: honor

```text
REVIEWPULSE_DATA_DIR=/persistent/data
REVIEWPULSE_RUNS_DIR=/persistent/runs
HF_HOME=/persistent/hf
```

If we skip the code change, the start script must symlink `data/` and `runs/` onto the
volume (§7). Either way, **do not** write SQLite on the container overlay filesystem.

### 5.8 Health

`GET /api/v1/health` already exists. Railway health check path: `/api/v1/health`.
Web health: `/` (or a tiny `/health` route if `/` is gated by Basic Auth — health checks
must not require the password). Prefer an ungated `GET /health` on Next that returns 200.

---

## 6. Railway project layout

One Railway **project** (e.g. `reviewpulse`), three services (two new):

```
reviewpulse/
├─ reviewpulse-api     ← this repo, root directory = /
├─ reviewpulse-web     ← this repo, root directory = web
└─ mcp-gmail-...       ← existing, do not rebuild from this repo
```

### 6.1 API service

| Setting | Value |
| --- | --- |
| Root directory | `/` (repo root) |
| Builder | Dockerfile (`Dockerfile.api`) preferred; Nixpacks only if the Dockerfile is delayed |
| Watch paths | `src/**`, `pyproject.toml`, `config/taxonomy.toml`, `Dockerfile.api` |
| Start | see §5.1 |
| Restart policy | on failure |
| Replicas | **1** |
| App sleep | **off** (Hobby sleep kills in-flight runs and drops the SQLite lock) |

Python extras: `pip install -e ".[web]"` so FastAPI + uvicorn are present.
`sentence-transformers` pulls CPU torch — expect a **large** image and a slow first build.

Do **not** copy `.env` or `config/settings.toml` into the image. Copy
`config/settings.example.toml` and `config/taxonomy.toml`.

### 6.2 Web service

| Setting | Value |
| --- | --- |
| Root directory | `web` |
| Builder | Dockerfile (`web/Dockerfile`) or Nixpacks Node |
| Watch paths | `web/**` excluding `web/.next`, `web/node_modules` |
| Install | `npm ci` |
| Build | `npm run build` with `REVIEWPULSE_API_ORIGIN` set |
| Start | `npm start` on `0.0.0.0:$PORT` |
| Replicas | 1 is enough |

`NEXT_PUBLIC_*` values are inlined at build. Do not put secrets in `NEXT_PUBLIC_*`.
The Basic Auth password is server-only (`CONSOLE_BASIC_*`).

### 6.3 Suggested repo files (not created by this document)

| File | Role |
| --- | --- |
| `Dockerfile.api` | Python 3.12-slim, install `.[web]`, non-root user, `CMD` serve |
| `web/Dockerfile` | Node 22, `npm ci` + `npm run build`, `npm start` |
| `.dockerignore` | `.venv`, `web/node_modules`, `web/.next`, `data/`, `runs/`, `.env` |
| `web/.dockerignore` | `node_modules`, `.next` |
| `railway.toml` or service dashboard | health checks, restart policy |

Nixpacks can substitute for Dockerfiles on a first spike; pin Dockerfiles before treating
the deploy as durable (reproducible torch/CPU wheels).

---

## 7. Persistent volume (API only)

F23 still holds: GitHub Actions and a volume-less Railway container will re-download the
corpus and forget Doc append / Gmail `message_id`.

Attach **one volume** to **reviewpulse-api** only (Railway volumes are one service).

| Mount | Suggested path | Holds |
| --- | --- | --- |
| Volume | `/persistent` | everything that must survive a deploy |

Layout on the volume:

```
/persistent/
├─ data/
│  ├─ reviews.db
│  ├─ cache/                 # embedding npz
│  ├─ raw/                   # Play CSVs
│  ├─ exports/
│  ├─ publish-state.json
│  └─ schedule.lock
├─ runs/                     # runs/<run_id>/manifest.json, note.md, …
├─ config/
│  └─ settings.toml          # production overlay (document_id, recipient, …)
└─ hf/                       # Hugging Face / MiniLM weights
```

**Seed once** (Railway shell or a first-boot script):

1. If `/persistent/config/settings.toml` is missing, copy `config/settings.example.toml`
   and set `mcp.gdocs.document_id` + `gmail.recipient_alias`.
2. Point the process at that file (`REVIEWPULSE_SETTINGS=/persistent/config/settings.toml`
   — requires a small `load_settings` hook — **or** symlink
   `config/settings.toml` → the volume file).
3. First pipeline run fills `reviews.db`, cache, and `hf/`.

Web service: **no volume**. It is stateless.

Do not commit production `settings.toml`. Treat `document_id` and recipient as sensitive.

---

## 8. Networking

### 8.1 Private API, public UI

1. Generate a domain on **reviewpulse-web** (`*.up.railway.app` is enough for v1).
2. **Do not** generate a public domain on **reviewpulse-api** once private networking works.
3. Put both services in the same Railway environment so `*.railway.internal` resolves.
4. Service name **must** match the rewrite host (`reviewpulse-api`).

### 8.2 What the browser calls

| Call | Browser URL | Server-side destination |
| --- | --- | --- |
| Pages | `https://<web>/…` | Next |
| JSON API | `https://<web>/api/v1/…` | rewrite → FastAPI |
| SSE logs | `https://<web>/api/v1/pipeline/jobs/{id}/log` | rewrite → FastAPI (after §5.3) |

### 8.3 Outbound from the API

| Destination | Why |
| --- | --- |
| Play Store (unauthenticated scrape) | `google-play-scraper` |
| Groq API | theme labels (`GROQ_API_KEY`) |
| Google Generative Language API | pulse compose (`GEMINI_API_KEY`) |
| Hugging Face | first MiniLM download (then volume cache) |
| `https://mcp-gmail-google-docs-connect-production.up.railway.app/mcp` | Docs + Gmail |

No Google OAuth in this repo. MCP bearer is `MCP_AUTH_TOKEN` (same token the MCP service
already expects).

---

## 9. Configuration and secrets

Railway **variables**. Never bake keys into the image or into `NEXT_PUBLIC_*`.

### 9.1 API service

| Variable | Required | Notes |
| --- | --- | --- |
| `PORT` | injected | Bind this. Pin start to 8080 if the web rewrite is hardcoded to 8080. |
| `REVIEWPULSE_BIND_ALL` | yes | `1` |
| `GROQ_API_KEY` | for labels | Same as local `.env`. Missing → keyword fallback. |
| `GEMINI_API_KEY` | for compose | Missing → deterministic pulse frame. |
| `MCP_AUTH_TOKEN` | for live publish | Must match the MCP service. |
| `CORS_ORIGINS` | if API is ever public | Web origin(s). |
| `OPERATOR_INITIALS` | no | Console avatar; default `MK`. |
| `HF_HOME` | yes | `/persistent/hf` |
| `HUGGINGFACE_HUB_TOKEN` | no | Only if the hub rate-limits anonymous pulls. |
| `REVIEWPULSE_SETTINGS` | recommended | `/persistent/config/settings.toml` |

`load_env_file()` already skips keys that are already in `os.environ`, so Railway variables
win over a `.env` that should not exist in the image anyway.

Non-secret MCP URL, models, window, and package id stay in `settings.toml` on the volume.
`auth_token = "${MCP_AUTH_TOKEN}"` already expands from the environment.

### 9.2 Web service

| Variable | Required | When |
| --- | --- | --- |
| `PORT` | injected | `next start` |
| `REVIEWPULSE_API_ORIGIN` | yes | Build **and** runtime if we move rewrites to runtime. Internal URL. |
| `CONSOLE_BASIC_USER` | yes before public | Middleware |
| `CONSOLE_BASIC_PASSWORD` | yes before public | Middleware |

No LLM or MCP tokens on the web service.

### 9.3 Shared / documentation

Keep `config/settings.example.toml` as the template. Production differences vs example:

- `[mcp].url` — already the hosted Railway MCP URL.
- `[mcp.gdocs].document_id` — real Doc the MCP Google account can edit.
- `[gmail].recipient_alias` — real inbox.
- `[console].api_host` / `api_port` — unused for bind once CLI honors `PORT`; leave as
  documentation of local defaults.

---

## 10. Scheduler (Phase 6 on Railway)

Do **not** attach a second volume to a cron worker. Railway volumes do not shared-mount
cleanly across services.

**v1 go-live:** no clock. Operator hits **Run Pipeline** in the console.

**v1.1 clock** (pick one):

| Option | How | Pros | Cons |
| --- | --- | --- | --- |
| **A. HTTP cron** (preferred) | Railway Cron weekly `POST https://<web>/api/v1/pipeline/run` with cron key, `{dry_run:false, send:true}` | Same process as the UI; lock + SSE + volume already there | Needs cron key; rewrite must forward the header |
| **B. Sidecar in the API container** | `reviewpulse schedule` loop beside uvicorn (supervisord / a tiny wrapper) | No extra HTTP | Two processes, harder health checks |
| **C. `schedule --once` one-off** | Cron starts a **new** container | Familiar CLI | **Wrong** unless that container mounts the **same** volume — it cannot |

Crontab equivalent to keep: Monday 09:00 `Asia/Kolkata` = **03:30 UTC Monday**.

Until A or B ships, disable `[schedule] send_email` surprises by simply not running the
job. Console **Run with send** remains an explicit operator action.

---

## 11. Sizing and cost

| Service | RAM | CPU | Disk (volume) | Notes |
| --- | --- | --- | --- | --- |
| **reviewpulse-api** | **2 GB** | 1 vCPU | 5 GB start | MiniLM + sklearn + torch + SQLite. 512 MB will OOM on cluster. |
| **reviewpulse-web** | 512 MB | shared | none | `next start` is light. |
| MCP | already sized | — | — | Unchanged. |

Trial / Hobby **sleep** will freeze SQLite and drop job state. Use a plan that keeps the
API awake, or accept “cold start + empty in-memory jobs” and never schedule unattended
send on a sleeping box.

First API build: several minutes (torch wheels). First pipeline: extra minutes if MiniLM
is not cached. After that, embedding cache in `data/cache/` makes re-runs fast.

---

## 12. Security

| Rule | Why |
| --- | --- |
| API not on a public domain | No auth on FastAPI today. |
| Basic Auth (or equivalent) on the web service before sharing the URL | Pipeline run and `send` are destructive. |
| Secrets only in Railway variables | `.env` and `settings.toml` stay gitignored. |
| Reviews API still never returns `author` | Unchanged product invariant. |
| Settings JSON still never returns raw keys | Unchanged. |
| One API replica | In-memory jobs + file lock. |
| Dry-run default in the UI | Same as local console. First production click must not `--send`. |

Rotate `MCP_AUTH_TOKEN` in **both** this API service and the MCP service together.

---

## 13. Rollout sequence

Do not skip steps. Each has an abort condition.

### Step 0 — Repo

1. Land §5 code changes locally.
2. Confirm laptop still works: `reviewpulse serve` on 127.0.0.1 + `npm run dev`.
3. Confirm `REVIEWPULSE_BIND_ALL=1 reviewpulse serve --host 0.0.0.0 --port 8080` accepts
   `curl http://127.0.0.1:8080/api/v1/health`.
4. Add Dockerfiles + `.dockerignore` when ready to connect GitHub → Railway.

### Step 1 — Railway project

1. New project from this GitHub repo (or empty project + two services from the same repo).
2. Create **reviewpulse-api** (root `/`) and **reviewpulse-web** (root `web`).
3. Attach volume to API at `/persistent`.
4. Set API env vars (§9.1). Do not expose a public API domain yet if private DNS works;
   for a first smoke you may temporarily public-expose the API, hit `/health`, then lock it
   down.

### Step 2 — API smoke (no UI)

1. Deploy API. Health check `/api/v1/health` → `ok`.
2. Railway shell: `reviewpulse mcp-check` (needs `MCP_AUTH_TOKEN` + `document_id` on volume).
3. Optional: `reviewpulse run --dry-run --window-weeks 4` once to seed SQLite and MiniLM
   onto the volume (slow, expected).

Abort if mcp-check fails or the volume is empty after the dry-run (mount is wrong).

### Step 3 — Web

1. Set `REVIEWPULSE_API_ORIGIN` to the **internal** API URL (or temporary public URL).
2. Set Basic Auth env.
3. Deploy web. Open `/health` (ungated) then `/` (gated).
4. Pulse / themes / reviews render from the dry-run artifacts.

Abort if the browser shows API errors or EventSource still points at `127.0.0.1:8000`.

### Step 4 — Live publish (manual)

1. In the console, MCP chip live.
2. Dry-run pipeline from **Pipeline** — SSE lines stream; a new row on **Runs**.
3. **Do not send** on the first live run. Append-only or draft-only after gates pass.
4. Confirm Google Doc + Gmail draft, then a second run with send if Phase 6 behaviour is
   wanted.

### Step 5 — Lock down

1. Remove any public domain from the API service.
2. Rebuild web so rewrites use `*.railway.internal`.
3. Confirm the UI still works.
4. Only then add a custom domain / share the URL.

### Step 6 — Clock (later)

HTTP cron (§10 option A) with a cron key. Watch one Monday tick before trusting send.

---

## 14. Verification

| Check | Pass |
| --- | --- |
| `GET /api/v1/health` on API (private or smoke URL) | `{"ok": true, ...}` |
| Web `/health` | 200 without credentials |
| Web `/` | 401 without Basic; 200 with |
| Weekly Pulse | KPIs from `manifest.json`, not Stitch placeholders |
| Reviews | no `author` column; scrubbed text only |
| Dry-run from UI | new `runs/<id>/` on the volume; SSE completes |
| Redeploy API | `reviews.db` and last run still present |
| `mcp-check` from API container | tools listed; 401 without token |
| Kill API mid-thought | in-flight SSE dies; completed artifacts remain |
| `send` | still confirm-modal; still MCP-only |

Contract tests stay in CI (`tests/contract/test_api.py`). They do not replace the Railway
smoke. Playwright against production is optional; local e2e is enough if Step 3 is walked
in a browser.

---

## 15. Local vs Railway

| | Local | Railway |
| --- | --- | --- |
| API | `reviewpulse serve` → 127.0.0.1:8000 | `0.0.0.0:$PORT`, bind-all env |
| UI | `cd web && npm run dev` | `next start` |
| Data | repo `data/`, `runs/` | `/persistent/...` |
| Secrets | `.env` | Railway variables |
| Settings | `config/settings.toml` | volume copy of TOML |
| MCP | same hosted URL | same hosted URL |
| Auth | none (loopback) | Basic on web |

---

## 16. Out of scope (v1)

- Frontend on Vercel, Cloudflare Pages, or a second cloud.
- Backend on Vercel / Cloud Run / Lambda.
- Postgres / migrating off SQLite.
- Multi-replica API or a job queue (Redis/Celery).
- Real user accounts, SSO, or Groww VPN — Basic Auth is the gate.
- Baking GPU torch; CPU MiniLM is enough.
- Changing the MCP server or Google OAuth (lives in the other repo).
- GitHub Actions as the weekly clock (F23).

---

## 17. Task list

Implementation work after this plan is accepted:

| # | Task | Depends on |
| --- | --- | --- |
| D1 | Bind `0.0.0.0` + `PORT` behind `REVIEWPULSE_BIND_ALL` | — |
| D2 | `CORS_ORIGINS` env | — |
| D3 | Relative `jobLogUrl`; optional local `NEXT_PUBLIC_API_ORIGIN` | — |
| D4 | Next `start` honors `PORT`; ungated `/health` | — |
| D5 | Basic Auth middleware + env | D4 |
| D6 | Data/runs/settings paths (env or start-script symlinks) | — |
| D7 | `Dockerfile.api`, `web/Dockerfile`, dockerignores | D1–D4 |
| D8 | Create Railway project, two services, volume, variables | D7 |
| D9 | Seed volume `settings.toml`; API smoke + mcp-check | D8 |
| D10 | Web deploy, rewrite to private DNS, browser walkthrough | D5, D9 |
| D11 | First dry-run from UI on Railway; then draft/append | D10 |
| D12 | Remove public API domain; rebuild web | D10 |
| D13 | HTTP cron + cron key (optional) | D5, D12 |

---

## 18. Go-live checklist

- [ ] §5 code landed; local serve + console still work
- [ ] API image builds; `/api/v1/health` green on Railway
- [ ] Volume mounted; `reviews.db` survives a redeploy
- [ ] MiniLM cached under `HF_HOME` after first cluster
- [ ] `settings.toml` on the volume has real Doc id + recipient
- [ ] `GROQ_API_KEY`, `GEMINI_API_KEY`, `MCP_AUTH_TOKEN` set on API only
- [ ] Web Basic Auth on; `/health` ungated
- [ ] Browser JSON and SSE go to the **web** origin, not `127.0.0.1`
- [ ] API has no public domain (or it is removed after smoke)
- [ ] Dry-run from Pipeline succeeds; Runs shows the new id
- [ ] Live append/draft verified; send only after that
- [ ] Hobby sleep disabled on the API service
- [ ] Scheduler **not** enabled until HTTP cron (or sidecar) is tested

When every box is ticked, ReviewPulse is deployed: UI on Railway, API on Railway, MCP
where it already is.
