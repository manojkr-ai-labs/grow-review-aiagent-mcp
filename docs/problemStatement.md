# Groww Review Intelligence Agent — Problem Statement & Project Context

> Source of truth for this project. Derived from `docs/problemStatement.txt` (the original course
> assignment brief). Sections marked **[Derived]** are interpretation/planning notes, not
> requirements from the brief.

---

## 1. Project Overview

Build an AI agent that turns raw mobile app-store feedback for **Groww** into a **weekly pulse**
that a product team can scan in minutes: what users care about, what they actually said, and what
to do next.

Reviews are already public. The job is not data acquisition heroics — it is to **aggregate, theme,
summarize, and deliver** the insight through surfaces the team already lives in:

- **Google Docs** — the written weekly pulse
- **Gmail** — a draft email containing (or pointing to) that pulse

Crucially, both integrations must go through **MCP servers**, so the project never handles OAuth
credentials or REST plumbing directly.

### Target Product

| Field | Value |
| --- | --- |
| App | Groww — Stocks, Mutual Fund, IPO |
| Platform | Google Play (Android) |
| Package ID | `com.nextbillion.groww` |
| Store URL | https://play.google.com/store/apps/details?id=com.nextbillion.groww&hl=en_IN |

### Scope (v1)

**In scope:** Google Play Store reviews only — the explicitly named source for Groww.

**Out of scope (deferred):** Apple App Store reviews. The original brief mentions both stores;
this project version focuses on Play Store to reduce integration surface area. An App Store adapter
can be added later without changing the downstream pipeline.

---

## 2. End-to-End Flow (Definition of "Done")

1. **Pull** recent **Google Play Store** reviews for the product, within the rules in
   [§6 Constraints](#6-key-constraints). (App Store is deferred — see [Scope (v1)](#scope-v1).)
2. **Cluster** them into a small set of themes.
3. **Distill** a one-page weekly note.
4. **Publish** that note where stakeholders can read it — Google Docs.
5. **Draft** an email to yourself (or an alias) that contains or links to that pulse — Gmail.

---

## 3. What You Must Build

- **Import reviews** covering roughly the **last 8–12 weeks**. Use whatever fields the export
  provides (e.g. rating, title, text, date).
- **Group reviews into at most 5 themes.** Themes should fit the product; examples given:
  onboarding, KYC, payments, statements, withdrawals.
- **Generate a weekly one-page note** containing:
  - **Top 3 themes** (a subset of your ≤5 themes, as appropriate)
  - **3 user quotes**
  - **3 action ideas**
- **Draft an email** with the note, addressed to yourself or an alias.

---

## 4. Deliverables

The weekly one-page pulse must include:

| Deliverable | Requirement |
| --- | --- |
| Top themes | What people are talking about most |
| Real user quotes | Verbatim snippets from reviews — **no invented wording** |
| Three action ideas | Concrete next steps, grounded in the themes |
| Draft email | Sent to yourself as a draft, containing the weekly note or a clear pointer to it |

---

## 5. Integrations: Google Docs & Gmail via MCP

Use **MCP (Model Context Protocol) servers** for Google Docs and Gmail — for example, creating or
updating the pulse document and creating the draft message — **rather than integrating Google APIs
directly**. No bespoke OAuth client plus REST client code as the primary integration path.

MCP servers expose tools the agent or app can call. Leaning on that pattern keeps Docs and Gmail
consistent with the course tooling and avoids duplicating auth and HTTP plumbing.

Choose whichever MCP servers or connectors the environment provides for Docs and Gmail. The
requirement is **MCP-first**, not "call Google APIs manually."

---

## 6. Key Constraints

| Constraint | Rule |
| --- | --- |
| **Reviews** | Public review exports only. No scraping behind store logins, no ToS-violating automation. |
| **Themes** | Maximum **5** themes for clustering; the written pulse highlights the **top 3**. |
| **Length** | Keep the note scannable and **≤ 250 words** where applicable. |
| **Privacy** | **No PII** in any artifact — no usernames, emails, device IDs, or other identifiable reviewer data. Quotes must be anonymous / stripped as needed. |

---

## 7. Who This Helps

| Audience | Why |
| --- | --- |
| Product / Growth | Prioritize fixes and improvements from real signals |
| Support | Align messaging with what users are actually saying |
| Leadership | One-page health check without drowning in raw reviews |

---

## 8. Pipeline Shape **[Derived]**

A reading of the brief as an implementable pipeline:

```
Public Play Store review export (8–12 weeks)
        │
        ▼
  Ingest & normalize  ──►  rating, title, text, date  (strip PII at this boundary)
        │
        ▼
  Theme clustering    ──►  ≤ 5 themes, ranked by volume
        │
        ▼
  Pulse synthesis     ──►  top 3 themes + 3 verbatim quotes + 3 action ideas, ≤ 250 words
        │
        ├──► MCP: Google Docs  ──►  create / update the weekly pulse doc
        └──► MCP: Gmail        ──►  create draft email to self, with note or doc link
```

Design points worth holding onto:

- PII stripping belongs **at ingestion**, so no downstream stage can leak it into an artifact.
- Quotes must be carried through verbatim, which means the summarization step needs access to the
  original review text rather than only to cluster labels or paraphrases.
- The Docs and Gmail steps are the only two that touch external systems, and both go through MCP.

---

## 9. Acceptance Checklist **[Derived]**

- [ ] Play Store reviews imported from a public export spanning roughly the last 8–12 weeks
- [ ] No PII present anywhere in the stored data or output artifacts
- [ ] At most 5 themes produced by clustering
- [ ] Weekly note names the top 3 themes
- [ ] Weekly note contains exactly 3 verbatim user quotes, unedited in wording
- [ ] Weekly note contains 3 concrete action ideas tied to the themes
- [ ] Weekly note is ≤ 250 words and reads as one scannable page
- [ ] Pulse document created or updated in Google Docs **via MCP**
- [ ] Draft email created in Gmail **via MCP**, containing the note or a clear link to it
- [ ] No direct Google API / hand-rolled OAuth integration used as the primary path

---

## 10. Open Questions **[Derived]**

These are unresolved in the brief and need a decision before or during implementation:

1. **Review source mechanics** — which specific public export is used for Play Store reviews.
2. **MCP server selection** — which Docs and Gmail MCP servers the environment provides, and how
   they are authenticated at the environment level.
3. **Recipient alias** — the exact address the Gmail draft is addressed to.
4. **Cadence and doc strategy** — whether each week creates a new Google Doc or appends to a single
   rolling document.
5. **Theme taxonomy** — whether themes are fixed up front for Groww or discovered per run from the
   review text.

### Resolved decisions

| Decision | Choice |
| --- | --- |
| Review sources (v1) | **Google Play Store only** — App Store deferred |
