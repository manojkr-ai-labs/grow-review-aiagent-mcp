# Project 3 repository audit

Read-only inspection on branch `multi-agent-support-desk` at commit `3b86020` (`review aigent`). Application code was not modified. Dependencies were not installed. Phase 1 has not started.

Specification: `docs/project-3/ProblemStatements.txt`.

## 1. Git and working tree

| Item | Evidence |
| --- | --- |
| Branch | `multi-agent-support-desk` |
| HEAD | `3b86020`, same commit as `main` and `origin/main` |
| Ahead/behind | The branch has no commits of its own |
| Untracked | `docs/project-3/` only (this audit, the implementation plan, and the problem statement) |
| Ignored local data | `data/reviews.db`, `data/exports/`, `data/raw/*.csv`, `data/cache/`, `data/publish-state.json`, `runs/`, `config/settings.toml`, `.env` |

`config/settings.toml` exists on disk and is gitignored. This audit did not open it, so the live Google Doc id and Gmail alias were not copied into documentation.

## 2. What this repository actually is

This repository is the Project 2 Groww Review Intelligence Agent (`reviewpulse`). It downloads public Play Store reviews, scrubs them, clusters themes, writes a weekly pulse, and publishes through a Google Docs/Gmail MCP client. The operator console is a Next.js app under `web/` that talks to the FastAPI API in `src/reviewpulse/api/`.

`main.py` starts that API with uvicorn. It is the Railway entrypoint, not a support-desk entrypoint.

There is no Project 3 package, no support-case store, and no multi-agent workflow in this tree. `src/reviewpulse/orchestrator.py` is the weekly pulse pipeline. It must stay in place.

Python is 3.11+. Dependencies are declared in `pyproject.toml`: `mcp`, LangChain provider packages, Pydantic 2, scikit-learn, numpy, sentence-transformers, google-play-scraper, FastAPI, uvicorn, httpx. Pytest is the test runner (`testpaths = ["tests"]`, `pythonpath = ["src"]`). Ruff is not configured. Mypy is not configured.

`docs/architecture.md` still says the repository contains no code. That sentence is stale. It is a Project 2 document and was left unchanged.

## 3. Project 2 components Project 3 can reuse

| Need | Actual module | Reuse note |
| --- | --- | --- |
| Scrubbed reviews | `src/reviewpulse/store/sqlite.py` `ReviewStore` | Table `reviews`: `review_id`, `source`, `rating`, `title_clean`, `text_clean`, `review_date`, `lang`, `scrub_flags`. Author is never stored. |
| Canonical filtered CSV | `data/exports/play_store.csv` | Same 1,880 rows as SQLite. Header: `review_id`, `source`, `rating`, `review_date`, `lang`, `word_count`, `scrub_flags`, `title_clean`, `text_clean`. Gitignored. |
| Raw downloads | `data/raw/play_com.nextbillion.groww_{8,12}w_*.csv` | Unfiltered. Header: `Review ID`, `Review Title`, `Review Text`, `Star Rating`, `Review Date`. The 12-week file has 13,207 rows. Themes were not built from this file. |
| Review model | `src/reviewpulse/models.py` `Review`, `Theme` | `Theme.trend` and `Theme.emerging` exist. `emerging` is not a Project 3 `rising` signal. |
| Generated themes | `runs/<run_id>/clusters.json` | 47 cluster files on disk, all gitignored. Latest inspected run: `20260904T133248Z-22d7b6b8`. |
| Comparable-period counts | `runs/<run_id>/cluster_debug.json` | `early_count` and `late_count` are written here (`orchestrator.py` cluster debug payload). They are absent from `clusters.json` theme objects. |
| Trend formula | `src/reviewpulse/analysis/cluster.py` `_build_stats` | Split date is `window_end - trend_split_weeks` (default 4, `config/settings.example.toml`). `trend = late/early` when `early > 0`, otherwise `None`. `emerging` is true when `trend >= 1.5`, and also when `early == 0` and `late >= 3`. |
| PII scrubber | `src/reviewpulse/privacy/scrubber.py` | Email, long digit runs (12+), a broad phone pattern, UUID, URL query strings, non-brand `@handles`. No PAN pattern, no Aadhaar grouping, no OTP pattern. Used at ingest and by the pulse `no_pii` gate. |
| MCP client | `src/reviewpulse/mcp/client.py` | The only Google path. Streamable HTTP or stdio. Tool arguments are bound from the server schema. |
| Docs append | `src/reviewpulse/publish/gdocs.py` | Hosted server can append to an existing Doc. It cannot create one. |
| Gmail draft | `src/reviewpulse/publish/gmail.py` `create_or_update_draft` | Draft path. `send_pulse_email` exists and must not be called by Project 3. |
| Weekly idempotency | `src/reviewpulse/publish/base.py` `idempotency_key` | Key shape `groww:<ISO year>-W<week>`. Stored in `data/publish-state.json`. This key is for the pulse, not for a support case. |
| Config | `src/reviewpulse/config.py`, `config/settings.example.toml` | `[mcp].url`, `[mcp.gdocs].document_id`, `[mcp.gmail]` tool names, `[gmail].recipient_alias`. Token is `MCP_AUTH_TOKEN`. |

