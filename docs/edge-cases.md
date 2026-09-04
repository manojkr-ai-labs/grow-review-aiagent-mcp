# Edge Cases & Corner Scenarios — Groww Review Intelligence Agent

> Catalog of boundary conditions, failure modes, and unusual inputs for the weekly pulse pipeline.
> Derived from [`architecture.md`](./architecture.md) and [`implementation-plan.md`](./implementation-plan.md).
>
> Each entry follows: **Scenario → Impact → Expected behavior → Owner (module/gate) → Test hint**.

---

## 1. How to use this document

| Column | Meaning |
| --- | --- |
| **Severity** | `Critical` — must abort or block publish; `High` — degraded output risk; `Medium` — handle gracefully; `Low` — cosmetic / ops |
| **Owner** | Primary module or validation gate responsible |
| **Phase** | Implementation phase where handling must exist |

Use this doc when writing unit tests, designing fixtures, and reviewing run failures in `runs/<run_id>/manifest.json`.

---

## 2. Ingestion & export data

### EC-ING-01 — Empty export file

| Field | Value |
| --- | --- |
| **Scenario** | `data/raw/` file exists but has zero data rows (headers only or blank file). |
| **Severity** | Critical |
| **Impact** | Cannot produce themes, quotes, or a meaningful pulse. |
| **Expected behavior** | Abort ingest with clear error: `No reviews found in export`. Do not write to SQLite. Do not proceed to clustering. |
| **Owner** | `sources/play_export.py`, `orchestrator.py` |
| **Phase** | 1 |
| **Test hint** | `tests/fixtures/empty_export.csv` |

---

### EC-ING-02 — Export covers fewer than 8 weeks

| Field | Value |
| --- | --- |
| **Scenario** | User requests `--window-weeks 12` but export only contains 4–6 weeks of reviews. |
| **Severity** | Medium |
| **Impact** | Pulse may under-represent trends; manifest would misstate coverage if unchecked. |
| **Expected behavior** | **Warn loudly** in logs and manifest (`window_warning: "actual_coverage_weeks": 6`). Proceed with available data. Never claim 12 weeks in the rendered note — use actual `window_start` / `window_end` from data. |
| **Owner** | `sources/normalize.py`, `window_declared` gate |
| **Phase** | 1, 3 |
| **Test hint** | Fixture with reviews spanning 3 weeks only |

---

### EC-ING-03 — Export spans more than 12 weeks

| Field | Value |
| --- | --- |
| **Scenario** | Export file contains 18 months of history; window filter is 12 weeks. |
| **Severity** | Low |
| **Impact** | None if window filter works; stale reviews excluded correctly. |
| **Expected behavior** | Window filter drops out-of-range rows. Manifest records filtered count vs. total parsed. |
| **Owner** | `sources/normalize.py` |
| **Phase** | 1 |
| **Test hint** | Mix of old and recent dates; assert only window rows in DB |

---

### EC-ING-04 — Unknown or renamed export columns

| Field | Value |
| --- | --- |
| **Scenario** | CSV uses `Review Text` instead of `text`, or columns are reordered. |
| **Severity** | High |
| **Impact** | Silent field loss or ingest failure. |
| **Expected behavior** | Support configurable column mapping in `settings.toml`. Fail with explicit message listing required vs. found columns if mapping cannot resolve `text` and `date`. |
| **Owner** | `sources/play_export.py` |
| **Phase** | 1 |
| **Test hint** | Alternate header fixture |

---

### EC-ING-05 — Mixed CSV encodings (UTF-8 vs Latin-1)

| Field | Value |
| --- | --- |
| **Scenario** | Hindi/regional-language reviews with mojibake from wrong encoding. |
| **Severity** | Medium |
| **Impact** | Garbled text in quotes; clustering quality drops. |
| **Expected behavior** | Try UTF-8 first; fallback to `utf-8-sig`, then `latin-1` with warning. Record `encoding_detected` in manifest. |
| **Owner** | `sources/play_export.py` |
| **Phase** | 1 |
| **Test hint** | UTF-8 Hindi review fixture |

---

### EC-ING-06 — Duplicate rows within same export

| Field | Value |
| --- | --- |
| **Scenario** | Same review appears twice in one file (export glitch). |
| **Severity** | Low |
| **Impact** | Inflated theme counts if not deduped. |
| **Expected behavior** | `review_id` hash upsert — second row is no-op. Manifest: `deduped_count`. |
| **Owner** | `store/sqlite.py` |
| **Phase** | 1 |
| **Test hint** | File with identical rows |

---

### EC-ING-07 — Re-import overlapping export on weekly run

