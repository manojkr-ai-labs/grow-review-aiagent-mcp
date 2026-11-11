# Capstone start prompt

Paste the one prompt below into a new chat. That is the only text you paste.

After each slice the agent asks: `Build the next slice? yes or no`

- `yes` builds the next slice.
- `no` stops.

Everything under Agent 1–21 is a slice instruction for that prompt. Do not paste those sections.

This finishes the local code build only. It does not commit, deploy, or record the demo.

BEGIN PROMPT

Build the Support Desk capstone one slice at a time. Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`.

On this turn, do the single next unfinished slice, then stop. The only replies you accept are `yes` and `no`. `yes` means build the next slice only. `no` means stop and do no more work. Do not start a later slice in the same turn.

Before editing, read only:

- `docs/capstone/implementation-plan.md` section 1 status table and section 19
- In `docs/capstone/agent-prompts.md`, the one `## Agent N` section for the slice below that has no section 19 note yet. Read from `SLICE START` to `SLICE END` inside that section only. Follow that section's files, tests, and done check.

Slice order: Agent 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21.

Extra rules that override the slice text:

- Stay on branch `capstone-support-desk`. Agent 1 creates it from `main` only when that branch is missing. Do not commit, push, or deploy.
- Agent 4 also implements edge case EC-SIG-05: the queue count is the number of log rows, and the stored pattern signal, pattern count, and analysis window are copied onto the signal when every row in the group shares them. A missing pattern result stays missing. Do not edit the customer draft.
- Agent 6 looks for the sibling `mutual-fund-faq-assistant` catalog before leaving the fee-question list empty. An empty list is allowed only when that catalog is absent.
- Do not read `docs/capstone/edge-case.md` except EC-SIG-05 on the Agent 4 turn.
- The same failing assertion twice: append a HANDOFF and stop. Do not start the next slice.
- Trust section 19 over earlier chat if they disagree.

When the slice's done check passes, append four lines to section 19 and stop. End with this question and nothing after it: `Build the next slice? yes or no`

When Agent 21's done check has already passed, do no more work. Say the local build is finished, and that commit, push, Railway redeploy, the hosted check, and the demo video are still manual.

END PROMPT

The sections below are slice instructions for the prompt above. Do not paste them.

| Agent | Phase | What it finishes | Stop the agent at |
| --- | --- | --- | --- |
| 1 | 1 | Question key and contracts | 15 min |
| 2 | 2 | SQLite log, ledger, case blob | 15 min |
| 3 | 3 | Record one reviewed desk case | 15 min |
| 4 | 4 | Five-times support signals | 12 min |
| 5 | 5a | Fee-theme pick only | 12 min |
| 6 | 5b | Factual explainer bullets | 15 min |
| 7 | 5c | Ledger bullet, gates, `explainer.json` | 15 min |
| 8 | 6 | Package hash and assemble | 15 min |
| 9 | 7a | Submit a question and read the queue | 15 min |
| 10 | 7b | Refine, decide, publish | 15 min |
| 11 | 8 | Weekly package HTTP | 15 min |
| 12 | 9a | Queue page | 15 min |
| 13 | 9b | Case page and source panel | 15 min |
| 14 | 9c | Desk approval page | 15 min |
| 15 | 9 verify | Browser check of the queue only | 15 min |
| 16 | 10a | One pipeline trigger calls assemble | 15 min |
| 17 | 10b | Pulse and publish screens | 15 min |
| 18 | 10 verify | Browser check of pulse and publish | 12 min |
| 19 | 11a | Scenarios C1–C5 | 15 min |
| 20 | 11b | E1–E3 and `eval.md` | 15 min |
| 21 | 12 | README section and demo script | 12 min |

---

## Agent 1 — identity and contracts

SLICE START

Finish only Phase 1 of the Support Desk capstone. Do not start Phase 2.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

First command, and only if the current branch is not already `capstone-support-desk`:

`git checkout main` then `git checkout -b capstone-support-desk`

If `main` is dirty, stop and say so. Do not stash, commit, or push.

Read only:

- `docs/capstone/implementation-plan.md` sections 2, 3, and 5 (Phase 1). Stop at section 6.
- `docs/capstone/architecture.md` section 4.1 only.
- `docs/capstone/edge-case.md` headings EC-ID-01 through EC-ID-05 and EC-ID-12 only. Do not read the rest of that file.

