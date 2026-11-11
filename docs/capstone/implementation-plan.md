# Capstone implementation plan

Progress tracker for The Support Desk. Requirements are `docs/capstone/ProblemStatements.md`. The target design is `docs/capstone/architecture.md`.

A new session should read those two files and this plan, then verify the working tree, before editing code.

## Handoff (Phase 0)

**Phase:** 0 — plan only  
**Status:** Written. No capstone application code yet.  
**Next phase:** 1 — package, question identity, and contracts.  
**Branch:** Create `capstone-support-desk` from current `main` before Phase 1. Do not branch from `multi-agent-support-desk`. That branch is behind `main`.

`src/capstone/` does not exist. The console has no `/queue` route. `src/reviewpulse/` and `src/supportdesk/` already implement Milestones 2 and 3. This plan adds the join. It does not reopen either milestone.

## 1. Phase status

| Phase | Scope | Requirements | Status |
| --- | --- | --- | --- |
| 0 | This plan | — | Written |
| 1 | Package, question identity, contracts | J2 key rule, J5 field shapes | Not started |
| 2 | SQLite question log, ledger, case durability | J1, J3, P1 | Not started |
| 3 | Record a reviewed desk case into the log | J1, J3, J4 copy, P2 | Not started |
| 4 | Five-times support signals | J2, J5 | Not started |
| 5 | Fee theme and six-bullet explainer | W1, W2, G1–G5, S3, A1 | Not started |
| 6 | Assemble, package hash, gates | W3 library, W4 hash, B2, S2 | Not started |
| 7 | Desk HTTP queue and publish lock | R1–R5, B1, B3, B5 | Not started |
| 8 | Capstone HTTP assemble, decision, publish | W3, W4, B4, E2 library path | Not started |
| 9 | Queue, source panel, desk approval screens | Section 8, R4, G5 | Not started |
| 10 | Pulse blocks and one weekly trigger | W1–W4 on the console | Not started |
| 11 | C1–C5 and E1–E3 | C1–C5, E1–E3 | Not started |
| 12 | README, host notes, demo script | Section 12 of the problem statement | Not started |

There is no Phase 13. A demo video is recorded only after Phase 12, by a person, from the script. This plan does not treat the recording as a coding phase.

## 2. Rules for every phase

- Work on `capstone-support-desk`.
- Close the phase tests before starting the next phase.
- Milestone 2 behavior stays in `src/reviewpulse/`. Milestone 3 behavior stays in `src/supportdesk/`. Capstone code calls those packages.
- Do not edit `docs/problemStatement.md`, `docs/project-3/ProblemStatements.txt`, or their acceptance criteria.
- Do not add a framework, a vector store, or a second retriever.
- Do not call the hosted MCP server from tests. Desk publish tests use `tests/contract/fake_mcp.py`.
- Do not send mail from any desk path. `refuse_send_tool(..., allow_send=False)` stays on the tool the desk invokes.
- Counts, theme ids, coverage, and searched URLs are copied from stored results. A test that passes a client-supplied citation must show that the server ignores it.
- No raw personal data in git, fixtures, logs, or screenshots. Fixtures use placeholders such as `[phone]`.
- Ruff and mypy are not configured. Each phase records that, until someone adds them on purpose.
- Setuptools already discovers packages under `src/`. A new `src/capstone` package needs no extra package list. Pytest already puts `src` on `pythonpath`.

## 3. Decisions this plan locks

These come from the architecture. Later phases implement them as written.

1. New package `src/capstone`. Tests in `tests/capstone`.
2. Question identity lives only in `src/capstone/identity.py`. NFKC, casefold, strip redaction placeholders, keep letters and digits, collapse whitespace. Empty keys do not enter the five-times count. No stemming and no model call.
3. The five-times week is the ISO week in `Asia/Kolkata`, formatted `YYYY-Www`. It is not the 8–12 week review lookback.
4. Persistence is `data/capstone.db`, gitignored. Tables: `question_log`, `not_covered_ledger`, and `desk_cases`. The third table is durability for the queue: one sanitized JSON blob of the Milestone 3 case object per `case_id`. Approval rules stay in `supportdesk.decisions` and `supportdesk.approval`. The blob is not a second implementation of the hash check.
5. `note.md` is unchanged by the capstone. Signals go to `support_signals.json`. The explainer goes to `explainer.json`. The package hash covers the exact bytes of all three.
6. Fee theme selection uses the lexicon and the count floor of 3 from the architecture. No match stores `fee_theme: null`. It does not invent a theme.
7. Factual explainer bullets call `supportdesk.facts.answer_facts`. Phase 5 freezes the ordered question list from the real Milestone 1 catalog. A question the catalog cannot answer is not hard-coded as a covered bullet.
8. The empty-ledger bullet is exactly `No queued question in this week was outside the corpus.`
9. HTTP routes mount on the existing FastAPI app in `src/reviewpulse/api/app.py` by including a router. One include line is the intended edit in that file during Phases 7 and 8.
10. The weekly trigger is the existing console pipeline (`pipeline_run`), plus one trailing `capstone.assemble` call after pulse gates pass. `reviewpulse run --send` is left on the Milestone 2 path.
11. Intent chips are derived from stored compliance, pattern, and facts fields, in the order Personal data, Advice, Complaint, Fact, Not covered. Every chip that applies is shown.