Latest theme artifact (`runs/20260904T133248Z-22d7b6b8`):

| Field | Value |
| --- | --- |
| Package | `com.nextbillion.groww` |
| Strategy | `ward` |
| Requested window | 2026-06-12 to 2026-09-04 |
| Actual window | 2026-06-12 to 2026-09-03 (11.86 weeks) |
| Stored reviews in SQLite | 1,880, source `play`, language `en`, dates 2026-06-12 to 2026-09-03 |

Theme labels, sizes, and stored period counts from `cluster_debug.json`:

| Label | Size | Early | Late | Trend | Emerging |
| --- | --- | --- | --- | --- | --- |
| Customer support responsiveness | 281 | 162 | 119 | 0.73 | false |
| App stability and crashes | 283 | 168 | 115 | 0.68 | false |
| Brokerage fees and charges | 287 | 187 | 100 | 0.53 | false |
| Investment transaction accuracy and fees | 231 | 149 | 82 | 0.55 | false |
| Charting and analysis tools | 145 | 81 | 64 | 0.79 | false |

Those five themes have both periods populated, so a later Pattern Agent can treat this run as comparable. None meet the existing 1.5 emerging ratio. Member review text was not copied into this audit.

SQLite date range and the export CSV row count match (1,880). The raw 12-week download is larger because ingest drops short and non-English reviews before storage. Pattern counts that use theme membership must use the filtered store or `data/exports/play_store.csv`, then join `review_id` to the selected run's theme membership. Using the raw CSV would not match the generated themes.

## 4. Project 1, located outside this repository

Project 1 is the sibling checkout `D:\manoj\AI course\nextleap.app\mutual-fund-faq-assistant`. It is not imported by `reviewpulse`, not listed in `pyproject.toml`, and not vendored here.

What the code does:

| Item | Evidence |
| --- | --- |
| Retrieval entry point | `app/pipeline/retrieve.py` `retrieve_for_question(question, *, intent, root=None, chunks=None) -> RetrievalResult` |
| Index load | `load_index()` reads `data/processed/chunks.jsonl` and keeps rows whose `source_url` is in the catalog |
| Result statuses | `hit`, `not_found`, `clarify`, `empty_index` |
| Public ask API | `app/pipeline/orchestrator.py` `ask()` runs guardrails, then retrieval, then Groq formatting, then validation |
| Allowlist | `app/corpus/catalog.py` `ALLOWED_HOSTS = {groww.in, www.groww.in}`, publisher `groww`, HTTPS only |
| Catalog file | `data/catalog/sources.json`: `host_allowlist: ["groww.in"]`, `retrieved_on: 2026-09-01`, 5 schemes, 2 education pages, 3 process pages |
| Chunks | 44 chunks in `data/processed/chunks.jsonl`. Hosts observed: `groww.in`. Doc types: `scheme_page`, `education`, `process` |
| Schemes | `hdfc-elss-tax-saver-direct-growth`, `hdfc-gold-etf-fof-direct-growth`, `hdfc-large-cap-direct-growth`, `hdfc-mid-cap-direct-growth`, `hdfc-small-cap-direct-growth` |
| Fact types on chunks | `benchmark`, `capital_gains`, `education`, `elss_statement`, `exit_load`, `expense_ratio`, `lockin`, `process`, `riskometer`, `sip`, `statement` |
| Citation metadata | Chunk fields include `source_url`, `source_title`, `as_of`, `retrieved_on`, `scheme_id`, `text` |
| Chunk `retrieved_on` values | `2026-08-23` and `2026-09-01` |
| PII detector | `app/pipeline/pii.py` `detect_pii`: PAN, email, OTP, Indian mobile, 12+ digit account runs, Aadhaar. Returns the category, not the matched value. It detects; it does not redact. |
| Advice router | `app/pipeline/router.py` `route`: rule lexicon for advisory, comparison, performance, process, scheme facts. No session memory. |

