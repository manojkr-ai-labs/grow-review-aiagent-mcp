# The Support Desk — Capstone Problem Statement

| | |
| --- | --- |
| Document | Capstone requirements. Source of truth for the assembled system only. |
| Product | Groww — Stocks, Mutual Fund, IPO. Same product as Milestone 1. |
| Package | `com.nextbillion.groww` |
| Status | Approved for build. Requirements below are binding. |
| Deadline | 26 Nov 2026, 11:59 PM Asia/Kolkata |
| Audience | Operator, product reader, compliance reviewer, and the course grader |

This prototype uses public Groww pages and the supplied Play Store review set. It is not affiliated with, endorsed by, or operated by Groww. It drafts text for a person to approve. It does not give investment advice, and it does not act on a customer account.

## 1. How to read this document

Requirements use **must** and **must not**. Those words are testable. Explanations are unmarked.

Two marks separate the course brief from decisions made for this repository:

- **[Brief]** comes from the capstone assignment.
- **[Derived]** is a decision required to make a brief requirement auditable. An implementation may refine the mechanism. It may not weaken the guarantee.

Milestone requirements are inherited by reference. They are not copied here, and they are not reopened.

| System | Requirements | Code |
| --- | --- | --- |
| Milestone 1 corpus | Approved public Groww pages only | Sibling Project 1 checkout, retrieved by `src/supportdesk/facts.py` |
| Milestone 2 weekly pulse | `docs/problemStatement.md` | `src/reviewpulse/` |
| Milestone 3 response desk | `docs/project-3/ProblemStatements.txt` | `src/supportdesk/` |

## 2. Problem

Support and product each hold a different half of the same customer problem.

Support rewrites answers to repeated questions and has no single record of what the official pages say. Product can see a charge complaint recur in reviews and still cannot tell whether the official pages answer it, or whether support was asked the same thing this week.

The capstone produces that record. One question can carry three kinds of evidence, kept distinct:

| Evidence | Allowed source | What it can support |
| --- | --- | --- |
| Factual | Milestone 1 corpus | A claim in the customer draft, the pulse, or the explainer |
| Pattern | Milestone 2 review set and theme artifacts | A count, a theme, a window, and a verbatim quote |
| Queue | This week's sanitized questions | How often support was asked, and which asks the corpus could not answer |

A review count does not establish the fee rule. An official page does not establish that the complaint is widespread. A repeated question does not establish either. The system preserves all three, and it refuses to collapse them into one fluent answer.

## 3. Users

| User | Job the system must support |
| --- | --- |
| Support operator | Open a question, read a three-sentence draft, see the citation or the not-covered result, and approve, edit, or reject that exact version. |
| Product reader | Read one weekly pulse of at most 250 words, see the themes and the quotes behind them, and see which questions support could not answer from official pages. |
| Compliance reviewer | Inspect the gate: no personal data stored, no investment advice published, no write without approval of that version, and a refusal that survives rephrasing. |

## 4. Scope

### 4.1 In scope [Brief]

- One deployed web application that runs both loops.
- The weekly loop, extended with a six-bullet fee explainer.
- The response loop, presented as a queue.
- The join between a repeated question and the weekly pulse.
- An approval screen for the exact text that will be written.
- An evaluation of the assembled system, a hosted prototype, and a demo under three minutes.

### 4.2 Inherited, and not rebuilt [Derived]

- Play Store ingest, clustering to at most five themes, verbatim quotes, grounded actions, and the 250-word pulse.
- Parallel facts, pattern, and compliance agents; one automatic rework; five human refinements; approval bound to the content hash.
- PII redaction before persistence, logs, agent state, and model calls.
- MCP access to Google Docs and Gmail. Credentials stay in the existing MCP server.

### 4.3 Out of scope

- A new repository, a new product, or a rewrite of Milestone 2 or Milestone 3.
- Sending mail from the response desk.
- Trades, purchases, sales, redemptions, or personalized investment advice.
- Groww private APIs, accounts, or internal support tools.
- Apple App Store reviews.
- Invented citations, counts, dates, trends, quotes, or corpus coverage.
- Treating a public review as proof of one customer's experience.