## 4. Phase 0 — plan

**Done when:** this file, the problem statement, and the architecture exist, and no file under `src/capstone/` or `tests/capstone/` exists.

**Validation:** none. No product code changes.

**Remaining work:** Phases 1–12.

## 5. Phase 1 — identity and contracts

**Goal.** A capstone package whose question key and record shapes can be tested without a database, a desk run, or a model.

**Closes.** The J2 identity rule. The J5 ban on invented fields, expressed as Pydantic models with `extra = forbid`.

**Create**

- `src/capstone/__init__.py`
- `src/capstone/identity.py`
- `src/capstone/contracts.py` — models for a log row, a ledger row, a support signal, an explainer bullet, an explainer, and a weekly package manifest. Include `evidence_type` with the only legal queue value `queue`.
- `tests/capstone/test_identity.py`
- `tests/capstone/test_contracts.py`

**Tests**

- `"What is the exit load?"` and the same text with different casing and spacing share one key.
- A PAN placeholder and a phone placeholder on otherwise identical text share one key, and the key contains neither placeholder.
- An empty or punctuation-only string yields an empty key. `counts_for_signal` is false.
- A model dump rejects an unknown field and rejects a signal whose `evidence_type` is `pattern` or `review`.

**Do not.** Open SQLite. Import `reviewpulse` or call `orchestrate`. Add HTTP routes.

**Done when:** `python -m pytest tests/capstone -q` passes, and `import capstone` works.

## 6. Phase 2 — log, ledger, and case store

**Goal.** Sanitized rows can be appended and read back. The raw message has nowhere to go.

**Closes.** J1, J3, P1 for storage.

**Create**

- `src/capstone/log.py` — open `data/capstone.db`, migrate, append, list by `week_id`, fetch by `case_id`.
- `tests/capstone/test_log.py`
- `.gitignore` entry `data/capstone.db`

**Schema.** The two tables in architecture section 6, plus `desk_cases(case_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)`. `payload` is sanitized JSON. Tests pass a temporary database path. The default path is `data/capstone.db`.

**Tests**

- Append a covered row. The ledger does not gain a row.
- Append a not-covered row. The ledger row copies case id, sanitized text, searched URLs, week, and theme id in the same transaction.
- A second append of the same `case_id` updates the row and does not duplicate the ledger.
- The schema has no column whose name contains `raw`.
- Round-trip a sanitized case blob. A payload that fails the Milestone 3 case model is rejected, once that model is imported only for validation. If importing it pulls unwanted startup work, validate the required keys in the capstone contract instead, and keep the desk model for Phase 3.

**Do not.** Call the facts agent. Write `explainer.json`. Add a route.

**Done when:** `python -m pytest tests/capstone -q` passes. `data/capstone.db` is gitignored.

**Doc touch.** Add `desk_cases` to the schema table in `docs/capstone/architecture.md` so the design matches the store. No other architecture change.

## 7. Phase 3 — record a reviewed case

**Goal.** One function takes a finished Milestone 3 reviewed case and writes the log, the ledger when required, and the case blob.

**Closes.** J1 and J3 from a real desk result. P2: a blocked redaction writes nothing. J4 fields needed later are copied onto the stored case, not rewritten.

**Create**

- `src/capstone/record.py`
- `tests/capstone/test_record.py`

**Behavior**

- Call this only after `review_case` (or `decide`) returns. `record.py` does not orchestrate.
- Build the log row from the sanitized request, the facts coverage, `searched_urls`, the pattern `theme_id` when the match is real, and `identity.question_key`.
- Week id uses `Asia/Kolkata` at record time, unless the caller passes a clock. Tests pass a fixed clock.
- If compliance blocked the case because redaction failed, write no row and return a recorded-nothing result.
- Personal-data values from the architecture's redaction placeholders may appear. A raw 10-digit phone or a PAN pattern must not.

**Tests**

- Covered fact case: one log row, no ledger row, case blob stored.
- Not-covered case: log row and ledger row, searched URLs equal the facts result.
- Pattern theme id is stored only when the pattern result matched. `insufficient_data` stores null.
- Blocked redaction: all three tables unchanged.
- The function does not call `publish_case`.

**Do not.** Add the five-times rollup. Change `supportdesk.orchestrate` control flow. Phase 7 is what calls `record` from HTTP. This phase is the library.

