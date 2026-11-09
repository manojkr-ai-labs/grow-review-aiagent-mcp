# Project 3 implementation plan

Progress tracker for the Multi-Agent Support Desk. The requirements are `docs/project-3/ProblemStatements.txt`. The inspection evidence is `docs/project-3/repository-audit.md`.

A new Agent conversation should read those two files and this plan, then verify the working tree, before doing anything else.

## Handoff (Phase 10 approved)

**Phase:** 10 — Project 3 documentation and demo notes  
**Status:** Completed and approved.  
**Branch:** `multi-agent-support-desk` at `3b86020`. Project 3 files are still untracked, except `README.md` and `.gitignore`, which are modified and unstaged. No commit has been requested.  
**Project 2 code and Project 2 docs:** unchanged. No edits under `src/reviewpulse/`, `docs/architecture.md`, `docs/edge-cases.md`, `docs/eval.md`, or `docs/problemStatement.md`.

Phases 0–10 are done. There is no Phase 11. A demo video was not recorded. The script is in the root README.

## 1. Phase status

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Read-only audit and this plan | Completed |
| 1 | Contracts, ids, workflow states, approval and MCP action models, unit tests | Completed |
| 2 | PII redaction, advice and performance checks, session context | Completed |
| 3 | Facts Agent on Project 1 `retrieve_for_question` | Completed |
| 4 | Pattern Agent on Project 2 CSV and theme artifacts | Completed |
| 5 | Parallel dispatch, reply, routing note | Completed |
| 6 | Reviewer and one rework | Completed |
| 7 | Five refinement rounds and version-bound approval | Completed |
| 8 | Approval-gated Docs append and Gmail draft | Completed |
| 9 | Twenty sanitized examples and adversarial tests | Completed |
| 10 | Project 3 documentation and demo notes | Completed |

## 2. Architecture decisions already verified

These come from code and local artifacts, not from the suggested folder sketch in the problem statement.

- Runtime stays Python 3.11, Pydantic 2, pytest, and the stdlib `asyncio` module. CrewAI, Chroma, and a new web framework are not required.
- Persistence for reviews stays SQLite `data/reviews.db`. Support-desk cases need a separate store, proposed as `data/supportdesk.db` (gitignored, same policy as `data/reviews.db`).
- Project 1 retrieval is `mutual-fund-faq-assistant/app/pipeline/retrieve.py`. Status values are `hit`, `not_found`, `clarify`, and `empty_index`. The approved hosts are `groww.in` and `www.groww.in`. The index is 44 catalogued chunks.
- Project 2 pattern inputs are `data/exports/play_store.csv` (1,880 scrubbed rows), `ReviewStore`, `runs/<run_id>/clusters.json`, and `runs/<run_id>/cluster_debug.json` (`early_count`, `late_count`). Latest inspected run is `20260904T133248Z-22d7b6b8`.
- MCP writes go through `reviewpulse.mcp.client` and the existing Docs/Gmail publishers. Hosted tools: `append_to_google_doc`, `draft_email`, `send_email`. Project 3 uses the first two only.
- Weekly idempotency (`groww:<year>-W<week>` in `data/publish-state.json`) belongs to the pulse. Support cases need a different key and a different state file.
- The hosted server does not offer exactly-once delivery. Uncertain append and draft calls are not retried by the current client. Draft retries can duplicate because the hosted server has no update-draft tool.
- Ruff and mypy are not configured. Phase gates record them as not configured until someone adds them on purpose.

## 3. Decisions accepted for Phase 1

Accepted when Phase 1 was approved. Later phases should follow these unless a new conflict appears.