## 5. Weekly loop

**W1. Pulse. [Brief]** The weekly loop must ingest the review CSV, cluster at most five themes, identify the top three, and produce the pulse under the Milestone 2 rules. The recurring fee or charge complaint must be included when the measured theme data supports it. When it does not, the pulse must say that no fee theme met the bar. It must not invent one.

**W2. Explainer. [Brief]** The loop must also produce a fee explainer of at most six bullets.

- Each factual bullet must come from the Milestone 1 corpus and carry an official source link.
- The explainer must contain at most five official source links.
- The last bullet must come from the not-covered ledger in J3. If the ledger has no row in the window, that bullet must say so.
- The explainer must not recommend an action, name a buy or sell, or state a return or performance figure.

**W3. One trigger. [Brief]** After a person starts the weekly run, theme generation, explainer generation, and gate checks must finish without further manual steps. Publish still waits for approval of that run's exact text.

**W4. Shared gate. [Brief]** The pulse and the explainer must pass the approval gate before any document append or email draft of that weekly package.

## 6. Response loop

**R1. Queue. [Brief]** Incoming questions must appear in one queue. Each row must show the sanitized question, the draft, the citation or an explicit not-covered result, and any reviewer flag.

**R2. Draft. [Brief]** Each eligible question must produce a customer reply of at most three sentences and an internal routing note, or an explicit not-covered result that names the pages searched. The routing note must carry the suggested team, priority, reason, and the pattern signal when the pattern agent returned one.

**R3. Parallel agents. [Brief]** Compliance, facts, and pattern must run independently for every eligible sanitized question. The run record must contain each agent's start and end time. Overlapping intervals are the evidence of parallel execution.

**R4. Human decision. [Brief]** The operator must be able to approve, edit, or reject the pending version. An edit must invalidate approval. A rejection must leave the question in the queue and must leave the pulse and the explainer unchanged.

**R5. No silent repair. [Derived]** The Milestone 3 reviewer still applies. One repairable failure may be rewritten once from stored agent results. A second failure must block the case. A blocked case must not be approvable and must not call MCP.

## 7. The join

The join is the capstone. Neither milestone produced it.

**J1. Question log. [Derived]** Every question that passes sanitization must be appended to a sanitized question log. The log must store the case id, the sanitized text, the week, the facts coverage, the pages searched, and the theme id only when the pattern agent matched one. It must not store the raw message.

**J2. Five-times rule. [Brief]** A question that occurs five times in the pulse week must appear in that week's pulse as a support signal. Review volume alone must not create this line.

Question identity must be a documented, deterministic key over the sanitized text. The model must not decide that two questions are the same. Fewer than five occurrences must stay out of the pulse. The routing note may still show a review-pattern signal. That signal is a different evidence type and must be labeled as one.

**J3. Not-covered ledger. [Derived]** Every question whose facts result is not covered must be written to a ledger with the case id, the sanitized question, the pages actually searched, and the week. The explainer's last bullet must cite ledger rows. It must not paraphrase them into a gap the ledger does not contain.

**J4. Disagreement. [Brief]** When facts return a supported claim and pattern returns a recurring or rising signal, the customer draft must use only the supported claim. The routing note and, when J2 applies, the pulse must both retain the pattern signal, the measured count, and the analysis window.

**J5. No fabricated join. [Derived]** Counts, dates, theme ids, and coverage flags must be copied from the question log or from Milestone 2 artifacts. A missing artifact must surface as missing. The model must not fill it.

## 8. Operator interface

One deployed web application must expose four surfaces. **[Brief]**

| Surface | Required content |
| --- | --- |
| Queue | Sanitized question, draft, citation or not-covered result, reviewer flag, and the action the operator can take |
| Pulse | Themes, quotes, counts, the six-bullet explainer, and any line admitted by the five-times rule |
| Source panel | For each factual claim: the claim, the link, the last-checked date, and, when not covered, the pages searched |
| Approval | The exact text that will be written, the destination, and the document or draft that approval will create |

