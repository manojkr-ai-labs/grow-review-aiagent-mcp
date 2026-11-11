"""Weekly package HTTP. Assemble does not call MCP."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from capstone.api.desk import DeskDeps, desk_deps
from capstone.api.package import PackageDeps, package_deps
from capstone.explainer import EMPTY_LEDGER_SENTENCE
from capstone.log import LogStore
from reviewpulse.api.app import app
from reviewpulse.pulse.validate import GATE_NAMES
from supportdesk.facts import RetrievalBundle
from tests.contract.fake_mcp import hosted_docs_client, hosted_gmail_client

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

CLOCK = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
NOTE = "ALPHA NOTE BODY\n"
RUN_ID = "run_week"
COVERED = "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"
PASSAGE = "Expense ratio is listed on this page."
GROWW = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"


def _write_run(runs: Path) -> None:
    run_dir = runs / RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "note.md").write_text(NOTE, encoding="utf-8")
    (run_dir / "clusters.json").write_text(
        json.dumps({"themes": []}),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
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


def _hit(question: str) -> RetrievalBundle:
    return RetrievalBundle(
        status="hit",
        chunks=[
            {
                "text": PASSAGE,
                "source_url": GROWW,
                "source_title": "HDFC Large Cap Fund",
                "retrieved_on": "2026-09-01",
            }
        ],
    )


class _Api:
    def __init__(self, http: TestClient, docs, gmail, explainer: Path, pulse: Path, desk_state: Path) -> None:
        self.http = http
        self.docs = docs
        self.gmail = gmail
        self.explainer = explainer
        self.pulse = pulse
        self.desk_state = desk_state


@pytest.fixture
def api(tmp_path: Path):
    runs = tmp_path / "runs"
    _write_run(runs)
    pulse = tmp_path / "publish-state.json"
    desk_state = tmp_path / "supportdesk-publish-state.json"
    pulse.write_text("{}\n", encoding="utf-8")
    desk_state.write_text("{}\n", encoding="utf-8")
    docs = hosted_docs_client()
    gmail = hosted_gmail_client()
    store = LogStore(tmp_path / "capstone.db")
    pattern = tmp_path / "pattern"
    pattern.mkdir()
    app.dependency_overrides[package_deps] = lambda: PackageDeps(
        store=store,
        clock=CLOCK,
        retriever=_hit,
        runs_dir=runs,
        publish_state_path=pulse,
        desk_state_path=desk_state,
        docs=docs,
        gmail=gmail,
    )
    app.dependency_overrides[desk_deps] = lambda: DeskDeps(
        store=store,
        retriever=_hit,
        clock=CLOCK,
        run_dir=pattern,
        csv_path=tmp_path / "missing.csv",
        docs=docs,
        gmail=gmail,
        state_path=desk_state,
    )
    try:
        yield _Api(
            TestClient(app),
            docs,
            gmail,
            runs / RUN_ID / "explainer.json",
            pulse,
            desk_state,
        )
    finally:
        app.dependency_overrides.clear()


def test_assemble_returns_the_hash_and_does_not_call_mcp(api: _Api) -> None:
    response = api.http.post(f"/api/capstone/runs/{RUN_ID}/assemble")
    assert response.status_code == 200
    body = response.json()
    assert body["package_hash"]
    assert api.docs.calls == []
    assert api.gmail.calls == []

    viewed = api.http.get(f"/api/capstone/runs/{RUN_ID}/package")
    assert viewed.status_code == 200
    loaded = viewed.json()
    assert loaded["note"] == NOTE
    assert loaded["package_hash"] == body["package_hash"]
    assert loaded["signals"] == []
    assert loaded["ledger"] == []
    assert loaded["explainer"]["bullets"][-1]["text"] == EMPTY_LEDGER_SENTENCE
    assert loaded["approval"] is None


def test_publish_of_a_different_hash_is_rejected(api: _Api) -> None:
    assembled = api.http.post(f"/api/capstone/runs/{RUN_ID}/assemble")
    approved_hash = assembled.json()["package_hash"]
    decision = api.http.post(
        f"/api/capstone/runs/{RUN_ID}/decision",
        json={"decision": "approve", "approver_ref": "operator.1", "action": "draft"},
    )
    assert decision.status_code == 200
    viewed = api.http.get(f"/api/capstone/runs/{RUN_ID}/package")
    assert viewed.json()["approval"]["matches"] is True
    assert viewed.json()["approval"]["content_hash"] == approved_hash
    other = "b" * 64
    rejected = api.http.post(
        f"/api/capstone/runs/{RUN_ID}/publish",
        json={"package_hash": other, "action": "draft"},
    )
    assert rejected.status_code == 409
    assert api.docs.calls == []
    assert api.gmail.calls == []

    note = api.explainer.parent / "note.md"
    note.write_bytes(note.read_bytes().replace(b"A", b"B", 1))
    stale = api.http.post(
        f"/api/capstone/runs/{RUN_ID}/publish",
        json={"package_hash": approved_hash, "action": "draft"},
    )
    assert stale.status_code == 409
    assert api.http.get(f"/api/capstone/runs/{RUN_ID}/package").json()["approval"]["matches"] is False
    assert api.docs.calls == []


def test_approvals_stay_in_their_own_state_files(api: _Api) -> None:
    pulse_before = api.pulse.read_bytes()
    desk_before = api.desk_state.read_bytes()
    assembled = api.http.post(f"/api/capstone/runs/{RUN_ID}/assemble")
    assert assembled.status_code == 200
    explainer_before = api.explainer.read_bytes()

    package_decision = api.http.post(
        f"/api/capstone/runs/{RUN_ID}/decision",
        json={"decision": "approve", "approver_ref": "operator.1"},
    )
    assert package_decision.status_code == 200
    assert api.desk_state.read_bytes() == desk_before

    created = api.http.post("/api/desk/questions", json={"text": COVERED})
    assert created.status_code == 200
    case_id = created.json()["run"]["case_id"]
    approved = api.http.post(
        f"/api/desk/cases/{case_id}/decision",
        json={"decision": "approve", "approver_ref": "operator.1"},
    )
    assert approved.status_code == 200
    assert api.pulse.read_bytes() == pulse_before

    other = api.http.post("/api/desk/questions", json={"text": COVERED})
    assert other.status_code == 200
    rejected = api.http.post(
        f"/api/desk/cases/{other.json()['run']['case_id']}/decision",
        json={"decision": "reject", "approver_ref": "operator.1"},
    )
    assert rejected.status_code == 200
    assert api.explainer.read_bytes() == explainer_before


def test_a_desk_case_id_cannot_publish_a_package(api: _Api) -> None:
    case_id = "case_" + "ab" * 16
    response = api.http.post(
        f"/api/capstone/runs/{case_id}/publish",
        json={"package_hash": "ab" * 32, "action": "send"},
    )
    assert response.status_code == 409
    assert api.docs.calls == []
    assert api.gmail.calls == []
    assert "send_email" not in [name for name, _args in api.gmail.calls]