1. New package `src/supportdesk`. Tests in `tests/supportdesk`. Project 2 modules stay behaviorally unchanged.
2. Facts Agent calls `retrieve_for_question` and `load_index` with `SUPPORTDESK_PROJECT1_ROOT`. Default root: the sibling `mutual-fund-faq-assistant` directory when it exists. Missing root or empty index returns an agent error or `not_covered`, and never a model-knowledge answer. Do not call Project 1 `ask()`.
3. Map `hit` to `covered`. Map `not_found`, `clarify`, and `empty_index` to `not_covered`, with a limitation string for clarify and empty index. `last_checked` is chunk `retrieved_on`.
4. Pattern population is the filtered export CSV cross-checked with `ReviewStore`. Theme membership comes from the selected run's `clusters.json`. Period counts come from that run's `cluster_debug.json`. `emerging` is not copied to `rising`. `rising` requires `early_count > 0`, `late_count > 0`, and `late/early >= emerging_trend_ratio` (default 1.5).
5. Recurring threshold, to confirm in Phase 4: a matched theme is `recurring` when its measured matching count is at least `cluster_size_floor` (default 3) and the rising test fails. Count `1` is `one_off`. Count `0`, a missing date, or a missing theme file is `insufficient_data`.
6. Support-desk Google Doc id and Gmail recipient are new settings. They must not reuse the pulse ISO-week state. Until they are set, MCP actions stay disabled and tests use the existing fake MCP server.
7. Human approval in Phases 1–7 is a Python API plus tests. The Next.js console is not extended in those phases.
8. Compliance redaction is new code in `supportdesk`. It follows Project 1's PAN, Aadhaar, email, Indian mobile, OTP, and 12-digit account categories, and it redacts. `reviewpulse.privacy.scrubber` stays the ingest scrubber.

## 4. Phase 1 scope (done)

Implemented in `src/supportdesk/` and `tests/supportdesk/`:

- Pydantic models for the sanitized request, the three agent results, facts evidence, pattern signal, compliance decision, orchestrator draft, reviewer finding, human approval, MCP action, workflow run, and agent execution.
- Enums for agent status, coverage, pattern signal, compliance decision, workflow state, and MCP action status.
- Legal transitions for the state diagram in the problem statement, including the block on MCP actions before approval.
- Case id and execution id generators that do not embed raw message text.
- Approval record bound to a content hash, so a later edit invalidates approval. The approval service itself waits until Phase 7; Phase 1 only defines the contract and the hash rule.
- Unit tests for validation, illegal transitions, hash invalidation, and id stability.

Do not implement agent bodies, redaction, retrieval, or MCP calls in Phase 1.

## 5. Later phase notes (do not implement now)

- **Phase 2.** Redact before any persist, log, or model call. Keep a session flag so a later turn that asks for a buy, sell, hold, redeem, suitability, or expected return is still refused. Add adversarial cases from section 14.3 of the problem statement.
- **Phase 3.** Adapter around Project 1. Claims must be substrings or tightly bounded extracts of retrieved chunk text. Searched URLs must be the URLs actually considered.
- **Phase 4.** Record `run_id`, window `requested_start`/`actual_end`, matching method, and measured count. Recompute early/late from review dates if `cluster_debug.json` has no counts. Empty CSV, missing dates, and `early_count == 0` are explicit tests.
- **Phase 5.** `asyncio.gather` (or equivalent) with overlapping start/end timestamps in the test. Timeout and error stay as agent errors, not as citations.
- **Phase 6.** Deterministic gates for citation provenance, allowlisted `groww.in` URLs, sentence count, advice, performance claims, and surviving PII. One rework, then `BLOCKED`.
- **Phase 7.** At most five refinement rounds. Each round records which agents ran. Approval stores the content hash. Rejection does not open the MCP path.
- **Phase 8.** Persist returned ids. On partial failure, retry only the action whose local state says it did not complete. An uncertain timeout stays `uncertain`, not success and not a blind retry. Tests use `tests/contract/fake_mcp.py` first. Do not call `publish_document` or `create_or_update_draft`: those helpers stamp the weekly pulse title and subject. Call `append_to_google_doc` and `draft_email` through `bind_arguments`, with `refuse_send_tool(..., allow_send=False)` on the tool actually invoked. State file: `data/supportdesk-publish-state.json`, never `data/publish-state.json`.
- **Phase 9.** Select 20 rows from the filtered CSV, store sanitized text only, and record the window and selection method. Include the ten required scenarios and the rephrased advice cases.
- **Phase 10.** Add `docs/project-3/architecture.md`, `edge-cases.md`, and `eval.md`. Extend the root README with a Project 3 section. Do not rewrite Project 2 docs.