Create:

- `src/capstone/__init__.py`
- `src/capstone/identity.py` with `question_key` and `counts_for_signal`
- `src/capstone/contracts.py` — Pydantic models, `extra = forbid`, for a log row, a ledger row, a support signal, an explainer bullet, an explainer, and a weekly package manifest. `evidence_type` for a signal allows only `queue`.
- `tests/capstone/test_identity.py`
- `tests/capstone/test_contracts.py`

Key rule, in this order: NFKC, casefold, strip `[pan]` `[aadhaar]` `[account]` `[phone]` `[email]` `[otp]`, keep letters and digits, collapse whitespace. Empty key means `counts_for_signal` is false. No stemming. No model call.

Tests: same key for different case and spacing; a PAN placeholder and a phone placeholder share a key and the key contains neither; empty or punctuation-only yields an empty key; a model dump rejects an unknown field and rejects `evidence_type` of `pattern` or `review`.

Do not open SQLite. Do not import `reviewpulse`. Do not add HTTP routes. Do not edit `src/supportdesk/` or `src/reviewpulse/`.

Done when `python -m pytest tests/capstone -q` passes and `python -c "import capstone"` works.

Then append four lines to section 19 of `docs/capstone/implementation-plan.md`: phase, files, pytest result, next phase. Stop.

If the same assertion fails twice, stop after the second failure and append a HANDOFF instead of a third fix.

SLICE END

---

## Agent 2 — log, ledger, case store

SLICE START

