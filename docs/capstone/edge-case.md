# Edge cases — The Support Desk

Boundary conditions for the capstone join. Derived from [`architecture.md`](./architecture.md) and [`implementation-plan.md`](./implementation-plan.md). Requirement ids point at [`ProblemStatements.md`](./ProblemStatements.md).

Milestone 2 boundaries stay in [`docs/edge-cases.md`](../edge-cases.md). Milestone 3 boundaries stay in [`docs/project-3/edge-cases.md`](../project-3/edge-cases.md). This file covers what `src/capstone/` adds, and the places it must keep those two packages' results intact.

Each entry is a behavior a test can lock. Review text and customer text are not copied here. Fixtures use placeholders such as `[phone]`.

## 1. How to use this document

| Column | Meaning |
| --- | --- |
| **Severity** | `Critical` — block the write, or data is false; `High` — wrong evidence or a skipped gate; `Medium` — handle explicitly; `Low` — stable output or operator clarity |
| **Owner** | Module that implements the behavior |
| **Phase** | Phase in the implementation plan where the test must exist |

`question_key` is the only identity function (`src/capstone/identity.py`). The week id is an ISO week in `Asia/Kolkata`, formatted `YYYY-Www` (zero-padded week, no `groww:` prefix). The empty-ledger sentence is exactly `No queued question in this week was outside the corpus.` The support-signal template is exactly `Support was asked "{question_key}" {count} times in {week_id}. This line is the question log, not review volume.`

---

## 2. Question identity (J2, Phase 1)

### EC-ID-01 — Casing, spacing, and NFKC

| Field | Value |
| --- | --- |
| **Scenario** | `"What is the exit load?"` compared with different case, extra spaces, newlines, or compatibility characters (fullwidth letters, the `ﬁ` ligature). |
| **Severity** | Critical |
| **Expected behavior** | One key. NFKC, then casefold, then collapse whitespace. |
| **Owner** | `identity.py` |
| **Phase** | 1 |
| **Test hint** | The Phase 1 pair that shares a key |

### EC-ID-02 — Redaction placeholders on otherwise identical text

| Field | Value |
| --- | --- |
| **Scenario** | The same question with `[pan]` on one row and `[phone]` on the other. |
| **Severity** | Critical |
| **Expected behavior** | One key. The key contains none of `[pan]`, `[aadhaar]`, `[account]`, `[phone]`, `[email]`, `[otp]`. |
| **Owner** | `identity.py` |
| **Phase** | 1 |

### EC-ID-03 — Placeholder case and fullwidth brackets

| Field | Value |
| --- | --- |
| **Scenario** | `[PHONE]`, `[Phone]`, or fullwidth brackets and letters that NFKC folds to `[phone]`. |
| **Severity** | High |
| **Expected behavior** | Casefold runs before placeholder removal, so those forms are removed. The key contains no placeholder and no personal value. |
| **Owner** | `identity.py` |
| **Phase** | 1 |

### EC-ID-04 — Empty, punctuation-only, or emoji-only text

| Field | Value |
| --- | --- |
| **Scenario** | `""`, `"???"`, or a string of emoji. |
| **Severity** | Critical |
| **Expected behavior** | The key is empty. `counts_for_signal` is false. The row may be stored. It is excluded from the five-times count. |
| **Owner** | `identity.py`, `signals.py` |
| **Phase** | 1, 4 |

### EC-ID-05 — Text that is only placeholders

| Field | Value |
| --- | --- |
| **Scenario** | `"[phone] [email]"`. |
| **Severity** | Critical |
| **Expected behavior** | Empty key after placeholder removal. The row does not join any signal. |
| **Owner** | `identity.py` |
| **Phase** | 1, 4 |

### EC-ID-06 — Many empty keys in one week

| Field | Value |
| --- | --- |
| **Scenario** | Six rows in the same week, each with an empty key. |
| **Severity** | Critical |
| **Expected behavior** | No signal. Empty keys are not one group. |
| **Owner** | `signals.py` |
| **Phase** | 4 |

### EC-ID-07 — No stemming and no synonyms

| Field | Value |
| --- | --- |
| **Scenario** | `charge` versus `charges`. `exit load` versus `redemption fee`. |
| **Severity** | Critical |
| **Expected behavior** | Different keys. Equality is exact string equality. No stemmer, embedding, synonym list, or model call. |
| **Owner** | `identity.py` |
| **Phase** | 1 |

### EC-ID-08 — Digits stay in the key

| Field | Value |
| --- | --- |
| **Scenario** | `"exit load on fund 1"` and `"exit load on fund 2"`. |
| **Severity** | High |
| **Expected behavior** | Two keys. Letters and digits are kept. |
| **Owner** | `identity.py` |
| **Phase** | 1 |

### EC-ID-09 — Spacing around a placeholder

| Field | Value |
| --- | --- |
| **Scenario** | `call[phone]now` versus `call [phone] now`. |
| **Severity** | Medium |
| **Expected behavior** | Placeholder removal happens before non-letters become spaces. The first key is `callnow`. The second is `call now`. |
| **Owner** | `identity.py` |
| **Phase** | 1 |

### EC-ID-10 — A token that is not in the placeholder list

| Field | Value |
| --- | --- |
| **Scenario** | The text contains `[number]` or `[email address]`. |
| **Severity** | Medium |
| **Expected behavior** | Those tokens are not removed by the placeholder step. Non-letters then become spaces, so the words remain. A raw PAN or a raw phone still never reaches this function: redaction blocks first (EC-REC-02). |
| **Owner** | `identity.py` |
| **Phase** | 1 |

### EC-ID-11 — Zero-width characters and homoglyphs

| Field | Value |
| --- | --- |
| **Scenario** | The same letters with a zero-width space between them. Separately, a Cyrillic lookalike in place of a Latin letter. |
| **Severity** | Medium |
| **Expected behavior** | A zero-width character is not a letter or digit, so it collapses and the keys match. NFKC does not fold homoglyphs, so the Cyrillic form is a different key. |
| **Owner** | `identity.py` |
| **Phase** | 1 |

### EC-ID-12 — `counts_for_signal` is not a new column

| Field | Value |
| --- | --- |
| **Scenario** | An empty key is stored in `question_log`. |
| **Severity** | Medium |
| **Expected behavior** | The schema columns stay the ones in architecture section 6. Exclusion is applied when signals are grouped. No column is added whose name contains `raw`. |
| **Owner** | `identity.py`, `log.py` |
| **Phase** | 1, 2 |

---

## 3. The pulse week (J2, Phases 3 and 4)

