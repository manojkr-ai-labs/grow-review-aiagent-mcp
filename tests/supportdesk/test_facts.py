"""Facts Agent: Project 1 retrieval mapping, with fakes and the local corpus."""

from __future__ import annotations

from pathlib import Path

import pytest

from supportdesk.compliance import ComplianceSession
from supportdesk.enums import ComplianceDecision, Coverage, FactsStatus
from supportdesk.facts import RetrievalBundle, answer_facts, default_project1_root
from supportdesk.ids import new_case_id, new_execution_id

PROJECT1 = Path(__file__).resolve().parents[2].parent / "mutual-fund-faq-assistant"
CHUNK = {
    "text": (
        "The scheme was launched in 1994. "
        "Expense ratio is listed on this page. "
        "Past results vary."
    ),
    "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
    "source_title": "HDFC Large Cap Fund",
    "retrieved_on": "2026-09-01",
    "scheme_id": "hdfc-large-cap-direct-growth",
}


def _hit(**overrides: object) -> RetrievalBundle:
    chunk = dict(CHUNK)
    chunk.update(overrides)
    return RetrievalBundle(
        status="hit",
        chunks=[chunk],
        lane="A",
        scheme_id="hdfc-large-cap-direct-growth",
        fact_type="expense_ratio",
        resolution_status="resolved",
    )


def _answer(message: str, retriever=None, **kwargs):
    return answer_facts(
        message,
        session=ComplianceSession(),
        case_id=new_case_id(),
        execution_id=kwargs.pop("execution_id", new_execution_id()),
        retriever=retriever,
        **kwargs,
    )


def test_hit_cites_a_substring_and_retrieval_metadata() -> None:
    execution_id = new_execution_id()
    output = _answer(
        "What is the expense ratio of HDFC Large Cap Fund?",
        retriever=lambda _question: _hit(),
        execution_id=execution_id,
    )
    result = output.result
    assert result.status is FactsStatus.SUPPORTED
    assert result.coverage is Coverage.COVERED
    assert result.execution_id == execution_id
    claim = result.answer_facts[0]
    assert claim.claim in claim.evidence
    assert claim.evidence in CHUNK["text"]
    assert claim.evidence == "Expense ratio is listed on this page."
    assert claim.source_url == CHUNK["source_url"]
    assert claim.last_checked is not None
    assert claim.last_checked.isoformat() == "2026-09-01"
    assert result.searched_sources == [CHUNK["source_url"]]


def test_not_found_clarify_and_empty_index_are_not_covered() -> None:
    not_found = _answer(
        "Why was my stock delivery charge different yesterday?",
        retriever=lambda _question: RetrievalBundle(status="not_found", chunks=[], lane="none"),
    )
    assert not_found.result.status is FactsStatus.NOT_COVERED
    assert not_found.result.answer_facts == []
    assert "no retrieved chunk" in not_found.result.limitations[0]

    clarify = _answer(
        "What is the expense ratio?",
        retriever=lambda _question: RetrievalBundle(
            status="clarify",
            chunks=[],
            lane="C",
            resolution_status="ambiguous",
        ),
    )
    assert clarify.result.status is FactsStatus.NOT_COVERED
    assert "scheme was not resolved" in clarify.result.limitations

    empty = _answer(
        "What is the expense ratio of HDFC Large Cap Fund?",
        retriever=lambda _question: RetrievalBundle(status="empty_index", chunks=[]),
    )
    assert empty.result.status is FactsStatus.NOT_COVERED
    assert "index is empty" in empty.result.limitations[0]


def test_unapproved_url_is_not_cited() -> None:
    output = _answer(
        "What is the expense ratio of HDFC Large Cap Fund?",
        retriever=lambda _question: _hit(
            source_url="https://example.com/not-approved",
        ),
    )
    assert output.result.status is FactsStatus.NOT_COVERED
    assert output.result.answer_facts == []
    assert output.result.searched_sources == ["https://example.com/not-approved"]