## 6. Phase 0 record

**Completed requirements:** repository inspection, reusable-module map, missing-function list, dependency map, integration risks, and the sequence above.

**Files created:**

- `docs/project-3/repository-audit.md`
- `docs/project-3/implementation-plan.md`

**Files already present, not modified:**

- `docs/project-3/ProblemStatements.txt`

**Files modified in application code:** none.

**Commands:**

- `git status -sb`, `git branch -vv`, `git log -5 --oneline`
- Directory listings for `src/reviewpulse`, `tests`, `docs`, `data`, `runs`, and the sibling Project 1 tree
- Aggregate SQLite/CSV/theme/catalog summaries (counts, dates, labels, ids). Review text and chunk text were not printed.

**Validation:**

- Pytest: not run. No product code changed, and the existing suite includes embedding and integration tests that this audit did not need to execute.
- Ruff: not configured.
- Mypy: not configured.
- Application startup: not required for a read-only audit. `main.py` remains the ReviewPulse API entrypoint.

**Known issues:**

- Project 1 is a sibling checkout, not a package dependency.
- Local review artifacts and `config/settings.toml` are gitignored. Another machine will not have the 1,880-row store or the 47 run directories until ingest and cluster have been run.
- Live Doc id, Gmail alias, and MCP token were not inspected.
- Hosted MCP cannot promise exactly-once drafts.

**Remaining work:** Phases 1–10.

**Exact next phase:** Phase 1 — contracts and workflow foundation. Started after approval.

## 7. Phase 1 record

**Completed requirements:** typed contracts for the sanitized request, three agent results, orchestrated reply and routing note, reviewer finding, human approval, MCP action, workflow run, and agent execution. Case, run, execution, and session ids. Legal transitions, including no MCP path before a matching approval. One automatic rework. Five-refinement cap. Content-hash binding that invalidates approval on edit. No email-send action in the MCP enum.

**Not in this phase:** redaction, advice detection, retrieval, pattern counting, parallel dispatch, reviewer checks, the approval flow, and live or mocked MCP calls.

**Files created:**

- `src/supportdesk/__init__.py`
- `src/supportdesk/enums.py`
- `src/supportdesk/ids.py`
- `src/supportdesk/approval.py`
- `src/supportdesk/contracts.py`
- `src/supportdesk/workflow.py`
- `tests/supportdesk/test_ids.py`
- `tests/supportdesk/test_contracts.py`
- `tests/supportdesk/test_workflow.py`

**Files modified:** `docs/project-3/implementation-plan.md`

**Project 2 files modified:** none.

**Commands:**

- `python -m pytest tests/supportdesk -q`
- `python -c "import supportdesk"`
- `git status -sb`

**Validation:**

- Pytest: `29 passed` in `tests/supportdesk` (about 0.2s). The full Project 2 suite was not run.
- Ruff: not configured.
- Mypy: not configured.
- Application check: `import supportdesk` succeeds and reports version `0.1.0`. `main.py` was not started.

**Known issues:**

- Sentence counting splits on `.`, `!`, and `?` only. Abbreviations are a Phase 6 concern.
- `rising` is rejected unless `comparable_periods` is true and both window dates are set. The count that justifies the flag is still Phase 4.
- Approval storage is the contract only. There is no CLI or persistence yet.

**Remaining work:** Phases 2–10.

**Exact next phase:** Phase 2 — privacy and compliance foundation. Started after approval.

## 8. Phase 2 record

**Completed requirements:** deterministic detection and redaction of PAN, Aadhaar, account or customer ids, Indian phone numbers, email addresses, and OTPs. Released text is scanned again and withheld if a pattern still matches. Investment-advice and return-prediction requests are refused, including the spec examples and rephrases. A session remembers an earlier advice or performance request. A vague later turn such as "Your thoughts?" is refused. A direct fact question such as "What is the expense ratio?" stays allowed and carries `session_advice_context` or `session_performance_context`.