The five-times window is the ISO week of the record clock in `Asia/Kolkata`. It is the same format as the pulse idempotency key in `reviewpulse.publish.base` after the `groww:` prefix is removed. It is not the 8–12 week review lookback.

### EC-WEEK-01 — Week format

| Field | Value |
| --- | --- |
| **Scenario** | A timestamp whose ISO week is 1. |
| **Severity** | High |
| **Expected behavior** | `YYYY-W01`. `YYYY-W1` is a different string and does not group with it. |
| **Owner** | `record.py` |
| **Phase** | 3 |

### EC-WEEK-02 — UTC evening that is already Monday in Kolkata

| Field | Value |
| --- | --- |
| **Scenario** | Sunday 18:30 UTC, which is Monday 00:00 in `Asia/Kolkata`. `Asia/Kolkata` has no daylight-saving transition. |
| **Severity** | Critical |
| **Expected behavior** | The week id is Monday's ISO week. A clock in UTC that formats the calendar date first assigns the row to the previous week. |
| **Owner** | `record.py` |
| **Phase** | 3 |
| **Test hint** | Pass a fixed clock, as Phase 3 requires |

### EC-WEEK-03 — ISO year boundary

| Field | Value |
| --- | --- |
| **Scenario** | A timestamp on 31 December or 1 January whose ISO week belongs to the other calendar year. In this calendar, 31 Dec 2025 falls in `2026-W01`, and 1 Jan 2027 falls in `2026-W53`. |
| **Severity** | High |
| **Expected behavior** | Use `isocalendar()` of the Kolkata civil time: ISO year and ISO week. The calendar year is not the prefix. |
| **Owner** | `record.py` |
| **Phase** | 3 |

### EC-WEEK-04 — Same key in two weeks

| Field | Value |
| --- | --- |
| **Scenario** | Three rows in week W and two rows of the same key in week W+1. |
| **Severity** | Critical |
| **Expected behavior** | Neither week emits a signal. Counts do not roll across weeks. |
| **Owner** | `signals.py` |
| **Phase** | 4 |

### EC-WEEK-05 — Review lookback is a different window

| Field | Value |
| --- | --- |
| **Scenario** | A theme has 40 review members across 12 weeks. The question log has four rows this ISO week. |
| **Severity** | Critical |
| **Expected behavior** | No queue signal. The routing note may still carry a pattern signal, labeled `pattern`. The on-screen dates for the review window and the question week stay distinct. |
| **Owner** | `signals.py`, console |
| **Phase** | 4, 10 |

### EC-WEEK-06 — Assemble reads the run's week, not every row in the database

| Field | Value |
| --- | --- |
| **Scenario** | The log holds five matching rows stamped last week, and the run being assembled is this week. |
| **Severity** | High |
| **Expected behavior** | This week's signal list does not include those rows. Ledger bullets for this package cite this week's ledger rows. |
| **Owner** | `signals.py`, `explainer.py` |
| **Phase** | 4, 5 |

### EC-WEEK-07 — Pulse key and log week

| Field | Value |
| --- | --- |
| **Scenario** | The pulse publish state stores `groww:2026-W46`. |
| **Severity** | Medium |
| **Expected behavior** | The log and the signal use `2026-W46`. The capstone does not write a second prefix and does not parse the 8–12 week window as the five-times window. |
| **Owner** | `record.py`, `package.py` |
| **Phase** | 3, 6 |

---

## 4. Log, ledger, and case blob (J1, J3, P1, Phases 2 and 3)

### EC-LOG-01 — Covered row

| Field | Value |
| --- | --- |
| **Scenario** | Facts coverage is `covered`. |
| **Severity** | Critical |
| **Expected behavior** | One `question_log` row. The ledger does not gain a row. The sanitized case blob is stored. |
| **Owner** | `log.py`, `record.py` |
| **Phase** | 2, 3 |

### EC-LOG-02 — Not-covered row

| Field | Value |
| --- | --- |
| **Scenario** | Facts coverage is `not_covered`. |
| **Severity** | Critical |
| **Expected behavior** | The log row and the ledger row commit in one transaction. The ledger copies `case_id`, `sanitized_text`, `searched_urls`, `week_id`, and `theme_id`. `searched_urls` are the URLs the facts agent returned. An empty search list is stored as empty. |
| **Owner** | `log.py` |
| **Phase** | 2, 3 |

### EC-LOG-03 — Second append of the same case

| Field | Value |
| --- | --- |
| **Scenario** | `record` is called again for an existing `case_id`. |
| **Severity** | High |
| **Expected behavior** | `question_log` and `desk_cases` update in place. The ledger has at most one row for that `case_id`. |
| **Owner** | `log.py` |
| **Phase** | 2 |

### EC-LOG-04 — Coverage flips on re-record

| Field | Value |
| --- | --- |
| **Scenario** | The first write was `covered` and a later write for the same id is `not_covered`, or the reverse. |
| **Severity** | High |
| **Expected behavior** | The log row shows the latest coverage. A not-covered write still creates one ledger row if none exists. A second not-covered write does not insert another. The explainer cites whatever the ledger holds at the next assemble. It does not rewrite a package already written. |
| **Owner** | `log.py`, `assemble.py` |
| **Phase** | 2, 6 |

### EC-LOG-05 — No raw-message column

| Field | Value |
| --- | --- |
| **Scenario** | Schema inspection, a log model with an extra field, or a payload that includes the customer message under any name containing `raw`. |
| **Severity** | Critical |
| **Expected behavior** | The schema has no such column. Contract models use `extra = forbid` and reject the field. The raw message is not a log field and not an agent argument. |
| **Owner** | `log.py`, `contracts.py` |
| **Phase** | 1, 2 |

### EC-LOG-06 — Case blob that fails validation

| Field | Value |
| --- | --- |
| **Scenario** | The JSON is missing the Milestone 3 case keys, or it still matches a PII pattern. |
| **Severity** | Critical |
| **Expected behavior** | The write is rejected. If importing the desk case model pulls unwanted startup work, the capstone contract checks the required keys and still rejects a raw phone or PAN. |
| **Owner** | `log.py` |
| **Phase** | 2 |

### EC-LOG-07 — Theme id only from a real pattern match

| Field | Value |
| --- | --- |
| **Scenario** | Pattern status is `insufficient_data`, `error`, or a match flag that is false. |
| **Severity** | High |
| **Expected behavior** | `theme_id` is null. A client-supplied theme id is ignored. |
| **Owner** | `record.py` |
| **Phase** | 3 |

### EC-LOG-08 — Ledger row without a log row

| Field | Value |
| --- | --- |
| **Scenario** | A ledger insert is attempted for a `case_id` that is not in `question_log`. |
| **Severity** | High |
| **Expected behavior** | The foreign key rejects it. The transaction rolls back, so a crash between the two inserts leaves neither row. |
| **Owner** | `log.py` |
| **Phase** | 2 |