**Done when:** `python -m pytest tests/capstone tests/supportdesk -q` passes. The support-desk suite stays green, which is the regression check that Milestone 3 was not rewritten.

## 8. Phase 4 — support signals

**Goal.** Five identical keys in one ISO week become one queue signal. Four do not. Review artifacts cannot create one.

**Closes.** J2, J5 for signals.

**Create**

- `src/capstone/signals.py`
- `tests/capstone/test_signals.py`

**Behavior**

- Read the log for one `week_id`. Group by non-empty `question_key`. Emit a signal when the count is at least 5.
- `case_ids` are sorted. `theme_id` is set only when every row in the group has that same id. Otherwise null.
- `evidence_type` is `queue`.
- Render the architecture template from the record fields. The renderer does not call a model.
- Write `runs/<run_id>/support_signals.json` as a list. An empty list is a valid file.
- A function that is handed `clusters.json` without log rows returns an empty list. This is the test that review volume is not a signal.

**Tests**

- Five rows, one key: one signal, count 5, template contains the key, the count, the week, and the words `question log`.
- Four rows: empty list.
- Empty keys excluded.
- Mixed theme ids: `theme_id` null.
- File round-trip uses the contract model.

**Do not.** Edit `note.md`. Mention the signal inside the 250-word note.

**Done when:** `python -m pytest tests/capstone -q` passes.

## 9. Phase 5 — fee theme and explainer

**Goal.** A deterministic explainer of at most six bullets, with at most five official links, and a ledger bullet that quotes the ledger.

**Closes.** W1's fee-theme line, W2, G1–G5 for explainer bullets, S3, and the advice scan on explainer text.

**Create**

- `src/capstone/explainer.py`
- `tests/capstone/test_explainer.py`

**Inspect before coding the question list.** Read the sibling Project 1 catalog. Record the ordered fee questions in a module constant and in the Phase 5 notes at the bottom of this file. If the catalog is absent on the machine, the constant stays empty and every factual bullet is skipped. Absence is not a license to invent a claim.

**Behavior**

- Select the fee theme from `clusters.json` with the architecture lexicon and a member count of at least 3. Largest count wins. No match yields `fee_theme: null` and the sentence that no fee theme met the bar.
- For each frozen question, call `answer_facts`. Keep a bullet only when coverage is `covered`, the claim is a substring of the passage, and the URL host is `groww.in` or `www.groww.in`. Stop at five links.
- Last bullet: ledger rows for that week, each cited by `case_id` and sanitized text, or the exact empty-ledger sentence.
- Reject the explainer when a bullet matches the desk's advice or performance checks, when `content` still matches a PII pattern, when links exceed five, or when bullets exceed six.
- Write `runs/<run_id>/explainer.json` only when the gates pass. On failure, write nothing and return the failing codes.

**Tests**

- Two qualifying themes: the larger count is chosen.
- No qualifying theme: null, and the bar sentence is present.
- A fake retriever that returns an off-host URL or a claim that is not in the passage produces no factual bullet.
- Six ledger rows still produce one last bullet that contains every case id.
- Empty ledger uses the exact sentence.
- A bullet that says "you should redeem" fails the gate and writes no file.
- Last-checked date is the retrieval value, or the explicit unavailable marker. It is never today's date filled in by the explainer.

**Do not.** Call the hosted corpus in unit tests. Inject the retriever. Do not hash the package yet.

**Done when:** `python -m pytest tests/capstone -q` passes.

## 10. Phase 6 — assemble and the package hash

**Goal.** One function builds both JSON files from a finished pulse run and hashes them with `note.md`.

**Closes.** The library half of W3. W4's hash. B2 for the package. S2, by proving `note.md` bytes do not change.

**Create**

- `src/capstone/package.py` — canonical JSON encoding and SHA-256 over `note.md`, `explainer.json`, and `support_signals.json` in that order.
- `src/capstone/assemble.py`
- `src/capstone/gates.py` — word count is not reimplemented; assemble reads the existing pulse manifest and refuses to package a note that failed its gates. Bullet, link, advice, and PII gates from Phase 5 run here again.
- `tests/capstone/test_assemble.py`

**Behavior**

- Input is a `run_id` whose `note.md` and `clusters.json` already exist, plus a log database and a clock.
- Refuse when the pulse gate record is missing or failed. Do not publish.
- Write the two JSON files. Then compute the hash.
- Store `runs/<run_id>/package.json` with the hash, `fee_theme`, and file names. Do not store the note body twice.
- Changing any of the three inputs changes the hash.
- Assemble does not import the MCP client and does not call `publish_case`.

**Tests**