**Decision:** a failed sell order, "how do I redeem", and "exit load" are support requests, not advice. Bare `sell` or `redeem` does not refuse. A later fact question is not turned into a refusal; the session flag is what later phases must honor so the reply still does not recommend.

**Classification rule for 12-digit runs:** a separated 4-4-4 number, or a contiguous run of exactly 12 digits, is Aadhaar. A contiguous run of 13 digits or more is an account number. A labeled id (`customer id`, `folio number`, `account number`) that contains a digit is an account id. The word PAN or folio without a value is not redacted.

**Files created:**

- `src/supportdesk/privacy.py`
- `src/supportdesk/advice.py`
- `src/supportdesk/compliance.py`
- `tests/supportdesk/test_compliance.py`

**Files modified:**

- `src/supportdesk/contracts.py` (docstring on `SanitizedRequest` only)
- `docs/project-3/implementation-plan.md`

**Project 2 files modified:** none. `reviewpulse.privacy.scrubber` is unchanged.

**Commands:**

- `python -m pytest tests/supportdesk -q`

**Validation:**

- Pytest: `55 passed` in `tests/supportdesk`.
- Ruff: not configured.
- Mypy: not configured.
- Application check: import path covered by pytest. `main.py` was not started. No MCP call.

**Known issues:**

- Redaction is regex-only. Unusual spacing or an id with no digit can pass.
- `session_advice_context` does not itself change the decision to `refuse`. Phase 5 must keep that flag from becoming a recommendation.
- No case store yet. `ComplianceSession.export_state` keeps only the session id and the two flags.

**Remaining work:** Phases 3–10.

**Exact next phase:** Phase 3 — Facts Agent. Started after approval.

## 9. Phase 3 record

**Completed requirements:** Facts Agent calls Project 1 `load_index`, `route`, and `retrieve_for_question`. It does not call `ask`. Compliance runs first. Blocked and refused messages are not retrieved. The retriever receives redacted text. `hit` becomes `supported` only when the cited passage is a substring of the chunk, the URL is `https` on `groww.in` or `www.groww.in`, and the title comes from the chunk. `last_checked` is `retrieved_on`. `not_found`, `clarify`, and `empty_index` become `not_covered` with no claims. A missing checkout or a raised exception becomes `error` with no claims. Exception text is not copied into the result.

**Root:** `SUPPORTDESK_PROJECT1_ROOT` when set, otherwise the sibling `mutual-fund-faq-assistant` directory. A set but invalid path is an error.

**Live check:** with that sibling checkout, "What is the expense ratio of HDFC Large Cap Fund?" is `supported` from `https://groww.in/...` with `last_checked` 2026-09-01. "Why was my stock delivery charge different yesterday?" is `not_covered`. "What is the expense ratio?" with no scheme is `not_covered` because the scheme was not resolved.

**Files created:**

- `src/supportdesk/facts.py`
- `tests/supportdesk/test_facts.py`

**Files modified:** `docs/project-3/implementation-plan.md`

**Project 2 files modified:** none.

**Commands:**

- `python -m pytest tests/supportdesk -q`

**Validation:**

- Pytest: `64 passed` in `tests/supportdesk` (0.26s), including the live Project 1 corpus checks.
- Ruff: not configured.
- Mypy: not configured.
- Application check: covered by pytest. No MCP call and no Groq call. `main.py` was not started.

**Known issues:**

- Only the first citable returned chunk is turned into a claim. Education retrieval can return several chunks.
- A question outside the five HDFC schemes and the catalogued education or process pages is `not_covered`. That is the corpus boundary.
- Retrieval is a local index read. This phase does not add an HTTP timeout because Project 1's lookup does not make a network call.

**Remaining work:** Phases 4–10.

**Exact next phase:** Phase 4 — Pattern Agent. Started after approval.

## 10. Phase 4 record