### EC-LOG-09 — Facts error labeled as covered

| Field | Value |
| --- | --- |
| **Scenario** | Project 1 root is missing, the index is empty, or retrieval raises. The desk facts status is `error` (see desk EC SD-11 and SD-12). |
| **Severity** | Critical |
| **Expected behavior** | The log does not store `covered`. Assemble writes no factual bullet for that question. No general-knowledge sentence is added. |
| **Owner** | `record.py`, `explainer.py` |
| **Phase** | 3, 5 |

### EC-LOG-10 — Database path, git, and restart

| Field | Value |
| --- | --- |
| **Scenario** | The default file `data/capstone.db`, a test that opens it, or a process restart. |
| **Severity** | High |
| **Expected behavior** | Tests pass a temporary path. The default file is gitignored. It stores no tokens. After restart the `desk_cases` blob is still readable. Approval rules stay in `supportdesk.decisions` and `supportdesk.approval`. The blob is not a second hash check. |
| **Owner** | `log.py` |
| **Phase** | 2 |

### EC-LOG-11 — Corrupt or locked database

| Field | Value |
| --- | --- |
| **Scenario** | The file is unreadable, or two writers hit `database is locked`. |
| **Severity** | High |
| **Expected behavior** | The operation fails with the database error. The API does not answer from an empty in-memory week and does not publish. |
| **Owner** | `log.py` |
| **Phase** | 2, 7 |

---

## 5. Recording a reviewed case (J1, J3, J4, P2, Phase 3)

`record.py` runs only after `review_case` or `decide` returns. It does not orchestrate, and it does not call `publish_case`.

### EC-REC-01 — Redaction cannot be guaranteed

| Field | Value |
| --- | --- |
| **Scenario** | Compliance blocks the case because `redact_pii` still sees a PII pattern. |
| **Severity** | Critical |
| **Expected behavior** | No log row, no ledger row, no case blob. The function returns a recorded-nothing result. All three tables stay as they were. |
| **Owner** | `record.py` |
| **Phase** | 3 |

### EC-REC-02 — Raw personal data in a case that looks sanitized

| Field | Value |
| --- | --- |
| **Scenario** | A 10-digit phone or a PAN pattern is present on the object handed to `record`. |
| **Severity** | Critical |
| **Expected behavior** | Nothing is written. Placeholders from the architecture list may appear in stored text. The raw value does not. |
| **Owner** | `record.py` |
| **Phase** | 3 |

### EC-REC-03 — Empty or whitespace message

| Field | Value |
| --- | --- |
| **Scenario** | The desk blocks before retrieval (desk SD-01). Review never produces a case. |
| **Severity** | High |
| **Expected behavior** | `record` is not called. No log row. |
| **Owner** | `api/desk.py` |
| **Phase** | 7 |

### EC-REC-04 — Advice refusal

| Field | Value |
| --- | --- |
| **Scenario** | Compliance returns `REFUSE` for buy, sell, hold, redeem, suitability, or an expected return. Facts did not retrieve. |
| **Severity** | High |
| **Expected behavior** | This is not EC-REC-01. The question passed sanitization, so the reviewed case is logged. Coverage is whatever the facts result actually is, and it is not filled in as `covered`. The customer reply has no recommendation and no citation URL. |
| **Owner** | `record.py` |
| **Phase** | 3, 7 |

### EC-REC-05 — Second reviewer failure

| Field | Value |
| --- | --- |
| **Scenario** | The reviewer blocks the case after the one allowed rework (desk SD-24). |
| **Severity** | Critical |
| **Expected behavior** | The case is `blocked`. Publish returns an error and does not call MCP. This block is not the redaction skip in EC-REC-01. |
| **Owner** | `api/desk.py`, `supportdesk.reviewer` |
| **Phase** | 7, 11 |

### EC-REC-06 — Searched URLs and citations supplied by the client

| Field | Value |
| --- | --- |
| **Scenario** | The request JSON includes `citation`, `count`, `searched_urls`, or `facts_coverage`. |
| **Severity** | Critical |
| **Expected behavior** | Those fields are ignored. Stored values are copied from the facts result, the pattern result, and `identity.question_key`. |
| **Owner** | `api/desk.py`, `record.py` |
| **Phase** | 3, 7 |

### EC-REC-07 — Rejection does not remove the row

| Field | Value |
| --- | --- |
| **Scenario** | An operator rejects a case that was logged. |
| **Severity** | High |
| **Expected behavior** | The case stays on the queue. The log row and any ledger row remain, so they still count at the next assemble. `explainer.json` from the last assemble is not opened and stays byte-for-byte the same. |
| **Owner** | `api/desk.py` |
| **Phase** | 7, 8 |

---

## 6. Five-times signals (J2, J4, J5, Phase 4)

Groups are `(week_id, question_key)` with a non-empty key and a count of at least 5. `evidence_type` is the constant `queue`. `case_ids` are sorted. The renderer fills the template and does not call a model.

### EC-SIG-01 — Four, five, and six

| Field | Value |
| --- | --- |
| **Scenario** | One key with four rows, five rows, or six rows in the same week. |
| **Severity** | Critical |
| **Expected behavior** | Four writes an empty list. Five writes one signal with `count` 5. Six writes one signal with `count` 6, not two signals. The template contains the key, the count, the week, and the words `question log`. |
| **Owner** | `signals.py` |
| **Phase** | 4 |

### EC-SIG-02 — Several keys

| Field | Value |
| --- | --- |
| **Scenario** | Two keys, each with five rows, plus a third key with four. |
| **Severity** | High |
| **Expected behavior** | Two signals. The file bytes are identical on a second render, including list order. |
| **Owner** | `signals.py` |
| **Phase** | 4, 6 |

### EC-SIG-03 — Theme id inside the group

| Field | Value |
| --- | --- |
| **Scenario** | Every row shares one theme id. Separately, the rows disagree, or every theme id is null. |
| **Severity** | High |
| **Expected behavior** | Shared id is stored. Any disagreement stores null. All null stores null. |
| **Owner** | `signals.py` |
| **Phase** | 4 |

### EC-SIG-04 — Review volume without log rows

| Field | Value |
| --- | --- |
| **Scenario** | The caller passes `clusters.json` and no log rows. A theme may have a large member count. |
| **Severity** | Critical |
| **Expected behavior** | The signal list is empty. Review volume cannot create a queue row. |
| **Owner** | `signals.py` |
| **Phase** | 4 |

### EC-SIG-05 — Pattern fields when J2 also matches

