"""Contract tests for the Phase 7 console API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from reviewpulse.api.app import app
from reviewpulse.api.context import ApiContext
from reviewpulse.api.jobs import JOBS
from reviewpulse.config import Settings
from reviewpulse.models import Review
from reviewpulse.store.sqlite import ReviewStore

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture
def api_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runs = tmp_path / "runs"
    run_dir = runs / "20260904T110430Z-test"
    run_dir.mkdir(parents=True)
    db_path = tmp_path / "reviews.db"
    state_path = tmp_path / "publish-state.json"
    lock_path = tmp_path / "schedule.lock"

    store = ReviewStore(db_path)
    reviews = [
        Review(
            review_id="r-crash",
            source="play",
            rating=1,
            title_clean=None,
            text_clean="The app crashes after every update and support is automated.",
            date=datetime(2026, 8, 1, tzinfo=timezone.utc),
            lang="en",
            scrub_flags=["phone"],
        ),
        Review(
            review_id="r-ok",
            source="play",
            rating=5,
            title_clean=None,
            text_clean="Really smooth interface for mutual funds and SIPs every month.",
            date=datetime(2026, 8, 20, tzinfo=timezone.utc),
            lang="en",
            scrub_flags=[],
        ),
    ]
    store.upsert_many(reviews)

    manifest = {
        "run_id": run_dir.name,
        "stage": "pulse",
        "timestamp": "2026-09-04T11:04:52+00:00",
        "package_id": "com.nextbillion.groww",
        "window_weeks": 12,
        "window": {
            "requested_start": "2026-06-12",
            "requested_end": "2026-09-04",
            "actual_start": "2026-06-12",
            "actual_end": "2026-09-03",
            "actual_weeks": 11.86,
        },
        "clustering": {
            "mode": "embedding",
            "strategy": "ward",
            "linkage": "ward",
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        },
        "counts": {
            "window_reviews": 2,
            "clustered": 1,
            "dropped_low_signal": 1,
            "themes": 1,
        },
        "themes": [
            {
                "theme_id": "t1",
                "rank": 1,
                "label": "App crashes after update",
                "size": 1,
                "mean_rating": 1.0,
                "neg_share": 1.0,
                "priority": 1.0,
                "trend": 1.0,
                "emerging": False,
            }
        ],
        "stages": ["cluster", "pulse"],
        "pulse": {
            "analysed_reviews": 1,
            "mean_rating": 1.0,
            "word_count": 80,
            "max_words": 250,
            "compose_source": "heuristic",
            "compose_provider": "gemini",
            "compose_model": "gemini-3.6-flash",
            "scrub_flags": {"phone": 1},
            "top_themes": [
                {
                    "theme_id": "t1",
                    "rank": 1,
                    "label": "App crashes after update",
                    "line": "Crashes after updates",
                    "size": 1,
                    "mean_rating": 1.0,
                    "neg_share": 1.0,
                    "emerging": False,
                }
            ],
            "quotes": [
                {
                    "review_id": "r-crash",
                    "theme_id": "t1",
                    "rating": 1,
                    "text": "The app crashes after every update and support is automated.",
                    "words": 10,
                }
            ],
            "actions": [
                {"text": "Fix post-update crashes", "theme_ids": ["t1"]}
            ],
        },
        "checks": {
            "themes_capped": True,
            "quotes_verbatim": True,
            "quotes_count": True,
            "actions_grounded": True,
            "word_count": True,
            "no_pii": True,
            "window_declared": True,
        },
        "gates": [
            {"gate": name, "passed": True, "detail": "ok"}
            for name in (
                "themes_capped",
                "quotes_verbatim",
                "quotes_count",
                "actions_grounded",
                "word_count",
                "no_pii",
                "window_declared",
            )
        ],
        "publish": {
            "mode": "dry_run",
            "published": True,
            "idempotency_key": "groww:2026-W36",
            "doc_id": "dry-run-doc:groww:2026-W36",
            "draft_id": "dry-run-draft:groww:2026-W36",
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "clusters.json").write_text(
        json.dumps(
            {
                "themes": [
                    {
                        "theme_id": "t1",
                        "rank": 1,
                        "label": "App crashes after update",
                        "summary": "Crashes after updates.",
                        "size": 1,
                        "mean_rating": 1.0,
                        "neg_share": 1.0,
                        "priority": 1.0,
                        "trend": 1.0,
                        "emerging": False,
                        "keywords": ["crash", "update"],
                        "review_ids": ["r-crash"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "cluster_debug.json").write_text(
        json.dumps(
            {
                "clusters": [
                    {
                        "rank": 1,
                        "top_terms": ["crash", "update", "support"],
                        "label": "App crashes after update",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "note.md").write_text("# Pulse\n\nFix crashes.\n", encoding="utf-8")
    (run_dir / "publish.json").write_text(
        json.dumps({"mode": "dry_run", "published": True, "idempotency_key": "groww:2026-W36"}),
        encoding="utf-8",
    )

    settings = Settings()
    settings.db_path = db_path
    settings.pulse.recipient_alias = "pm@example.com"
    ctx = ApiContext(
        settings=settings,
        runs_dir=runs,
        db_path=db_path,
        publish_state_path=state_path,
        lock_path=lock_path,
    )

    def _ctx() -> ApiContext:
        return ctx

    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret_value_should_never_leak_zz99")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_secret_value_should_never_leak")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "mcp-secret-token-value")

    from reviewpulse.api.app import get_context

    app.dependency_overrides[get_context] = _ctx
    JOBS.set_pipeline(lambda **kwargs: True)
    yield ctx
    app.dependency_overrides.clear()
    JOBS.set_pipeline(None)
    JOBS._jobs.clear()


@pytest.fixture
def client(api_env) -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_cors_allows_local_next_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:3000"


def test_pulse_binds_fixture_not_placeholders(client: TestClient) -> None:
    data = client.get("/api/v1/pulse").json()
    assert data["run_id"] == "20260904T110430Z-test"
    assert data["counts"]["clustered"] == 1
    assert data["word_count"] == 80
    assert data["all_gates_passed"] is True
    assert data["quotes"][0]["text"].startswith("The app crashes")
    assert data["top_themes"][0]["label"] == "App crashes after update"
    assert "14820" not in json.dumps(data)


def test_reviews_have_no_author_and_paginate(client: TestClient) -> None:
    data = client.get("/api/v1/reviews", params={"limit": 1}).json()
    assert data["total"] == 2
    assert data["next_cursor"]
    row = data["items"][0]
    assert "author" not in row
    assert "text_clean" in row
    blob = json.dumps(data)
    assert "author" not in blob
    page2 = client.get("/api/v1/reviews", params={"limit": 1, "cursor": data["next_cursor"]}).json()
    assert len(page2["items"]) == 1
    assert page2["items"][0]["review_id"] != row["review_id"]


def test_reviews_search_and_theme_filter(client: TestClient) -> None:
    found = client.get("/api/v1/reviews", params={"q": "crashes"}).json()
    assert found["total"] == 1
    themed = client.get("/api/v1/reviews", params={"theme_id": "t1"}).json()
    assert themed["total"] == 1
    assert themed["items"][0]["theme_id"] == "t1"


def test_settings_redacts_secrets(client: TestClient) -> None:
    data = client.get("/api/v1/settings").json()
    blob = json.dumps(data)
    assert "gsk_secret_value_should_never_leak_zz99" not in blob
    assert "AIza_secret_value_should_never_leak" not in blob
    assert "mcp-secret-token-value" not in blob
    assert "MCP_AUTH_TOKEN" not in blob
    assert data["groq_configured"] is True
    assert data["package_id"] == "com.nextbillion.groww"
    assert data["store"] == "SQLite"


def test_pipeline_rejects_send_with_dry_run(client: TestClient) -> None:
    response = client.post(
        "/api/v1/pipeline/run",
        json={"dry_run": True, "send": True},
    )
    assert response.status_code == 400


def test_pipeline_dry_run_job(client: TestClient) -> None:
    response = client.post("/api/v1/pipeline/run", json={"dry_run": True, "window_weeks": 8})
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    job = client.get(f"/api/v1/pipeline/jobs/{job_id}").json()
    assert job["dry_run"] is True
    assert job["status"] in {"queued", "running", "succeeded", "failed"}


def test_send_requires_confirm(client: TestClient) -> None:
    response = client.post("/api/v1/publish/send", json={"confirm": False})
    assert response.status_code == 400


def test_theme_detail(client: TestClient) -> None:
    data = client.get("/api/v1/themes/t1").json()
    assert data["theme"]["label"] == "App crashes after update"
    assert data["rating_histogram"]["1"] == 1


def test_runs_list(client: TestClient) -> None:
    data = client.get("/api/v1/runs").json()
    assert data[0]["run_id"] == "20260904T110430Z-test"
    assert data[0]["publish_mode"] == "dry-run"
    note = client.get(f"/api/v1/runs/{data[0]['run_id']}/note")
    assert note.status_code == 200
    assert "Pulse" in note.text