**Completed requirements:** Pattern Agent reads the filtered export CSV and a `runs/<id>/clusters.json` theme artifact. `cluster_debug.json` early/late values are recorded and are not the rising test. The count is the number of distinct matched `review_id`s that have a parseable date inside the artifact's actual window and, when `data/reviews.db` is used, also exist in `ReviewStore`. A theme matches when the redacted message shares at least two stemmed tokens with its label plus keywords. `rising` requires `early > 0`, `late > 0`, `matching_count >= 3`, and `round(late/early, 2) >= 1.5`, using the split `requested_end` minus 4 weeks. `emerging` is ignored. Count `1` is `one_off`. Count `0`, a missing window, a missing theme file, or a count of 2 is `insufficient_data`. An empty early period with count >= 3 is `recurring`, with a limitation that it is not a rise.

**Compliance:** a blocked message is not matched. A redacted message is matched, and review snippets that still match a PII pattern are omitted.

**Live check:** "The customer support team is not responding." against the latest local cluster run matched the support theme, was not classified as `rising`, and the returned count equalled an independent count of those theme ids in the CSV and the review store. The window was the artifact's actual start and end.

**Files created:**

- `src/supportdesk/pattern.py`
- `tests/supportdesk/test_pattern.py`

**Files modified:** `docs/project-3/implementation-plan.md`

**Project 2 files modified:** none. `ReviewStore` is read when a database path is supplied.

**Commands:**

- `python -m pytest tests/supportdesk -q`

**Validation:**

- Pytest: `73 passed` in `tests/supportdesk` (0.64s), including the live theme-count check.
- Ruff: not configured.
- Mypy: not configured.
- Application check: covered by pytest. No MCP call. `main.py` was not started.

**Known issues:**

- Keyword lists on the real themes are broad. The two-token threshold can miss a complaint whose words are not in the label or keywords, and it can join a second theme when two distinctive tokens overlap.
- Count 2 is `insufficient_data` because it is neither one match nor the recurring floor of 3.
- The default database is opened only when the caller uses the default CSV and runs directory. Fixture calls do not touch `data/reviews.db` unless they pass `db_path`.

**Remaining work:** Phases 5–10.

**Exact next phase:** Phase 5 — parallel execution and orchestration. Started after approval.

## 11. Phase 5 record

**Completed requirements:** `orchestrate` dispatches Facts, Pattern, and Compliance with `asyncio.gather` and `asyncio.to_thread`. Each agent gets a copy of the compliance session. The caller's advice and performance flags change only after the default compliance runner returns. A blocked message ends at `BLOCKED` and is not drafted. A compliance timeout also ends at `BLOCKED` and does not keep a fact citation. Facts or pattern timeout and unexpected exceptions become agent errors: the reply does not contain a URL, and the stored detail is `timed out` or `failed: TypeName`. The workflow then still reaches `DRAFTED` unless stored agent text matches a PII pattern, in which case the run is `BLOCKED` and the text is dropped.

The customer reply is at most three sentences under the current counter. A covered fact is the claim sentence plus `Source: <url>, last checked <date>`. The reply does not include the customer message or the pattern count. A refusal without a usable claim is a fixed two-sentence refusal. `session_advice_context` stays on the routing note and does not add a recommendation. When a cited fact and a `recurring` or `rising` signal both exist, the note records that disagreement and the reply keeps the citation.

Routing uses the matched theme label: KYC, payments, technical support, account access, or general support. Priority is high for `rising`, normal for `recurring`, and low otherwise. `urgent` is not assigned.

**Files created:**

- `src/supportdesk/orchestrate.py`
- `tests/supportdesk/test_orchestrate.py`

**Files modified:**

- `src/supportdesk/__init__.py` (package docstring only)
- `docs/project-3/implementation-plan.md`

**Project 2 files modified:** none.

**Commands:**

- `python -m pytest tests/supportdesk -q`

**Validation:**

- Pytest: `84 passed` in `tests/supportdesk` (3.27s). The overlap test's latest start is before the earliest end, and the wall clock is under one second for three 0.4s sleeps.
- Ruff: not configured.
- Mypy: not configured.
- Application check: covered by pytest. No MCP call. `main.py` was not started.