| Field | Value |
| --- | --- |
| **Scenario** | Five rows share a key, and the stored pattern results also carry a signal, a count, and a window. |
| **Severity** | Critical |
| **Expected behavior** | The queue `count` is the number of log rows. Pattern signal, pattern count, and window are copied from the stored pattern result. They are a different evidence type. A missing pattern artifact stays missing. Rows that do not share one pattern result do not get a synthesized pattern count. The customer draft is not edited to mention the queue count. |
| **Owner** | `signals.py` |
| **Phase** | 4, 11 |

### EC-SIG-06 — Illegal evidence type or an unknown field

| Field | Value |
| --- | --- |
| **Scenario** | A signal dump sets `evidence_type` to `pattern` or `review`, or adds a field the model does not define. |
| **Severity** | Critical |
| **Expected behavior** | The contract rejects the dump. The only legal value on a queue signal is `queue`. |
| **Owner** | `contracts.py` |
| **Phase** | 1, 4 |

### EC-SIG-07 — Empty list and the pulse note

| Field | Value |
| --- | --- |
| **Scenario** | The week has no qualifying key. |
| **Severity** | High |
| **Expected behavior** | `support_signals.json` exists and is an empty list. `note.md` is not edited. The signal text is not inserted into the 250-word note. |
| **Owner** | `signals.py`, `assemble.py` |
| **Phase** | 4, 6 |

### EC-SIG-08 — Five refusals of the same advice question

| Field | Value |
| --- | --- |
| **Scenario** | Five sanitized copies of the same refused redeem or return question fall in one week. |
| **Severity** | Medium |
| **Expected behavior** | One queue signal. The template quotes the key. The line is a count of asks. It is not an explainer bullet and it does not recommend an action. |
| **Owner** | `signals.py` |
| **Phase** | 4, 5 |

### EC-SIG-09 — A fee theme does not mint a signal, and a signal does not mint a fee theme

| Field | Value |
| --- | --- |
| **Scenario** | A fee theme has member count 3 and the log is empty. Separately, five identical KYC questions have no fee theme. |
| **Severity** | High |
| **Expected behavior** | The first case writes an empty signal list and a null `fee_theme` only if the theme failed the lexicon test; a qualifying fee theme still does not create a signal. The second case writes one queue signal and records `fee_theme: null` with the bar statement. |
| **Owner** | `signals.py`, `explainer.py` |
| **Phase** | 4, 5 |

---

## 7. Fee theme and explainer (W1, W2, G1–G5, S3, A1, Phase 5)

Fee lexicon, matched as a case-insensitive substring of the theme label or keywords: `fee`, `fees`, `charge`, `charges`, `brokerage`, `exit load`, `expense ratio`, `demat`, `amc`. The measured member count is the cluster's stored size. The floor is 3. The largest qualifying theme wins. Factual bullets call `supportdesk.facts.answer_facts` on the frozen catalog list. A bullet is kept only when coverage is `covered`, the claim is a substring of the passage, and the URL is `https` on `groww.in` or `www.groww.in`.

### EC-EXP-01 — Floor and the winner

| Field | Value |
| --- | --- |
| **Scenario** | One lexicon theme with size 2. One with size 3. Two qualifying themes with sizes 3 and 9. |
| **Severity** | Critical |
| **Expected behavior** | Size 2 does not qualify. Size 3 does. Of the two that qualify, size 9 is chosen. |
| **Owner** | `explainer.py` |
| **Phase** | 5 |

### EC-EXP-02 — Tie for the largest count

| Field | Value |
| --- | --- |
| **Scenario** | Two lexicon themes share the same member count, and that count is at least 3. |
| **Severity** | Medium |
| **Expected behavior** | `fee_theme` is one of those two ids, and a second assemble returns the same id. No other id is invented. Phase 5's required test uses unequal counts. |
| **Owner** | `explainer.py` |
| **Phase** | 5, 6 |

### EC-EXP-03 — No qualifying theme

| Field | Value |
| --- | --- |
| **Scenario** | `clusters.json` has themes, and none pass both the lexicon and the floor. |
| **Severity** | Critical |
| **Expected behavior** | `fee_theme` is null. The pulse screen states that no fee theme met the bar. No theme id is invented. |
| **Owner** | `explainer.py` |
| **Phase** | 5 |

### EC-EXP-04 — Lexicon near misses

| Field | Value |
| --- | --- |
| **Scenario** | Label `Exit Load` or keyword `FEES`. Label `feedback` (contains `fee`). Label `exit` without `load`. A missing size. |
| **Severity** | High |
| **Expected behavior** | `Exit Load` and `FEES` qualify when size is at least 3, because the match is case-insensitive. Under the written contain rule, `feedback` matches `fee`. `exit` alone matches neither `exit load` nor `fee`. A missing size does not meet the floor and is not filled with 0 or 3. |
| **Owner** | `explainer.py` |
| **Phase** | 5 |

### EC-EXP-05 — Clusters file missing

| Field | Value |
| --- | --- |
| **Scenario** | Assemble is asked to run and `clusters.json` is absent. |
| **Severity** | Critical |
| **Expected behavior** | Assemble refuses. No fee theme is invented. No package hash is written. Pattern status elsewhere may be `insufficient_data`; J2 can still be computed later from the log once a real run exists. |
| **Owner** | `assemble.py` |
| **Phase** | 6 |

### EC-EXP-06 — Catalog missing or a question the catalog cannot answer

| Field | Value |
| --- | --- |
| **Scenario** | The sibling Project 1 catalog is absent, so the frozen question list is empty. Or a frozen question returns anything other than `covered`. |
| **Severity** | Critical |
| **Expected behavior** | Every factual bullet is skipped. Absence is not a license to invent a claim. A not-covered retrieval does not become a factual bullet. |
| **Owner** | `explainer.py` |
| **Phase** | 5 |

### EC-EXP-07 — Claim or host fails the grounding check

| Field | Value |
| --- | --- |
| **Scenario** | The claim is not a substring of the passage. The URL is `http://`, a lookalike host (`groww.in.example`), a subdomain other than `www`, or any host other than `groww.in` or `www.groww.in`. The passage is a review or a third-party page. |
| **Severity** | Critical |
| **Expected behavior** | That question adds no factual bullet. App-store text is not a factual source. |
| **Owner** | `explainer.py` |
| **Phase** | 5 |

### EC-EXP-08 — Five-link stop

| Field | Value |
| --- | --- |
| **Scenario** | More than five frozen questions would qualify. |
| **Severity** | High |
| **Expected behavior** | Bullets stop at five links. The ledger bullet is still last. The explainer never has a sixth official link. |
| **Owner** | `explainer.py` |
| **Phase** | 5 |