- Fixture run with a passing pulse manifest, five log rows, and a fake facts retriever: both JSON files exist, hash is stable across two calls, `note.md` bytes are identical before and after.
- Failed pulse manifest: no JSON files, no hash.
- Empty signals and empty ledger: files still exist, last bullet is the empty sentence, hash covers that sentence.
- A second assemble after a one-byte note change yields a different hash.

**Do not.** Add the pipeline hook. That is Phase 10. Do not approve or write to Google.

**Done when:** `python -m pytest tests/capstone -q` passes.

## 11. Phase 7 — desk HTTP

**Goal.** An operator can submit a question, list the queue, refine, decide, and publish only through the existing desk functions.

**Closes.** R1–R5, B1, B3, B5 for the desk path.

**Create**

- `src/capstone/api/desk.py` — APIRouter
- `tests/capstone/test_desk_api.py`
- One `include_router` in `src/reviewpulse/api/app.py`

**Routes.** Those named in architecture section 7 for `/api/desk`.

**Behavior**

- `POST /api/desk/questions` runs sanitize, orchestrate, review, then `record.record_case`. The response is the stored case. A client field named `citation` or `count` is ignored.
- `GET /api/desk/queue` reads `desk_cases` and returns sanitized text, draft or not covered, citation or searched URLs, reviewer flag, and state.
- Refine and decision call `supportdesk.decisions`. They do not open `explainer.json`.
- Publish calls `supportdesk.publish.publish_case` only when `assert_mcp_permitted` and `approval_matches` succeed. The router has no `allow_send` parameter. Tests assert `send_email` is absent from the fake client call list.
- A `blocked` case returns an error from publish and does not call the fake client.
- Partial failure and `uncertain` stay the behaviors already implemented in `supportdesk.publish`. The test asserts a timeout is not retried.

**Tests**

- Covered, not covered, PII redaction, and advice refusal through the HTTP client.
- Reject leaves the case on the queue. Snapshot `explainer.json` from a fixture and show the file is untouched.
- Approve hash A, then change the reply and attempt publish: no MCP call.
- Second reviewer failure: blocked, no MCP call.

**Do not.** Build React pages. Assemble a weekly package inside the question route.

**Done when:** `python -m pytest tests/capstone tests/supportdesk -q` passes.

## 12. Phase 8 — capstone HTTP

**Goal.** Assemble, read the package, approve that hash, and publish it on the pulse path only.

**Closes.** W3 as an HTTP action, W4, B4, and the E2 publish rule at the API.

**Create**

- `src/capstone/api/package.py`
- `tests/capstone/test_package_api.py`
- Include this router from `app.py` next to the desk router.

**Routes.** Those named in architecture section 7 for `/api/capstone`.

**Behavior**

- Assemble calls Phase 6. It does not call MCP.
- Decision stores an approval record beside `package.json`: decision, hash, time, `approver_ref`. A later file change makes `approval_matches` fail for the stored hash.
- Publish uses the existing pulse publisher and `data/publish-state.json`. It refuses when the hash differs. It refuses when the caller is a desk case id.
- Desk publish still uses `data/supportdesk-publish-state.json`. A test approves a package and shows the desk state file is unchanged, then approves a desk case and shows the pulse state file is unchanged.
- Package publish may call `draft_email` and, only when the approved action says send, `send_email`. Desk publish still cannot.

**Tests**

- Assemble on a fixture run returns the hash and does not touch the fake MCP client.
- Publish of hash B after approval of hash A is rejected.
- Cross-approval test for the two state files.
- Rejecting a desk case during this test still leaves `explainer.json` unchanged.

**Do not.** Change `reviewpulse run --send`. Render the console.

**Done when:** `python -m pytest tests/capstone -q` passes.

## 13. Phase 9 — queue, source panel, desk approval

**Goal.** The four operator jobs for a single question are possible in the existing console.

**Closes.** Problem-statement section 8 for the queue, the source panel, and the desk approval screen. G5 on screen. The four intent chips.

**Create**

- `web/app/queue/page.tsx`
- `web/app/queue/[caseId]/page.tsx`
- `web/app/queue/[caseId]/approve/page.tsx`
- API client functions in `web/lib/api.ts` only as far as these pages need
- Nav entry in `web/components/chrome/AppShell.tsx`

**Screen contract**

- Queue row: sanitized question, draft or not covered, citation or not-covered badge, reviewer flag, state, intent chips.
- Case page: reply, routing note, source panel (claim, allow-listed link, last-checked or "date unavailable", searched pages when not covered), agent start and end times.
- Approval page: the exact reply, the exact routing note, the Doc id, the draft recipient, the content hash, and the sentence that Gmail send will not be called. Approve and reject post to the Phase 7 decision route. Publish posts only after approve, and only for the hash on screen.

**Verify in the browser.** Submit one covered question and one not-covered question. Reject one. Approve another and confirm the request body has no send flag. Confirm a complaint-plus-fact case shows both chips. Use the running console, not a screenshot-only check.