| Field | Value |
| --- | --- |
| **Scenario** | Week 2 export overlaps week 1 by 11 weeks (rolling 12-week window). |
| **Severity** | Low |
| **Impact** | None — by design. |
| **Expected behavior** | Upsert on `review_id`; only new/changed rows increment `accepted_count`. |
| **Owner** | `store/sqlite.py` |
| **Phase** | 1 |
| **Test hint** | Import A, then import B ⊃ A |

---

### EC-ING-08 — Missing `external_id` in export

| Field | Value |
| --- | --- |
| **Scenario** | Export has no stable review ID column. |
| **Severity** | Medium |
| **Impact** | Hash collision risk if fallback is naive. |
| **Expected behavior** | `review_id = sha256(source \| normalized_text \| date \| rating)`. Log when fallback path used. |
| **Owner** | `store/sqlite.py` |
| **Phase** | 1 |
| **Test hint** | Rows without ID; near-duplicate text same day |

---

### EC-ING-09 — App Store export provided (out of scope v1)

| Field | Value |
| --- | --- |
| **Scenario** | User places an Apple App Store CSV in `data/raw/`. |
| **Severity** | Medium |
| **Impact** | Wrong adapter or parse failure. |
| **Expected behavior** | Reject with message: App Store not supported in v1. Point to Play-only scope (ADR-7). Do not silently ingest. |
| **Owner** | `sources/play_export.py`, `cli.py` |
| **Phase** | 1 |
| **Test hint** | App Store column layout fixture → expect clear error |

---

## 3. Normalization

### EC-NORM-01 — Review with empty or whitespace-only text

| Field | Value |
| --- | --- |
| **Scenario** | Rating and title present; `text` is `""` or `"   "`. |
| **Severity** | Low |
| **Impact** | Noise in clustering. |
| **Expected behavior** | Drop row; increment `dropped_empty_text` in manifest. |
| **Owner** | `sources/normalize.py` |
| **Phase** | 1 |

---

### EC-NORM-02 — Rating missing or out of range

| Field | Value |
| --- | --- |
| **Scenario** | `rating` is `null`, `0`, `6`, or non-numeric string. |
| **Severity** | Low |
| **Impact** | Broken stats in pulse header. |
| **Expected behavior** | Missing → `None`; out of range → clamp to 1–5 or drop with warning (document choice in config). Pulse shows `avg N/A` if no ratings. |
| **Owner** | `sources/normalize.py`, `pulse/render.py` |
| **Phase** | 1, 3 |

---

### EC-NORM-03 — Title-only reviews (no body)

| Field | Value |
| --- | --- |
| **Scenario** | Play export has star rating + short title, empty body. |
| **Severity** | Medium |
| **Impact** | Very short embedding; weak clusters. |
| **Expected behavior** | Keep if title is non-empty (use `title_clean` as text). Drop only if both empty. |
| **Owner** | `sources/normalize.py` |
| **Phase** | 1 |

---

### EC-NORM-04 — Future-dated reviews

| Field | Value |
| --- | --- |
| **Scenario** | Export contains dates ahead of `today` (timezone/export bug). |
| **Severity** | Low |
| **Impact** | Window filter edge confusion. |
| **Expected behavior** | Exclude dates > `now + 1 day` (clock skew tolerance). Warn in manifest. |
| **Owner** | `sources/normalize.py` |
| **Phase** | 1 |

---

### EC-NORM-05 — Non-English / mixed-script reviews

| Field | Value |
| --- | --- |
| **Scenario** | Hindi, Hinglish, or emoji-heavy reviews for Groww India. |
| **Severity** | Medium |
| **Impact** | English-only embedder may weaken clusters; labels may be wrong language. |
| **Expected behavior** | Detect language; keep all reviews. Use multilingual embedding model. Preserve quote text as written (no translation). LLM labels may be English for stakeholder readability — document in manifest `label_lang: en`. |
| **Owner** | `analysis/embed.py`, `chains/label_themes.py` |
| **Phase** | 2 |

---

### EC-NORM-06 — Extremely long reviews (10k+ chars)

| Field | Value |
| --- | --- |
| **Scenario** | User pastes essay-length feedback. |
| **Severity** | Low |
| **Impact** | Embedding truncation; token cost for labeling sample. |
| **Expected behavior** | Truncate at embed/label time (e.g. first 2k chars); store full `text_clean` in DB for quote substring checks. |
| **Owner** | `analysis/embed.py`, `analysis/label.py` |
| **Phase** | 2 |

---

## 4. PII scrubbing

### EC-PII-01 — Email in review text

