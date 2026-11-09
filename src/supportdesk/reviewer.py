"""Deterministic review of a drafted reply and one draft-only rework.

The reviewer does not retrieve, read reviews, or call MCP. The customer
message is not available here, so a failed check corrects the draft from
the stored agent results. A second failure ends in ``BLOCKED``.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from supportdesk.advice import requests_advice, requests_performance
from supportdesk.contracts import (
    ComplianceResult,
    FactClaim,
    FactsResult,
    OrchestratorResult,
    PatternResult,
    ReviewerFinding,
    ReviewerResult,
    WorkflowRun,
    count_sentences,
)
from supportdesk.enums import (
    ComplianceDecision,
    Coverage,
    FactsStatus,
    PatternSignal,
    ReviewerDecision,
    ReviewerFindingCode,
    WorkflowState,
)
from supportdesk.orchestrate import (
    OrchestrationOutcome,
    draft_from_agents,
    is_template_reply,
)
from supportdesk.privacy import contains_pii
from supportdesk.workflow import transition

_ALLOWED_HOSTS = frozenset({"groww.in", "www.groww.in"})
_POSITIVE = frozenset({PatternSignal.RECURRING, PatternSignal.RISING})
_URL = re.compile(r"https://[^\s,;)>\]]+")
_DATE = re.compile(r"last checked (\d{4}-\d{2}-\d{2})")
_REPLY_ADVICE = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\byou should\b",
        r"\bi recommend\b",
        r"\bwe recommend\b",
        r"\brecommend (?:buying|selling|holding|you)\b",
        r"\b(?:buy|sell|hold|redeem) (?:this|the|that) (?:fund|scheme)\b",
        r"\bsuitable for you\b",
        r"\bright for you\b",
        r"\bgood for you\b",
    )
)
_REPLY_PERFORMANCE = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bguaranteed?\b",
        r"\bpredict(?:ed|ion)?\b",
        r"\bexpected returns?\b",
        r"\bwill (?:beat|outperform)\b",
        r"\bcagr\b",
        r"\byou will (?:earn|make|get)\b",
    )
)
_DENIAL = re.compile(
    r"\bno (?:matching )?reviews\b|\bno complaints\b|\bone-off\b|\bnot a pattern\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-z]{4,}")
_WORD_STOP = frozenset(
    {
        "this",
        "that",
        "with",
        "from",
        "your",
        "have",
        "page",
        "listed",
        "source",
        "last",
        "checked",
        "thanks",
        "contacting",
        "approved",
        "sources",
        "couldn",
        "confirm",
        "provide",
        "investment",
        "recommendation",
        "performance",
        "expectation",
        "published",
        "product",
        "information",
        "official",
        "groww",
        "pages",
    }
)
_PII_LIMITATION = "withheld during review because it matched a PII pattern"


class ReviewedCase(BaseModel):
    """Draft after at most one rework. ``result`` is absent when it cannot be stored."""

    model_config = ConfigDict(extra="forbid")

    run: WorkflowRun
    result: OrchestratorResult | None = None
    states: list[WorkflowState]
    reviews: list[ReviewerResult]


def content_has_pii(result: OrchestratorResult) -> bool:
    """True when reply, note, or agent prose matches a PII pattern.

    Case, execution, and run ids are excluded. A hex id can contain ten
    digits and would otherwise look like a phone number.
    """
    return contains_pii(_content_text(result))


def _content_text(result: OrchestratorResult) -> str:
    note = result.routing_note
    parts = [
        result.reply.text,
        note.team,
        note.reason,
        note.next_action,
        note.disagreement or "",
        *note.limitations,
        *note.citation_refs,
        *note.compliance_flags,
        *result.disagreements,
        *result.facts.limitations,
        *result.facts.searched_sources,
        result.pattern.method,
        *result.pattern.limitations,
        *result.pattern.matched_themes,
        result.compliance.safe_handling,
        *result.compliance.flags,
    ]
    for claim in result.facts.answer_facts:
        parts.extend([claim.claim, claim.evidence, claim.source_title, claim.source_url])
    for item in result.pattern.evidence:
        if item.snippet:
            parts.append(item.snippet)
    return "\n".join(parts)


def exceeds_sentence_limit(text: str) -> bool:
    """The customer reply may contain at most three sentences."""
    return count_sentences(text) > 3


def review(result: OrchestratorResult, *, rework_attempt: int = 0) -> ReviewerResult:
    """Return every hard-fail finding for this draft. A pass has no findings."""
    findings = [
        *_sentence_findings(result),
        *_pii_findings(result),
        *_advice_findings(result),
        *_performance_findings(result),
        *_citation_findings(result),
        *_disagreement_findings(result),
    ]
    if findings:
        return ReviewerResult(
            decision=ReviewerDecision.FAIL,
            findings=findings,
            rework_attempt=rework_attempt,
        )
    return ReviewerResult(decision=ReviewerDecision.PASS, rework_attempt=rework_attempt)


def revise(result: OrchestratorResult) -> OrchestratorResult:
    """Replace the reply and note from the stored agent results."""
    facts = _clean_facts(result.facts)
    pattern = _clean_pattern(result.pattern)
    compliance = _clean_compliance(result.compliance)
    reply, note, disagreements, withheld = draft_from_agents(facts, pattern, compliance)
    if withheld or contains_pii(reply):
        reply = (
            "I can't provide an investment recommendation or a performance expectation. "
            "Published product information is on the official Groww pages."
            if compliance.decision is ComplianceDecision.REFUSE
            else (
                "Thanks for contacting us. "
                "I don't have an answer for that in the approved sources."
            )
        )
        note = note.model_copy(update={"citation_refs": [], "disagreement": None})
        disagreements = []
    return OrchestratorResult(
        case_id=result.case_id,
        reply=_reply(reply),
        routing_note=note,
        facts=facts,
        pattern=pattern,
        compliance=compliance,
        disagreements=disagreements,
    )


def review_case(outcome: OrchestrationOutcome) -> ReviewedCase:
    """Review a drafted run. One repairable failure is redrafted. The next failure blocks."""
    states = list(outcome.states)
    run = outcome.run
    result = outcome.result
    if run.state is not WorkflowState.DRAFTED or result is None:
        finding = _finding(
            ReviewerFindingCode.ILLEGAL_TRANSITION,
            "Review requires a drafted reply.",
            repairable=False,
        )
        return ReviewedCase(
            run=run,
            result=_store(result),
            states=states,
            reviews=[_failed([finding], 0)],
        )
    if result.case_id != run.case_id:
        run = transition(run, WorkflowState.REVIEWING)
        states.append(WorkflowState.REVIEWING)
        run = transition(run, WorkflowState.BLOCKED)
        states.append(WorkflowState.BLOCKED)
        finding = _finding(
            ReviewerFindingCode.ILLEGAL_TRANSITION,
            "The reply case id does not match the run.",
            repairable=False,
        )
        return ReviewedCase(run=run, result=None, states=states, reviews=[_failed([finding], 0)])

    run = transition(run, WorkflowState.REVIEWING)
    states.append(WorkflowState.REVIEWING)
    first = review(result, rework_attempt=0)
    if first.decision is ReviewerDecision.PASS:
        run = transition(run, WorkflowState.PENDING_APPROVAL)
        states.append(WorkflowState.PENDING_APPROVAL)
        return ReviewedCase(run=run, result=result, states=states, reviews=[first])
    if any(not item.repairable for item in first.findings):
        run = transition(run, WorkflowState.BLOCKED)
        states.append(WorkflowState.BLOCKED)
        return ReviewedCase(run=run, result=_store(result), states=states, reviews=[first])

    run = transition(run, WorkflowState.REWORK_ONCE)
    states.append(WorkflowState.REWORK_ONCE)
    revised = revise(result)
    run = transition(run, WorkflowState.REVIEWING)
    states.append(WorkflowState.REVIEWING)
    if content_has_pii(revised):
        second = _failed(
            [
                _finding(
                    ReviewerFindingCode.PII,
                    "Rework output still matched a PII pattern.",
                    repairable=False,
                )
            ],
            1,
        )
        stored = None
    else:
        second = review(revised, rework_attempt=1)
        stored = revised if second.decision is ReviewerDecision.PASS else _store(revised)
    if second.decision is ReviewerDecision.PASS:
        run = transition(run, WorkflowState.PENDING_APPROVAL)
        states.append(WorkflowState.PENDING_APPROVAL)
    else:
        run = transition(run, WorkflowState.BLOCKED)
        states.append(WorkflowState.BLOCKED)
    return ReviewedCase(run=run, result=stored, states=states, reviews=[first, second])


def _sentence_findings(result: OrchestratorResult) -> list[ReviewerFinding]:
    if exceeds_sentence_limit(result.reply.text):
        return [
            _finding(
                ReviewerFindingCode.SENTENCE_LIMIT,
                "Customer reply exceeds three sentences. Correct the draft.",
            )
        ]
    return []


def _pii_findings(result: OrchestratorResult) -> list[ReviewerFinding]:
    if content_has_pii(result):
        return [
            _finding(
                ReviewerFindingCode.PII,
                "PII remains in the reply, routing note, or stored agent text. Correct the draft.",
            )
        ]
    return []


def _advice_findings(result: OrchestratorResult) -> list[ReviewerFinding]:
    text = result.reply.text
    if requests_advice(text) or any(pattern.search(text) for pattern in _REPLY_ADVICE):
        return [
            _finding(
                ReviewerFindingCode.INVESTMENT_ADVICE,
                "Reply contains an investment recommendation. Correct the draft.",
            )
        ]
    return []


def _performance_findings(result: OrchestratorResult) -> list[ReviewerFinding]:
    text = result.reply.text
    if requests_performance(text) or any(pattern.search(text) for pattern in _REPLY_PERFORMANCE):
        return [
            _finding(
                ReviewerFindingCode.PERFORMANCE_CLAIM,
                "Reply contains a performance or return claim. Correct the draft.",
            )
        ]
    return []


def _citation_findings(result: OrchestratorResult) -> list[ReviewerFinding]:
    reply = result.reply.text
    findings: list[ReviewerFinding] = []
    urls = _URL.findall(reply)
    if re.search(r"\bhttp://", reply):
        findings.append(
            _finding(
                ReviewerFindingCode.CITATION_DOMAIN,
                "Citation is not an https URL on an approved Groww host. Correct the draft.",
            )
        )
    claim = _supported_claim(result.facts)
    retrieved = set(result.facts.searched_sources)
    if claim is not None:
        retrieved.add(claim.source_url)
    for url in [*urls, *result.routing_note.citation_refs]:
        if not _approved_url(url):
            findings.append(
                _finding(
                    ReviewerFindingCode.CITATION_DOMAIN,
                    "Citation host is outside the approved Groww list. Correct the draft.",
                )
            )
        if url not in retrieved:
            findings.append(
                _finding(
                    ReviewerFindingCode.CITATION_NOT_RETRIEVED,
                    "Citation was not in the Facts Agent source list. Correct the draft.",
                )
            )
    if is_template_reply(reply):
        if urls:
            findings.append(
                _finding(
                    ReviewerFindingCode.UNSUPPORTED_CLAIM,
                    "Reply points at a source the Facts Agent did not support. Correct the draft.",
                )
            )
        return _unique(findings)
    if claim is None:
        if urls or not _is_non_claim(reply):
            findings.append(
                _finding(
                    ReviewerFindingCode.UNSUPPORTED_CLAIM,
                    "Reply states a fact that is not in the Facts Agent evidence. Correct the draft.",
                )
            )
        return _unique(findings)
    if claim.claim.strip() not in claim.evidence:
        findings.append(
            _finding(
                ReviewerFindingCode.EVIDENCE_MISMATCH,
                "Facts evidence does not contain the claim. Correct the draft.",
            )
        )
    factual = reply.split(" Source:", 1)[0].strip()
    if factual not in claim.evidence and factual.rstrip(".!?") not in claim.evidence:
        findings.append(
            _finding(
                ReviewerFindingCode.EVIDENCE_MISMATCH,
                "Reply is not supported by the Facts Agent evidence. Correct the draft.",
            )
        )
    elif _outside_evidence(factual, claim):
        findings.append(
            _finding(
                ReviewerFindingCode.EVIDENCE_MISMATCH,
                "Reply names a product that is not in the cited evidence. Correct the draft.",
            )
        )
    if claim.source_url not in reply:
        findings.append(
            _finding(
                ReviewerFindingCode.MISSING_CITATION,
                "Factual reply is missing the retrieved citation. Correct the draft.",
            )
        )
    elif urls and claim.source_url not in result.routing_note.citation_refs:
        findings.append(
            _finding(
                ReviewerFindingCode.MISSING_CITATION,
                "Routing note is missing the citation used in the reply. Correct the draft.",
            )
        )
    stamped = _DATE.search(reply)
    if claim.last_checked is None and stamped:
        findings.append(
            _finding(
                ReviewerFindingCode.EVIDENCE_MISMATCH,
                "Reply states a last-checked date the source metadata does not have. Correct the draft.",
            )
        )
    elif claim.last_checked is not None and (
        stamped is None or stamped.group(1) != claim.last_checked.isoformat()
    ):
        findings.append(
            _finding(
                ReviewerFindingCode.MISSING_CITATION,
                "Factual reply is missing the source last-checked date. Correct the draft.",
            )
        )
    return _unique(findings)


def _disagreement_findings(result: OrchestratorResult) -> list[ReviewerFinding]:
    findings: list[ReviewerFinding] = []
    facts = result.facts
    pattern = result.pattern
    note = result.routing_note
    if note.pattern_signal is not pattern.signal or note.matching_count != pattern.matching_count:
        findings.append(_hidden("Routing note does not match the Pattern Agent signal or count."))
    if note.facts_coverage is not facts.coverage:
        findings.append(_hidden("Routing note does not match the Facts Agent coverage."))
    if note.analysis_window != pattern.analysis_window:
        findings.append(_hidden("Routing note does not match the Pattern Agent analysis window."))
    for item in [*facts.limitations, *pattern.limitations]:
        if item not in note.limitations:
            findings.append(_hidden("Routing note drops an agent limitation."))
            break
    if note.disagreement and note.disagreement not in result.disagreements:
        findings.append(_hidden("Routing note disagreement is not on the orchestrator result."))
    covered_pattern = facts.coverage is Coverage.COVERED and pattern.signal in _POSITIVE
    if covered_pattern:
        text = note.disagreement or ""
        if pattern.signal.value not in text or not result.disagreements:
            findings.append(_hidden("A covered fact and a pattern signal are not both recorded."))
    if pattern.signal in _POSITIVE and _DENIAL.search(result.reply.text):
        findings.append(_hidden("Reply denies a pattern signal the Pattern Agent reported."))
    claim = _supported_claim(facts)
    if (
        facts.status is FactsStatus.SUPPORTED
        and claim is not None
        and ("don't have an answer" in result.reply.text or "couldn't confirm" in result.reply.text)
        and not any("not copied" in item or "withheld" in item for item in note.limitations)
    ):
        findings.append(_hidden("Reply says the fact is unavailable without recording why."))
    return _unique(findings)


def _clean_facts(facts: FactsResult) -> FactsResult:
    limitations = _safe_lines(facts.limitations)
    if facts.status is not FactsStatus.SUPPORTED:
        return facts.model_copy(update={"answer_facts": [], "limitations": limitations})
    kept = [claim for claim in facts.answer_facts if _claim_ok(claim, facts.searched_sources)]
    if kept:
        return facts.model_copy(update={"answer_facts": kept[:1], "limitations": limitations})
    limitations = [*limitations, "a fact claim was withheld during review"]
    return facts.model_copy(
        update={
            "status": FactsStatus.NOT_COVERED,
            "coverage": Coverage.NOT_COVERED,
            "answer_facts": [],
            "limitations": limitations,
        }
    )


def _clean_pattern(pattern: PatternResult) -> PatternResult:
    evidence = []
    for item in pattern.evidence:
        if item.snippet and contains_pii(item.snippet):
            evidence.append(item.model_copy(update={"snippet": None}))
        else:
            evidence.append(item)
    themes = [item if not contains_pii(item) else "theme withheld" for item in pattern.matched_themes]
    method = pattern.method if not contains_pii(pattern.method) else "Pattern matching did not run."
    return pattern.model_copy(
        update={
            "evidence": evidence,
            "matched_themes": themes,
            "method": method,
            "limitations": _safe_lines(pattern.limitations),
        }
    )


def _clean_compliance(compliance: ComplianceResult) -> ComplianceResult:
    handling = compliance.safe_handling
    if contains_pii(handling):
        handling = "Compliance text was withheld because it matched a PII pattern."
    flags = [item for item in compliance.flags if not contains_pii(item)]
    return compliance.model_copy(update={"safe_handling": handling, "flags": flags})


def _claim_ok(claim: FactClaim, searched: list[str]) -> bool:
    if contains_pii(claim.claim) or contains_pii(claim.evidence) or contains_pii(claim.source_title):
        return False
    if not _approved_url(claim.source_url):
        return False
    if searched and claim.source_url not in searched:
        return False
    sentence = claim.claim.strip()
    if count_sentences(sentence) > 1:
        return False
    return sentence in claim.evidence or sentence.rstrip(".!?") in claim.evidence


def _supported_claim(facts: FactsResult) -> FactClaim | None:
    if facts.status is not FactsStatus.SUPPORTED or not facts.answer_facts:
        return None
    return facts.answer_facts[0]


def _approved_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc.lower() in _ALLOWED_HOSTS


def _outside_evidence(factual: str, claim: FactClaim) -> bool:
    hay = f"{claim.evidence} {claim.source_title} {claim.source_url}".casefold()
    for word in _WORD.findall(factual.casefold()):
        if word in _WORD_STOP:
            continue
        if word not in hay:
            return True
    return False


def _is_non_claim(reply: str) -> bool:
    return is_template_reply(reply)


def _safe_lines(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for line in lines:
        if contains_pii(line):
            if _PII_LIMITATION not in cleaned:
                cleaned.append(_PII_LIMITATION)
        else:
            cleaned.append(line)
    return cleaned


def _hidden(message: str) -> ReviewerFinding:
    return _finding(ReviewerFindingCode.HIDDEN_DISAGREEMENT, f"{message} Correct the draft.")


def _finding(code: ReviewerFindingCode, message: str, *, repairable: bool = True) -> ReviewerFinding:
    return ReviewerFinding(code=code, message=message, repairable=repairable)


def _failed(findings: list[ReviewerFinding], attempt: int) -> ReviewerResult:
    return ReviewerResult(
        decision=ReviewerDecision.FAIL,
        findings=findings,
        rework_attempt=attempt,
    )


def _unique(findings: list[ReviewerFinding]) -> list[ReviewerFinding]:
    seen: set[tuple[str, str]] = set()
    ordered: list[ReviewerFinding] = []
    for finding in findings:
        key = (finding.code.value, finding.message)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(finding)
    return ordered


def _reply(text: str):
    from supportdesk.contracts import CustomerReply

    return CustomerReply(text=text, sentence_count=count_sentences(text))


def _store(result: OrchestratorResult | None) -> OrchestratorResult | None:
    if result is None:
        return None
    if content_has_pii(result):
        return None
    return result