**Do not.** Restyle the pulse pages. Call MCP from the browser.

**Done when:** the three routes render against the Phase 7 API, and the browser pass above has been done.

## 14. Phase 10 — pulse surface and one trigger

**Goal.** Starting the weekly pipeline once produces a note, an explainer, and support signals, then waits for package approval.

**Closes.** W1–W4 on the hosted console path.

**Edit**

- The pipeline job that `pipeline_run` already starts. After the pulse gates pass, call `capstone.assemble`. A failed assemble leaves the note in place, writes no package hash, and does not publish.
- `web/app/page.tsx` — show the explainer and the support-signal block under the existing pulse. Label signals `queue`. Leave theme counts labeled as pattern evidence.
- `web/app/publish/page.tsx` — show the package hash and the three artifacts. Publish posts to the Phase 8 route.

**Tests**

- An API-level test runs the trailing assemble on a fixture and asserts one trigger, no MCP call, and a hash.
- A UI check: the pulse page shows the empty-ledger sentence when the ledger is empty, and shows a five-times line when the fixture has five rows. Approving the package does not change a desk case.

**Do not.** Insert signal text into `note.md`. Wire `reviewpulse run --send` to assemble.

**Done when:** one pipeline start on a fixture reaches the approval screen with all three artifacts, and `note.md` still passes the existing word-count gate.

## 15. Phase 11 — acceptance and evaluation

**Goal.** C1–C5 and E1–E3 are executed and written down.

**Closes.** Problem-statement sections 10 and 11.

**Create**

- `tests/capstone/test_scenarios.py` — C1 through C5
- `tests/capstone/test_eval.py` — E1 through E3
- `docs/capstone/eval.md` — command, date, pass or fail, and the known catalog limit

**Scenario notes**

| Id | Setup |
| --- | --- |
| C1 | Fake or real retriever with one allow-listed chunk. Draft has at most three sentences, one link, and a last-checked value or the unavailable marker. |
| C2 | Retriever returns not covered. Ledger has the case. No claim in the draft. |
| C3 | Five identical sanitized charge questions and a fixture theme that meets the fee floor. Routing note has signal, count, and window. Signal file has the queue line. Explainer has at most six bullets. |
| C4 | Message contains a phone-shaped number. Response JSON, log row, and case blob do not contain the raw number. |
| C5 | "Should I redeem this fund?" then "What do you think?" on the same session id. Both refused. A separate double review failure is blocked and the fake MCP client records no call. |

**Evaluation notes**

- E1 uses one assemble. Every queued case is a draft or not covered. Themes in the fixture carry review ids. Word count and bullet count pass. The weekly path stops at the hash.
- E2 approves hash A, refuses publish of hash B, and hashes `explainer.json` before and after a desk rejection.
- E3 records five claims with link, passage, and review id where the pulse is involved. Then sends a PAN-shaped value, an account-shaped value, a phone-shaped value, and a return-figure request through the desk route. Assert no publish-state file changes.

If the sibling corpus or the Play export is missing, the live half of a test skips and `docs/capstone/eval.md` says `not run` for that half. A skip is not a pass.

**Done when:** `python -m pytest tests/capstone -q` passes, and `docs/capstone/eval.md` matches that run.

## 16. Phase 12 — README, host, demo script

**Goal.** A reviewer can run the assembled system from the README and can see the demo script match the problem statement.

**Closes.** Problem-statement section 12, except the video file, which a person records afterward.

**Edit**

- Root `README.md` — add a capstone section: architecture pointer, source list, `SUPPORTDESK_PROJECT1_ROOT`, how the loops connect, what C1–C5 do, how to run E1–E3, the two state files, and the exactly-once limit (B6).
- `docs/capstone/demo-script.md` — under three minutes, in this order: weekly pulse to the gate, one question, one rejection, one approval of the hash on screen, one evaluation row.
- Confirm `data/capstone.db` is gitignored. Confirm `.env` is not required to contain a new secret.

**Do not.** Rewrite the Milestone 2 README sections. Do not record the video inside this phase.

**Done when:** the definition-of-done table in the problem statement can be checked against the hosted app. Leave the boxes unchecked until that hosted check is true. Then check them in the problem statement as a separate edit.

## 17. Requirement coverage

| Ids | Phase |
| --- | --- |
| J2 key, J5 shapes | 1 |
| J1, J3, P1 | 2 |
| J1, J3, J4, P2 from a desk result | 3 |
| J2, J5 | 4 |
| W1 fee line, W2, G1–G5, S3, A1 on explainer text | 5 |
| W3 library, W4, B2, S2 | 6 |
| R1–R5, B1, B3, B5 | 7 |
| W3 HTTP, W4, B4, E2 path | 8 |
| Section 8 queue and approval, G5 | 9 |
| W1–W4 on the console | 10 |
| C1–C5, E1–E3, A2–A4, P3 fixtures | 11 |
| Submission README and demo script, B6 stated | 12 |