**Known issues:**

- The sentence counter treats dots inside `https://groww.in` as sentence breaks. A covered reply therefore has no greeting. A `www.groww.in` URL can exceed three counted sentences and is left out of the reply, with a limitation on the note.
- `asyncio.wait_for` stops waiting. It does not kill the worker thread. The late result is discarded.
- A blocked message still starts the other two agents. Those agents return before retrieval or CSV reads. The run never enters `AGENTS_RUNNING`.

**Remaining work:** Phases 6–10.

**Exact next phase:** Phase 6 — reviewer and one rework. Started after approval.

## 12. Phase 6 record

**Completed requirements:** `review` checks a drafted reply and routing note against the stored agent results. The gates are sentence count, surviving PII, investment advice, performance or return language, citation host, citation provenance, evidence match, hidden or contradicted agent results, and a drafted workflow state. Finding text does not quote the matched PII or the rejected URL.

`review_case` moves `DRAFTED` to `REVIEWING`. A pass goes to `PENDING_APPROVAL` and does not open MCP. A repairable failure goes through `REWORK_ONCE` once. Rework rebuilds the reply with `draft_from_agents` and does not call Project 1 or the review CSV, because the customer message is not stored. The second review then passes to `PENDING_APPROVAL` or the run becomes `BLOCKED`. A blocked run cannot be approved and `assert_mcp_permitted` fails. A case that is not drafted is not reworked.

**Files created:**

- `src/supportdesk/reviewer.py`
- `tests/supportdesk/test_reviewer.py`

**Files modified:**

- `src/supportdesk/orchestrate.py` (`draft_from_agents`, `is_template_reply`)
- `src/supportdesk/__init__.py` (package docstring only)
- `docs/project-3/implementation-plan.md`

**Project 2 files modified:** none.

**Commands:**

- `python -m pytest tests/supportdesk -q`

**Validation:**

- Pytest: `97 passed` in `tests/supportdesk` (3.37s).
- Ruff: not configured.
- Mypy: not configured.
- Application check: covered by pytest. No MCP call. `main.py` was not started.

**Known issues:**

- `CustomerReply` already rejects four sentences, so the sentence gate is also covered by a direct counter test.
- A fact claim that is itself advice or a performance promise cannot be repaired. The second review blocks.
- Rework cannot re-run Facts or Pattern. The raw message is not retained on the draft.

**Remaining work:** Phases 7–10.

**Exact next phase:** Phase 7 — five refinement rounds and version-bound approval. Started after approval.

## 13. Phase 7 record

**Completed requirements:** A pending case can be refined at most five times. The stored instruction is redacted, and a sixth round is refused. The instruction names the agents to run: facts, pattern, compliance, or a draft-only reply change. A new message is inspected before any named agent runs, and agents that were not named are not called. Each round records the agents, execution ids, timestamps, and whether the reviewer accepted the attempt.

A failed refinement does not replace the accepted reply. Approve and reject apply only to the hash of the reply and canonical routing note that passed review. Rejection cannot be refined and cannot start MCP. Changing the hash of an approved or pending case returns it to review and clears approval. `assert_mcp_permitted` stays closed until a new approval matches the new hash. This phase does not call MCP.

A pending case may move back to `REVIEWING` when refinement starts. That edge was added because the version waiting for a decision is no longer the reviewed version.

**Reviewer fix found while refining:** PII checks no longer scan case, run, or execution ids. A hex id can contain ten digits and was being treated as a phone number.

**Files created:**

- `src/supportdesk/decisions.py`
- `tests/supportdesk/test_decisions.py`

**Files modified:**

- `src/supportdesk/workflow.py` (pending approval can return to review; a changed pending hash does too)
- `src/supportdesk/reviewer.py` (PII check ignores ids)
- `src/supportdesk/approval.py` (module docstring only)
- `src/supportdesk/__init__.py` (package docstring only)
- `tests/supportdesk/test_reviewer.py` (id false-positive regression)
- `docs/project-3/implementation-plan.md`

