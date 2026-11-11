"""Factual explainer bullets from an injected retriever. No hosted corpus."""

from __future__ import annotations

from datetime import date

from capstone.explainer import FEE_QUESTIONS, factual_bullets
from supportdesk.facts import RetrievalBundle

QUESTION = FEE_QUESTIONS[0]
PASSAGE = "Exit load of 1% if redeemed within 1 year."
GROWW = "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"
OFF_HOST = "https://example.com/fees"


def _bundle(chunks: list[dict], status: str = "hit") -> RetrievalBundle:
    return RetrievalBundle(status=status, chunks=chunks)


def _chunk(text: str, url: str = GROWW, retrieved_on: str | None = "2026-09-01") -> dict:
    chunk = {
        "source_url": url,
        "source_title": "HDFC Mid Cap Fund — Direct Growth",
        "text": text,
    }
    if retrieved_on is not None:
        chunk["retrieved_on"] = retrieved_on
    return chunk


def test_frozen_questions_come_from_the_sibling_catalog() -> None:
    assert FEE_QUESTIONS
    assert FEE_QUESTIONS[0].startswith("What is the exit load")
    assert any(question.startswith("What is the expense ratio") for question in FEE_QUESTIONS)


def test_off_host_url_produces_no_bullet() -> None:
    def retriever(question: str) -> RetrievalBundle:
        return _bundle([_chunk(PASSAGE, url=OFF_HOST)])

    assert factual_bullets(retriever, questions=(QUESTION,)) == []


def test_claim_not_in_the_passage_produces_no_bullet() -> None:
    stray = PASSAGE

    def retriever(question: str) -> RetrievalBundle:
        return _bundle(
            [
                {
                    "source_url": GROWW,
                    "source_title": "HDFC Mid Cap Fund — Direct Growth",
                    "claim": stray,
                    "text": "",
                    "retrieved_on": "2026-09-01",
                }
            ]
        )

    bullets = factual_bullets(retriever, questions=(QUESTION,))
    assert bullets == []
    assert all(stray not in bullet.text for bullet in bullets)


def test_not_covered_retrieval_is_not_a_bullet() -> None:
    def retriever(question: str) -> RetrievalBundle:
        return _bundle([], status="not_found")

    assert factual_bullets(retriever, questions=(QUESTION,)) == []


def test_covered_bullet_copies_the_retrieval_date_and_the_passage() -> None:
    def retriever(question: str) -> RetrievalBundle:
        return _bundle([_chunk(PASSAGE)])

    bullets = factual_bullets(retriever, questions=(QUESTION,))

    assert len(bullets) == 1
    bullet = bullets[0]
    assert bullet.text in PASSAGE
    assert bullet.url == GROWW
    assert bullet.last_checked == "2026-09-01"
    assert bullet.last_checked != date.today().isoformat()


def test_missing_retrieval_date_uses_the_unavailable_marker() -> None:
    def retriever(question: str) -> RetrievalBundle:
        return _bundle([_chunk(PASSAGE, retrieved_on=None)])

    bullets = factual_bullets(retriever, questions=(QUESTION,))

    assert len(bullets) == 1
    assert bullets[0].last_checked == "unavailable"
    assert bullets[0].last_checked != date.today().isoformat()


def test_five_links_is_the_cap() -> None:
    def retriever(question: str) -> RetrievalBundle:
        slug = str(abs(hash(question)) % 100000)
        return _bundle(
            [
                _chunk(
                    PASSAGE,
                    url=f"https://www.groww.in/mutual-funds/example-{slug}",
                )
            ]
        )

    bullets = factual_bullets(retriever)

    assert len(FEE_QUESTIONS) > 5
    assert len(bullets) == 5
    assert all(bullet.url and "groww.in" in bullet.url for bullet in bullets)