| Field | Value |
| --- | --- |
| **Scenario** | `"Contact me at user@gmail.com for refund"`. |
| **Severity** | Critical |
| **Impact** | Privacy violation if published. |
| **Expected behavior** | Replace with `[email]`; `scrub_flags: ["email"]`. Quote may contain `[email]` — valid under D2/D3. |
| **Owner** | `privacy/scrubber.py`, `no_pii` gate |
| **Phase** | 1, 3 |
| **Test hint** | Required fixture per implementation plan §3.2 |

---

### EC-PII-02 — Phone number variants

| Field | Value |
| --- | --- |
| **Scenario** | `+91-9876543210`, `(987) 654-3210`, `9876543210`. |
| **Severity** | Critical |
| **Expected behavior** | All variants → `[phone]`. |
| **Owner** | `privacy/scrubber.py` |
| **Phase** | 1 |

---

### EC-PII-03 — PAN / account / order ID digit runs

| Field | Value |
| --- | --- |
| **Scenario** | `"My PAN ABCDE1234F failed KYC"` or 12-digit account number. |
| **Severity** | Critical |
| **Expected behavior** | Long digit runs and PAN-like patterns → `[number]`. Avoid redacting valid star ratings (`5`). |
| **Owner** | `privacy/scrubber.py` |
| **Phase** | 1 |
| **Test hint** | Near-miss: `"5 star app"` must NOT become `[number] star app` |

---

### EC-PII-04 — @handles and social mentions

| Field | Value |
| --- | --- |
| **Scenario** | `"@groww please fix this"`. |
| **Severity** | High |
| **Expected behavior** | `@groww` → `[handle]` or keep brand handle — **decide explicitly**: redact user handles, allow `@groww`/`@Groww` as product mentions. Document in scrubber config. |
| **Owner** | `privacy/scrubber.py` |
| **Phase** | 1 |

---

### EC-PII-05 — URL with PII in query string

| Field | Value |
| --- | --- |
| **Scenario** | `https://example.com/track?email=user@test.com&token=abc`. |
| **Severity** | High |
| **Expected behavior** | Redact full URL or strip query string → `[url]`. |
| **Owner** | `privacy/scrubber.py`, `no_pii` gate |
| **Phase** | 1, 3 |

---

### EC-PII-06 — Author field present in export

| Field | Value |
| --- | --- |
| **Scenario** | Export includes reviewer display name. |
| **Severity** | Critical |
| **Expected behavior** | Drop `author` at scrub boundary; never persist. |
| **Owner** | `privacy/scrubber.py` |
| **Phase** | 1 |

---

### EC-PII-07 — LLM echoes PII from prompt context

| Field | Value |
| --- | --- |
| **Scenario** | Scrubbed sample still contains edge pattern; LLM copies it into action text. |
| **Severity** | Critical |
| **Expected behavior** | `no_pii` gate on **final rendered note** aborts run. No auto-repair. |
| **Owner** | `pulse/validate.py` (`no_pii`) |
| **Phase** | 3 |

---

### EC-PII-08 — False positive: product name contains digits

| Field | Value |
| --- | --- |
| **Scenario** | `"Groww is best"` or `"SIP ₹500"` — short numbers in normal prose. |
| **Severity** | Medium |
| **Expected behavior** | Do not redact short currency amounts or single-digit ratings. Tune digit-run minimum length (e.g. ≥10 digits). |
| **Owner** | `privacy/scrubber.py` |
| **Phase** | 1 |
| **Test hint** | Near-miss fixtures in `tests/fixtures/pii_reviews.json` |

---

### EC-PII-09 — Quote contains redaction placeholder

| Field | Value |
| --- | --- |
| **Scenario** | Best quote for a theme includes `[phone]` after scrubbing. |
| **Severity** | Low |
| **Impact** | Quote reads awkwardly but is compliant. |
| **Expected behavior** | Allow quote; prefer candidates with fewer `scrub_flags` when scores tie. |
| **Owner** | `analysis/quotes.py` |
| **Phase** | 3 |

---

## 5. Storage & data volume

### EC-STORE-01 — Very few reviews in window (< 10)

| Field | Value |
| --- | --- |
| **Scenario** | New app listing or sparse week; only 3–8 reviews after filter. |
| **Severity** | High |
| **Impact** | Cannot form 5 themes or 3 meaningful quotes. |
| **Expected behavior** | If `review_count < min_reviews` (config, e.g. 15): abort with `Insufficient reviews for pulse`. Alternative: allow run with `k = min(5, viable)` and fewer quotes only if brief allows — **v1: abort** to avoid fabricated pulse. |
| **Owner** | `orchestrator.py`, `analysis/cluster.py` |
| **Phase** | 2 |
| **Test hint** | 5-review fixture |

---

### EC-STORE-02 — Very large volume (10k+ reviews)