**Project 2 files modified:** none.

**Commands:**

- `python -m pytest tests/supportdesk -q`

**Validation:**

- Pytest: `108 passed` in `tests/supportdesk` (3.41s).
- Ruff: not configured.
- Mypy: not configured.
- Application check: covered by pytest. No MCP call. `main.py` was not started.

**Known issues:**

- Refinement can re-run Facts or Pattern only when the caller supplies a new message. The original customer message is not stored.
- A failed fifth refinement leaves the last accepted reply pending. It does not block the case.
- `urgent` is still not assigned by routing.

**Remaining work:** Phases 8–10.

**Exact next phase:** Phase 8 — approval-gated Docs append and Gmail draft, after approval. Mock the MCP client first. Do not send email.

## 14. Phase 8 record

**Completed requirements:** An approved case can append `append_to_google_doc` and create a `draft_email`. `send_email` is never called. `allow_send` stays false: `refuse_send_tool` runs on the tool name about to be invoked, and that name is only the append or draft tool.

The pulse helpers were not used. `publish_document` prefixes “Groww Weekly Review Pulse”. `create_or_update_draft` requires a `PulseNote` and sets the weekly pulse subject. Support cases call the same client primitives (`ToolClient`, `bind_arguments`, `extract_id`, `refuse_send_tool`) and write `data/supportdesk-publish-state.json`. Tests pass a temporary path. The state file stores status and external ids, not the reply.

A definite tool error is `failed` and may be retried. A message containing “timeout” or “timed out” is `uncertain` and is not retried. Docs success plus draft failure is `PARTIAL_FAILURE`; the retry skips the completed append. If the append is failed or uncertain, Gmail is not called. Both successes move the run to `COMPLETED`. A later call on that run returns the saved ids and does not call the tools. Pending and rejected runs raise before any call. Content that matches a PII pattern raises before any call. The check uses `content_has_pii`, which does not scan case or execution ids.

**Files created:**

- `src/supportdesk/publish.py`
- `tests/supportdesk/test_publish.py`

**Files modified:**

- `src/supportdesk/__init__.py` (package docstring only)
- `docs/project-3/implementation-plan.md`

**Project 2 files modified:** none.

**Commands:**

- `python -m pytest tests/supportdesk -q`
- `git status -sb` (only untracked `docs/project-3/`, `src/supportdesk/`, `tests/supportdesk/`)

**Validation:**

- Pytest: `113 passed` in `tests/supportdesk` (3.77s).
- Ruff: not configured.
- Mypy: not configured.
- Application check: covered by pytest against `tests/contract/fake_mcp.py`. The live MCP server was not called. `main.py` was not started. No email was sent.

**Known issues:**

- The hosted server cannot update a draft. A non-timeout draft failure can create a second draft on retry. A timeout is stored as uncertain and is not retried, because the write may already have landed.
- The publisher does not create a Google Doc. The caller supplies an existing document id.
- Support-desk document id and recipient are still function arguments. They are not read from `config/settings.toml`.

**Remaining work:** Phases 9–10.

**Exact next phase:** Phase 9 — twenty sanitized examples and adversarial tests, after approval. Do not call the live MCP server.

## 15. Phase 9 record

**Completed requirements:** Twenty real rows from `data/exports/play_store.csv`, theme members of run `20260904T133248Z-22d7b6b8`. The window is `2026-06-12` through `2026-09-03`. Selection round-robins themes `t1` through `t5` in theme-id order, four reviews each, after sorting review ids. Stored text is `redact_pii(text_clean)` only. Zero rows were skipped for residual PII or empty text in this draw. The fixture is `tests/supportdesk/fixtures/sanitized_examples.json`. The test reloads that file and checks it still matches a fresh selection.

Each example was orchestrated and reviewed. All 20 executions overlapped. All 20 reviews passed and stopped at `pending_approval`. No email was sent and the live MCP server was not called.