### EC-EXP-09 — Ledger bullet shape

| Field | Value |
| --- | --- |
| **Scenario** | Zero ledger rows. One row. Six or more rows. Rows that belong to another week. A covered question. |
| **Severity** | Critical |
| **Expected behavior** | Zero rows: the last bullet is exactly `No queued question in this week was outside the corpus.` One or more rows: one last bullet contains every `case_id` and the sanitized question, copied from the ledger. Six rows are still one bullet, so the six-bullet ceiling is kept and no case id is dropped. Other weeks and covered questions are not described as gaps. |
| **Owner** | `explainer.py` |
| **Phase** | 5, 6 |

### EC-EXP-10 — Advice, performance, or PII inside a bullet

| Field | Value |
| --- | --- |
| **Scenario** | A bullet matches the desk advice or performance checks, including the sentence "you should redeem". A kept claim contains a return figure. Ledger text still matches a PII pattern. |
| **Severity** | Critical |
| **Expected behavior** | The gate fails. `explainer.json` is not written. Failing codes are returned. The package is not published as a shorter rewrite with the bad bullet removed. |
| **Owner** | `explainer.py`, `gates.py` |
| **Phase** | 5, 6 |

### EC-EXP-11 — Last-checked date

| Field | Value |
| --- | --- |
| **Scenario** | The chunk has `retrieved_on`. Separately, the metadata has no date. |
| **Severity** | Critical |
| **Expected behavior** | The bullet and the source panel use the retrieval value. If it is missing, they say `date unavailable`. The explainer does not fill today's date. |
| **Owner** | `explainer.py`, source panel |
| **Phase** | 5, 9 |

### EC-EXP-12 — Over the shape limits

| Field | Value |
| --- | --- |
| **Scenario** | A built explainer has seven bullets or six official links. |
| **Severity** | Critical |
| **Expected behavior** | The gate fails and writes no file. |
| **Owner** | `explainer.py`, `gates.py` |
| **Phase** | 5 |

### EC-EXP-13 — Hosted corpus in unit tests

| Field | Value |
| --- | --- |
| **Scenario** | A Phase 5 test needs a retrieval result. |
| **Severity** | Medium |
| **Expected behavior** | The retriever is injected. The test does not call the hosted corpus or the hosted MCP server. |
| **Owner** | `tests/capstone/test_explainer.py` |
| **Phase** | 5 |

---

## 8. Assemble and the package hash (W3, W4, B2, S2, Phase 6)

The hash is SHA-256 over the exact bytes of `note.md`, `explainer.json`, and `support_signals.json`, in that order. JSON is UTF-8 with `sort_keys` and compact separators. `package.json` stores the hash, `fee_theme`, and the file names.

### EC-PKG-01 — Pulse gates missing or failed

| Field | Value |
| --- | --- |
| **Scenario** | The run has no pulse gate record, or the note failed its gates, including `word_count`. |
| **Severity** | Critical |
| **Expected behavior** | Assemble refuses. No explainer file, no signal file, no hash, no publish. Word count is read from the pulse manifest and is not reimplemented. |
| **Owner** | `assemble.py`, `gates.py` |
| **Phase** | 6 |

### EC-PKG-02 — Note bytes

| Field | Value |
| --- | --- |
| **Scenario** | Assemble runs on a fixture whose pulse gates passed. |
| **Severity** | Critical |
| **Expected behavior** | `note.md` bytes are identical before and after. A one-byte edit of the note produces a different hash. |
| **Owner** | `assemble.py`, `package.py` |
| **Phase** | 6 |

### EC-PKG-03 — Empty signals and empty ledger

| Field | Value |
| --- | --- |
| **Scenario** | The log week is empty and no fee question produces a factual bullet. |
| **Severity** | High |
| **Expected behavior** | Both JSON files exist. The last explainer bullet is the empty-ledger sentence. The hash covers that sentence. |
| **Owner** | `assemble.py` |
| **Phase** | 6 |

### EC-PKG-04 — Canonical bytes

| Field | Value |
| --- | --- |
| **Scenario** | The same objects are serialized with a different key order, with pretty printing, or as UTF-16. A trailing newline is added to `note.md`. |
| **Severity** | High |
| **Expected behavior** | The hashed JSON is the canonical encoding only. Any other byte string is a different hash. Approval is bound to the canonical bytes. |
| **Owner** | `package.py` |
| **Phase** | 6 |

### EC-PKG-05 — What the hash does not cover

| Field | Value |
| --- | --- |
| **Scenario** | A client posts a hash, or `package.json` is edited so `fee_theme` changes while the three files stay put. |
| **Severity** | Critical |
| **Expected behavior** | The hash is computed locally from the three files. `package.json` is not a fourth hash input and does not store the note body again. Publish compares the approved hash with the current files. |
| **Owner** | `package.py`, `api/package.py` |
| **Phase** | 6, 8 |

### EC-PKG-06 — Stable re-assemble

| Field | Value |
| --- | --- |
| **Scenario** | Assemble runs twice on unchanged inputs. |
| **Severity** | High |
| **Expected behavior** | The hash matches. Assemble does not import the MCP client and does not call `publish_case`. |
| **Owner** | `assemble.py` |
| **Phase** | 6 |

### EC-PKG-07 — Failure is all-or-nothing

| Field | Value |
| --- | --- |
| **Scenario** | Explainer or signal gates fail after a previous package existed, or the process is killed while writing. |
| **Severity** | Critical |
| **Expected behavior** | A failed assemble writes no package hash and does not replace one of the three hashed files with a new body while leaving the others stale. The existing `note.md` stays. Nothing is published. A partial file is not treated as an approved package. |
| **Owner** | `assemble.py` |
| **Phase** | 6, 10 |

### EC-PKG-08 — One trigger

| Field | Value |
| --- | --- |
| **Scenario** | The operator starts the weekly pipeline once. Separately, someone runs `reviewpulse run --send`, or `POST /api/desk/questions`. |
| **Severity** | Critical |
| **Expected behavior** | After pulse gates pass, the pipeline calls `capstone.assemble` once and then waits. A failed assemble leaves the note, writes no hash, and does not publish. `reviewpulse run --send` stays the Milestone 2 path and does not assemble. The question route does not assemble. |
| **Owner** | pipeline job, `assemble.py` |
| **Phase** | 6, 7, 10 |

### EC-PKG-09 — File replaced after approval

| Field | Value |
| --- | --- |
| **Scenario** | An approval record exists. Any of the three files then changes. |
| **Severity** | Critical |
| **Expected behavior** | `approval_matches` fails for the stored hash. Publish is refused. |
| **Owner** | `api/package.py` |
| **Phase** | 8 |