| Field | Value |
| --- | --- |
| **Scenario** | Popular app; 12-week window has 50k reviews. |
| **Severity** | Medium |
| **Impact** | Memory/time for embeddings. |
| **Expected behavior** | Batch embed; cache vectors. Optional stratified sample for clustering (e.g. cap 5k) while keeping full DB for quote selection from cluster members. Record `sampled_for_cluster: true` in manifest. |
| **Owner** | `analysis/embed.py`, `analysis/cluster.py` |
| **Phase** | 2 |

---

### EC-STORE-03 — SQLite locked (concurrent ingest)

| Field | Value |
| --- | --- |
| **Scenario** | Two `reviewpulse ingest` processes run simultaneously. |
| **Severity** | Medium |
| **Expected behavior** | Retry on `database is locked` with backoff; or document single-writer constraint in README. |
| **Owner** | `store/sqlite.py` |
| **Phase** | 1 |

---

### EC-STORE-04 — Corrupt or missing `reviews.db`

| Field | Value |
| --- | --- |
| **Scenario** | DB file deleted mid-pipeline or corrupted. |
| **Severity** | High |
| **Expected behavior** | Fail at store read with actionable error: run `reviewpulse ingest` first. |
| **Owner** | `store/sqlite.py`, `orchestrator.py` |
| **Phase** | 1 |

---

## 6. Clustering & embeddings

### EC-CLUST-01 — Fewer than 3 viable clusters after merge

| Field | Value |
| --- | --- |
| **Scenario** | Sparse data or homogeneous reviews → only 1–2 clusters above size floor. |
| **Severity** | High |
| **Impact** | `themes_capped` gate expects `top_themes == 3`. |
| **Expected behavior** | If viable clusters < 3: abort with `Insufficient thematic diversity`. Do not duplicate cluster to fake 3 themes. |
| **Owner** | `analysis/cluster.py`, `themes_capped` gate |
| **Phase** | 2, 3 |

---

### EC-CLUST-02 — All reviews nearly identical ("great app" spam)

| Field | Value |
| --- | --- |
| **Scenario** | 90% of text is generic 5★ praise. |
| **Severity** | Medium |
| **Impact** | One giant cluster; weak action ideas. |
| **Expected behavior** | Still cap at 5 clusters; tiny clusters merge. Pulse reflects reality (one dominant theme). Optionally surface `low_diversity_warning` in manifest. |
| **Owner** | `analysis/cluster.py` |
| **Phase** | 2 |

---

### EC-CLUST-03 — Exactly 6 natural groupings

| Field | Value |
| --- | --- |
| **Scenario** | Data has 6 clear semantic groups. |
| **Severity** | Low |
| **Impact** | Brief caps at 5. |
| **Expected behavior** | Hard cap `k_max = 5`; merge smallest into nearest. Assert `len(themes) <= 5` in tests. |
| **Owner** | `analysis/cluster.py`, `themes_capped` gate |
| **Phase** | 2 |

---

### EC-CLUST-04 — Embedding model download fails (offline / air-gapped)

| Field | Value |
| --- | --- |
| **Scenario** | No network; `sentence-transformers` cannot fetch weights. |
| **Severity** | High |
| **Expected behavior** | Fall back to keyword taxonomy (`config/taxonomy.toml`). Log `clustering_mode: keyword_fallback`. |
| **Owner** | `analysis/cluster.py` |
| **Phase** | 2 |

---

### EC-CLUST-05 — Embedding cache stale after model upgrade

| Field | Value |
| --- | --- |
| **Scenario** | Model version changed in config; cached vectors are incompatible. |
| **Severity** | Medium |
| **Expected behavior** | Cache key includes `model_name` + `model_version`. Miss → re-embed. |
| **Owner** | `analysis/embed.py` |
| **Phase** | 2 |

---

### EC-CLUST-06 — Tie for 3rd and 4th theme rank

| Field | Value |
| --- | --- |
| **Scenario** | Themes ranked 3 and 4 have equal `size`. |
| **Severity** | Low |
| **Expected behavior** | Deterministic tie-break: higher `mean_rating` variance, then lexical `theme_id`. Same tie-break on every re-run. |
| **Owner** | `analysis/cluster.py`, `analysis/quotes.py` |
| **Phase** | 2, 3 |

---

### EC-CLUST-07 — Single review isolated cluster

| Field | Value |
| --- | --- |
| **Scenario** | Agglomerative clustering creates singleton cluster. |
| **Severity** | Low |
| **Expected behavior** | Tiny-cluster rule merges into nearest neighbour before labeling. |
| **Owner** | `analysis/cluster.py` |
| **Phase** | 2 |

---

## 7. Theme labeling (LangChain / LLM)

### EC-LABEL-01 — LLM returns invalid structured output

