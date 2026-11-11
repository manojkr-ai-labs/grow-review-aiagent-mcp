"""C1–C5 on fakes. No hosted MCP and no live model."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from capstone.api.desk import DeskDeps, desk_deps
from capstone.assemble import run as assemble_run
from capstone.log import LogStore
from capstone.signals import read_support_signals, render_signal
from reviewpulse.api.app import app
from reviewpulse.pulse.validate import GATE_NAMES
from supportdesk.compliance import ComplianceSession
from supportdesk.enums import ComplianceDecision
from supportdesk.facts import RetrievalBundle
from supportdesk.ids import new_case_id
from tests.contract.fake_mcp import hosted_docs_client, hosted_gmail_client

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

CLOCK = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
PHONE = "9876543210"
GROWW = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
SEARCHED = "https://groww.in/help/not-this-page"
PASSAGE = "Expense ratio is listed on the scheme page."
CHARGE = "What is the brokerage charge?"
WINDOW = {
    "requested_start": "2026-06-01",
    "requested_end": "2026-09-01",
    "actual_start": "2026-06-01",
    "actual_end": "2026-09-01",
}


def _bundle(text: str, *, url: str = GROWW, checked: str | None = "2026-09-01") -> RetrievalBundle:
    chunk: dict[str, str] = {
        "text": text,
        "source_url": url,
        "source_title": "HDFC Large Cap Fund",
    }
    if checked is not None:
        chunk["retrieved_on"] = checked
    return RetrievalBundle(status="hit", chunks=[chunk])


def _client(tmp_path: Path, retriever, *, run_dir: Path | None = None, csv_path: Path | None = None):
    store = LogStore(tmp_path / "capstone.db")
    docs = hosted_docs_client()
    gmail = hosted_gmail_client()
    app.dependency_overrides[desk_deps] = lambda: DeskDeps(
        store=store,
        retriever=retriever,
        clock=CLOCK,
        run_dir=run_dir,
        csv_path=csv_path,
        docs=docs,
        gmail=gmail,
        state_path=tmp_path / "supportdesk-publish-state.json",
    )
    return TestClient(app), store, docs, gmail


def _close() -> None:
    app.dependency_overrides.clear()


def test_c1_covered_fact_has_one_link_and_a_last_checked_value(tmp_path: Path) -> None:
    def retriever(question: str) -> RetrievalBundle:
        return _bundle(PASSAGE)

    http, _store, _docs, _gmail = _client(tmp_path, retriever)
    try:
        response = http.post(
            "/api/desk/questions",
            json={"text": "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"},
        )
    finally:
        _close()

    assert response.status_code == 200
    body = response.json()
    reply = body["result"]["reply"]
    assert reply["sentence_count"] <= 3
    links = re.findall(r"https://\S+", reply["text"])
    assert len(links) == 1
    assert "groww.in" in links[0]
    claim = body["result"]["facts"]["answer_facts"][0]
    assert claim["last_checked"] == "2026-09-01" or "unavailable" in reply["text"]
    assert body["reviews"][-1]["decision"] == "pass"


def test_c2_not_covered_writes_a_ledger_row_and_no_claim(tmp_path: Path) -> None:
    def retriever(question: str) -> RetrievalBundle:
        return RetrievalBundle(
            status="not_found",
            chunks=[
                {
                    "text": "Invented expense ratio is 9 percent.",
                    "source_url": SEARCHED,
                    "source_title": "Searched page",
                }
            ],
        )

    http, store, _docs, _gmail = _client(tmp_path, retriever)
    try:
        response = http.post(
            "/api/desk/questions",
            json={"text": "Where is the lost cheque?"},
        )
    finally:
        _close()

    assert response.status_code == 200
    body = response.json()
    facts = body["result"]["facts"]
    assert facts["coverage"] == "not_covered"
    assert facts["answer_facts"] == []
    assert SEARCHED in facts["searched_sources"]
    reply = body["result"]["reply"]["text"]
    assert "Invented expense ratio" not in reply
    assert "9 percent" not in reply
    case_id = body["run"]["case_id"]
    assert store.fetch_ledger(case_id) is not None


def _fee_theme(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "note.md").write_text("Weekly note stays unchanged.\n", encoding="utf-8")
    (path / "clusters.json").write_text(
        json.dumps(
            {
                "window": WINDOW,
                "themes": [
                    {
                        "theme_id": "t-fees",
                        "cluster_key": "c1",
                        "label": "Brokerage charges",
                        "keywords": ["brokerage", "charge", "fee"],
                        "review_ids": ["r1", "r2", "r3", "r4"],
                        "size": 4,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "gates": [
                    {"gate": name, "passed": True, "detail": ""}
                    for name in GATE_NAMES
                ]
            }
        ),
        encoding="utf-8",
    )
    with (path.parent / "charges.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["review_id", "review_date", "text_clean"])
        writer.writeheader()
        writer.writerows(
            [
                {"review_id": "r1", "review_date": "2026-07-01", "text_clean": "brokerage charge"},
                {"review_id": "r2", "review_date": "2026-07-15", "text_clean": "brokerage charge"},
                {"review_id": "r3", "review_date": "2026-08-20", "text_clean": "brokerage charge"},
                {"review_id": "r4", "review_date": "2026-08-25", "text_clean": "brokerage charge"},
            ]
        )


def test_c3_five_charge_questions_produce_a_queue_line(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_c3"
    _fee_theme(run_dir)
    note = (run_dir / "note.md").read_bytes()

    def retriever(question: str) -> RetrievalBundle:
        return RetrievalBundle(status="not_found", chunks=[])

    http, store, _docs, _gmail = _client(
        tmp_path,
        retriever,
        run_dir=run_dir,
        csv_path=run_dir.parent / "charges.csv",
    )
    try:
        for _ in range(5):
            response = http.post("/api/desk/questions", json={"text": CHARGE})
            assert response.status_code == 200
    finally:
        _close()

    note_row = response.json()["result"]["routing_note"]
    assert note_row["pattern_signal"] in {"recurring", "rising"}
    assert note_row["matching_count"] >= 3
    assert note_row["analysis_window"]["start"]
    assert note_row["analysis_window"]["end"]

    outcome = assemble_run(
        "run_c3",
        store=store,
        clock=CLOCK,
        retriever=retriever,
        runs_dir=tmp_path / "runs",
    )
    assert outcome.assembled is True
    assert (run_dir / "note.md").read_bytes() == note
    explainer = json.loads((run_dir / "explainer.json").read_text(encoding="utf-8"))
    assert len(explainer["bullets"]) <= 6
    assert explainer["fee_theme"] == "t-fees"
    signals = read_support_signals(run_dir / "support_signals.json")
    assert len(signals) == 1
    assert signals[0].count == 5
    assert signals[0].evidence_type == "queue"
    line = render_signal(signals[0])
    assert line == (
        f'Support was asked "{signals[0].question_key}" 5 times in {signals[0].week_id}. '
        "This line is the question log, not review volume."
    )
    stored = (run_dir / "support_signals.json").read_text(encoding="utf-8")
    assert signals[0].question_key in stored
    assert '"count":5' in stored


def test_c4_phone_number_is_absent_from_the_stored_case(tmp_path: Path) -> None:
    def retriever(question: str) -> RetrievalBundle:
        return RetrievalBundle(status="not_found", chunks=[])

    http, store, _docs, _gmail = _client(tmp_path, retriever)
    try:
        response = http.post(
            "/api/desk/questions",
            json={"text": f"What is the exit load for {PHONE}?"},
        )
    finally:
        _close()

    assert response.status_code == 200
    assert PHONE not in response.text
    case_id = response.json()["run"]["case_id"]
    row = store.fetch(case_id)
    assert row is not None
    logged = row.model_dump_json()
    blob = json.dumps(store.fetch_case(case_id))
    assert PHONE not in logged
    assert PHONE not in blob
    assert "[phone]" in row.sanitized_text
    assert PHONE not in row.sanitized_text


def test_c5_advice_followup_is_refused_and_a_second_failure_makes_no_mcp_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fresh = ComplianceSession()
    alone = fresh.inspect("What do you think?", case_id=new_case_id(), received_at=CLOCK)
    assert alone.result.decision is not ComplianceDecision.REFUSE

    shared = ComplianceSession()
    monkeypatch.setattr("capstone.api.desk.ComplianceSession", lambda *args, **kwargs: shared)

    def retriever(question: str) -> RetrievalBundle:
        if "scheme page" in question.casefold():
            return _bundle("You should buy this fund.")
        return RetrievalBundle(status="not_found", chunks=[])

    http, _store, docs, gmail = _client(tmp_path, retriever)
    try:
        first = http.post("/api/desk/questions", json={"text": "Should I redeem this fund?"})
        second = http.post("/api/desk/questions", json={"text": "What do you think?"})
        blocked = http.post("/api/desk/questions", json={"text": "What does the scheme page say?"})
        case_id = blocked.json()["run"]["case_id"]
        published = http.post(f"/api/desk/cases/{case_id}/publish", json={})
    finally:
        _close()

    assert first.status_code == 200
    assert second.status_code == 200
    for response in (first, second):
        body = response.json()
        assert body["result"]["compliance"]["decision"] == "refuse"
        reply = body["result"]["reply"]["text"].casefold()
        assert "recommendation" in reply
        assert "you should" not in reply
        assert "return" not in reply or "performance expectation" in reply
    assert shared.advice_requested is True
    assert blocked.status_code == 200
    assert blocked.json()["run"]["state"] == "blocked"
    assert [item["decision"] for item in blocked.json()["reviews"]] == ["fail", "fail"]
    assert published.status_code == 409
    assert docs.calls == []
    assert gmail.calls == []