`retrieve_for_question` is metadata-first. It resolves a scheme and a fact type, then filters chunks. It does not run an unfiltered vector search. Sentence-transformers in this Project 2 repo are for review clustering, not for the Project 1 corpus.

`ask()` is the wrong Facts Agent entry point. It refuses PII and advice before retrieval, calls Groq when a key is present, and returns a three-sentence public `AskResponse`. That mixes Compliance, drafting, and retrieval. The Facts Agent should call `retrieve_for_question` and `load_index`, and should quote chunk text and catalog metadata.

Project 1's own problem statement says citations should come from AMC, AMFI, and SEBI pages, and that Groww URLs are reference pages only. The implemented catalog rejects every host except `groww.in`. Project 3's rule is to search the corpus Project 1 actually uses. The Facts Agent should use this groww.in catalog. Changing Project 1's corpus is out of scope.

Suggested status mapping, to be confirmed before Phase 3:

| `RetrievalResult.status` | Facts Agent |
| --- | --- |
| `hit` with at least one chunk | `coverage=covered`, claims taken from that chunk |
| `not_found` | `coverage=not_covered` |
| `empty_index` | `coverage=not_covered`, limitation that the index was empty |
| `clarify` | `coverage=not_covered`, limitation that the scheme was not resolved |

`last_checked` should be the chunk's `retrieved_on` when present. `as_of` stays a separate source field. A missing date stays unavailable.

## 5. MCP capabilities and limits

Hosted server documented in `README.md` and `config/settings.example.toml`:

| Item | Value |
| --- | --- |
| Repository | `https://github.com/manojkr-ai-labs/mcp-gmail-google-docs-connect` |
| Endpoint | `https://gmail-docs-mcp-production.up.railway.app/mcp` |
| Health | `GET /health`, no auth |
| Auth | `Authorization: Bearer ${MCP_AUTH_TOKEN}` |
| Tools this client expects | `append_to_google_doc`, `draft_email`, `send_email` |

Verified client behavior:

- Interactive `reviewpulse run` appends a Doc section and creates a draft. `reviewpulse run --send` and `reviewpulse schedule` may call `send_email`. The API also exposes `POST /api/v1/publish/send`.
- `FORBIDDEN_SEND_TOOLS` is `send_email`, `send_message`, `messages.send`. A client constructed with `allow_send=False` refuses those names.
- Mutating hosted tools are in `NO_RETRY_TOOLS`. After an uncertain error, the client does not retry `append_to_google_doc`, `draft_email`, or `send_email`, because the write may already have landed.
- HTTP timeout is 60 seconds (`HTTP_TIMEOUT_SECONDS`).
- Hosted append needs `mcp.gdocs.document_id`. The server cannot create a Doc.
- Same-week Doc append is skipped only when local `publish-state.json` already has that notebook id for the ISO-week key. The server itself does not provide a case idempotency key.
- Hosted Gmail has no update-draft tool. The README states that an interactive re-run creates a new draft. A retry after an uncertain draft result can duplicate.
- Argument names are schema-driven (`documentId` vs `document_id`, `to` as an array). Publishers pass semantic fields through `bind_arguments`.
- Partial pulse failure is already represented: if Docs succeeds and Gmail fails, the notebook id is kept so the next attempt does not append the same week again.

Project 3 needs its own action key, its own state file, and `allow_send=False`. Sharing `data/publish-state.json` or the weekly notebook would mix support cases with pulse sections and could suppress or duplicate the weekly append.

This audit did not call the live MCP server.

## 6. What is missing for Project 3