---

## 9. Desk HTTP (R1–R5, B1, B3, B5, Phase 7)

Routes mount by including a router. Publish calls `supportdesk.publish.publish_case` only when `assert_mcp_permitted` and `approval_matches` succeed. The router has no `allow_send` parameter. Desk tests use `tests/contract/fake_mcp.py`.

### EC-HTTP-01 — Queue contents

| Field | Value |
| --- | --- |
| **Scenario** | `GET /api/desk/queue` with pending, blocked, and rejected cases. |
| **Severity** | High |
| **Expected behavior** | Each row is sanitized text, draft or not covered, citation or searched URLs, reviewer flag, and state. The raw message is absent. |
| **Owner** | `api/desk.py` |
| **Phase** | 7 |

### EC-HTTP-02 — Unknown or malformed case id

| Field | Value |
| --- | --- |
| **Scenario** | Get, refine, decide, or publish is called for an id that is not in `desk_cases`, or for a string that is not `case_` plus 32 hex characters. |
| **Severity** | High |
| **Expected behavior** | The handler returns an error. No row is created. MCP is not called. |
| **Owner** | `api/desk.py` |
| **Phase** | 7 |

### EC-HTTP-03 — Two submits of the same question

| Field | Value |
| --- | --- |
| **Scenario** | The operator submits the same sanitized question twice. |
| **Severity** | Medium |
| **Expected behavior** | Two case ids and two log rows. Identity is not a unique constraint. The rows meet at signal time. |
| **Owner** | `api/desk.py`, `log.py` |
| **Phase** | 7 |

### EC-HTTP-04 — Refine and the sixth round

| Field | Value |
| --- | --- |
| **Scenario** | A refinement instruction, including one that contains a phone number. A sixth refine, or a refine of a rejected case. |
| **Severity** | High |
| **Expected behavior** | Refine and decision call `supportdesk.decisions`. They do not open `explainer.json`. A phone in the instruction is stored as `[phone]`, or the refine is refused if redaction cannot be guaranteed (desk SD-26). The sixth call raises `ContractError` and does not run agents (desk SD-25). |
| **Owner** | `api/desk.py` |
| **Phase** | 7 |

### EC-HTTP-05 — Approve, then change the reply

| Field | Value |
| --- | --- |
| **Scenario** | The operator approves hash A. The reply then changes. Publish is attempted. |
| **Severity** | Critical |
| **Expected behavior** | The case returns to review and the approval is cleared (desk SD-27). Publish makes no MCP call. |
| **Owner** | `api/desk.py` |
| **Phase** | 7 |

### EC-HTTP-06 — Publish of a blocked or rejected case

| Field | Value |
| --- | --- |
| **Scenario** | State is `blocked` or `rejected`, or the approved body still matches a PII pattern. |
| **Severity** | Critical |
| **Expected behavior** | Publish returns an error before any tool call. The fake client records no call. The desk state file is not created for the PII case (desk SD-28, SD-33). |
| **Owner** | `api/desk.py` |
| **Phase** | 7 |

### EC-HTTP-07 — Desk mail rights

| Field | Value |
| --- | --- |
| **Scenario** | A successful desk publish. The request body contains a send flag. |
| **Severity** | Critical |
| **Expected behavior** | The tool is `refuse_send_tool(..., allow_send=False)`. The fake client may see `append_to_google_doc` and `draft_email`. It does not see `send_email`. There is no request field that turns send on. |
| **Owner** | `api/desk.py` |
| **Phase** | 7 |

### EC-HTTP-08 — Partial failure and timeout

| Field | Value |
| --- | --- |
| **Scenario** | Doc append succeeds and the draft tool returns a definite failure. Separately, the append tool message contains "timeout" or "timed out". |
| **Severity** | Critical |
| **Expected behavior** | Definite draft failure after a successful append is `partial_failure`. Retry drafts only and does not repeat the append. A timeout is `uncertain`, Gmail is not called, and a later publish does not call append again. The capstone test asserts the timeout is not retried. |
| **Owner** | `supportdesk.publish`, `api/desk.py` |
| **Phase** | 7 |

### EC-HTTP-09 — Republish of a completed case

| Field | Value |
| --- | --- |
| **Scenario** | `publish_case` runs again after success. The idempotency keys are `desk:<case_id>:<digest prefix>:docs_append` and the matching `gmail_draft` key. |
| **Severity** | High |
| **Expected behavior** | Saved ids are returned. A succeeded action is skipped. Tool call lists stay unchanged (desk SD-32). |
| **Owner** | `supportdesk.publish` |
| **Phase** | 7 |

---

## 10. Weekly publish path (W4, B1, B2, B4, B5, B6, Phase 8)

Desk state is `data/supportdesk-publish-state.json`. Package state is `data/publish-state.json`. Package publish uses the pulse publisher. It may call `send_email` only when the approved action says send.

### EC-PUB-01 — Assemble over HTTP

| Field | Value |
| --- | --- |
| **Scenario** | `POST /api/capstone/runs/{run_id}/assemble` on a fixture run. |
| **Severity** | Critical |
| **Expected behavior** | The response includes the hash. The fake MCP client is not called. |
| **Owner** | `api/package.py` |
| **Phase** | 8 |

### EC-PUB-02 — Hash A approved, hash B published

| Field | Value |
| --- | --- |
| **Scenario** | Decision stores hash A. Publish is asked to write hash B. |
| **Severity** | Critical |
| **Expected behavior** | Publish is refused. No document append and no mail action. |
| **Owner** | `api/package.py` |
| **Phase** | 8 |

### EC-PUB-03 — Publish before approval, or after a rejection

| Field | Value |
| --- | --- |
| **Scenario** | Publish with no decision, or after the package decision is reject. |
| **Severity** | Critical |
| **Expected behavior** | Publish is refused. |
| **Owner** | `api/package.py` |
| **Phase** | 8 |

### EC-PUB-04 — A desk case id presented as a package

| Field | Value |
| --- | --- |
| **Scenario** | The package publish caller is a desk `case_id`. |
| **Severity** | Critical |
| **Expected behavior** | Publish is refused. Desk approval never sets the pulse state file. |
| **Owner** | `api/package.py` |
| **Phase** | 8 |

### EC-PUB-05 — Cross-approval of the two state files

| Field | Value |
| --- | --- |
| **Scenario** | Approve a package. Then approve a desk case. |
| **Severity** | Critical |
| **Expected behavior** | Package approval leaves `data/supportdesk-publish-state.json` unchanged. Desk approval leaves `data/publish-state.json` unchanged. The files are not merged. |
| **Owner** | `api/package.py`, `api/desk.py` |
| **Phase** | 8 |