| Field | Value |
| --- | --- |
| **Scenario** | Model omits `summary` or returns empty `label`. |
| **Severity** | High |
| **Expected behavior** | Pydantic validation fails → one retry → abort with `LabelChainError`. |
| **Owner** | `chains/label_themes.py` |
| **Phase** | 2 |

---

### EC-LABEL-02 — LLM invents theme not in sample

| Field | Value |
| --- | --- |
| **Scenario** | Label says "Crypto trading" but sample only mentions KYC. |
| **Severity** | Medium |
| **Expected behavior** | Prompt constrains "describe only sample content." Optional post-check: flag if label keywords absent from sample TF-IDF. Manual review via manifest. |
| **Owner** | `chains/label_themes.py`, `prompts/label_themes.yaml` |
| **Phase** | 2 |

---

### EC-LABEL-03 — LLM API rate limit / timeout

| Field | Value |
| --- | --- |
| **Scenario** | 429 or 30s timeout mid-labeling (5 clusters). |
| **Severity** | High |
| **Expected behavior** | Exponential backoff per cluster; max 3 retries. Partial labels → abort run (no half-labeled pulse). |
| **Owner** | `chains/label_themes.py`, `llm/factory.py` |
| **Phase** | 2 |

---

### EC-LABEL-04 — LLM assigns size or rank in output

| Field | Value |
| --- | --- |
| **Scenario** | Model returns `"size": 500` in JSON despite instructions. |
| **Severity** | Medium |
| **Expected behavior** | `ThemeLabels` schema excludes `size`/`rank`, and they are not sent in the prompt either; orchestrator overwrites from DB aggregates only. |
| **Owner** | `analysis/label.py`, `models.py` |
| **Phase** | 2 |

---

### EC-LABEL-05 — Cluster sample is all 1★ or all 5★

| Field | Value |
| --- | --- |
| **Scenario** | Stratified sample cannot span ratings. |
| **Severity** | Low |
| **Expected behavior** | Use all available ratings in sample; note in manifest `sample_skewed: true`. |
| **Owner** | `analysis/label.py` |
| **Phase** | 2 |

---

## 8. Quote selection

### EC-QUOTE-01 — Fewer than 3 quotable reviews in top 3 themes

| Field | Value |
| --- | --- |
| **Scenario** | Themes exist but reviews are single-word ("Good", "Bad"). |
| **Severity** | High |
| **Impact** | `quotes_count` gate fails. |
| **Expected behavior** | Relax min length threshold down to config floor (e.g. 10 chars). If still < 3: abort after one reselect. |
| **Owner** | `analysis/quotes.py`, `quotes_count` gate |
| **Phase** | 3 |

---

### EC-QUOTE-02 — Best quote candidate is same review for two themes

| Field | Value |
| --- | --- |
| **Scenario** | Multi-topic review appears in two clusters. |
| **Severity** | Medium |
| **Expected behavior** | Enforce distinct `review_id` per quote; pick next-best candidate for second theme. |
| **Owner** | `analysis/quotes.py` |
| **Phase** | 3 |

---

### EC-QUOTE-03 — Quote substring check fails due to whitespace normalization

| Field | Value |
| --- | --- |
| **Scenario** | Export normalizes newlines; slice boundaries differ by `\n` vs space. |
| **Severity** | High |
| **Expected behavior** | Normalize whitespace consistently at ingest and quote slice time. `quotes_verbatim` must pass on stored `text_clean`. |
| **Owner** | `sources/normalize.py`, `analysis/quotes.py`, `quotes_verbatim` gate |
| **Phase** | 1, 3 |

---

### EC-QUOTE-04 — Only emoji review

| Field | Value |
| --- | --- |
| **Scenario** | Text is `"👎👎👎"`. |
| **Severity** | Low |
| **Expected behavior** | Allow as quote if length threshold met; emoji preserved verbatim. |
| **Owner** | `analysis/quotes.py` |
| **Phase** | 3 |

---

### EC-QUOTE-05 — Quote would push rendered note over 250 words

| Field | Value |
| --- | --- |
| **Scenario** | Three long quotes selected; header + themes already 180 words. |
| **Severity** | Medium |
| **Expected behavior** | Quote selector prefers shorter candidates when projected word count > 250. Final check: `word_count` gate. |
| **Owner** | `analysis/quotes.py`, `pulse/render.py`, `word_count` gate |
| **Phase** | 3 |

---

## 9. Pulse composition & rendering

### EC-COMP-01 — LLM prose alone exceeds 250 words

| Field | Value |
| --- | --- |
| **Scenario** | Model ignores brevity instruction. |
| **Severity** | Medium |
| **Expected behavior** | `word_count` gate fails → one retry with `max_words` tightened in prompt → abort if still over. |
| **Owner** | `chains/compose_pulse.py`, `word_count` gate |
| **Phase** | 3 |

