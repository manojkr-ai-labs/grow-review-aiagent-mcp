"""End-to-end pulse stage on a synthetic store (Phase 3 tasks 3.9-3.11).

Keyword mode and no LLM, so the whole of Phase 3 is verifiable with no model
download and no API key — which is the point of proving the pipeline locally
before Phase 4 touches MCP.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from reviewpulse.config import load_settings
from reviewpulse.models import Review
from reviewpulse.orchestrator import run_cluster_stage, run_pulse_stage
from reviewpulse.pulse.render import count_words
from reviewpulse.store.sqlite import ReviewStore

TOPICS = [
    ("customer care never responds to my support ticket about this account", 1, 14),
    ("brokerage charges are far too high on every single trade i place here", 2, 12),
    ("i cannot withdraw my money it has been stuck on hold for many days", 1, 10),
    ("the chart interface is cluttered and the layout is confusing to use", 2, 8),
    ("zerodha provides this feature but it is not available on this platform", 3, 6),
]


@pytest.fixture()
def populated_db(tmp_path):
    store = ReviewStore(tmp_path / "reviews.db")
    now = datetime.now(timezone.utc)
    reviews = []
    for topic_index, (text, rating, days) in enumerate(TOPICS):
        for member in range(12):
            reviews.append(
                Review(
                    review_id=f"t{topic_index}m{member:03d}",
                    source="play",
                    rating=rating,
                    text_clean=f"{text} instance {member}",
                    date=now - timedelta(days=days + member),
                )
            )
    for member in range(20):
        reviews.append(
            Review(
                review_id=f"praise{member:03d}",
                source="play",
                rating=5,
                text_clean=f"super app nice {member}",
                date=now - timedelta(days=5),
            )
        )
    store.upsert_many(reviews)
    return tmp_path / "reviews.db"


def run_stage(populated_db, tmp_path, **kwargs):
    return run_pulse_stage(
        window_weeks=8,
        settings=load_settings(),
        db_path=populated_db,
        runs_dir=tmp_path / "runs",
        mode="keyword_fallback",
        use_llm=False,
        cluster_use_llm=False,
        **kwargs,
    )


def test_dry_run_produces_a_valid_note(populated_db, tmp_path) -> None:
    result = run_stage(populated_db, tmp_path)

    assert result.passed, result.checks
    assert all(result.checks.values())
    assert result.note_path.endswith("note.md")


def test_note_is_within_the_word_ceiling(populated_db, tmp_path) -> None:
    result = run_stage(populated_db, tmp_path)
    rendered = open(result.note_path, encoding="utf-8").read()

    assert count_words(rendered) == result.word_count
    assert result.word_count <= 250


def test_note_names_three_themes_three_quotes_and_three_actions(
    populated_db, tmp_path
) -> None:
    result = run_stage(populated_db, tmp_path)
    rendered = open(result.note_path, encoding="utf-8").read()

    assert len(result.note.top_themes) == 3
    assert len(result.note.quotes) == 3
    assert len(result.note.actions) == 3
    for section in ("Top themes", "What users said", "Three things to do next"):
        assert section in rendered
    for theme in result.note.top_themes:
        assert theme.label in rendered


def test_every_quote_is_a_substring_of_a_stored_review(populated_db, tmp_path) -> None:
    result = run_stage(populated_db, tmp_path)
    store = ReviewStore(populated_db)

    for quote in result.note.quotes:
        review = store.get_by_id(quote.review_id)
        assert review is not None
        assert quote.text in review.text_clean
    assert len({q.review_id for q in result.note.quotes}) == 3


def test_quotes_come_from_the_themes_they_are_attributed_to(
    populated_db, tmp_path
) -> None:
    result = run_stage(populated_db, tmp_path)
    by_id = {theme.theme_id: theme for theme in result.note.top_themes}

    for quote in result.note.quotes:
        assert quote.review_id in by_id[quote.theme_id].review_ids


def test_every_action_cites_a_theme_in_the_note(populated_db, tmp_path) -> None:
    result = run_stage(populated_db, tmp_path)
    known = {theme.theme_id for theme in result.note.top_themes}

    for action in result.note.actions:
        assert set(action.theme_ids) & known


def test_counts_in_the_note_come_from_the_database(populated_db, tmp_path) -> None:
    result = run_stage(populated_db, tmp_path)
    store = ReviewStore(populated_db)

    for theme in result.note.top_themes:
        members = [store.get_by_id(rid) for rid in theme.review_ids]
        assert all(m is not None for m in members)
        assert theme.size == len(members)
        ratings = [m.rating for m in members if m.rating is not None]
        assert theme.mean_rating == pytest.approx(sum(ratings) / len(ratings), abs=0.01)


def test_publish_artifacts_record_the_idempotency_key(populated_db, tmp_path) -> None:
    result = run_stage(populated_db, tmp_path)
    payload = json.loads(open(result.publish_path, encoding="utf-8").read())

    key = payload["idempotency_key"]
    assert key.startswith("groww:") and "-W" in key
    assert [call["target"] for call in payload["calls"]] == ["gdocs", "gmail"]
    assert payload["calls"][0]["title"].endswith(f"[{key}]")
    assert payload["calls"][1]["subject"].endswith(f"[{key}]")
    assert payload["mode"] == "dry_run"


def test_manifest_traces_themes_quotes_and_gates(populated_db, tmp_path) -> None:
    result = run_stage(populated_db, tmp_path)
    manifest = json.loads(open(result.manifest_path, encoding="utf-8").read())

    assert manifest["stage"] == "pulse"
    assert manifest["stages"] == ["cluster", "pulse"]
    assert len(manifest["gates"]) == 7
    assert all(gate["passed"] for gate in manifest["gates"])

    pulse = manifest["pulse"]
    assert len(pulse["top_themes"]) == 3
    assert len(pulse["quotes"]) == 3
    assert len(pulse["actions"]) == 3
    assert pulse["word_count"] == result.word_count

    # Every quote maps back to a member of the theme it illustrates.
    members = {theme["theme_id"]: theme["review_ids"] for theme in pulse["top_themes"]}
    for quote in pulse["quotes"]:
        assert quote["review_id"] in members[quote["theme_id"]]


def test_cluster_manifest_is_extended_not_replaced(populated_db, tmp_path) -> None:
    """One manifest per run, or a questioned quote takes two files to trace."""
    result = run_stage(populated_db, tmp_path)
    manifest = json.loads(open(result.manifest_path, encoding="utf-8").read())

    assert manifest["clustering"]["rank_by"] == "priority"
    assert manifest["checks"]["themes_capped"] is True
    assert manifest["checks"]["balanced"] is True
    assert manifest["artifacts"]["clusters"].endswith("clusters.json")
    assert manifest["artifacts"]["note"].endswith("note.md")


def test_an_existing_cluster_result_is_reused_in_the_same_run(
    populated_db, tmp_path
) -> None:
    cluster = run_cluster_stage(
        window_weeks=8,
        settings=load_settings(),
        db_path=populated_db,
        runs_dir=tmp_path / "runs",
        mode="keyword_fallback",
        use_llm=False,
    )
    result = run_pulse_stage(
        cluster=cluster,
        settings=load_settings(),
        db_path=populated_db,
        runs_dir=tmp_path / "runs",
        use_llm=False,
    )

    assert result.run_id == cluster.run_id
    assert result.note.top_themes == cluster.themes[:3]
    assert (tmp_path / "runs" / cluster.run_id / "note.md").is_file()


def test_offline_run_is_recorded_rather_than_failing(populated_db, tmp_path) -> None:
    result = run_stage(populated_db, tmp_path)
    assert result.compose_source == "heuristic"
    assert result.attempts == 1


def test_gate_failure_publishes_nothing_but_keeps_the_evidence(
    populated_db, tmp_path, monkeypatch
) -> None:
    settings = load_settings()
    monkeypatch.setattr(settings.pulse, "max_words", 20)

    result = run_pulse_stage(
        window_weeks=8,
        settings=settings,
        db_path=populated_db,
        runs_dir=tmp_path / "runs",
        mode="keyword_fallback",
        use_llm=False,
        cluster_use_llm=False,
    )

    assert result.passed is False
    assert "word_count" in [g["gate"] for g in result.gates if not g["passed"]]
    run_dir = tmp_path / "runs" / result.run_id
    assert not (run_dir / "note.md").exists()
    assert not (run_dir / "publish.json").exists()
    assert (run_dir / "note.rejected.md").is_file()

    manifest = json.loads(open(result.manifest_path, encoding="utf-8").read())
    assert manifest["publish"]["published"] is False
    assert manifest["artifacts"]["rejected_note"].endswith("note.rejected.md")


def test_a_recoverable_failure_is_retried_exactly_once(
    populated_db, tmp_path, monkeypatch
) -> None:
    settings = load_settings()
    monkeypatch.setattr(settings.pulse, "max_words", 20)

    result = run_pulse_stage(
        window_weeks=8,
        settings=settings,
        db_path=populated_db,
        runs_dir=tmp_path / "runs",
        mode="keyword_fallback",
        use_llm=False,
        cluster_use_llm=False,
    )

    manifest = json.loads(open(result.manifest_path, encoding="utf-8").read())
    attempts = manifest["pulse"]["attempts"]
    assert result.attempts == 2
    assert [entry["attempt"] for entry in attempts] == [1, 2]
    assert attempts[0]["retry"] is True
    assert attempts[1]["retry"] is False
    assert "retry budget exhausted" in attempts[1]["reason"]


def test_empty_window_raises(tmp_path) -> None:
    ReviewStore(tmp_path / "empty.db")
    with pytest.raises(ValueError, match="No reviews to cluster"):
        run_pulse_stage(
            window_weeks=8,
            settings=load_settings(),
            db_path=tmp_path / "empty.db",
            runs_dir=tmp_path / "runs",
            mode="keyword_fallback",
            use_llm=False,
            cluster_use_llm=False,
        )