### EC-PUB-06 — Desk rejection during a package test

| Field | Value |
| --- | --- |
| **Scenario** | A desk case is rejected while a package is pending or approved. |
| **Severity** | Critical |
| **Expected behavior** | `explainer.json` hashes the same before and after. Assemble is not called. The case remains on the queue. |
| **Owner** | `api/desk.py` |
| **Phase** | 8, 11 |

### EC-PUB-07 — Package send rights

| Field | Value |
| --- | --- |
| **Scenario** | An approved package whose action is draft only. Separately, an approved package whose action is send. |
| **Severity** | Critical |
| **Expected behavior** | Draft-only calls `draft_email` and does not call `send_email`. Send is available only on this path, and only when the approved action says send. The desk path still cannot send. |
| **Owner** | `api/package.py` |
| **Phase** | 8 |

### EC-PUB-08 — Hosted draft retry is not exactly-once

| Field | Value |
| --- | --- |
| **Scenario** | A definite Gmail draft failure is retried. Separately, the failure was a timeout. |
| **Severity** | High |
| **Expected behavior** | The hosted server has no update-draft tool, so a non-timeout retry can create a second draft. A timeout stays `uncertain` and is not retried. The approval screen and the README state that limit. The system does not claim exactly-once delivery. |
| **Owner** | `supportdesk.publish`, approval screen, README |
| **Phase** | 7, 9, 12 |

---

## 11. Console (section 8, G5, Phases 9 and 10)

Chips are derived from stored fields, in this order, and every chip that applies is shown: Personal data, Advice, Complaint, Fact, Not covered.

| Chip | Condition |
| --- | --- |
| Personal data | Compliance recorded a redaction, or the case was blocked because redaction could not be guaranteed |
| Advice | Compliance refused for advice or a return request |
| Complaint | Pattern signal is `recurring` or `rising`, and `theme_id` is set |
| Fact | Facts coverage is `covered` |
| Not covered | Facts coverage is `not_covered` |

### EC-UI-01 — Two chips for a disagreement

| Field | Value |
| --- | --- |
| **Scenario** | Facts are `covered` and the pattern signal is `recurring` or `rising` with a theme id. |
| **Severity** | High |
| **Expected behavior** | The row shows Fact and Complaint. It does not show one blended label. The reply cites the fact. The routing note keeps the pattern signal, the count, and the window. |
| **Owner** | `/queue` |
| **Phase** | 9 |

### EC-UI-02 — Chips that must stay off

| Field | Value |
| --- | --- |
| **Scenario** | Pattern is `one_off` or `insufficient_data`. A later turn in an advice session is a plain fact question (desk SD-09). Coverage is a single value. |
| **Severity** | High |
| **Expected behavior** | `one_off` and `insufficient_data` do not show Complaint. The later fact case shows Fact from its own compliance decision and does not inherit Advice from the session flag. One coverage value produces Fact or Not covered, not both. |
| **Owner** | `/queue` |
| **Phase** | 9 |

### EC-UI-03 — Personal data chip

| Field | Value |
| --- | --- |
| **Scenario** | Redaction succeeded. Separately, redaction blocked the case. |
| **Severity** | High |
| **Expected behavior** | Both show Personal data. The blocked case is on the queue and is not in the log (EC-REC-01). The screen shows sanitized text. |
| **Owner** | `/queue` |
| **Phase** | 9 |

### EC-UI-04 — Source panel

| Field | Value |
| --- | --- |
| **Scenario** | A covered claim with `retrieved_on`. A covered claim without it. A not-covered result. An advice refusal. |
| **Severity** | Critical |
| **Expected behavior** | Covered: the claim, the allow-listed link, and the retrieval date. Missing date: `date unavailable`. Not covered: the pages searched, and no claim. Advice refusal: no citation URL and no recommendation. |
| **Owner** | `/queue/[caseId]` |
| **Phase** | 9 |

### EC-UI-05 — Desk approval screen

| Field | Value |
| --- | --- |
| **Scenario** | The operator opens approve, then approves, rejects, or publishes. |
| **Severity** | Critical |
| **Expected behavior** | The screen shows the exact reply, the exact routing note, the Doc id, the draft recipient, and the content hash, plus the sentence that Gmail send will not be called. Approve and reject post to the Phase 7 decision route. Publish posts only after approve, and only for the hash on screen. The browser does not call MCP. |
| **Owner** | `/queue/[caseId]/approve` |
| **Phase** | 9 |

### EC-UI-06 — Pulse page labels

| Field | Value |
| --- | --- |
| **Scenario** | The pulse page renders themes and support signals. The ledger is empty. The fixture has five matching rows. |
| **Severity** | High |
| **Expected behavior** | Each signal is labeled `queue`. Theme counts stay labeled `pattern`. The empty ledger shows the exact empty-ledger sentence. Five rows show the five-times line. Approving the package does not change a desk case. Review windows and the question week are labeled with their own dates. |
| **Owner** | `/`, `/publish` |
| **Phase** | 10 |

### EC-UI-07 — Package publish screen

| Field | Value |
| --- | --- |
| **Scenario** | The operator opens `/publish` for a run that assembled. |
| **Severity** | High |
| **Expected behavior** | The package hash and the three artifacts are shown before the write. Publish posts to the Phase 8 route. |
| **Owner** | `/publish` |
| **Phase** | 10 |

### EC-UI-08 — Agent timings

| Field | Value |
| --- | --- |
| **Scenario** | A case page for an eligible question. One agent timed out. |
| **Severity** | Medium |
| **Expected behavior** | The page shows each agent's start and end. Overlapping intervals are the R3 evidence. A compliance timeout blocks the draft (desk SD-22). The page does not invent a reply for that case. |
| **Owner** | `/queue/[caseId]` |
| **Phase** | 9 |

---

## 12. Acceptance, evaluation, and operations (C1–C5, E1–E3, Phase 11)

### EC-EVAL-01 — C1 through C5

| Field | Value |
| --- | --- |
| **Scenario** | The five acceptance setups in the implementation plan. |
| **Severity** | Critical |
| **Expected behavior** | C1: at most three sentences, one allow-listed link, a last-checked value or `date unavailable`. C2: not covered, ledger row, no claim in the draft. C3: five identical sanitized charge questions and a fixture theme that meets the fee floor; the routing note has signal, count, and window; the signal file has the queue line; the explainer has at most six bullets. C4: a phone-shaped number is absent from the response JSON, the log row, and the case blob. C5: both advice turns are refused; a separate double review failure is blocked and the fake client records no call. |
| **Owner** | `tests/capstone/test_scenarios.py` |
| **Phase** | 11 |