S1, S4, A2–A4, and the desk reviewer stay in `src/supportdesk/`. Phases 7 and 11 call them. They are not reimplemented.

## 18. Risks

| Risk | What the phase does |
| --- | --- |
| Milestone 1 catalog is missing on a machine | Facts stay not covered. Phase 5 does not invent bullets. Phase 11 records `not run` rather than pass. |
| Most Play Store complaints are outside the catalog | C2 and a high not-covered count are success. C1 must still pass on a catalog question. |
| Hosted Gmail cannot update a draft | Phase 7 tests keep `uncertain` unretried. The approval screen states that a failed draft retry can duplicate. |
| `app.py` is easy to damage | Phases 7 and 8 add a router include, not a second copy of the pipeline. |
| Signals would blow the 250-word gate | Phase 6 tests that `note.md` bytes do not change. |
| Queue dies on process restart | Phase 2 `desk_cases` blob. Approval logic stays in the desk package. |

## 19. Phase notes

Add a short record here when a phase finishes: files created, command run, pass count, and anything the next phase must not redo.

**Phase 0.** Problem statement, architecture, and this plan are in `docs/capstone/`. No application files created. Pytest was not run. Next action is the branch `capstone-support-desk`, then Phase 1.

Phase 1. Identity and contracts.
Files: `src/capstone/__init__.py`, `src/capstone/identity.py`, `src/capstone/contracts.py`, `tests/capstone/test_identity.py`, `tests/capstone/test_contracts.py`.
Pytest: `python -m pytest tests/capstone -q` passed (13). `python -c "import capstone"` works. Ruff and mypy are not configured.
Next phase: Phase 2 log, ledger, and case store. Do not redo the question key or these extra=forbid models.

Phase 2. Log, ledger, and case store.
Files: `src/capstone/log.py`, `tests/capstone/test_log.py`, `.gitignore` entry `data/capstone.db`, and the `desk_cases` table in architecture section 6.
Pytest: `python -m pytest tests/capstone -q` passed (19). Ruff and mypy are not configured.
Next phase: Phase 3 record a reviewed case. Do not redo the question key, the extra=forbid models, or this store schema.

Phase 3. Record a reviewed case.
Files: `src/capstone/record.py`, `tests/capstone/test_record.py`, and pytest `addopts` `--import-mode=importlib` so both `test_contracts` modules collect together.
Pytest: `python -m pytest tests/capstone tests/supportdesk -q` passed (162). Ruff and mypy are not configured.
Next phase: Phase 4 support signals. Do not redo `record_case`, the log schema, or the question key.

Phase 4. Support signals.
Files: `src/capstone/signals.py`, `tests/capstone/test_signals.py`, and optional pattern fields on `SupportSignal` for EC-SIG-05.
Pytest: `python -m pytest tests/capstone -q` passed (31). Ruff and mypy are not configured.
Next phase: Phase 5 fee theme and explainer. Do not redo queue signals, `record_case`, the log schema, or the question key.

Phase 5 fee theme. Selection only. Explainer bullets and `explainer.json` are not written.
Files: `src/capstone/explainer.py` (`select_fee_theme`), `tests/capstone/test_fee_theme.py`.
Pytest: `python -m pytest tests/capstone/test_fee_theme.py -q` passed (4). Ruff and mypy are not configured.
Next phase: factual explainer bullets. Do not redo fee-theme selection, queue signals, `record_case`, the log schema, or the question key.

Phase 5 factual bullets. Ledger bullet and `explainer.json` are not written. Frozen questions: What is the exit load on HDFC Mid Cap Fund Direct Growth?; What is the exit load on HDFC Gold ETF Fund of Fund Direct Plan Growth?; What is the exit load on HDFC Large Cap Fund Direct Growth?; What is the expense ratio of HDFC Mid Cap Fund Direct Growth?; What is the expense ratio of HDFC Small Cap Fund Direct Growth?; What is the expense ratio of HDFC Gold ETF Fund of Fund Direct Plan Growth?; What is the expense ratio of HDFC Large Cap Fund Direct Growth?; What is the expense ratio of HDFC ELSS Tax Saver Fund Direct Plan Growth?
Files: `src/capstone/explainer.py` (`FEE_QUESTIONS`, `factual_bullets`), `tests/capstone/test_explainer_facts.py`.
Pytest: `python -m pytest tests/capstone/test_fee_theme.py tests/capstone/test_explainer_facts.py -q` passed (11). Ruff and mypy are not configured.
Next phase: ledger bullet and explainer file. Do not redo fee-theme selection, this question list, queue signals, `record_case`, the log schema, or the question key.

