# Groww Review Intelligence Agent

Turns Google Play Store reviews for Groww into a weekly pulse: themes, verbatim quotes, and
action ideas — published to Google Docs and Gmail via MCP.

## Status

**Phase 1–7 complete** — fetch, ingest, clustering, pulse, hosted MCP append + Gmail draft/send, weekly scheduler, and the ReviewPulse operator console (Next.js).

## Requirements

- Python 3.11+
- See `pyproject.toml` for dependencies

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev,web]"

cp config/settings.example.toml config/settings.toml
cp .env.example .env            # fill GROQ_API_KEY, GEMINI_API_KEY, MCP_AUTH_TOKEN
```

Two stages call a model, and they use different providers:

| Stage | Provider | Key | Configured in |
| --- | --- | --- | --- |
| Theme labeling | [Groq](https://console.groq.com/keys), `openai/gpt-oss-120b` | `GROQ_API_KEY` | `[llm]` |
| Pulse composition | [Gemini](https://aistudio.google.com/apikey), `gemini-3.6-flash` | `GEMINI_API_KEY` | `[pulse.llm]` |

Both free tiers need no card. The two are independent: either key can be absent
and only that stage falls back to its deterministic path, saying so in the run's
warnings. Everything else in the pipeline is offline.

## Getting review data

Review data is downloaded automatically — there is no manual export step and no
Google account, API key, or OAuth flow involved. Play Store reviews are public,
and `google-play-scraper` reads the same unauthenticated endpoint the store's
web listing uses.

```bash
reviewpulse ingest --window-weeks 8    # download + scrub + store, one command
```

The download lands in `data/raw/play_<package>_<weeks>w_<date>.csv` (git-ignored)
using Play Console export column names, then flows straight into
`data/reviews.db`. Reviewer names are discarded at download time, so PII never
reaches disk. Re-running is idempotent — existing reviews are deduped by
`review_id`.

Which app gets downloaded is set by `package_id` in `config/settings.toml`,
defaulting to `com.nextbillion.groww` — the `id=` parameter in the Play Store
URL. Every run prints the resolved store listing (`Groww Stocks, Mutual Fund,
IPO by Billionbrains Garage Ventures Limited`) so a wrong package is obvious
before any data is stored, and `package_id` is recorded in the run manifest.

Language and country come from `[fetch]` in `config/settings.toml` (defaults
`en` / `in`). Use `fetch` on its own when you only want the CSV:

```bash
reviewpulse fetch --window-weeks 8              # download only
reviewpulse fetch --window-weeks 8 --ingest     # same as `ingest --window-weeks 8`
```

If the endpoint runs out of pages before covering the requested window, the run
prints a coverage warning naming the oldest date actually reached.

## Quality filters

Two filters run after scrubbing, before storage, configured under `[ingest]` in
`config/settings.toml`:

| Setting | Default | Effect |
| --- | --- | --- |
| `min_words` | `8` | Drops reviews with fewer than 8 words ("good app", "nice") |
| `english_only` | `true` | Drops non-English reviews |

Language detection is rule-based, so ingest stays deterministic and every
rejection carries a reason. It combines three signals: non-Latin script
detection (Devanagari, Tamil, Telugu, Bengali, Arabic, CJK and more), a
romanized-Indic marker list that catches Hinglish written in Latin script
("bahut accha app hai"), and the share of tokens recognised as common English.
Per-reason counts land in `runs/<run_id>/manifest.json` under `filters`.

Set `min_words = 0` and `english_only = false` to store everything.

## Where the data lands

| Path | Contents | Refreshed by |
| --- | --- | --- |
| `data/raw/play_<package>_<weeks>w_<date>.csv` | Raw download, **unfiltered** | `fetch` |
| `data/reviews.db` | Scrubbed + filtered reviews | `ingest` |
| `data/exports/play_store.csv` | Same rows as the database, readable CSV | `ingest` (auto), `export` |

`data/raw/` is deliberately left unfiltered so the filtering step stays
auditable against its own input. `data/exports/play_store.csv` is the
post-filter view and is rewritten on every ingest, so it cannot drift out of
sync with the database. Regenerate it on its own with:

```bash
reviewpulse export
```

## Themes

`reviewpulse cluster` groups stored reviews into at most five themes and ranks
them by how much negative feedback they carry:

```bash
reviewpulse cluster --window-weeks 8            # embeddings + LLM labels
reviewpulse cluster --window-weeks 8 --no-llm   # deterministic keyword labels
reviewpulse cluster --mode keyword_fallback     # no embeddings at all
```

Three choices in this stage are driven by measurements on the real corpus,
recorded in `docs/implementation-plan.md` §4.2:

| Behaviour | Why | Setting |
| --- | --- | --- |
| Short 4–5★ praise is dropped before clustering | 23% of reviews are "super app nice"; left in, they form their own cluster and crowd out actionable feedback | `signal_min_words`, `signal_max_rating` |
| Ward linkage, with a balance guard | Cosine/average linkage put 98.7% of reviews in one cluster at every k from 2 to 8 — while scoring the *best* silhouette, so silhouette cannot be trusted here | `linkage`, `max_cluster_share` |
| Themes ranked by `size × negative share`, not size | The biggest clusters are praise; size ranking buried a 92%-negative support theme below a 4.6-star one | `rank_by` |

Each run writes its artifacts to `runs/<run_id>/`:

| File | Written by | Contents |
| --- | --- | --- |
| `clusters.json` | `cluster` | Themes with labels, member `review_id`s, and all statistics |
| `cluster_debug.json` | `cluster` | Silhouette, size histogram, which fallback rung was used, per-cluster top terms |
| `note.md` | `pulse` | The rendered weekly note — only written when every gate passed |
| `note.rejected.md` | `pulse` | The note that failed, kept for inspection instead of published |
| `publish.json` | `pulse` | Idempotency key and the payloads a real publish would have sent |
| `manifest.json` | both | Window, configuration, themes, quotes, gate results, publish identity |

The manifest is extended rather than replaced as the run progresses, so tracing a
questioned quote back to a review row takes one file: theme → member
`review_id`s → the quote's own `review_id`, with its selection scores alongside.

Labeling calls an LLM only if `GROQ_API_KEY` is set; otherwise it derives labels
from the keyword taxonomy in `config/taxonomy.toml` and says so in the output.
Labels that describe sentiment rather than a product surface ("Negative
feedback") are rejected, retried once, then replaced by a keyword label.
Embeddings are cached in `data/cache/` keyed by `review_id`, so re-runs on the
same window skip the model entirely (~22s cold, ~2s warm on 855 reviews).

### Labeling model and rate limits

`openai/gpt-oss-120b` on Groq, asked for its answer through Groq's
structured-output API so the label and summary always parse. **All five themes
are named in one call**, and only themes whose label was rejected are re-asked,
so a run costs one request and about 1.3K tokens — two and 2.6K in the worst
case. The free tier's quotas live in `[llm]` in `config/settings.toml`:

| Quota | Free tier | Used by one run |
| --- | --- | --- |
| Requests per minute | 30 | 1–2 |
| Requests per day | 1,000 | 1–2 |
| Tokens per minute | 8,000 | ~1,300–2,600 |
| Tokens per day | 200,000 | ~1,300–2,600 |

Tokens are the binding limit, not requests, which is why the stage is shaped
around them:

| Choice | Saving |
| --- | --- |
| One call for all themes, not one per theme | The naming rules and the response schema are sent once per run instead of five times (~1,040 tokens) |
| Only rejected themes are re-asked | A retry costs one theme, not all five |
| `samples_per_theme = 6`, from the short end of the quotable band | 6 short samples name a surface as well as 10 long ones, at 40% of the tokens, and arrive untruncated |
| Cluster size, mean rating, and negative share are not sent | The per-sample star ratings already carry the sentiment, and the prompt had to forbid restating the numbers anyway |

Together those took the stage from 5 calls and ~4,300 tokens to 1 call and
~1,300, measured on the 855-review corpus with the `o200k` tokenizer. Corpus size
barely matters: only the samples are sent, so 200 reviews and 2,000 reviews cost
the same. `samples_per_theme` is the dial if you want to trade tokens for
context — 4 costs ~1,050 tokens, 10 costs ~1,835.

`llm/rate_limit.py` paces calls on whichever quota is tighter, so the whole stage
goes out without waiting. If a quota is breached anyway, Groq replies `429` with
`Retry-After` and the call is retried; if it still fails, the affected themes
fall back to keyword labels and the run records it rather than aborting.

Any other Groq model works via `model` in `[llm]` (or `LLM_MODEL` for a single
run) — adjust the quotas to match, since they are per-model. `LLM_MODEL` is
scoped to this stage; composition has its own `GEMINI_MODEL`.

## The weekly note

`reviewpulse pulse` takes the ranked themes, picks one quote for each, writes the
prose around them, and refuses to publish anything that fails a gate:

```bash
reviewpulse pulse --window-weeks 8 --show    # cluster, compose, validate, print
reviewpulse run --dry-run --window-weeks 8   # the same, after a fresh download
```

A passing run writes `note.md` and `publish.json` to `runs/<run_id>/`. A failing
one writes `note.rejected.md` instead and exits non-zero — the run aborts rather
than publishing a note that broke a rule.

### Quotes are sliced, never written

Every quote is a character slice of the stored review text. Nothing generates
one, so `quotes_verbatim` is an exact substring check rather than a fuzzy
comparison, and the model is never in a position to invent a quote. Candidate
spans are one or two sentences, trimmed at a word boundary to `quote_max_words`,
and scored on four things:

| Signal | What it rules out |
| --- | --- |
| Centrality to the theme's centroid | A member that sits at the edge of its cluster |
| Density of the theme's **distinctive** anchor terms | A charges complaint illustrating the ease-of-use theme — terms shared by two themes in the same note anchor neither |
| Star rating close to the theme's mean | A 92%-negative theme quoting the one reviewer who liked it |
| Overlap with quotes already chosen | Two of three quotes making the same complaint |

Reviews carrying redaction placeholders are penalised, not banned, so a theme
whose evidence is entirely redacted still gets a quote.

### Validation gates

Seven gates run between synthesis and publishing. Any failure aborts the run.

| Gate | Assertion |
| --- | --- |
| `themes_capped` | ≤ 5 themes clustered, exactly 3 in the note |
| `quotes_verbatim` | Each quote is a substring of its **stored** review |
| `quotes_count` | Exactly 3, from distinct reviews |
| `actions_grounded` | Exactly 3, each citing a real `theme_id` |
| `word_count` | ≤ 250 words in the rendered note |
| `no_pii` | Scrubber patterns find nothing in the final artifact |
| `window_declared` | The note's window matches the data actually used |

`word_count`, `actions_grounded` and `quotes_count` get one bounded retry —
tighter prompt, or a wider quote band. `no_pii` and `quotes_verbatim` never do:
regenerating a note that leaked PII only rerolls the dice on a defect that has to
abort. A hard failure vetoes the retry even when a recoverable one is present.

Word count is measured on the rendered note, not the model's output, because the
header, the counts and the quotes are all words on the page the model never saw.

### Composition model

Composition runs on **Gemini** (`gemini-3.6-flash`), configured in `[pulse.llm]`
and keyed by `GEMINI_API_KEY` — deliberately not the Groq model that Phase 2
labels with. Prose for a whole page is a different job from naming five themes
in eight words, and separating them means a quota or an outage on one provider
degrades one stage instead of the run. The manifest records `compose_provider`
and `compose_model` next to `compose_source`, so a surprising note can be traced
to the model that wrote it.

The stage spends at most two calls a run — one draft plus the single bounded
retry — so it stays far inside the free tier's 10 requests per minute. Override
the model for one run with `GEMINI_MODEL`, or switch the stage back to Groq by
setting `provider = "groq"` in `[pulse.llm]`.

Without `GEMINI_API_KEY` the run uses a deterministic prose frame and records
that, so every gate stays verifiable offline.

## Publishing (Google Docs + Gmail)

Live publishing talks to Google **only through MCP**. This repo never calls the Docs or Gmail
REST APIs and never handles OAuth.

The production server is the hosted
[gmail-docs-mcp](https://github.com/manojkr-ai-labs/mcp-gmail-google-docs-connect) service:

| | |
| --- | --- |
| Base URL | `https://mcp-gmail-google-docs-connect-production.up.railway.app/` |
| MCP endpoint | `POST /mcp` (Streamable HTTP). Railway's container port is 8080; clients use the HTTPS URL, not `:8080`. |
| Health | `GET /health` (no auth) |
| Auth | `Authorization: Bearer <MCP_AUTH_TOKEN>` — same value as the Railway variable, **not** a Google token |
| Tools used | `append_to_google_doc`, `draft_email` (interactive `run`); `send_email` with `--send` or `schedule` |
| Tools never used on `reviewpulse run` | `send_email` unless `--send` |