---

### EC-COMP-02 — Action ideas not grounded in themes

| Field | Value |
| --- | --- |
| **Scenario** | LLM cites `theme_id` that does not exist or generic advice ("improve UX"). |
| **Severity** | High |
| **Expected behavior** | `actions_grounded` gate fails → one regeneration with explicit theme list → abort. |
| **Owner** | `pulse/validate.py` (`actions_grounded`) |
| **Phase** | 3 |

---

### EC-COMP-03 — Fewer than 3 action ideas returned

| Field | Value |
| --- | --- |
| **Scenario** | Structured output returns 2 actions. |
| **Severity** | High |
| **Expected behavior** | Pydantic `min_length=3` on schema → retry → abort. |
| **Owner** | `chains/compose_pulse.py` |
| **Phase** | 3 |

---

### EC-COMP-04 — Duplicate action ideas

| Field | Value |
| --- | --- |
| **Scenario** | Two actions are semantically identical. |
| **Severity** | Low |
| **Expected behavior** | v1: allow (no semantic dedup). Optional manifest warning `duplicate_actions_detected`. |
| **Owner** | `pulse/validate.py` |
| **Phase** | 3 |

---

### EC-COMP-05 — Special characters break Docs/Gmail payload

| Field | Value |
| --- | --- |
| **Scenario** | Quotes contain `"`, `<`, `&`, or unmatched Unicode surrogates. |
| **Severity** | Medium |
| **Expected behavior** | Renderer escapes for target format. Quotes remain verbatim in `text_clean` check — escaping is publish-layer only. |
| **Owner** | `pulse/render.py`, `publish/gdocs.py` |
| **Phase** | 3, 4 |

---

### EC-COMP-06 — Retry exhausted; gates still fail

| Field | Value |
| --- | --- |
| **Scenario** | Two compose attempts; still > 250 words or ungrounded actions. |
| **Severity** | Critical |
| **Expected behavior** | Abort run. Write partial debug artifacts to `runs/<id>/` (note draft + gate failures). **Do not publish.** |
| **Owner** | `orchestrator.py`, ADR-5 |
| **Phase** | 3 |

---

## 10. Validation gates (cross-cutting)

### EC-GATE-01 — `themes_capped` with exactly 5 themes but only 2 in top 3 slice

| Field | Value |
| --- | --- |
| **Scenario** | Logic bug: `top_themes` sliced wrong. |
| **Severity** | Critical |
| **Expected behavior** | Gate asserts `len(top_themes) == 3` when `review_count >= min_reviews`. |
| **Owner** | `pulse/validate.py` |
| **Phase** | 3 |

---

### EC-GATE-02 — `window_declared` mismatch

| Field | Value |
| --- | --- |
| **Scenario** | Manifest says 12 weeks; DB query used 8. |
| **Severity** | High |
| **Expected behavior** | Abort before publish. |
| **Owner** | `pulse/validate.py` (`window_declared`) |
| **Phase** | 3 |

---

### EC-GATE-03 — Gate passes but manifest not written

| Field | Value |
| --- | --- |
| **Scenario** | Crash between validate and manifest flush. |
| **Severity** | Medium |
| **Expected behavior** | On retry, full pipeline re-runs or resumes from checkpoint if implemented. v1: full re-run. |
| **Owner** | `orchestrator.py` |
| **Phase** | 3, 5 |

---

## 11. MCP publishing

### EC-MCP-01 — MCP server not installed / wrong command

| Field | Value |
| --- | --- |
| **Scenario** | `npx` package missing; stdio spawn fails. |
| **Severity** | Critical |
| **Expected behavior** | Fail at startup during `list_tools` — before LLM or ingest spend on publish path. Clear error with configured command. |
| **Owner** | `mcp/client.py` |
| **Phase** | 4 |

---

### EC-MCP-02 — Tool name mismatch

| Field | Value |
| --- | --- |
| **Scenario** | Config says `create_document`; server exposes `docs.create`. |
| **Severity** | Critical |
| **Expected behavior** | Startup verification fails with diff of available vs. expected tools. |
| **Owner** | `mcp/client.py` |
| **Phase** | 4 |

---

### EC-MCP-03 — Docs succeeds; Gmail fails

| Field | Value |
| --- | --- |
| **Scenario** | Network blip after doc created. |
| **Severity** | High |
| **Expected behavior** | Persist `doc_id` immediately. Retry reuses doc; does not create duplicate. Manifest not finalized until both succeed. |
| **Owner** | `orchestrator.py`, `publish/gmail.py` |
| **Phase** | 4 |

---