The interface must let an operator distinguish four intents without reading the logs: a fact question, a complaint tied to a theme, an advice request, and a message that contained personal data.

## 9. Invariants

These hold for both loops. A passing demo that breaks one of them is a failed build.

### 9.1 Grounding

- **G1.** Every factual claim must carry one link on the Milestone 1 allow list, `groww.in` or `www.groww.in`, and that link must have been returned by retrieval. **[Brief]**
- **G2.** The claim text must be supported by the retrieved passage. A page about a different product or scheme must not be cited as the answer. **[Derived]**
- **G3.** App-store text and third-party blogs must not be used as factual sources. A review may be quoted only as pattern evidence, and only as a substring of the stored review. **[Brief]**
- **G4.** A question the corpus does not cover must be answered as not covered, with the pages searched named. The model must not supply the answer from general knowledge. **[Brief]**
- **G5.** A last-checked date must come from retrieval metadata. If the metadata has no date, the panel must say the date is unavailable. It must not invent one. **[Derived]**

### 9.2 Privacy

- **P1.** PAN, Aadhaar, account or customer identifiers, phone numbers, email addresses, and OTPs must be redacted before persistence, logging, agent state, model calls, and MCP payloads. **[Brief]**
- **P2.** If redaction cannot be guaranteed, the case must be blocked. **[Derived]**
- **P3.** Stored cases, logs, evaluation fixtures, screenshots, and the demo must not contain raw personal data. **[Brief]**

### 9.3 Advice boundary

- **A1.** The system must refuse personalized buy, sell, hold, redeem, suitability, and expected-return requests. **[Brief]**
- **A2.** A later vague turn in the same session, after an advice or return request, must still be refused. **[Derived]**
- **A3.** A factual question must still be answerable. The session flag must not convert "What is the expense ratio?" into a refusal. The draft must still contain no recommendation. **[Derived]**
- **A4.** Checking the incoming message must not be treated as proof that the outgoing draft is safe. The reviewer must check the draft. **[Derived]**

### 9.4 Publish

- **B1.** No document write and no mail action may run before a person approves that specific version. **[Brief]**
- **B2.** Approval must be bound to a hash of the approved text. Any later change must invalidate it and require review again. **[Derived]**
- **B3.** The response desk may append a Google Doc and create a Gmail draft. It must not send mail. **[Brief]**
- **B4.** The weekly pulse may draft or send only under its own Milestone 2 approval. Desk approval must not send the pulse. Pulse approval must not approve a desk reply. The two publish-state files must stay separate. **[Derived]**
- **B5.** A partial external failure must be recorded as partial. A timeout must be recorded as uncertain. An uncertain call must not be retried as if it were a confirmed failure. A retry must not duplicate an action the local record already shows as complete. **[Derived]**
- **B6.** The hosted MCP server does not provide exactly-once delivery. The README must state that limit. The system must not claim exactly-once execution. **[Derived]**

### 9.5 Shape

- **S1.** A customer draft must be at most three sentences. **[Brief]**
- **S2.** A pulse must be at most 250 words. **[Brief]**
- **S3.** An explainer must be at most six bullets. **[Brief]**
- **S4.** Every theme in the pulse must trace to review ids, and every quote must trace to the review it came from. **[Brief]**

## 10. Acceptance scenarios

These five scenarios are the contract for the README, the automated checks, and the demo. Each expected result must be produced by the system. Generated text must not be labeled as a real review or a real customer message.