The server **cannot create** a Google Doc. Create a blank Doc while signed in as the Google
account that authorized the MCP server, then set `mcp.gdocs.document_id` to the `{id}` in
`https://docs.google.com/document/d/{id}/edit` (a full URL is also accepted). Each ISO week
appends a headed section to that notebook. A retry for the same week does not append again.

Set `gmail.recipient_alias` and `MCP_AUTH_TOKEN` in `.env`. Then:

```bash
reviewpulse mcp-check                        # list tools; fail fast on 401 / missing Doc ID
reviewpulse run --dry-run --window-weeks 12  # local note.md + publish.json
reviewpulse run --window-weeks 12            # append to the notebook + Gmail draft
reviewpulse run --send --window-weeks 12     # same, but send the email
```

A live run verifies tool names **before** it downloads reviews or calls an LLM. If Docs
succeeds and Gmail fails, the notebook id is kept so the next attempt does not duplicate the
section. Same-week re-runs skip a second Doc append. Interactive re-runs create a new Gmail
draft (the server has no update-draft tool). `--send` skips a second send if that ISO week
already stored a `message_id`.

If a tool returns `AUTH_REQUIRED` / `AUTH_EXPIRED`, re-authenticate **that MCP server**
(refresh token on Railway). There is no Google login flow in this project.