Finish only Phase 2. Stay on branch `capstone-support-desk`. If that branch does not exist, stop. Do not start Phase 3.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` sections 3 and 6, plus the Phase 1 note in section 19.
- `docs/capstone/architecture.md` section 6 only.
- `src/capstone/contracts.py` and `src/capstone/identity.py`. Do not re-read the edge-case file.

Create `src/capstone/log.py` and `tests/capstone/test_log.py`. Add `data/capstone.db` to `.gitignore`.

SQLite file default `data/capstone.db`. Tests pass a temporary path. Tables: `question_log`, `not_covered_ledger` (architecture section 6), and `desk_cases(case_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)`.

Behavior: append a covered row writes no ledger row. Append a not-covered row copies case id, sanitized text, searched URLs, week, and theme id in the same transaction. A second append of the same `case_id` updates and does not duplicate the ledger. No column name contains `raw`. Round-trip a sanitized case JSON blob. Reject a payload that is missing the keys the contract requires. Do not import the Milestone 3 case model if that import starts the app or loads a corpus.

Do not call the facts agent. Do not write `explainer.json`. Do not add a route. Do not edit `src/supportdesk/` or `src/reviewpulse/`.

In `docs/capstone/architecture.md`, add `desk_cases` to the schema table in section 6. No other architecture edit.

Done when `python -m pytest tests/capstone -q` passes.

Append four lines to section 19. If the same assertion fails twice, append a HANDOFF and stop.

SLICE END

---

## Agent 3 — record a reviewed case

SLICE START

Finish only Phase 3. Stay on `capstone-support-desk`. Do not start Phase 4.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 7 and the Phase 2 note in section 19.
- `src/capstone/log.py`, `src/capstone/identity.py`, `src/capstone/contracts.py`.
- Signatures only, not the whole files: `src/supportdesk/decisions.py` class `DeskCase` (about line 96), `src/supportdesk/reviewer.py` `review_case` (about line 213), `src/supportdesk/contracts.py` `FactsResult` and `PatternResult`.

Create `src/capstone/record.py` and `tests/capstone/test_record.py`.

`record_case` runs only after a reviewed case exists. It does not call `orchestrate` or `publish_case`. Build the log row from the sanitized request, facts coverage, `searched_urls`, pattern `theme_id` only when the match is real (`insufficient_data` stores null), and `identity.question_key`. Week id is the ISO week in `Asia/Kolkata`, format `YYYY-Www`. Tests pass a fixed clock. If compliance blocked the case because redaction failed, write nothing. A raw 10-digit phone or a PAN pattern must not be stored. Placeholders such as `[phone]` may be stored.

Tests: covered fact writes one log row and no ledger row, and stores the case blob. Not-covered writes log and ledger with the facts URLs. Blocked redaction leaves all three tables unchanged. The function does not call `publish_case`.

Do not add the five-times rollup. Do not change `supportdesk.orchestrate`. Do not add HTTP.

Done when `python -m pytest tests/capstone tests/supportdesk -q` passes.

Append four lines to section 19. Two failures of the same assertion: HANDOFF and stop.

SLICE END

---

## Agent 4 — support signals

SLICE START

Finish only Phase 4. Stay on `capstone-support-desk`. Do not start Phase 5.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 8 and the Phase 3 note in section 19.
- `docs/capstone/architecture.md` section 4.3 only.
- `src/capstone/log.py` and `src/capstone/contracts.py`.

Create `src/capstone/signals.py` and `tests/capstone/test_signals.py`.

Read one `week_id`. Group by non-empty `question_key`. Emit a signal at count >= 5. `case_ids` sorted. `theme_id` only when every row in the group has that same id, otherwise null. `evidence_type` is `queue`. Render this template with no model call:

`Support was asked "{question_key}" {count} times in {week_id}. This line is the question log, not review volume.`

Write `runs/<run_id>/support_signals.json` as a list. An empty list is valid. A function handed `clusters.json` and no log rows returns an empty list.

Tests: five rows one key; four rows empty; empty keys excluded; mixed theme ids yield null; file round-trip uses the contract model.

Do not edit `note.md`. Do not mention the signal inside the 250-word note. Do not add HTTP.

Done when `python -m pytest tests/capstone -q` passes.

Append four lines to section 19. Two failures of the same assertion: HANDOFF and stop.

SLICE END

---

## Agent 5 — fee theme only

SLICE START

Finish only the fee-theme half of Phase 5. Stay on `capstone-support-desk`. Do not write explainer bullets or `explainer.json`.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 9, the fee-theme decision in section 3 item 6, and the Phase 4 note in section 19.
- `docs/capstone/architecture.md` section 4.5, first paragraph only.

Create `src/capstone/explainer.py` with one function that reads `clusters.json` and returns the winning fee theme or null. Create `tests/capstone/test_fee_theme.py`.

A theme qualifies when its label or keywords contain one of `fee`, `fees`, `charge`, `charges`, `brokerage`, `exit load`, `expense ratio`, `demat`, `amc`, and its member count is at least 3. Largest count wins. No match returns `fee_theme: null` and the sentence that no fee theme met the bar. Do not invent a theme id. Do not call a model. Do not call `answer_facts`.

Tests: two qualifying themes, the larger count wins. No qualifying theme returns null and the bar sentence. A count of 2 does not qualify.

Do not open the Milestone 1 catalog in this prompt. Do not add HTTP.

Done when `python -m pytest tests/capstone/test_fee_theme.py -q` passes.

Append four lines to section 19. Two failures of the same assertion: HANDOFF and stop.

SLICE END

---

## Agent 6 — factual explainer bullets

SLICE START

Finish only the factual-bullet half of Phase 5. Stay on `capstone-support-desk`. Do not write the ledger bullet and do not write `explainer.json` yet.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 9 and section 3 item 7.
- `docs/capstone/architecture.md` section 4.5, the factual-bullet paragraph.
- `src/supportdesk/facts.py` function `answer_facts` only (about lines 94–143) and `FactClaim` in `src/supportdesk/contracts.py`.
- `src/capstone/explainer.py` as it exists after Agent 5.

If `SUPPORTDESK_PROJECT1_ROOT` is set, list fee-related question titles in that catalog and freeze them as an ordered constant in `explainer.py`. Spend at most five minutes on that lookup. If the root is unset or the catalog is missing, leave the constant empty. Do not clone a repo. Do not invent a claim to fill an empty list. Record the constant, or that it is empty, in section 19.

For each frozen question, call `answer_facts` with an injected `retriever`. Keep a bullet only when coverage is `covered`, the claim text is a substring of the retrieved passage, and the URL host is `groww.in` or `www.groww.in`. Stop at five links. A not-covered result is not a bullet. Last-checked date is the retrieval value, or an explicit unavailable marker. Never fill today's date.

Tests in `tests/capstone/test_explainer_facts.py` use a fake retriever. An off-host URL or a claim that is not in the passage produces no bullet. Do not call the hosted corpus.

Do not hash a package. Do not add HTTP. Do not edit `src/supportdesk/`.

Done when `python -m pytest tests/capstone/test_fee_theme.py tests/capstone/test_explainer_facts.py -q` passes.

Append four lines to section 19, including the frozen question list or `empty`. Two failures of the same assertion: HANDOFF and stop.

SLICE END

---

## Agent 7 — ledger bullet and explainer file

SLICE START

Finish Phase 5. Stay on `capstone-support-desk`. Do not start Phase 6.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 9 and the Agent 6 note in section 19.
- `docs/capstone/architecture.md` sections 4.4 and the last paragraph of 4.5.
- `src/capstone/explainer.py` and `src/capstone/log.py`.
- Advice and PII checkers already in the desk: `src/supportdesk/advice.py` function names `requests_advice` and `requests_performance`, and `src/supportdesk/privacy.py` `contains_pii`. Call them. Do not copy their patterns into a new scanner unless the call cannot see explainer text.

Last bullet: ledger rows for that week, each cited by `case_id` and sanitized text, or exactly `No queued question in this week was outside the corpus.` Six ledger rows still produce one last bullet that contains every case id. Total bullets at most six. Official links at most five.

Reject the explainer when a bullet matches advice or performance, when content matches a PII pattern, or when links or bullets exceed the caps. On failure write nothing and return the failing codes. On success write `runs/<run_id>/explainer.json`.

Tests in `tests/capstone/test_explainer.py`. Include: empty ledger exact sentence, six case ids in one bullet, a bullet that says "you should redeem" writes no file, last-checked date is never today's date filled in by the explainer.

Do not call the hosted corpus. Do not hash the package. Do not add HTTP.

Done when `python -m pytest tests/capstone -q` passes.

Append four lines to section 19. Two failures of the same assertion: HANDOFF and stop.

SLICE END

---

## Agent 8 — assemble and package hash

SLICE START

Finish only Phase 6. Stay on `capstone-support-desk`. Do not hook the pipeline and do not add HTTP.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 10 and the Phase 5 note in section 19.
- `docs/capstone/architecture.md` section 5, the package-file table and the hash paragraph. Skip the MCP paragraphs.
- `src/capstone/explainer.py`, `src/capstone/signals.py`, `src/capstone/log.py`.

Create:

- `src/capstone/package.py` — canonical JSON (`sort_keys`, compact separators, UTF-8) and SHA-256 over the bytes of `note.md`, `explainer.json`, and `support_signals.json` in that order.
- `src/capstone/gates.py` — do not reimplement the 250-word count. Read the existing pulse manifest and refuse a note whose gates failed. Re-run the Phase 5 bullet, link, advice, and PII gates.
- `src/capstone/assemble.py`
- `tests/capstone/test_assemble.py`

Input is a `run_id` whose `note.md` and `clusters.json` already exist, plus a log database and a clock. Refuse when the pulse gate record is missing or failed. Do not publish. Write the two JSON files, then the hash, then `runs/<run_id>/package.json` with the hash, `fee_theme`, and file names. Do not store the note body twice. Assemble does not import the MCP client and does not call `publish_case`.

Tests: fixture run with a passing pulse manifest, five log rows, and a fake facts retriever. Hash stable across two calls. `note.md` bytes identical before and after. Failed pulse manifest writes no JSON and no hash. Empty signals and empty ledger still write files, and the last bullet is the empty sentence. A one-byte note change changes the hash.

Done when `python -m pytest tests/capstone -q` passes.

Append four lines to section 19. Two failures of the same assertion: HANDOFF and stop.

SLICE END

---

## Agent 9 — desk HTTP, submit and queue

SLICE START

Finish only the read and submit half of Phase 7. Stay on `capstone-support-desk`. Do not implement refine, decision, or publish in this prompt.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 11, routes list, and the Phase 6 note in section 19.
- `docs/capstone/architecture.md` section 7, the `/api/desk` rows only.
- `src/reviewpulse/api/app.py` lines 66–75 only, to see how `app` is created. Do not read the rest of that file.
- How a desk case is produced: `src/supportdesk/orchestrate.py` search for the public orchestrate function name, and `src/supportdesk/reviewer.py` `review_case`, and `src/capstone/record.py`. Read those function signatures, not the whole modules.
- `tests/contract/test_api.py` only far enough to copy the existing TestClient setup. Stop after the first test.

Create `src/capstone/api/desk.py` as an `APIRouter` and `tests/capstone/test_desk_api.py`. Add one `include_router` in `src/reviewpulse/api/app.py`. That include is the only edit in `app.py`.

Implement now:

- `POST /api/desk/questions` — sanitize, orchestrate, review, then `record.record_case`. Response is the stored case. Ignore a client field named `citation` or `count`.
- `GET /api/desk/queue` — sanitized text, draft or not covered, citation or searched URLs, reviewer flag, state.
- `GET /api/desk/cases/{case_id}` — draft, routing note, agent timings, claims, reviewer findings.

Tests through the HTTP client: one covered question, one not-covered question, one message with a phone-shaped number so the stored body has no raw number, one advice refusal. Use fakes. Do not call hosted MCP. Do not call a live model if the desk already has a deterministic path; if a test would need a live model, inject the same fakes the support-desk tests use. Look in `tests/supportdesk/test_orchestrate.py` only for the fake pattern, then stop reading.

Do not build React pages. Do not assemble a weekly package inside the question route.

Done when `python -m pytest tests/capstone/test_desk_api.py tests/supportdesk -q` passes.

Append four lines to section 19. Two failures of the same assertion: HANDOFF and stop.

SLICE END

---

## Agent 10 — desk HTTP, decide and publish

SLICE START

Finish Phase 7. Stay on `capstone-support-desk`. Do not start Phase 8.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 11, the publish bullets, and the Agent 9 note in section 19.
- `src/capstone/api/desk.py` as Agent 9 left it.
- Signatures only: `src/supportdesk/decisions.py` `refine` and `decide`, `src/supportdesk/publish.py` `publish_case`, `src/supportdesk/workflow.py` `assert_mcp_permitted`, `src/supportdesk/approval.py` `approval_matches`.
- `tests/contract/fake_mcp.py` far enough to see the fake client. Do not read the whole contract suite.

Add to the existing router:

- `POST /api/desk/cases/{case_id}/refine` — `supportdesk.decisions`. Do not open `explainer.json`.
- `POST /api/desk/cases/{case_id}/decision` — approve or reject the current hash.
- `POST /api/desk/cases/{case_id}/publish` — `publish_case` only when `assert_mcp_permitted` and `approval_matches` succeed. No `allow_send` parameter. `send_email` must be absent from the fake client call list. A `blocked` case returns an error and does not call the fake client. A timeout is not retried.

Tests: reject leaves the case on the queue, and a fixture `explainer.json` is byte-for-byte unchanged. Approve hash A, change the reply, attempt publish: no MCP call. Second reviewer failure: blocked, no MCP call.

Do not build React. Do not add `/api/capstone` routes.

Done when `python -m pytest tests/capstone tests/supportdesk -q` passes.

Append four lines to section 19. Two failures of the same assertion: HANDOFF and stop.

SLICE END

---

## Agent 11 — weekly package HTTP

SLICE START

Finish only Phase 8. Stay on `capstone-support-desk`. Do not render the console and do not change `reviewpulse run --send`.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 12 and the Phase 7 note in section 19.
- `docs/capstone/architecture.md` section 7, the `/api/capstone` rows, and the state-file table in section 5.
- `src/capstone/assemble.py` and `src/capstone/package.py`.
- The pulse publisher entry used by `src/reviewpulse/api/app.py` `publish_append` (about line 470). Read that function only.

Create `src/capstone/api/package.py` and `tests/capstone/test_package_api.py`. Include this router from `app.py` next to the desk router. One include line. Do not copy pipeline code.

Routes:

- `POST /api/capstone/runs/{run_id}/assemble` calls Phase 6. It does not call MCP.
- `GET /api/capstone/runs/{run_id}/package` returns note, explainer, signals, hash, ledger rows.
- `POST /api/capstone/runs/{run_id}/decision` stores decision, hash, time, and `approver_ref` beside `package.json`. A later file change makes the stored hash fail `approval_matches`.
- `POST /api/capstone/runs/{run_id}/publish` uses the pulse publisher and `data/publish-state.json`. Refuse when the hash differs. Refuse when the caller is a desk case id.

Package publish may call `draft_email` and, only when the approved action says send, `send_email`. Desk publish still cannot send.

Tests: assemble on a fixture returns the hash and does not touch the fake MCP client. Publish of hash B after approval of hash A is rejected. Approving a package leaves `data/supportdesk-publish-state.json` unchanged. Approving a desk case leaves `data/publish-state.json` unchanged. Rejecting a desk case leaves `explainer.json` unchanged.

Done when `python -m pytest tests/capstone -q` passes.

Append four lines to section 19. Two failures of the same assertion: HANDOFF and stop.

SLICE END

---

## Agent 12 — queue page

SLICE START

Build only the queue list. Stay on `capstone-support-desk`. Do not build the case page or the approval page.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 13, the queue-row bullet, and section 3 item 11.
- `docs/capstone/architecture.md` section 8, the `/queue` row and the intent-chip table.
- `web/components/chrome/AppShell.tsx` nav array only (about lines 14–21).
- `web/lib/api.ts` only far enough to copy one existing fetch helper. Stop after that helper.
- One existing page, `web/app/page.tsx`, only for layout habits. Do not restyle it.

Create `web/app/queue/page.tsx`. Add the API functions this page needs in `web/lib/api.ts`. Add a Queue nav entry in `AppShell.tsx`.

Each row shows sanitized question, draft or not covered, citation or not-covered badge, reviewer flag, state, and every intent chip that applies, in this order: Personal data, Advice, Complaint, Fact, Not covered. Chips come from stored fields. Do not infer them with a model.

Do not call MCP from the browser. Do not edit pulse pages. Do not start a long dev-server session. A TypeScript check of the new page is enough in this prompt.

Done when `npx tsc --noEmit` in `web/` reports no error in the files you touched, and the page compiles against `GET /api/desk/queue`.

Append four lines to section 19. If a type error in your files survives two fixes, HANDOFF and stop. Do not fix unrelated type errors.

SLICE END

---

## Agent 13 — case page and source panel

SLICE START

Build only the case page. Stay on `capstone-support-desk`. Do not build the approval page.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 13, the case-page bullet.
- `docs/capstone/architecture.md` section 8, the `/queue/[caseId]` row and the last-checked paragraph.
- `web/app/queue/page.tsx` and the desk client functions already in `web/lib/api.ts`.

Create `web/app/queue/[caseId]/page.tsx`. Add only the client function this page needs.

Show the reply, the routing note, and the source panel. For a covered claim show the claim, the allow-listed link, and the last-checked date. If the date is missing, show the words `date unavailable`. Do not invent a date. For not covered, show the pages searched. Show each agent's start and end time from the stored case.

Do not call MCP from the browser. Do not restyle the queue list beyond a link to this page.

Done when `npx tsc --noEmit` in `web/` reports no error in the files you touched.

Append four lines to section 19. Two failed fixes of the same type error: HANDOFF and stop.

SLICE END

---

## Agent 14 — desk approval page

SLICE START

Build only the desk approval page. Stay on `capstone-support-desk`. Do not change the pulse publish page.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 13, the approval-page bullet.
- `docs/capstone/architecture.md` section 8, the approve row.
- `web/app/queue/[caseId]/page.tsx` and `web/lib/api.ts` desk helpers.
- The request body of `POST /api/desk/cases/{case_id}/decision` and `POST /api/desk/cases/{case_id}/publish` in `src/capstone/api/desk.py`. Read those two handlers only.

Create `web/app/queue/[caseId]/approve/page.tsx`.

Show the exact reply, the exact routing note, the Doc id, the draft recipient, the content hash, and the sentence that Gmail send will not be called. Approve and reject post to the decision route. Publish posts only after approve, and only for the hash on screen. The publish request body has no send flag.

Do not call MCP from the browser.

Done when `npx tsc --noEmit` in `web/` reports no error in the files you touched.

Append four lines to section 19. Two failed fixes of the same type error: HANDOFF and stop.

SLICE END

---

## Agent 15 — browser check of the queue

SLICE START

Verify the queue screens. Stay on `capstone-support-desk`. Do not add features. One bug fix is allowed if a click fails. A second bug stops you.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only section 13 of `docs/capstone/implementation-plan.md`, the "Verify in the browser" paragraph, and `web/app/queue/page.tsx`.

Start the API and the console if they are not already running (`reviewpulse serve`, then `npm run dev` in `web/`). Use the browser tools.

Do this and then stop:

1. Submit one covered question and one not-covered question.
2. Reject one.
3. Open the other and approve it. Confirm the publish request body has no send flag.
4. Confirm a complaint-plus-fact case shows both chips when the stored case has both signals. If you cannot produce that case from the fixtures without a long setup, say which fixture was missing and stop. Do not invent data in the UI.

Do not restyle the pulse pages. Do not call MCP from the browser. Do not run the full weekly pipeline.

Append what you clicked and what you saw to section 19. If a server is already running in a terminal, use it. Do not start a second copy.

SLICE END

---

## Agent 16 — one weekly trigger

SLICE START

Finish only the pipeline hook of Phase 10. Stay on `capstone-support-desk`. Do not edit React pages in this prompt.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 14, the "Edit" bullets and the "Do not" lines.
- `src/reviewpulse/api/jobs.py` method `_run` (about lines 116–157).
- `src/capstone/assemble.py` signature only.

After the pipeline function returns success and `job.run_id` is set, call `capstone.assemble`. Do not call assemble when the pulse gates failed. A failed assemble leaves `note.md` in place, writes no package hash, and does not publish. Do not call MCP inside this hook. Do not edit `reviewpulse.orchestrator.run_pipeline`. Do not wire `reviewpulse run --send` to assemble.

Add an API-level test that runs the trailing assemble on a fixture and asserts one trigger, no MCP call, and a hash. Put it in `tests/capstone/test_pipeline_hook.py`. The test may call the hook function directly if driving `JOBS.start` would start a real pipeline. Do not download reviews. Do not call a model.

Done when `python -m pytest tests/capstone/test_pipeline_hook.py tests/capstone/test_assemble.py -q` passes.

Append four lines to section 19. Two failures of the same assertion: HANDOFF and stop.

SLICE END

---

## Agent 17 — pulse and publish screens

SLICE START

Finish the console half of Phase 10. Stay on `capstone-support-desk`. Do not change the pipeline hook again.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 14, the `web/app/page.tsx` and `web/app/publish/page.tsx` bullets.
- `docs/capstone/architecture.md` section 8, the `/` and `/publish` rows.
- The package GET handler in `src/capstone/api/package.py`.
- The existing render sections of `web/app/page.tsx` and `web/app/publish/page.tsx`. Do not rewrite the pages. Add blocks.

On `/`, under the existing pulse, show the explainer and the support-signal block. Label signals `queue`. Leave theme counts labeled as pattern evidence. When the ledger is empty, show the exact sentence `No queued question in this week was outside the corpus.` When five-times rows exist, show that line. Do not insert signal text into `note.md`.

On `/publish`, show the package hash and the three artifact names. Publish posts to the Phase 8 route.

Done when `npx tsc --noEmit` in `web/` reports no error in the files you touched.

Append four lines to section 19. Two failed fixes of the same type error: HANDOFF and stop.

SLICE END

---

## Agent 18 — browser check of pulse and publish

SLICE START

Verify the weekly screens on a fixture. Stay on `capstone-support-desk`. Do not add features. One bug fix is allowed. A second bug stops you.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only the "UI check" paragraph in section 14 of `docs/capstone/implementation-plan.md`.

Use the running console if one is up. Otherwise start `reviewpulse serve` and `npm run dev` in `web/`. Do not start a second copy of a server that is already running.

On a fixture run that already has a package: the pulse page shows the empty-ledger sentence when the ledger is empty, and a five-times line when the fixture has five rows. Open publish and confirm the package hash is on screen. Approving the package must not change a desk case. Do not run a live model pipeline. Do not call hosted MCP. If no fixture package exists, assemble one with the Phase 8 route against an existing `runs/<id>` that already has `note.md` and `clusters.json`. If none exists, stop and say so.

Append what you clicked and what you saw to section 19.

SLICE END

---

## Agent 19 — scenarios C1 through C5

SLICE START

Write and run C1–C5 only. Stay on `capstone-support-desk`. Do not write E1–E3 in this prompt.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 15, the scenario table. Stop before "Evaluation notes".
- `docs/capstone/ProblemStatements.md` section 10 only (the C1–C5 table).
- The desk and package routes you need, by name, in `src/capstone/api/desk.py` and `src/capstone/api/package.py`. Do not read `src/reviewpulse/`.

Create `tests/capstone/test_scenarios.py`.

- C1: fake retriever, one allow-listed chunk. Draft has at most three sentences, one link, and a last-checked value or the unavailable marker.
- C2: retriever returns not covered. Ledger has the case. No guessed claim in the draft.
- C3: five identical sanitized charge questions and a fixture theme that meets the fee floor of 3. Routing note has signal, count, and window. Signal file has the queue line. Explainer has at most six bullets.
- C4: message contains a phone-shaped number. Response JSON, log row, and case blob do not contain the raw number.
- C5: "Should I redeem this fund?" then "What do you think?" on the same session id. Both refused. A separate double review failure is blocked and the fake MCP client records no call.

Use fakes. Do not call hosted MCP. Do not call a live model. If the sibling corpus is required and missing, skip that half and leave a comment that says `not run`. A skip is not a pass you should force.

Done when `python -m pytest tests/capstone/test_scenarios.py -q` passes.

Append four lines to section 19 with pass counts. Two failures of the same assertion: HANDOFF and stop. Do not edit `docs/capstone/eval.md` in this prompt.

SLICE END

---

## Agent 20 — evaluation E1 through E3

SLICE START

Write and run E1–E3, then record the result. Stay on `capstone-support-desk`. Do not rewrite C1–C5.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 15, "Evaluation notes" through the done line.
- `docs/capstone/ProblemStatements.md` section 11 only.
- `docs/capstone/architecture.md` section 10 only.

Create `tests/capstone/test_eval.py` and write `docs/capstone/eval.md`.

- E1: one assemble. Every queued case is a draft or not covered. Themes in the fixture carry review ids. Word count and bullet count pass. The weekly path stops at the hash. No MCP call.
- E2: approve hash A, refuse publish of hash B, and hash `explainer.json` before and after a desk rejection. The two hashes match.
- E3: five stored claims with link, passage, and review id where the pulse is involved. Then a PAN-shaped value, an account-shaped value, a phone-shaped value, and a return-figure request through the desk route. No publish-state file changes.

`docs/capstone/eval.md` records the command, today's date, and pass or fail for E1, E2, and E3. A check that did not run is the words `not run`. Do not mark a skip as pass. State the known limit: the Milestone 1 catalog is a bounded public-page index, and a high not-covered count on real complaints is correct when C1 still passes on a catalog question.

Use fixtures. Do not call hosted MCP. Do not download reviews.

Done when `python -m pytest tests/capstone -q` passes and `docs/capstone/eval.md` matches that run.

Append four lines to section 19. Two failures of the same assertion: HANDOFF and stop.

SLICE END

---

## Agent 21 — README and demo script

SLICE START

Finish only Phase 12. Stay on `capstone-support-desk`. Do not record a video. Do not check the definition-of-done boxes. Do not rewrite the existing Milestone 2 README sections.

Workspace: `D:\manoj\AI course\nextleap.app\grow-review-aiagent-mcp`

Read only:

- `docs/capstone/implementation-plan.md` section 16.
- `docs/capstone/ProblemStatements.md` section 12 and section 9.4 item B6.
- The current top of `README.md` so you can add a section without replacing it. Read the first 40 lines, then jump to the end.
- `docs/capstone/eval.md` so the README points at the recorded commands.

Edit `README.md` with one new capstone section: pointer to `docs/capstone/architecture.md`, source list, `SUPPORTDESK_PROJECT1_ROOT`, how the two loops connect, what C1–C5 do, how to run E1–E3, the two state files (`data/publish-state.json` and `data/supportdesk-publish-state.json`), and the exactly-once limit. The README must say the hosted MCP server is not exactly-once.

Create `docs/capstone/demo-script.md`. Under three minutes, in this order: weekly pulse to its gate, one question through the response loop, one reviewer rejection, one approval of the hash on screen, one evaluation row. Four spoken sentences a reviewer can check: which source supplied the fact, the count, and the repeated question; where the model is forbidden to continue; which gate stopped the write and which hash it was bound to; why that line was drawn there.

Confirm `data/capstone.db` is in `.gitignore`. Do not add a new secret to `.env.example`.

Do not run the full test suite. Do not deploy.

Append four lines to section 19 and stop.

SLICE END