### EC-MCP-04 — Gmail succeeds; Docs fails (reverse partial failure)

| Field | Value |
| --- | --- |
| **Scenario** | Doc quota exceeded; draft created in prior attempt. |
| **Severity** | High |
| **Expected behavior** | No manifest completion. Retry creates/updates doc first, then idempotent draft update. |
| **Owner** | `orchestrator.py` |
| **Phase** | 4 |

---

### EC-MCP-05 — Google OAuth expired in MCP server

| Field | Value |
| --- | --- |
| **Scenario** | MCP returns auth error on tool call. |
| **Severity** | Critical |
| **Expected behavior** | Surface MCP server error verbatim; do not attempt OAuth in this repo. README: re-auth MCP server. |
| **Owner** | `mcp/client.py` |
| **Phase** | 4 |

---

### EC-MCP-06 — Rendered note too large for single Docs insert

| Field | Value |
| --- | --- |
| **Scenario** | MCP tool has payload size limit (unlikely at 250 words). |
| **Severity** | Low |
| **Expected behavior** | Chunk `insert_text` calls if needed; or link to `runs/<id>/note.md` in Gmail only. |
| **Owner** | `publish/gdocs.py` |
| **Phase** | 4 |

---

### EC-MCP-07 — Invalid recipient alias

| Field | Value |
| --- | --- |
| **Scenario** | `settings.toml` has malformed email for draft. |
| **Severity** | High |
| **Expected behavior** | Validate email format at config load. Gmail MCP error → abort with config hint. |
| **Owner** | `config` loader, `publish/gmail.py` |
| **Phase** | 4 |

---

### EC-MCP-08 — Dry-run accidentally disabled in CI

| Field | Value |
| --- | --- |
| **Scenario** | CI runs `reviewpulse run` without MCP secrets. |
| **Severity** | Medium |
| **Expected behavior** | CI uses `--dry-run` only. Live MCP tests marked `@pytest.mark.manual`. |
| **Owner** | `cli.py`, CI config |
| **Phase** | 5 |

---

## 12. Idempotency & re-runs

### EC-IDEM-01 — Re-run same ISO week

| Field | Value |
| --- | --- |
| **Scenario** | Operator runs `reviewpulse run` twice on Friday same week. |
| **Severity** | Medium |
| **Expected behavior** | Idempotency key `groww:2026-W35` matches existing doc/draft → update in place. |
| **Owner** | `publish/base.py` |
| **Phase** | 4 |

---

### EC-IDEM-02 — Re-run crosses ISO week boundary (Sunday → Monday)

| Field | Value |
| --- | --- |
| **Scenario** | Two runs 1 day apart fall in different ISO weeks. |
| **Severity** | Low |
| **Expected behavior** | New idempotency key → new doc/draft (by design). |
| **Owner** | `publish/base.py` |
| **Phase** | 4 |

---

### EC-IDEM-03 — Doc exists but was manually deleted in Google Drive

| Field | Value |
| --- | --- |
| **Scenario** | Lookup by title finds nothing; old `doc_id` stale in local state. |
| **Severity** | Medium |
| **Expected behavior** | Create new doc; log `doc_recreated: true`. Update manifest with new `doc_id`. |
| **Owner** | `publish/gdocs.py` |
| **Phase** | 4 |

---

### EC-IDEM-04 — Partial manifest from crashed prior run

| Field | Value |
| --- | --- |
| **Scenario** | `publish.json` has `doc_id` but no `draft_id`. |
| **Severity** | Medium |
| **Expected behavior** | Resume: skip doc create, only create/update draft. |
| **Owner** | `orchestrator.py` |
| **Phase** | 4 |

---

## 13. Configuration & environment

### EC-CFG-01 — Missing `GROQ_API_KEY`

| Field | Value |
| --- | --- |
| **Scenario** | `.env` not created. |
| **Severity** | Critical |
| **Expected behavior** | Fail at LLM factory init before ingest if full run; cluster-only commands fail at label stage with clear message. |
| **Owner** | `llm/factory.py` |
| **Phase** | 0, 2 |

---

### EC-CFG-02 — Missing `config/settings.toml`

| Field | Value |
| --- | --- |
| **Scenario** | Only example file committed. |
| **Severity** | High |
| **Expected behavior** | Fail at startup: copy `settings.example.toml`. |
| **Owner** | `cli.py` |
| **Phase** | 0 |

---

### EC-CFG-03 — `window-weeks` set to 0 or negative

| Field | Value |
| --- | --- |
| **Scenario** | `reviewpulse run --window-weeks 0`. |
| **Severity** | Medium |
| **Expected behavior** | CLI validation reject; require 1–52. |
| **Owner** | `cli.py` |
| **Phase** | 1 |

---