- Typed support-desk contracts, case ids, execution ids, and workflow transitions.
- A case store that is separate from `reviews`.
- PAN, Aadhaar, and OTP redaction that runs before persistence, logs, agent state, and model calls.
- Session memory for a later-turn advice request.
- A Facts Agent adapter over Project 1 retrieval.
- A Pattern Agent that counts theme membership and classifies `recurring`, `rising`, `one_off`, or `insufficient_data` under the Project 3 comparable-period rule.
- Concurrent dispatch of three agents, with timestamps that can prove overlap.
- An orchestrated three-sentence reply and an internal routing note that keep facts and pattern signals separate.
- Reviewer hard gates and a single automatic rework.
- Human refinement capped at five rounds, with approval bound to an exact content version.
- Approval-gated Docs append and Gmail draft for a support case, with partial-failure state.
- Sanitized 20-example evaluation artifacts.

## 7. Conflicts to resolve before application code

1. **Facts entry point.** The spec says reuse Project 1 RAG. The working retrieval function is `retrieve_for_question`. `ask()` also generates and applies Project 1 guardrails. Proposed: call retrieval only.
2. **Corpus vs Project 1 problem statement.** Implemented sources are Groww pages for five HDFC schemes plus a few education and process pages. Proposed: treat that catalog as the approved corpus and cite only its URLs.
3. **`emerging` vs `rising`.** Project 2 can flag `emerging` when the early period is empty. Project 3 forbids `rising` without two comparable periods. Proposed: classify from `early_count` and `late_count` in `cluster_debug.json`, recomputed from review dates when that file is missing. Do not copy `emerging` into `rising`.
4. **Which review file is the pattern population.** Themes match the filtered 1,880-row store and export CSV. The raw download is a different population. Proposed: count against `data/exports/play_store.csv`, and check the same ids in `ReviewStore`.
5. **Where Project 3 code lives.** Proposed package: `src/supportdesk/`, tests in `tests/supportdesk/`. `reviewpulse` CLI, scheduler, pulse gates, and `POST /api/v1/publish/send` stay as they are.
6. **MCP destination.** Proposed settings, separate from the pulse notebook: a support-desk document id and recipient, plus `data/supportdesk-publish-state.json`. Live values stay in gitignored config and `.env`.
7. **Approval UI.** The Next.js console is the pulse operator view. Proposed Phase 7 surface: a Python API in `supportdesk` with tests. No new console pages until a later explicit request.
8. **Exactly-once MCP.** The hosted server does not guarantee it. Local state can skip a completed append. An uncertain draft can still duplicate. Documentation must say that.

## 8. Integration risks

- Importing Project 1 by inserting its root on `sys.path` couples two checkouts. If the sibling path is missing, the Facts Agent must return an error status and must not answer from general knowledge.
- Project 1 retrieval only covers the five HDFC schemes and the catalogued education/process pages. Most Groww support complaints (orders, KYC, charts, charges) will be `not_covered`. That is correct behavior.
- Theme matching can drift if a newer `runs/` directory is selected accidentally. The Pattern Agent should record the chosen `run_id`.
- `reviewpulse` phone regex is broad. Replacing it would change Project 2 ingest. Project 3 redaction should be a new module. Project 1's `detect_pii` categories are the closer match, with redaction added locally because that function only detects.
- Support-case text must never be written into `runs/<pulse-run>/`, `data/reviews.db`, or test logs.
- `reviewpulse schedule` sends mail when `send_email = true`. Project 3 code must not call that job.

## 9. Recommended sequence

Follow the specification phases. Do not start the next phase until it is approved.

1. Contracts, ids, workflow states, approval and MCP action models, unit tests.
2. PII redaction and advice/performance checks, including a session.
3. Facts Agent over `retrieve_for_question`.
4. Pattern Agent over the export CSV, `clusters.json`, and `cluster_debug.json`.
5. Concurrent orchestration, reply, and routing note.
6. Reviewer and one rework.
7. Five refinement rounds and version-bound approval.
8. MCP append and draft, mocked first, `allow_send=False`.
9. Twenty sanitized examples and adversarial advice tests.
10. Project 3 docs and a short demo. Leave Project 2 README sections and `docs/problemStatement.md` intact; add a Project 3 section rather than rewriting the pulse guide.

## 10. Inspection limits

- Full `pytest` was not run. No application code changed relative to `3b86020`.
- The live MCP server was not called.
- `config/settings.toml` and `.env` were not read.
- Review text, chunk text, and catalog page bodies were not copied here.
- `docs/architecture.md` was sampled, not rewritten.