## Weekly schedule

`reviewpulse schedule --once` is the unattended job: lock → incremental Play fetch →
classify on the rolling 8–12 week window → pulse → append the notebook → **send** mail.
The Python process does not stay running; Windows Task Scheduler or cron wakes it.

Configure `[schedule]` in `config/settings.toml` (Monday 09:00 `Asia/Kolkata` by default,
`send_email = true`). The store, embedding cache, and `data/publish-state.json` must live
on a **persistent** disk — do not use GitHub Actions as the weekly clock.

```bash
reviewpulse schedule --once --dry-run   # fetch + classify + local note, no MCP
reviewpulse schedule --once             # live: Doc append + send_email
reviewpulse schedule                    # optional in-process wait until the next slot
```

**Windows Task Scheduler** — the `cd` is required; Task Scheduler does not start in the repo:

```text
schtasks /Create /TN "Groww Review Pulse" /SC WEEKLY /D MON /ST 09:00 ^
  /TR "cmd /c cd /d C:\path\to\grow-review-aiagent-mcp && .venv\Scripts\reviewpulse.exe schedule --once" ^
  /RL LIMITED
```

**cron** (09:00 IST = 03:30 UTC):

```cron
30 3 * * 1  cd /path/to/grow-review-aiagent-mcp && .venv/bin/reviewpulse schedule --once >> runs/schedule.log 2>&1
```