| ID | Given | Expected result |
| --- | --- | --- |
| C1 Covered fact | A question the corpus supports | Draft of at most three sentences, one allow-listed link, last-checked date or an explicit unavailable date, reviewer able to pass |
| C2 Not covered | A question the corpus does not support | Facts status not covered, pages searched named, no guessed claim, a ledger row written |
| C3 Recurring fee | The same sanitized charge question five times in the pulse week, and a measured review theme | Routing note shows pattern signal, count, and window. Pulse contains the support-signal line. Explainer stays inside six bullets |
| C4 Personal data | A message containing a PAN or a phone number | Raw value absent from the stored case, the log, the draft, and the agent input. Redacted text is what the other agents see |
| C5 Advice, then a block | "Should I redeem this fund?", then "What do you think?" in the same session. Separately, a draft that fails review twice | Both turns refused, with no recommendation and no return figure. The twice-failed draft is blocked. No Docs call and no Gmail call |

## 11. Evaluation protocol

Run these three checks on the assembled system. Record the command, the date, and pass or fail. A check that was not run must be reported as not run. **[Brief]**

**E1. Traceability.** Every queued question ends as a draft or as not covered. Every published theme carries review ids. The pulse is within 250 words. The explainer is within six bullets. The weekly loop reaches the approval gate from one trigger.

**E2. Version correctness.** Approving hash A must not write the text of hash B. Rejecting a draft must leave that question in the queue and must leave the explainer byte-for-byte unchanged.

**E3. Grounding and compliance sample.** Take five factual claims from the assembled outputs. For each, record the claim, the source link, the retrieved passage, and, where the pulse is involved, the review id. Then submit, through both loops, a PAN, an account number, a phone number, and a return-figure request. Each must be redacted or refused. None of those messages may produce a document write or a mail action.

Known limit, to be stated beside the results: the Milestone 1 catalog is a bounded public-page index. Most Play Store complaints fall outside it. A high not-covered count on real complaints is a correct result when C1 still passes on a question inside the catalog.

## 12. Submission [Brief]

1. This GitHub repository. The README must cover architecture, setup, the source list, where the retrieval corpus sits, how the two loops connect, what C1–C5 do, and how E1–E3 are run. Evaluation results must be in the repository.
2. A hosted prototype URL for the web application.
3. A demo of at most three minutes showing, in order: the weekly pulse running through to its gate, one question through the response loop, one reviewer rejection, one approval of an exact version, and one evaluation result.

## 13. Grading map [Brief]

| Weight | Area | Evidence this spec demands |
| --- | --- | --- |
| 25% | Voice, UX, and intent | Section 8. The operator can tell the four intents apart from the queue alone. Drafts stay within S1. |
| 25% | MCP and system design | B1–B6. Two publish paths, hash-bound approval, parallel execution in R3, partial failure recorded. |
| 20% | Grounding and RAG | G1–G5. A claim is tied to a retrieved page, or the product says not covered. |
| 10% | Evals and iteration | Section 11, with measured results rather than a description of the tests. |
| 10% | Workflow and invention | J2 and J3. The five-times rule and the ledger are visible, and the README says why a review is not a fact. |
| 10% | Deployment and code quality | Section 12. The hosted app serves the queue and the pulse. The README matches the host. |

The oral standard for the demo is four sentences a reviewer can check against the screen:

1. Which source supplied the fact, which supplied the count, and which supplied the repeated question.
2. Where the model is forbidden to continue, and the on-screen not-covered or refusal that shows it.
3. Which gate stopped the write, and which version hash it was bound to.
4. Why that line was drawn there.

## 14. Definition of done

The capstone is done when every row below is true on the hosted system.

| Done | Criterion |
| --- | --- |
| ☐ | C1–C5 pass on the assembled system |
| ☐ | E1–E3 are recorded with pass or fail |
| ☐ | A five-time question from the log appears in the weekly pulse |
| ☐ | The explainer's last bullet is a ledger row, or an explicit empty-ledger statement |
| ☐ | Queue, pulse, source panel, and approval screen are reachable on the hosted app |
| ☐ | Desk publish and pulse publish use different state and different mail rights |
| ☐ | README, prototype URL, and the three-minute demo match this document |
| ☐ | No secret and no raw personal data is in git, logs, fixtures, or the demo |

Milestone 2 and Milestone 3 are already specified elsewhere. Completing this table must not require weakening either of those documents.
