"""Facts Agent.

Calls Project 1 ``retrieve_for_question`` on text that has already passed
the compliance gate. It does not call Project 1 ``ask``, and it does not
answer from general knowledge.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from supportdesk.compliance import ComplianceInspection, ComplianceSession
from supportdesk.contracts import FactClaim, FactsResult
from supportdesk.enums import ComplianceDecision, Coverage, FactsStatus
from supportdesk.ids import new_execution_id
from supportdesk.privacy import contains_pii

_ALLOWED_HOSTS = frozenset({"groww.in", "www.groww.in"})
_MAX_EVIDENCE = 500
_MAX_CLAIM = 280
_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "for",
        "to",
        "is",
        "what",
        "on",
        "in",
        "and",
        "this",
        "that",
        "fund",
        "scheme",
    }
)
_KNOWN_STATUSES = frozenset({"hit", "not_found", "clarify", "empty_index"})


class FactsAgentOutput(BaseModel):
    """Facts result plus the compliance inspection that gated retrieval."""

    model_config = ConfigDict(extra="forbid")

    result: FactsResult
    inspection: ComplianceInspection


@dataclass(frozen=True)
class RetrievalBundle:
    """Shape copied from Project 1 ``RetrievalResult``. Chunks are the only evidence."""

    status: str
    chunks: list[dict]
    lane: str = ""
    scheme_id: str | None = None
    fact_type: str | None = None
    resolution_status: str | None = None


Retriever = Callable[[str], RetrievalBundle]


class Project1Unavailable(RuntimeError):
    """The configured Project 1 checkout cannot answer a retrieval call."""


def default_project1_root() -> Path | None:
    """Sibling ``mutual-fund-faq-assistant`` checkout, unless the env var is set."""
    configured = os.environ.get("SUPPORTDESK_PROJECT1_ROOT", "").strip()
    if configured:
        return Path(configured)
    sibling = Path(__file__).resolve().parents[2].parent / "mutual-fund-faq-assistant"
    if _is_project1(sibling):
        return sibling
    return None


def answer_facts(
    message: str,
    *,
    session: ComplianceSession,
    case_id: str,
    execution_id: str | None = None,
    project1_root: Path | None = None,
    retriever: Retriever | None = None,
) -> FactsAgentOutput:
    """Inspect ``message``, then retrieve only the redacted text.

    A blocked or refused message never reaches the retriever.
    """
    facts_execution = execution_id or new_execution_id()
    inspection = session.inspect(message, case_id=case_id)
    decision = inspection.result.decision
    if decision in {ComplianceDecision.BLOCK, ComplianceDecision.REFUSE}:
        return _output(
            inspection,
            _uncovered(
                facts_execution,
                FactsStatus.ERROR,
                [inspection.result.safe_handling],
            ),
        )
    redacted = inspection.redacted_text
    if contains_pii(redacted):
        return _output(
            inspection,
            _uncovered(
                facts_execution,
                FactsStatus.ERROR,
                ["redacted text still matched a PII pattern; retrieval was not run"],
            ),
        )
    try:
        bundle = _retrieve(redacted, project1_root=project1_root, retriever=retriever)
    except Project1Unavailable as exc:
        return _output(inspection, _uncovered(facts_execution, FactsStatus.ERROR, [str(exc)]))
    except Exception as exc:
        return _output(
            inspection,
            _uncovered(
                facts_execution,
                FactsStatus.ERROR,
                [f"retrieval failed: {type(exc).__name__}"],
            ),
        )
    return _output(inspection, _from_bundle(bundle, redacted, facts_execution))


def _retrieve(
    question: str,
    *,
    project1_root: Path | None,
    retriever: Retriever | None,
) -> RetrievalBundle:
    if retriever is not None:
        return retriever(question)
    root = project1_root if project1_root is not None else default_project1_root()
    if root is None:
        raise Project1Unavailable("Project 1 retrieval root is not available")
    if not _is_project1(root):
        raise Project1Unavailable("Project 1 root is not a retrieval checkout")
    return _project1_retriever(root)(question)


def _project1_retriever(root: Path) -> Retriever:
    root_str = str(root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    retrieve_mod = importlib.import_module("app.pipeline.retrieve")
    router_mod = importlib.import_module("app.pipeline.router")
    loaded = Path(getattr(retrieve_mod, "__file__", "")).resolve()
    if root.resolve() not in loaded.parents:
        raise Project1Unavailable("loaded retrieve module is not under the Project 1 root")

    def retrieve(question: str) -> RetrievalBundle:
        index = retrieve_mod.load_index(root=root)
        if not index:
            return RetrievalBundle(status="empty_index", chunks=[])
        intent = router_mod.route(question)
        result = retrieve_mod.retrieve_for_question(
            question,
            intent=intent,
            root=root,
            chunks=index,
        )
        resolution = getattr(result, "resolution", None)
        return RetrievalBundle(
            status=str(result.status),
            chunks=list(result.chunks or []),
            lane=str(result.lane or ""),
            scheme_id=result.scheme_id,
            fact_type=result.fact_type,
            resolution_status=getattr(resolution, "status", None),
        )

    return retrieve


def _from_bundle(bundle: RetrievalBundle, question: str, execution_id: str) -> FactsResult:
    searched = _searched_urls(bundle.chunks)
    context = _context(bundle)
    if bundle.status not in _KNOWN_STATUSES:
        return _uncovered(
            execution_id,
            FactsStatus.ERROR,
            [f"unexpected retrieval status {bundle.status!r}", *context],
            searched,
        )
    if bundle.status == "empty_index":
        return _uncovered(
            execution_id,
            FactsStatus.NOT_COVERED,
            ["the Project 1 index is empty", *context],
            searched,
        )
    if bundle.status == "clarify":
        return _uncovered(
            execution_id,
            FactsStatus.NOT_COVERED,
            ["scheme was not resolved", *context],
            searched,
        )
    if bundle.status == "not_found":
        return _uncovered(
            execution_id,
            FactsStatus.NOT_COVERED,
            ["no retrieved chunk supports an answer", *context],
            searched,
        )

    claim = _first_claim(bundle.chunks, question)
    if claim is None:
        return _uncovered(
            execution_id,
            FactsStatus.NOT_COVERED,
            ["retrieved chunk had no citable passage or approved URL", *context],
            searched,
        )
    limitations = [item for item in context if item]
    if claim.last_checked is None:
        limitations.append("last_checked unavailable")
    return FactsResult(
        status=FactsStatus.SUPPORTED,
        coverage=Coverage.COVERED,
        answer_facts=[claim],
        searched_sources=searched,
        limitations=limitations,
        execution_id=execution_id,
    )


def _first_claim(chunks: list[dict], question: str) -> FactClaim | None:
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        claim = _claim_from_chunk(chunk, question)
        if claim is not None:
            return claim
    return None


def _claim_from_chunk(chunk: dict, question: str) -> FactClaim | None:
    url = str(chunk.get("source_url") or "")
    if not _approved_url(url):
        return None
    title = chunk.get("source_title") or chunk.get("scheme_name") or chunk.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    text = chunk.get("text")
    if not isinstance(text, str):
        return None
    evidence = _passage(text, question)
    if evidence is None or evidence not in text:
        return None
    claim = evidence if len(evidence) <= _MAX_CLAIM else _prefix(evidence, _MAX_CLAIM)
    if not claim or claim not in evidence:
        return None
    return FactClaim(
        claim=claim,
        source_title=title.strip(),
        source_url=url,
        evidence=evidence,
        last_checked=_checked_on(chunk.get("retrieved_on")),
    )


def _passage(text: str, question: str) -> str | None:
    spans = [(match.group(0).strip(), match.group(0)) for match in _SENTENCE.finditer(text)]
    spans = [(stripped, raw) for stripped, raw in spans if stripped]
    if not spans:
        snippet = text.strip()
        if not snippet:
            return None
        clipped = snippet if len(snippet) <= _MAX_EVIDENCE else _prefix(snippet, _MAX_EVIDENCE)
        return clipped if clipped and clipped in text else None
    wanted = _tokens(question)
    best = max(spans, key=lambda item: len(wanted & _tokens(item[0])))
    snippet = best[0]
    if len(snippet) > _MAX_EVIDENCE:
        snippet = _prefix(snippet, _MAX_EVIDENCE)
    return snippet if snippet and snippet in text else None


def _prefix(text: str, limit: int) -> str:
    clipped = text[:limit]
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.strip()


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN.findall(text.casefold()) if token not in _STOP}


def _checked_on(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _approved_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc.lower() in _ALLOWED_HOSTS


def _searched_urls(chunks: list[dict]) -> list[str]:
    seen: list[str] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        url = str(chunk.get("source_url") or "")
        if url.startswith("https://") and url not in seen:
            seen.append(url)
    return seen


def _context(bundle: RetrievalBundle) -> list[str]:
    parts = [f"retrieval status {bundle.status}"]
    if bundle.lane:
        parts.append(f"lane {bundle.lane}")
    if bundle.fact_type:
        parts.append(f"fact_type {bundle.fact_type}")
    if bundle.scheme_id:
        parts.append(f"scheme_id {bundle.scheme_id}")
    if bundle.resolution_status:
        parts.append(f"scheme_resolution {bundle.resolution_status}")
    return parts


def _uncovered(
    execution_id: str,
    status: FactsStatus,
    limitations: list[str],
    searched: list[str] | None = None,
) -> FactsResult:
    return FactsResult(
        status=status,
        coverage=Coverage.NOT_COVERED,
        answer_facts=[],
        searched_sources=searched or [],
        limitations=[item for item in limitations if item],
        execution_id=execution_id,
    )


def _output(inspection: ComplianceInspection, result: FactsResult) -> FactsAgentOutput:
    return FactsAgentOutput(result=result, inspection=inspection)


def _is_project1(root: Path) -> bool:
    return (root / "app" / "pipeline" / "retrieve.py").is_file()