Overlapping ticks take `data/schedule.lock` and exit 0 (`skipped: lock_held`). A failed
gate week writes `note.rejected.md`, publishes nothing, and exits non-zero.

## CLI

```bash
reviewpulse --help
reviewpulse ingest --window-weeks 8          # download and store
reviewpulse fetch --window-weeks 8           # download only
reviewpulse export                           # rewrite data/exports/play_store.csv
reviewpulse cluster --window-weeks 8         # cluster + label stored reviews
reviewpulse pulse --window-weeks 8 --show    # cluster + compose + validate, no download
reviewpulse run --dry-run --window-weeks 12  # download, store, cluster, compose, validate
reviewpulse run --window-weeks 12            # the same, then publish via MCP (Gmail draft)
reviewpulse run --send --window-weeks 12     # publish and send the email
reviewpulse mcp-check                        # verify hosted MCP tools + auth
reviewpulse schedule --once                  # weekly job: new reviews → pulse → Doc + send
reviewpulse schedule --once --dry-run        # weekly job, local artifacts only
reviewpulse serve                            # Phase 7 console API on 127.0.0.1:8000
python -m reviewpulse.cli ingest --window-weeks 8
```

`cluster`, `pulse`, `run`, and `schedule --once` exit non-zero if any check or gate fails, so they
can gate a scheduled run.

`ingest --file <path>` still accepts an existing CSV/JSON export, which is used
by the tests and for replaying a previous download without re-fetching.

## Operator console (Phase 7)

The console is a **view** of SQLite + `runs/` + MCP publish state. It does not re-cluster or talk
to Google except through the same MCP path as the CLI.

```bash
pip install -e ".[web]"          # FastAPI + uvicorn
reviewpulse serve                # http://127.0.0.1:8000/api/v1/health  (local bind only)
```

In a second terminal:

```bash
cd web
npm install
npm run dev                      # http://127.0.0.1:3000  — rewrites /api/v1 to :8000
```

Screens: Weekly Pulse, Themes, theme detail, Reviews, Pipeline, Runs, Publish, Settings. Copy is
honest to this stack (SQLite, MiniLM + ward, Groq `openai/gpt-oss-120b` for labels, Gemini
`gemini-3.6-flash` for compose). Reviews never include `author`. Settings never return API keys
or `MCP_AUTH_TOKEN`.

`reviewpulse serve` refuses non-local hosts. Pipeline **Run with send** stays disabled while
dry-run is on; Publish **Send** requires a confirm modal.

Playwright smoke (with both processes up):

```bash
cd web
npx playwright install chromium
npm run e2e
```

## Project layout

See `docs/architecture.md` and `docs/implementation-plan.md`.

## Tests

```bash
pytest
```