Measured statuses on this dataset: facts `not_covered` 19, `supported` 1. Pattern `recurring` 14, `insufficient_data` 6. The approved corpus is the five HDFC scheme pages, so most support complaints stay `not_covered`. A review can belong to a theme and still be `insufficient_data` when its wording does not share two keyword stems with the theme label.

The ten functional scenarios are `tests/supportdesk/test_scenarios.py`: corpus covered, not covered, recurring theme, PII redaction, disagreement, one rework, second-failure block, human rejection, human approval, and partial MCP retry. Adversarial coverage is `tests/supportdesk/test_adversarial.py`: the direct asks, the rephrases, and a later turn (`What do you think?`) in the same session. None of those replies recommend, predict a return, or cite a URL.

**Files created:**

- `src/supportdesk/evalset.py`
- `tests/supportdesk/test_eval.py`
- `tests/supportdesk/test_scenarios.py`
- `tests/supportdesk/test_adversarial.py`
- `tests/supportdesk/fixtures/sanitized_examples.json`

**Files modified:**

- `src/supportdesk/__init__.py` (package docstring only)
- `tests/supportdesk/test_orchestrate.py` (PII assertions no longer scan execution ids)
- `docs/project-3/implementation-plan.md`

**Project 2 files modified:** none.

**Commands:**

- `python -m pytest tests/supportdesk -q`
- `git status -sb` (only untracked `docs/project-3/`, `src/supportdesk/`, `tests/supportdesk/`)

**Validation:**

- Pytest: `137 passed` in `tests/supportdesk` (4.47s).
- Ruff: not configured.
- Mypy: not configured.
- Application check: covered by pytest. The live MCP server was not called. `main.py` was not started. No email was sent.

**Known issues:**

- `contains_pii` on a full workflow JSON can treat digits inside an execution id as a phone number. The orchestrate tests now check reply and agent prose, which is the same rule as `content_has_pii`.
- `docs/project-3/eval.md` is still Phase 10. This phase stores the fixture and the measured counts above.
- Six of the twenty theme members did not meet the token-overlap threshold, so their pattern signal is `insufficient_data`.

**Remaining work:** Phase 10.

**Exact next phase:** Phase 10 — Project 3 architecture, edge cases, evaluation write-up, and a README section, after approval. Do not rewrite Project 2 docs. Do not copy review text into the docs.

## 16. Phase 10 record

**Completed requirements:** Project 3 architecture, edge cases, and evaluation write-up. The root README gains a Project 3 section and a three-minute demo script. Pulse README sections and the pulse docs were left in place. Review text was not copied into the new docs. The sanitized examples stay in `tests/supportdesk/fixtures/sanitized_examples.json`.

A video file was not produced. The script runs two prompts: the HDFC Large Cap expense-ratio question, which drafts a three-sentence reply with an `https://groww.in/` citation, and “Should I buy this scheme?”, which returns `refuse` with no citation URL. That check was run locally. The live MCP server was not called.

`data/supportdesk-publish-state.json` is now gitignored, next to the pulse publish state file.

**Files created:**

- `docs/project-3/architecture.md`
- `docs/project-3/edge-cases.md`
- `docs/project-3/eval.md`

**Files modified:**

- `README.md` (Project 3 section appended)
- `.gitignore` (support-desk publish state)
- `docs/project-3/implementation-plan.md`

**Project 2 files modified:** none.

**Commands:**

- `python -m pytest tests/supportdesk -q`
- Demo prompts via `python -c` (state `drafted`, reply sentence count 3, citation present; refusal decision `refuse`, no `https://`)
- `git diff --stat` for `README.md`, `.gitignore`, and the pulse docs

**Validation:**

- Pytest: `137 passed` in `tests/supportdesk` (4.27s).
- Ruff: not configured.
- Mypy: not configured.
- Application check: the two README prompts, as above. `main.py` was not started. No email was sent.

**Known issues:**

- The demo is a script, not a video.
- `docs/architecture.md` still says the repository contains no code. That line is in the pulse document and was left unchanged.

**Remaining work:** none in the phase plan.

**Exact next phase:** none. Phase 10 was approved. Phases 0–10 are complete.