def test_retrieval_error_does_not_echo_the_question() -> None:
    secret = "9876543210"

    def explode(_question: str) -> RetrievalBundle:
        raise RuntimeError(f"failed while reading {secret}")

    output = _answer("What is the exit load?", retriever=explode)
    dumped = output.model_dump_json()
    assert secret not in dumped
    assert output.result.status is FactsStatus.ERROR
    assert output.result.answer_facts == []
    assert output.result.limitations == ["retrieval failed: RuntimeError"]


def test_advice_and_unsanitized_text_do_not_call_retrieval() -> None:
    def forbid(_question: str) -> RetrievalBundle:
        raise AssertionError("retriever should not be called")

    refused = _answer("Should I redeem this fund?", retriever=forbid)
    assert refused.inspection.result.decision is ComplianceDecision.REFUSE
    assert refused.result.status is FactsStatus.ERROR
    assert refused.result.answer_facts == []

    blocked = _answer("   ", retriever=forbid)
    assert blocked.inspection.result.decision is ComplianceDecision.BLOCK
    assert blocked.result.status is FactsStatus.ERROR


def test_retriever_receives_redacted_text_only() -> None:
    seen: list[str] = []

    def capture(question: str) -> RetrievalBundle:
        seen.append(question)
        return _hit()

    phone = "9876543210"
    output = _answer(
        f"What is the expense ratio of HDFC Large Cap Fund? Call {phone}.",
        retriever=capture,
    )
    assert phone not in seen[0]
    assert "[phone]" in seen[0]
    assert phone not in output.model_dump_json()
    assert output.result.status is FactsStatus.SUPPORTED


def test_missing_project1_root_is_an_error_without_a_guess() -> None:
    output = answer_facts(
        "What is the expense ratio of HDFC Large Cap Fund?",
        session=ComplianceSession(),
        case_id=new_case_id(),
        project1_root=Path("D:/missing/mutual-fund-faq-assistant"),
    )
    assert output.result.status is FactsStatus.ERROR
    assert output.result.answer_facts == []
    assert "not a retrieval checkout" in output.result.limitations[0]


@pytest.mark.skipif(
    not (PROJECT1 / "app" / "pipeline" / "retrieve.py").is_file(),
    reason="Project 1 checkout is not beside this repository",
)
def test_live_corpus_covers_expense_ratio_and_refuses_unknown_topics() -> None:
    covered = answer_facts(
        "What is the expense ratio of HDFC Large Cap Fund?",
        session=ComplianceSession(),
        case_id=new_case_id(),
        project1_root=PROJECT1,
    )
    claim = covered.result.answer_facts[0]
    assert covered.result.status is FactsStatus.SUPPORTED
    assert claim.source_url.startswith("https://groww.in/")
    assert claim.claim in claim.evidence
    assert "expense" in claim.evidence.casefold()
    assert claim.last_checked is not None
    assert claim.last_checked.isoformat() == "2026-09-01"

    missing = answer_facts(
        "Why was my stock delivery charge different yesterday?",
        session=ComplianceSession(),
        case_id=new_case_id(),
        project1_root=PROJECT1,
    )
    assert missing.result.status is FactsStatus.NOT_COVERED
    assert missing.result.answer_facts == []

    unresolved = answer_facts(
        "What is the expense ratio?",
        session=ComplianceSession(),
        case_id=new_case_id(),
        project1_root=PROJECT1,
    )
    assert unresolved.result.status is FactsStatus.NOT_COVERED
    assert any("scheme was not resolved" in item for item in unresolved.result.limitations)


def test_default_root_points_at_the_sibling_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPPORTDESK_PROJECT1_ROOT", raising=False)
    root = default_project1_root()
    if (PROJECT1 / "app" / "pipeline" / "retrieve.py").is_file():
        assert root == PROJECT1
    else:
        assert root is None