### EC-CFG-04 — `k_max` overridden above 5 in config

| Field | Value |
| --- | --- |
| **Scenario** | User sets `k_max = 10`. |
| **Severity** | High |
| **Expected behavior** | Clamp to 5 at load time; warn — brief constraint D4. |
| **Owner** | config loader, `analysis/cluster.py` |
| **Phase** | 2 |

---

## 14. Operational & lifecycle

### EC-OPS-01 — Run interrupted (SIGINT / laptop sleep)

| Field | Value |
| --- | --- |
| **Scenario** | User Ctrl+C during embedding. |
| **Severity** | Medium |
| **Expected behavior** | Clean shutdown message; `runs/<id>/` may be partial. No publish on incomplete validate. |
| **Owner** | `orchestrator.py` |
| **Phase** | All |

---

### EC-OPS-02 — Disk full writing `runs/` or SQLite

| Field | Value |
| --- | --- |
| **Scenario** | `OSError: No space left on device`. |
| **Severity** | High |
| **Expected behavior** | Propagate with context; do not claim success. |
| **Owner** | `store/sqlite.py`, `orchestrator.py` |
| **Phase** | All |

---

### EC-OPS-03 — Clock skew affects window filter

| Field | Value |
| --- | --- |
| **Scenario** | System clock wrong; recent reviews excluded. |
| **Severity** | Medium |
| **Expected behavior** | Use UTC consistently; manifest logs `run_timestamp`. |
| **Owner** | `sources/normalize.py` |
| **Phase** | 1 |

---

### EC-OPS-04 — Weekly cron runs before new export lands

| Field | Value |
| --- | --- |
| **Scenario** | Cron Monday 9am; export updated Monday 10am. |
| **Severity** | Medium |
| **Expected behavior** | Uses stale export; manifest checksum unchanged — ops should alert on `source_checksum` match week-over-week. Document in README. |
| **Owner** | `orchestrator.py`, ops |
| **Phase** | 5 |

---

## 15. Edge-case → validation gate matrix

| Gate | Edge cases primarily caught |
| --- | --- |
| `themes_capped` | EC-CLUST-01, EC-CLUST-03, EC-GATE-01, EC-CFG-04 |
| `quotes_verbatim` | EC-QUOTE-03, EC-PII-09 |
| `quotes_count` | EC-QUOTE-01, EC-QUOTE-02 |
| `actions_grounded` | EC-COMP-02, EC-COMP-03 |
| `word_count` | EC-COMP-01, EC-QUOTE-05 |
| `no_pii` | EC-PII-01–07, EC-PII-08 |
| `window_declared` | EC-ING-02, EC-GATE-02 |

---

## 16. Priority test fixtures to create

| Fixture file | Edge cases covered |
| --- | --- |
| `tests/fixtures/empty_export.csv` | EC-ING-01 |
| `tests/fixtures/short_window_export.csv` | EC-ING-02 |
| `tests/fixtures/pii_reviews.json` | EC-PII-01–06, EC-PII-08 |
| `tests/fixtures/sparse_reviews.json` | EC-STORE-01, EC-CLUST-01 |
| `tests/fixtures/duplicate_rows.csv` | EC-ING-06 |
| `tests/fixtures/hindi_reviews.csv` | EC-NORM-05 |
| `tests/fixtures/generic_spam_reviews.json` | EC-CLUST-02 |
| `tests/fixtures/short_quote_reviews.json` | EC-QUOTE-01 |
| `tests/golden/frozen_pulse_input.json` | EC-COMP-01–06 (golden diff) |
| `tests/contract/fake_mcp_server.py` | EC-MCP-01–04, EC-IDEM-01 |

---

## 17. Scenarios explicitly out of scope (v1)

Do not implement handling unless scope changes:

| Scenario | Reason |
| --- | --- |
| App Store ingest | ADR-7 / deferred |
| Live Play Store scraping | D6 — public export only |
| Sending email (not draft) | Brief requires draft only |
| Auto-translating quotes to English | Alters verbatim requirement |
| Real-time streaming reviews | Batch weekly only |
| Multi-app / multi-package pulses | Single Groww package |
| LangGraph autonomous tool loops | ADR-6 — linear pipeline |

---

## 18. Quick reference: abort vs. warn vs. proceed

| Outcome | When |
| --- | --- |
| **Abort (no publish)** | Empty data, PII gate fail, quote gate fail, insufficient reviews/clusters, MCP auth failure, validation retry exhausted |
| **Warn and proceed** | Export < 8 weeks, low thematic diversity, encoding fallback, stale export checksum, skewed label sample |
| **Proceed silently** | Dedup on re-import, tiny cluster merge, rating clamp, whitespace normalize, cache hit |
