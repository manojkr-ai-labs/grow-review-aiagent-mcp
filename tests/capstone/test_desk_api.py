"""Desk submit and queue over HTTP. Fakes only. No hosted MCP."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from capstone.api.desk import DeskDeps, desk_deps
from capstone.log import LogStore
from reviewpulse.api.app import app
from supportdesk.facts import RetrievalBundle
from tests.contract.fake_mcp import hosted_docs_client, hosted_gmail_client

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

CLOCK = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
PHONE = "9876543210"
COVERED = "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"
NOT_COVERED = "Where is the lost cheque?"
PASSAGE = "Expense ratio is listed on this page."
ADVICE = "You should buy this fund."
GROWW = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"


def _bundle(text: str) -> RetrievalBundle:
    return RetrievalBundle(
        status="hit",
        chunks=[
            {
                "text": text,
                "source_url": GROWW,
                "source_title": "HDFC Large Cap Fund",
                "retrieved_on": "2026-09-01",
            }
        ],
    )


class _Desk:
    def __init__(self, http: TestClient, store: LogStore, docs, gmail) -> None:
        self.http = http
        self.store = store
        self.docs = docs
        self.gmail = gmail


@pytest.fixture
def desk(tmp_path: Path):
    run_dir = tmp_path / "pattern"
    run_dir.mkdir()
    store = LogStore(tmp_path / "capstone.db")
    docs = hosted_docs_client()
    gmail = hosted_gmail_client()

    def retriever(question: str) -> RetrievalBundle:
        if "cheque" in question.casefold() or PHONE in question:
            return RetrievalBundle(status="not_found", chunks=[])
        if "scheme page" in question.casefold():
            return _bundle(ADVICE)
        return _bundle(PASSAGE)

    app.dependency_overrides[desk_deps] = lambda: DeskDeps(
        store=store,
        retriever=retriever,
        clock=CLOCK,
        run_dir=run_dir,
        csv_path=tmp_path / "missing.csv",
        docs=docs,
        gmail=gmail,
        state_path=tmp_path / "supportdesk-publish-state.json",
    )
    try:
        yield _Desk(TestClient(app), store, docs, gmail)
    finally:
        app.dependency_overrides.clear()


def _post(desk: _Desk, text: str, **extra: object):
    return desk.http.post("/api/desk/questions", json={"text": text, **extra})


def test_covered_question_is_stored_and_listed(desk: _Desk) -> None:
    response = _post(
        desk,
        COVERED,
        citation="https://evil.example/made-up",
        count=99,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["facts"]["coverage"] == "covered"
    assert PASSAGE in body["result"]["reply"]["text"]
    assert "evil.example" not in response.text
    case_id = body["run"]["case_id"]

    queued = desk.http.get("/api/desk/queue")
    assert queued.status_code == 200
    row = queued.json()[0]
    assert row["case_id"] == case_id
    assert row["sanitized_text"] == COVERED
    assert row["draft"]
    assert row["not_covered"] is False
    assert GROWW in row["citation"]
    assert row["reviewer_flag"] == "pass"
    assert row["state"] == "pending_approval"
    assert isinstance(row["matching_count"], int)
    assert row["matching_count"] != 99
    assert "window_start" in row
    assert "window_end" in row

    detail = desk.http.get(f"/api/desk/cases/{case_id}")
    assert detail.status_code == 200
    viewed = detail.json()
    assert viewed["draft"]["text"]
    assert viewed["routing_note"]["team"]
    assert viewed["agent_timings"]
    assert viewed["claims"]
    assert viewed["claims"][0]["source_url"] == GROWW
    assert isinstance(viewed["reviewer_findings"], list)


def test_not_covered_question_is_listed_without_a_draft_citation(desk: _Desk) -> None:
    response = _post(desk, NOT_COVERED)
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["facts"]["coverage"] == "not_covered"
    case_id = body["run"]["case_id"]

    row = desk.http.get("/api/desk/queue").json()[0]
    assert row["case_id"] == case_id
    assert row["sanitized_text"] == NOT_COVERED
    assert row["not_covered"] is True
    assert row["draft"] is None

    detail = desk.http.get(f"/api/desk/cases/{case_id}").json()
    assert detail["claims"] == []
    assert detail["routing_note"]["facts_coverage"] == "not_covered"


def test_phone_number_is_not_stored(desk: _Desk) -> None:
    text = f"What is the exit load for {PHONE}?"
    response = _post(desk, text)
    assert response.status_code == 200
    assert PHONE not in response.text
    queued = desk.http.get("/api/desk/queue").json()
    assert queued
    assert all(PHONE not in item["sanitized_text"] for item in queued)
    case_id = queued[0]["case_id"]
    detail = desk.http.get(f"/api/desk/cases/{case_id}")
    assert PHONE not in detail.text
    assert "[phone]" in queued[0]["sanitized_text"]


def test_advice_is_refused(desk: _Desk) -> None:
    response = _post(desk, "Should I buy this fund?")
    assert response.status_code == 200
    body = response.json()
    decision = body["result"]["compliance"]["decision"]
    reply = body["result"]["reply"]["text"].casefold()
    assert decision == "refuse"
    assert "recommendation" in reply
    assert "you should buy" not in reply


def test_reject_stays_on_the_queue_and_leaves_the_explainer(desk: _Desk, tmp_path: Path) -> None:
    explainer = tmp_path / "runs" / "run_week" / "explainer.json"
    explainer.parent.mkdir(parents=True)
    explainer.write_bytes(b'{"week_id":"2026-W36","bullets":[]}\n')
    before = explainer.read_bytes()
    created = _post(desk, COVERED)
    assert created.status_code == 200
    case_id = created.json()["run"]["case_id"]

    rejected = desk.http.post(
        f"/api/desk/cases/{case_id}/decision",
        json={"decision": "reject", "approver_ref": "operator.1"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["run"]["state"] == "rejected"
    queued = desk.http.get("/api/desk/queue").json()
    assert any(row["case_id"] == case_id and row["state"] == "rejected" for row in queued)
    assert explainer.read_bytes() == before
    assert "explainer.json" not in Path(decide_case_source()).read_text(encoding="utf-8")


def test_edit_clears_approval_and_publish_waits(desk: _Desk) -> None:
    created = _post(desk, COVERED)
    case_id = created.json()["run"]["case_id"]
    approved = desk.http.post(
        f"/api/desk/cases/{case_id}/decision",
        json={"decision": "approve", "approver_ref": "operator.1"},
    )
    assert approved.status_code == 200
    previous = approved.json()["run"]["content_hash"]
    edited = desk.http.post(
        f"/api/desk/cases/{case_id}/refine",
        json={
            "instruction": "operator edit",
            "reply": (
                "Expense ratio is listed. "
                f"Source: {GROWW}, last checked 2026-09-01."
            ),
        },
    )
    assert edited.status_code == 200
    body = edited.json()
    assert body["run"]["state"] == "pending_approval"
    assert body["run"]["content_hash"] != previous
    assert "Expense ratio is listed." in body["result"]["reply"]["text"]
    published = desk.http.post(f"/api/desk/cases/{case_id}/publish", json={})
    assert published.status_code == 409
    assert desk.docs.calls == []
    assert desk.gmail.calls == []


def test_changed_reply_publishes_nothing(desk: _Desk) -> None:
    created = _post(desk, COVERED)
    case_id = created.json()["run"]["case_id"]
    approved = desk.http.post(
        f"/api/desk/cases/{case_id}/decision",
        json={"decision": "approve", "approver_ref": "operator.1"},
    )
    assert approved.status_code == 200
    payload = desk.store.fetch_case(case_id)
    assert payload is not None
    payload["result"]["reply"]["text"] = "The scheme page lists the expense ratio."
    payload["result"]["reply"]["sentence_count"] = 1
    desk.store.save_case(payload, updated_at=CLOCK)

    published = desk.http.post(f"/api/desk/cases/{case_id}/publish", json={})
    assert published.status_code == 409
    assert desk.docs.calls == []
    assert desk.gmail.calls == []


def test_second_reviewer_failure_is_blocked_and_does_not_call_mcp(desk: _Desk) -> None:
    created = _post(desk, "What does the scheme page say?")
    assert created.status_code == 200
    body = created.json()
    assert body["run"]["state"] == "blocked"
    assert [item["decision"] for item in body["reviews"]] == ["fail", "fail"]
    case_id = body["run"]["case_id"]

    published = desk.http.post(f"/api/desk/cases/{case_id}/publish", json={})
    assert published.status_code == 409
    assert desk.docs.calls == []
    assert desk.gmail.calls == []


def test_timeout_is_not_retried(desk: _Desk) -> None:
    created = _post(desk, COVERED)
    case_id = created.json()["run"]["case_id"]
    approved = desk.http.post(
        f"/api/desk/cases/{case_id}/decision",
        json={"decision": "approve", "approver_ref": "operator.1"},
    )
    assert approved.status_code == 200
    desk.docs.fail_next = "append_to_google_doc"
    desk.docs.fail_message = "timeout"

    first = desk.http.post(f"/api/desk/cases/{case_id}/publish", json={})
    assert first.status_code == 200
    assert first.json()["actions"][0]["status"] == "uncertain"
    calls_after_timeout = len(desk.docs.calls)
    second = desk.http.post(f"/api/desk/cases/{case_id}/publish", json={})
    assert second.status_code == 200
    assert len(desk.docs.calls) == calls_after_timeout
    names = [name for name, _arguments in desk.docs.calls + desk.gmail.calls]
    assert "send_email" not in names


def decide_case_source() -> str:
    from capstone.api.desk import decide_case

    return decide_case.__code__.co_filename
