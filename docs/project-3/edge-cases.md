# Edge cases — Multi-agent support desk

Boundary behavior of `src/supportdesk/`. Pulse edge cases stay in `docs/edge-cases.md`.

Each row is a behavior the current tests lock in. Review text is not copied here.

| Id | Condition | What the desk does | Where it is checked |
| --- | --- | --- | --- |
| SD-01 | Message is empty or whitespace | `BLOCK`. Facts does not retrieve. Pattern does not read the CSV. | `tests/supportdesk/test_compliance.py` |
| SD-02 | PAN, Aadhaar, phone, email, OTP, or a long account number | Redact before any agent persists the value. A phone inside a reply is not quoted in the reviewer finding. | `test_compliance.py`, `test_reviewer.py` |
| SD-03 | Redaction still matches a PII pattern | `BLOCK`. Retrieval and the review export are not opened. | `test_facts.py`, `test_pattern.py` |
| SD-04 | Ten digits inside a hex execution id | Not treated as a phone. `content_has_pii` skips ids. | `test_reviewer.py`, `test_orchestrate.py` |
| SD-05 | “Should I buy / sell / hold / redeem”, suitability, or “which fund should I choose” | `REFUSE`. Facts does not retrieve. The reply has no recommendation and no citation URL. | `test_compliance.py`, `test_adversarial.py` |
| SD-06 | “What returns can I expect?” or “Can you guarantee a return?” | `REFUSE`. Same reply rule as SD-05. | `test_adversarial.py` |
| SD-07 | Rephrase after a refusal, including “if you were me” and “ignore your policy” | Still `REFUSE`. | `test_adversarial.py` |
| SD-08 | Later turn “What do you think?” after an advice ask in the same session | Still `REFUSE`. The session stores the flag, not the message. | `test_adversarial.py` |
| SD-09 | A fact question after that flag | Allowed through compliance. The reply stays a fact or a not-covered line. It is not a recommendation. | `test_orchestrate.py` |
| SD-10 | “How do I redeem my units?” or a failed sell order | Support request. Advice patterns do not fire. | `test_compliance.py` |
| SD-11 | Project 1 root missing, or `SUPPORTDESK_PROJECT1_ROOT` points at a non-checkout | Facts status `error`. No guessed answer. The exception text is not copied. The limitation is `retrieval failed: <TypeName>` or the unavailable-root message. | `test_facts.py` |
| SD-12 | Retrieval raises | Facts status `error`. Limitation names the exception type only. | `test_facts.py` |
| SD-13 | Question is outside the five HDFC scheme pages | Facts `not_covered`, no claims. | `test_facts.py`, `test_scenarios.py` |
| SD-14 | Expense ratio of HDFC Large Cap Fund, and the sibling corpus is present | Facts `supported`. The claim is a substring of the chunk. The URL is `https://groww.in/...`. | `test_facts.py` |
| SD-15 | The drafted citation would count as more than three sentences | The URL is left out of the reply and a limitation says the claim was not copied. `CustomerReply` rejects four sentences. Dots inside a URL count as sentence breaks. | `test_contracts.py`, `test_orchestrate.py`, `test_reviewer.py` |
| SD-16 | Cited fact and a recurring or rising pattern | The reply cites the fact. The routing note keeps the pattern signal and the disagreement line. | `test_orchestrate.py`, `test_scenarios.py` |
| SD-17 | Pattern CSV or theme file missing | `insufficient_data` or `error` with a short limitation. The customer message is not in that limitation. | `test_pattern.py` |
| SD-18 | `early` count is 0, or the ratio is below 1.5 | Not `rising`. Count at least 3 becomes `recurring`. Count 1 is `one_off`. Count 2 is `insufficient_data`. | `test_pattern.py` |
| SD-19 | Project 2 marked a theme `emerging` | The flag is ignored. Rising is recomputed from review dates. | `test_pattern.py` |
| SD-20 | Caller passes `csv_path` or `run_dir` and omits `db_path` | The live `data/reviews.db` is not opened. | `test_pattern.py` |
| SD-21 | Support-theme wording on the local export | Signal is `recurring`, count at least 3, comparable periods true. It is not rising. | `test_pattern.py`, `test_scenarios.py` |
| SD-22 | One agent times out | That agent is an error with no citation. The other agents' results are kept only if compliance itself finished. A compliance timeout blocks the draft. | `test_orchestrate.py` |
| SD-23 | Repairable bad reply | One rework, then review again. Rework uses `draft_from_agents` and does not retrieve or read the CSV, because the customer message is not stored. | `test_reviewer.py`, `test_scenarios.py` |
| SD-24 | The fact claim itself is advice, or the second review still fails | `BLOCKED`. No approval and no MCP. | `test_reviewer.py`, `test_scenarios.py` |
| SD-25 | Sixth refinement, or a refinement of a rejected case | `ContractError`. The sixth call does not run agents. | `test_decisions.py` |
| SD-26 | Instruction contains a phone number | Stored as `[phone]`, or refused if redaction cannot be guaranteed. The raw value is not in the error. | `test_decisions.py` |
| SD-27 | Pending or approved content hash changes | Run returns to `reviewing`. Approval is cleared. | `test_decisions.py`, `test_workflow.py` |
| SD-28 | Human rejects | State `rejected`. `publish_case` raises before any tool call. | `test_scenarios.py`, `test_publish.py` |
| SD-29 | Human approves the reviewed hash | Docs append and Gmail draft. `send_email` is not called. | `test_publish.py`, `test_scenarios.py` |
| SD-30 | Draft tool returns 503 after a successful append | `partial_failure`. Retry skips the append and calls draft again. | `test_publish.py` |
| SD-31 | Append tool message contains “timeout” or “timed out” | Status `uncertain`. Gmail is not called. A later `publish_case` does not call append again. | `test_publish.py` |
| SD-32 | Completed case is published again | Saved ids are returned. Tool call lists stay unchanged. | `test_publish.py` |
| SD-33 | Approved content still matches a PII pattern | `publish_case` raises before any tool call. The state file is not created. | `test_publish.py` |
| SD-34 | Hosted draft retry after a definite failure | A second draft can appear. The server has no update-draft tool. A timeout is not retried, so that path does not add a second call. | `docs/project-3/architecture.md`, `test_publish.py` |

Ruff and mypy are not configured in this repository. The support-desk gate is `python -m pytest tests/supportdesk -q`.
