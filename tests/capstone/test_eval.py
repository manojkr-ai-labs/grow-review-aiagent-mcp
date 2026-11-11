"""E1–E3 on fixtures. No hosted MCP and no review download."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from capstone.api.desk import DeskDeps, desk_deps
from capstone.api.package import PackageDeps, package_deps
from capstone.explainer import FEE_QUESTIONS
from capstone.log import LogStore
from reviewpulse.api.app import app
from reviewpulse.mcp.client import MCPClient
from reviewpulse.pulse.render import count_words
from reviewpulse.pulse.validate import GATE_NAMES
from supportdesk.facts import RetrievalBundle
from tests.contract.fake_mcp import hosted_docs_client, hosted_gmail_client

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

CLOCK = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
NOTE = "Weekly note for the fixture week.\n"
PAN = "ABCDE1234F"
ACCOUNT = "1234567890123"
PHONE = "9876543210"
RETURN_ASK = "How much return will I get?"
GROWW = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
REVIEW_IDS = ["r1", "r2", "r3", "r4", "r5"]


def _manifest() -> dict:
    return {
        "gates": [{"gate": name, "passed": True, "detail": ""} for name in GATE_NAMES]
    }


def _write_run(runs: Path, run_id: str) -> Path:
    run_dir = runs / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "note.md").write_text(NOTE, encoding="utf-8")
    (run_dir / "clusters.json").write_text(
        json.dumps(
            {
                "themes": [
                    {
                        "theme_id": "t-fees",
                        "label": "Brokerage charges",
                        "keywords": ["brokerage", "charge", "fee"],
                        "review_ids": REVIEW_IDS,
                        "size": len(REVIEW_IDS),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    return run_dir


def _hit(text: str, url: str = GROWW) -> RetrievalBundle:
    return RetrievalBundle(
        status="hit",
        chunks=[
            {
                "text": text,
                "source_url": url,
                "source_title": "Scheme page",
                "retrieved_on": "2026-09-01",
            }
        ],
    )


def _missing(question: str) -> RetrievalBundle:
    return RetrievalBundle(status="not_found", chunks=[])


def _bind(tmp_path: Path, runs: Path, retriever) -> tuple[TestClient, LogStore, object, object, list[str]]:
    store = LogStore(tmp_path / "capstone.db")
    docs = hosted_docs_client()
    gmail = hosted_gmail_client()
    calls: list[str] = []
    app.dependency_overrides[desk_deps] = lambda: DeskDeps(
        store=store,
        retriever=retriever,
        clock=CLOCK,
        run_dir=runs / "run_eval",
        csv_path=tmp_path / "missing.csv",
        docs=docs,
        gmail=gmail,
        state_path=tmp_path / "supportdesk-publish-state.json",
    )
    app.dependency_overrides[package_deps] = lambda: PackageDeps(
        store=store,
        clock=CLOCK,
        retriever=retriever,
        runs_dir=runs,
        publish_state_path=tmp_path / "publish-state.json",
        desk_state_path=tmp_path / "supportdesk-publish-state.json",
        docs=docs,
        gmail=gmail,
    )
    return TestClient(app), store, docs, gmail, calls


def _watch_mcp(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    monkeypatch.setattr(
        MCPClient,
        "call_tool",
        lambda self, name, arguments: calls.append(name),
    )
    monkeypatch.setattr(
        "reviewpulse.mcp.client.verify_publish_servers",
        lambda *args, **kwargs: calls.append("verify"),
    )


def test_e1_one_assemble_stops_at_the_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runs = tmp_path / "runs"
    run_dir = _write_run(runs, "run_eval")
    themes = json.loads((run_dir / "clusters.json").read_text(encoding="utf-8"))["themes"]
    assert themes
    assert all(theme["theme_id"] and theme["review_ids"] for theme in themes)
    note = (run_dir / "note.md").read_text(encoding="utf-8")
    assert count_words(note) <= 250

    def retriever(question: str) -> RetrievalBundle:
        if "expense ratio" in question.casefold():
            return _hit("Expense ratio is listed on the scheme page.")
        return _missing(question)

    http, _store, docs, gmail, calls = _bind(tmp_path, runs, retriever)
    _watch_mcp(monkeypatch, calls)
    pulse = tmp_path / "publish-state.json"
    desk_state = tmp_path / "supportdesk-publish-state.json"
    pulse.write_text('{"sentinel":"pulse"}\n', encoding="utf-8")
    desk_state.write_text('{"sentinel":"desk"}\n', encoding="utf-8")
    try:
        covered = http.post(
            "/api/desk/questions",
            json={"text": "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"},
        )
        missed = http.post("/api/desk/questions", json={"text": "Where is the lost cheque?"})
        queued = http.get("/api/desk/queue")
        assembled = http.post("/api/capstone/runs/run_eval/assemble")
    finally:
        app.dependency_overrides.clear()

    assert covered.status_code == 200
    assert missed.status_code == 200
    rows = queued.json()
    assert len(rows) == 2
    assert all(row["draft"] or row["not_covered"] for row in rows)
    assert assembled.status_code == 200
    assert assembled.json()["package_hash"]
    explainer = json.loads((run_dir / "explainer.json").read_text(encoding="utf-8"))
    assert len(explainer["bullets"]) <= 6
    assert not (run_dir / "package-approval.json").is_file()
    assert docs.calls == []
    assert gmail.calls == []
    assert calls == []
    assert pulse.read_text(encoding="utf-8") == '{"sentinel":"pulse"}\n'
    assert desk_state.read_text(encoding="utf-8") == '{"sentinel":"desk"}\n'


def test_e2_wrong_hash_is_refused_and_rejection_keeps_the_explainer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    run_dir = _write_run(runs, "run_eval")
    http, _store, docs, gmail, calls = _bind(tmp_path, runs, _missing)
    _watch_mcp(monkeypatch, calls)
    try:
        assembled = http.post("/api/capstone/runs/run_eval/assemble")
        approved = assembled.json()["package_hash"]
        decision = http.post(
            "/api/capstone/runs/run_eval/decision",
            json={"decision": "approve", "approver_ref": "operator.1", "action": "draft"},
        )
        note_before = (run_dir / "note.md").read_bytes()
        explainer_before = (run_dir / "explainer.json").read_bytes()
        refused = http.post(
            "/api/capstone/runs/run_eval/publish",
            json={"package_hash": "b" * 64, "action": "draft"},
        )
        created = http.post(
            "/api/desk/questions",
            json={"text": "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"},
        )
        case_id = created.json()["run"]["case_id"]
        before_reject = (run_dir / "explainer.json").read_bytes()
        rejected = http.post(
            f"/api/desk/cases/{case_id}/decision",
            json={"decision": "reject", "approver_ref": "operator.1"},
        )
    finally:
        app.dependency_overrides.clear()

    assert assembled.status_code == 200
    assert decision.status_code == 200
    assert decision.json()["content_hash"] == approved
    assert refused.status_code == 409
    assert (run_dir / "note.md").read_bytes() == note_before
    assert (run_dir / "explainer.json").read_bytes() == explainer_before
    assert rejected.status_code == 200
    assert rejected.json()["run"]["state"] == "rejected"
    assert (run_dir / "explainer.json").read_bytes() == before_reject
    assert docs.calls == []
    assert gmail.calls == []
    assert calls == []


def test_e3_five_claims_and_sensitive_questions_do_not_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    run_dir = _write_run(runs, "run_eval")
    passages: dict[str, str] = {}
    urls = {
        question: f"https://groww.in/mutual-funds/scheme-{index}"
        for index, question in enumerate(FEE_QUESTIONS[:5], start=1)
    }

    def retriever(question: str) -> RetrievalBundle:
        if question not in urls:
            return _missing(question)
        passage = question.rstrip("?") + " is listed on the scheme page."
        passages[question] = passage
        return _hit(passage, urls[question])

    http, _store, docs, gmail, calls = _bind(tmp_path, runs, retriever)
    _watch_mcp(monkeypatch, calls)
    pulse = tmp_path / "publish-state.json"
    desk_state = tmp_path / "supportdesk-publish-state.json"
    pulse.write_text('{"sentinel":"pulse"}\n', encoding="utf-8")
    desk_state.write_text('{"sentinel":"desk"}\n', encoding="utf-8")
    sensitive = [
        f"What is the exit load for {PAN}?",
        f"The account number is {ACCOUNT}",
        f"My phone is {PHONE}",
        RETURN_ASK,
    ]
    try:
        assembled = http.post("/api/capstone/runs/run_eval/assemble")
        explainer_before = (run_dir / "explainer.json").read_bytes()
        posted = [http.post("/api/desk/questions", json={"text": text}) for text in sensitive]
        again = http.post("/api/capstone/runs/run_eval/assemble")
    finally:
        app.dependency_overrides.clear()

    assert assembled.status_code == 200
    themes = json.loads((run_dir / "clusters.json").read_text(encoding="utf-8"))["themes"]
    review_ids = themes[0]["review_ids"]
    assert review_ids == REVIEW_IDS
    explainer = json.loads(explainer_before.decode("utf-8"))
    claims = [bullet for bullet in explainer["bullets"] if bullet.get("url")]
    assert len(claims) == 5
    for claim in claims:
        assert claim["url"].startswith("https://groww.in/")
        assert any(claim["text"] in passage for passage in passages.values())
        assert review_ids
    assert all(item.status_code == 200 for item in posted)
    stored = explainer_before.decode("utf-8")
    stored += (run_dir / "support_signals.json").read_text(encoding="utf-8")
    for secret in (PAN, ACCOUNT, PHONE):
        assert secret not in stored
        assert all(secret not in item.text for item in posted)
    refusal = posted[-1].json()
    assert refusal["result"]["compliance"]["decision"] == "refuse"
    assert "performance expectation" in refusal["result"]["reply"]["text"].casefold()
    assert again.status_code == 409
    assert (run_dir / "explainer.json").read_bytes() == explainer_before
    assert docs.calls == []
    assert gmail.calls == []
    assert calls == []
    assert pulse.read_text(encoding="utf-8") == '{"sentinel":"pulse"}\n'
    assert desk_state.read_text(encoding="utf-8") == '{"sentinel":"desk"}\n'