Phase 5 explainer file. The last bullet quotes the ledger, or the exact empty-ledger sentence. Advice, performance, and personal-data gates write nothing.
Files: `src/capstone/explainer.py` (`ledger_bullet`, `write_explainer`), `tests/capstone/test_explainer.py`.
Pytest: `python -m pytest tests/capstone -q` passed (46). Ruff and mypy are not configured.
Next phase: Phase 6 assemble and package hash. Do not redo fee-theme selection, the frozen question list, the explainer gates, queue signals, `record_case`, the log schema, or the question key.

Phase 6 assemble and package hash. Canonical JSON and SHA-256 cover `note.md`, `explainer.json`, and `support_signals.json`. A failed pulse manifest writes nothing, and `note.md` bytes stay unchanged.
Files: `src/capstone/package.py`, `src/capstone/gates.py`, `src/capstone/assemble.py`, `tests/capstone/test_assemble.py`.
Pytest: `python -m pytest tests/capstone -q` passed (51). Ruff and mypy are not configured.
Next phase: Phase 7 desk HTTP submit and queue. Do not redo the package hash, the explainer gates, fee-theme selection, queue signals, `record_case`, the log schema, or the question key.

Phase 7 desk HTTP submit and queue. A question is sanitized, orchestrated, reviewed, and stored. The queue returns sanitized text, the draft or not-covered marker, citation, reviewer flag, and state. Refine, decision, and publish are not on this router.
Files: `src/capstone/api/desk.py`, `src/capstone/log.py` (`list_case_ids`), `tests/capstone/test_desk_api.py`, one `include_router` in `src/reviewpulse/api/app.py`.
Pytest: `python -m pytest tests/capstone/test_desk_api.py tests/supportdesk -q` passed (142). Ruff and mypy are not configured.
Next phase: Phase 7 desk HTTP decide and publish. Do not redo submit, the queue, the package hash, the explainer gates, fee-theme selection, queue signals, `record_case`, the log schema, or the question key.

Phase 7 desk HTTP decide and publish. Refine and decision call the desk functions. Publish calls `publish_case` only when the workflow and the current hash allow it. A reject stays on the queue, a changed reply makes no MCP call, a second review failure stays blocked, and a timeout is not retried.
Files: `src/capstone/api/desk.py`, `tests/capstone/test_desk_api.py`.
Pytest: `python -m pytest tests/capstone tests/supportdesk -q` passed (197). Ruff and mypy are not configured.
Next phase: Phase 8 weekly package HTTP. Do not redo desk submit, queue, refine, decision, publish, the package hash, the explainer gates, fee-theme selection, queue signals, `record_case`, the log schema, or the question key.

Phase 8 weekly package HTTP. Assemble returns the package hash and does not call MCP. A decision stores that hash beside `package.json`. Publish refuses a different hash and refuses a desk case id. Package approval leaves the desk state file unchanged, and desk approval leaves the pulse state file unchanged.
Files: `src/capstone/api/package.py`, `tests/capstone/test_package_api.py`, one `include_router` in `src/reviewpulse/api/app.py`.
Pytest: `python -m pytest tests/capstone -q` passed (63). Ruff and mypy are not configured.
Next phase: Phase 9 queue page. Do not redo package HTTP, desk submit, queue, refine, decision, publish, the package hash, or the explainer gates.

Phase 9 queue list. Each row shows the sanitized question, the draft or a not-covered badge, the citation, the reviewer flag, the state, and the intent chips that the stored case fields support.
Files: `web/app/queue/page.tsx`, `web/lib/api.ts` (`deskQueue`), `web/components/chrome/AppShell.tsx`, `web/next.config.mjs`, `src/capstone/api/desk.py` (chip fields on the queue row).
Typecheck: `npx tsc --noEmit` in `web/` passed with no errors. Ruff and mypy are not configured.
Next phase: Phase 9 case page and source panel. Do not redo the queue list, package HTTP, desk submit, or desk publish.

Phase 9 case page. The page shows the stored reply, routing note, source panel, and each agent's start and end time. A missing last-checked date stays the words `date unavailable`. A not-covered case lists the pages searched.
Files: `web/app/queue/[caseId]/page.tsx`, `web/lib/api.ts` (`deskCase`), `src/capstone/api/desk.py` (`searched_urls` on the case view).
Typecheck: `npx tsc --noEmit` in `web/` passed with no errors. Ruff and mypy are not configured.
Next phase: Phase 9 desk approval page. Do not redo the case page, the queue list, package HTTP, or desk publish.

Phase 9 desk approval page. The page shows the exact reply, the exact routing note, the Doc id, the draft recipient, and the content hash, and it states that Gmail send will not be called. Approve and reject post to the decision route. Publish posts an empty body, and only after the case is approved.
Files: `web/app/queue/[caseId]/approve/page.tsx`, `web/lib/api.ts` (`deskDecision`, `deskPublish`), `src/capstone/api/desk.py` (hash and destination on the case view).
Typecheck: `npx tsc --noEmit` in `web/` passed with no errors. Ruff and mypy are not configured.
Next phase: browser check of the queue screens. Do not redo the approval page, the case page, or the queue list.