### EC-EVAL-02 — E1 through E3

| Field | Value |
| --- | --- |
| **Scenario** | One assemble. Then hash A versus hash B and a desk rejection. Then five claims plus a PAN, an account number, a phone, and a return-figure request. |
| **Severity** | Critical |
| **Expected behavior** | E1: every queued case is a draft or not covered, theme ids are present, word count and bullet count hold, and MCP was not called. E2: publish of hash B is refused, and `explainer.json` is unchanged by the desk rejection. E3: no publish-state file changes for those four messages. |
| **Owner** | `tests/capstone/test_eval.py` |
| **Phase** | 11 |

### EC-EVAL-03 — A skip is not a pass

| Field | Value |
| --- | --- |
| **Scenario** | The sibling corpus or the Play export is missing, so the live half of a check cannot run. |
| **Severity** | High |
| **Expected behavior** | That half is skipped. `docs/capstone/eval.md` records `not run`. The known catalog limit is stated beside the result: most Play Store complaints fall outside the catalog, and a high not-covered count is a correct E1 outcome when C1 still passes on a catalog question. |
| **Owner** | `docs/capstone/eval.md` |
| **Phase** | 11 |

### EC-OPS-01 — Secrets, fixtures, and screenshots

| Field | Value |
| --- | --- |
| **Scenario** | A fixture, a log line, a screenshot, or the demo is prepared. |
| **Severity** | Critical |
| **Expected behavior** | Placeholders only. `data/capstone.db` is gitignored. `.env` gains no new secret. The database stores no tokens. |
| **Owner** | fixtures, README |
| **Phase** | 2, 11, 12 |

### EC-OPS-02 — Interrupted assemble or a full disk

| Field | Value |
| --- | --- |
| **Scenario** | The process is killed during assemble, or a write raises `No space left on device`. |
| **Severity** | High |
| **Expected behavior** | The error propagates. No package is marked approved. Nothing is published. |
| **Owner** | `assemble.py` |
| **Phase** | 6, 10 |

---

## 13. Edge case → requirement matrix

| Requirement | Edge cases |
| --- | --- |
| J1, P1, P2 | EC-LOG-01–08, EC-REC-01–03, EC-HTTP-01 |
| J2 | EC-ID-01–12, EC-WEEK-01–07, EC-SIG-01–09 |
| J3, W2 | EC-LOG-02, EC-EXP-09 |
| J4 | EC-SIG-05, EC-UI-01 |
| J5 | EC-REC-06, EC-SIG-04, EC-SIG-06, EC-EXP-04, EC-EXP-05 |
| W1 | EC-EXP-01–05, EC-SIG-09 |
| W3, W4, B2 | EC-PKG-01–09, EC-PUB-01–03 |
| G1–G5 | EC-EXP-06–08, EC-EXP-11, EC-UI-04 |
| A1 | EC-REC-04, EC-EXP-10, EC-SIG-08, EC-EVAL-01 |
| B1, B3, B5 | EC-HTTP-05–09, EC-PUB-08 |
| B4, B6 | EC-PUB-04–07, EC-PUB-08 |
| S2, S3 | EC-SIG-07, EC-PKG-01, EC-EXP-08, EC-EXP-12 |
| R1–R5 | EC-HTTP-01–06, EC-UI-05, EC-UI-08 |
| C1–C5, E1–E3 | EC-EVAL-01–03 |
| P3 | EC-OPS-01 |

S1, S4, A2–A4, and the desk reviewer stay in `src/supportdesk/`. The rows above only cover the join's use of them. Desk SD-01 through SD-34 remain the checklist for that package.

---

## 14. Priority fixtures

| Fixture | Edge cases |
| --- | --- |
| Identity strings: case, space, placeholders, empty, emoji, fullwidth | EC-ID-01–05, EC-ID-09–11 |
| Fixed clocks: Sunday 18:30 UTC, 31 Dec 2025, 1 Jan 2027 | EC-WEEK-02, EC-WEEK-03 |
| Five identical sanitized charge questions, and a four-row twin | EC-SIG-01, EC-EVAL-01 |
| `clusters.json` with two fee themes of different sizes, one theme under the floor, and a `feedback` label | EC-EXP-01, EC-EXP-04 |
| Fake retriever: off-host URL, claim absent from the passage, missing `retrieved_on` | EC-EXP-07, EC-EXP-11 |
| Six ledger rows, and an empty ledger | EC-EXP-09, EC-PKG-03 |
| A bullet containing "you should redeem" | EC-EXP-10 |
| Passing pulse manifest and a failed pulse manifest | EC-PKG-01, EC-PKG-02 |
| `tests/contract/fake_mcp.py` call list | EC-HTTP-07, EC-HTTP-08, EC-PUB-01 |
| Two temporary state files | EC-PUB-05 |
| Phone-shaped, PAN-shaped, and account-shaped strings | EC-REC-02, EC-EVAL-01, EC-EVAL-02 |

---

## 15. Out of scope

Handled only if the architecture changes:

| Scenario | Why it is out of scope |
| --- | --- |
| A second facts agent, redactor, retriever, or vector store | Architecture section 13 |
| A model deciding that two questions match, that a theme is about fees, or that a missing count is zero | Architecture section 13 |
| `send_email` on a desk case | B3 |
| Merging the two publish-state files | B4 |
| Editing Milestone 2 or Milestone 3 acceptance criteria | Implementation plan, section 2 |
| Apple App Store ingest, trades, or Groww private APIs | Problem statement section 4.3 |
| Putting support signals inside `note.md` | S2, architecture section 5 |
| A capstone path through `reviewpulse run --send` | Architecture section 5 |
| Recording the demo video | Phase 12 excludes it |

---

## 16. Abort, refuse, or proceed

| Outcome | When |
| --- | --- |
| **Write nothing** | Redaction cannot be guaranteed. The case blob fails validation. A raw phone or PAN is still present. |
| **Refuse publish, no MCP call** | Missing approval, hash mismatch, blocked or rejected case, desk send flag, package caller is a desk case id, timeout recorded as `uncertain`. |
| **Refuse the package, leave `note.md`** | Pulse gates failed or missing. Explainer gates fail on advice, a return figure, PII, a sixth link, or a seventh bullet. `clusters.json` is missing. |
| **Proceed with an explicit empty result** | No fee theme (`fee_theme` null and the bar statement). Empty ledger (the exact sentence). No five-times group (an empty signal list). Facts error or not covered (no factual bullet). |
| **Proceed and store** | Covered and not-covered cases that passed sanitization. A second append of the same `case_id`. Five or more rows of one non-empty key. A rejected case, which stays in the log for the next assemble. |