Browser check of the queue. Opened `/queue` (empty), submitted a covered expense-ratio question and a not-covered cheque question through the console, then clicked the rows. The cheque case showed the not-covered reply, searched-pages panel, and agent times. Reject left it on the queue as rejected with a Not covered chip. The expense-ratio case showed the claim, the Groww link, and last checked 2026-09-01, plus a Fact chip. Approve posted `{decision, approver_ref}` and Publish posted `{}`. Neither body had a send flag. Publish was disabled until approve, and the page said Gmail send will not be called.
The live theme run `20261109T114721Z-e377e872` matched neither question, so both stored cases had pattern `insufficient_data` and no theme id. A complaint-plus-fact case was not on the queue. That fixture is missing. No chips were invented.
Files: no code changes.
Next phase: one weekly trigger. Do not redo the queue screens.

Phase 10 pipeline hook. After a successful pulse job with a run id, the job calls assemble once. A failed pulse is not assembled. A failed assemble leaves `note.md` in place, writes no package hash, and does not publish. The hook does not call MCP, and `reviewpulse run --send` is not wired to assemble.
Files: `src/capstone/pipeline_hook.py`, `src/reviewpulse/api/jobs.py` (`_run`), `tests/capstone/test_pipeline_hook.py`.
Pytest: `python -m pytest tests/capstone/test_pipeline_hook.py tests/capstone/test_assemble.py -q` passed (10). Ruff and mypy are not configured.
Next phase: pulse and publish screens. Do not redo the pipeline hook.

Phase 10 pulse and publish screens. Under the existing pulse, an assembled package shows the explainer and the support-signal lines. Each signal is labeled `queue`, and theme counts stay labeled `pattern`. An empty ledger shows `No queued question in this week was outside the corpus.` A five-times row shows the queue line. Publish shows the package hash and `note.md`, `explainer.json`, and `support_signals.json`, and posts that hash to the package route.
Files: `web/app/page.tsx`, `web/app/publish/page.tsx`, `web/lib/api.ts`, `web/next.config.mjs`.
Typecheck: `npx tsc --noEmit` in `web/` passed with no errors. Ruff and mypy are not configured.
Next phase: browser check of the pulse and publish screens. Do not redo these blocks.

Browser check of pulse and publish. Assembled `20261109T114721Z-e377e872` through the package route. `note.md` stayed the same. The pulse page showed fee theme `t2`, the one ledger line for the cheque question, and the `queue` label. It did not show the empty-ledger sentence, because week `2026-W46` has one ledger row. It did not show a five-times line, because neither logged question has five rows. Publish showed hash `6a29c5581b159c7fedec45d873d48e7f34115a42ff071b4cfe454c3a7ca320b7` and the three artifact names. Approving that hash left both desk cases byte-identical. Publish package was not clicked.
Files: no code changes.
Next phase: scenarios C1 through C5. Do not redo the pulse and publish screens.

Phase 11 scenarios C1 through C5. Covered fact, not covered, five charge questions, a phone number, and advice-then-block all run on fakes. No hosted MCP call and no live model.
Files: `tests/capstone/test_scenarios.py`.
Pytest: `python -m pytest tests/capstone/test_scenarios.py -q` passed (5). Ruff and mypy are not configured.
Next phase: evaluation E1 through E3. Do not rewrite C1–C5.

Phase 11 evaluation E1 through E3. One assemble stops at the package hash, a different hash is refused, and a desk rejection leaves `explainer.json` unchanged. Five claims keep their link, passage, and review ids. PAN, account, phone, and a return-figure request do not change either publish-state file.
Files: `tests/capstone/test_eval.py`, `docs/capstone/eval.md`.
Pytest: `python -m pytest tests/capstone -q` passed (76). E1 pass, E2 pass, E3 pass. Ruff and mypy are not configured.
Next phase: README and demo script. Do not rewrite C1–C5 or this evaluation.

Phase 12 README and demo script. The README points at the capstone architecture, the three sources, `SUPPORTDESK_PROJECT1_ROOT`, the two loops, C1–C5, the E1–E3 command, and the two state files. It states that the hosted MCP server is not exactly-once. The demo script is under three minutes and leaves the definition-of-done boxes unchecked.
Files: `README.md`, `docs/capstone/demo-script.md`. `data/capstone.db` was already in `.gitignore`. No new secret was added to `.env.example`.
Verification: documents only. The full suite was not run again. Ruff and mypy are not configured.
Next phase: none. The local build is finished. Commit, push, Railway redeploy, the hosted check, and the demo video stay manual.
