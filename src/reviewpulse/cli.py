"""CLI entry point for the Groww review intelligence agent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reviewpulse import __version__
from reviewpulse.api.bind import BindError, resolve_bind, serve_api
from reviewpulse.config import load_settings
from reviewpulse.orchestrator import (
    export_reviews,
    fetch_export,
    ingest_reviews,
    run_cluster_stage,
    run_pipeline,
    run_pulse_stage,
)
from reviewpulse.mcp.client import MCPError, inspect_publish_servers
from reviewpulse.sources.play_fetch import PlayFetchError

DEFAULT_WINDOW_WEEKS = 12


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reviewpulse",
        description="Groww Play Store review intelligence agent - weekly pulse pipeline",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the full pipeline")
    run_mutex = run_parser.add_mutually_exclusive_group()
    run_mutex.add_argument(
        "--dry-run",
        action="store_true",
        help="Produce local artifacts only; skip MCP publishing (Phase 3+)",
    )
    run_mutex.add_argument(
        "--send",
        action="store_true",
        help="Send the pulse via MCP send_email instead of creating a Gmail draft (Phase 6)",
    )
    run_parser.add_argument(
        "--window-weeks",
        type=int,
        default=DEFAULT_WINDOW_WEEKS,
        metavar="N",
        help=f"Review lookback window in weeks (default: {DEFAULT_WINDOW_WEEKS})",
    )

    fetch_parser = subparsers.add_parser(
        "fetch",
        help="Download public Play Store reviews into data/raw/",
    )
    fetch_parser.add_argument(
        "--window-weeks",
        type=int,
        default=None,
        metavar="N",
        help="Review lookback window in weeks (default: from settings)",
    )
    fetch_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="PATH",
        help="Output CSV path (default: data/raw/play_<package>_<date>.csv)",
    )
    fetch_parser.add_argument("--lang", default=None, help="Review language (default: from settings)")
    fetch_parser.add_argument("--country", default=None, help="Store country (default: from settings)")
    fetch_parser.add_argument(
        "--ingest",
        action="store_true",
        help="Ingest the downloaded export immediately",
    )

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Download (if needed) and store reviews",
    )
    ingest_parser.add_argument(
        "--file",
        default=None,
        metavar="PATH",
        help="Ingest an existing export instead of downloading a fresh one",
    )
    ingest_parser.add_argument(
        "--window-weeks",
        type=int,
        default=None,
        metavar="N",
        help="Review lookback window in weeks (default: from settings)",
    )
    ingest_parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        metavar="PATH",
        help="SQLite database path (default: data/reviews.db)",
    )

    export_parser = subparsers.add_parser(
        "export",
        help="Write stored (scrubbed, filtered) reviews to data/exports/play_store.csv",
    )
    export_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="PATH",
        help="Output CSV path (default: data/exports/play_store.csv)",
    )
    export_parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        metavar="PATH",
        help="SQLite database path (default: data/reviews.db)",
    )

    cluster_parser = subparsers.add_parser(
        "cluster",
        help="Cluster and label stored reviews (Phase 2)",
    )
    cluster_parser.add_argument(
        "--window-weeks",
        type=int,
        default=None,
        metavar="N",
        help="Review lookback window in weeks (default: from settings)",
    )
    cluster_parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        metavar="PATH",
        help="SQLite database path (default: data/reviews.db)",
    )
    cluster_parser.add_argument(
        "--mode",
        choices=("embedding", "keyword_fallback"),
        default=None,
        help="Clustering backend (default: from settings)",
    )
    cluster_parser.add_argument(
        "--k-max",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of themes (default: from settings, 5)",
    )
    cluster_parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM labeling; use deterministic keyword labels",
    )

    pulse_parser = subparsers.add_parser(
        "pulse",
        help="Cluster, compose and validate the weekly note without fetching (Phase 3)",
    )
    pulse_parser.add_argument(
        "--window-weeks",
        type=int,
        default=None,
        metavar="N",
        help="Review lookback window in weeks (default: from settings)",
    )
    pulse_parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        metavar="PATH",
        help="SQLite database path (default: data/reviews.db)",
    )
    pulse_parser.add_argument(
        "--mode",
        choices=("embedding", "keyword_fallback"),
        default=None,
        help="Clustering backend (default: from settings)",
    )
    pulse_parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip all LLM calls; deterministic labels and prose frame",
    )
    pulse_parser.add_argument(
        "--show",
        action="store_true",
        help="Print the rendered note",
    )

    subparsers.add_parser(
        "mcp-check",
        help="Verify the hosted (or stdio) MCP server: auth, list_tools, required names",
    )

    schedule_parser = subparsers.add_parser(
        "schedule",
        help="Weekly job: incremental fetch → classify → pulse → Doc + mail (Phase 6)",
    )
    schedule_parser.add_argument(
        "--once",
        action="store_true",
        help="Run one tick now (Task Scheduler / cron body). Default waits for the next slot.",
    )
    schedule_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Produce local artifacts only; skip MCP publishing",
    )
    schedule_parser.add_argument(
        "--window-weeks",
        type=int,
        default=None,
        metavar="N",
        help="Rolling analysis window (default: from [schedule] / settings)",
    )
    schedule_parser.add_argument(
        "--full-window",
        action="store_true",
        help="Fetch the full lookback window instead of incremental new reviews",
    )

    serve_parser = subparsers.add_parser(
        "serve",
        help="Run the FastAPI console API (Phase 7). Pair with `npm run dev` in web/",
    )
    serve_parser.add_argument(
        "--host",
        default=None,
        help="Bind host (default: 127.0.0.1; 0.0.0.0 requires REVIEWPULSE_BIND_ALL=1)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (default: PORT env, else 8000)",
    )

    return parser


def _describe_app(result) -> str:
    if not result.app_title:
        return result.package_id
    developer = f" by {result.app_developer}" if result.app_developer else ""
    return f"{result.app_title}{developer} ({result.package_id})"


def _validate_window_weeks(parser: argparse.ArgumentParser, value: int) -> int:
    if value < 1 or value > 52:
        parser.error("--window-weeks must be between 1 and 52")
    return value


def _run_ingest(
    parser: argparse.ArgumentParser,
    file_path: Path,
    *,
    window_weeks: int,
    db_path: Path | None,
    settings,
) -> int:
    try:
        result = ingest_reviews(
            file_path,
            window_weeks=window_weeks,
            settings=settings,
            db_path=db_path,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"[reviewpulse] ingest failed: {exc}", file=sys.stderr)
        return 1

    print(f"[reviewpulse] Ingest complete - run_id={result.run_id}")
    print(f"  parsed:   {result.parsed_count}")
    print(f"  dropped:  {result.dropped_out_of_window} out of window, "
          f"{result.dropped_too_short} too short, "
          f"{result.dropped_non_english} not English")
    print(f"  accepted: {result.accepted_count} (window {result.window_weeks} weeks)")
    print(f"  inserted: {result.inserted_count}")
    print(f"  deduped:  {result.deduped_count}")
    print(f"  db:       {result.db_path}")
    print(f"  export:   {result.export_path} ({result.export_count} rows)")
    print(f"  manifest: {result.manifest_path}")
    if result.window.get("window_warning"):
        print(f"  warning:  {result.window['window_warning']}")
    return 0


def _print_cluster_result(result) -> None:
    print(f"[reviewpulse] Cluster complete - run_id={result.run_id}")
    print(
        f"  window:   {result.window.get('actual_start')} .. "
        f"{result.window.get('actual_end')}"
    )
    print(
        f"  reviews:  {result.clustered_reviews} clustered of {result.total_reviews} "
        f"({result.retention:.1%} retained; "
        f"{result.dropped_low_signal} low-signal dropped)"
    )
    print(
        f"  strategy: {result.strategy}"
        + (f" (silhouette {result.silhouette})" if result.silhouette is not None else "")
        + f", largest cluster {result.max_cluster_share:.1%}"
    )
    if result.embedding_model:
        print(
            f"  embed:    {result.embedding_model} "
            f"({result.embedding_cached} cached, {result.embedding_computed} computed)"
        )
    print(
        f"  labels:   {result.label_source_counts.get('llm', 0)} from LLM, "
        f"{result.label_source_counts.get('heuristic', 0)} keyword-derived"
    )

    print()
    header = f"  {'#':<2} {'theme':<34} {'n':>5} {'rating':>7} {'neg':>6} {'prio':>7} {'trend':>7}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for theme in result.themes:
        trend = "n/a" if theme.trend is None else f"{theme.trend:.2f}"
        if theme.emerging:
            trend += " ^"
        rating = "n/a" if theme.mean_rating is None else f"{theme.mean_rating:.2f}"
        print(
            f"  {theme.rank:<2} {theme.label[:34]:<34} {theme.size:>5} {rating:>7} "
            f"{theme.neg_share:>5.0%} {theme.priority:>7.1f} {trend:>7}"
        )

    print()
    for name, passed in result.checks.items():
        print(f"  [{'ok' if passed else 'FAIL'}] {name}")
    print(f"\n  clusters: {result.clusters_path}")
    print(f"  debug:    {result.debug_path}")
    print(f"  manifest: {result.manifest_path}")
    for warning in result.warnings:
        print(f"  warning:  {warning}")


def _print_pulse_result(result, *, show_note: bool) -> None:
    print(f"[reviewpulse] Pulse complete - run_id={result.run_id}")
    print(
        f"  note:     {result.word_count} words "
        f"({result.compose_source} prose, {result.attempts} attempt(s))"
    )

    print()
    for quote in result.quotes:
        rating = "n/a" if quote["rating"] is None else f"{quote['rating']}*"
        redundant = ", echoes an earlier quote" if quote["redundant"] else ""
        print(
            f"  quote {quote['theme_id']}: {quote['words']} words, {rating}, "
            f"score {quote['score']} (of {quote['candidates']} spans in "
            f"{quote['member_reviews']} reviews{redundant})"
        )

    print()
    for gate in result.gates:
        print(f"  [{'ok' if gate['passed'] else 'FAIL'}] {gate['gate']}: {gate['detail']}")

    print()
    if result.passed:
        print(f"  note:     {result.note_path}")
        print(f"  publish:  {result.publish_path}")
        if result.published and result.publish_result:
            print(f"  doc:      {result.publish_result.doc_id}")
            print(f"  draft:    {result.publish_result.draft_id}")
            if result.publish_result.message_id:
                print(f"  message:  {result.publish_result.message_id}")
    else:
        print(f"  rejected: {result.note_path} (nothing published)")
    print(f"  manifest: {result.manifest_path}")
    for warning in result.warnings:
        print(f"  warning:  {warning}")

    if show_note:
        print()
        print(_console_safe(result.rendered))


def _console_safe(text: str) -> str:
    """Print the note legibly even where the console codec cannot hold it."""
    from reviewpulse.pulse.render import to_ascii

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return to_ascii(text)
    return text


def main(argv: list[str] | None = None) -> int:
    # Review text and app names are non-ASCII; the default Windows console
    # codec raises rather than substituting.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        if args.send and args.dry_run:
            parser.error("--send and --dry-run cannot be combined")
        window_weeks = _validate_window_weeks(parser, args.window_weeks)
        try:
            passed = run_pipeline(
                dry_run=args.dry_run,
                window_weeks=window_weeks,
                send=args.send,
            )
        except (
            PlayFetchError,
            ValueError,
            FileNotFoundError,
            AssertionError,
            MCPError,
        ) as exc:
            print(f"[reviewpulse] run failed: {exc}", file=sys.stderr)
            return 1
        return 0 if passed else 1

    if args.command == "fetch":
        settings = load_settings()
        window_weeks = args.window_weeks or settings.default_window_weeks
        window_weeks = _validate_window_weeks(parser, window_weeks)
        try:
            result = fetch_export(
                window_weeks=window_weeks,
                settings=settings,
                out_path=args.out,
                lang=args.lang,
                country=args.country,
            )
        except PlayFetchError as exc:
            print(f"[reviewpulse] fetch failed: {exc}", file=sys.stderr)
            return 1

        print(f"[reviewpulse] Fetched {result.fetched_count} reviews for {result.package_id}")
        print(f"  app:    {_describe_app(result)}")
        print(f"  window: {result.window_start} .. {result.window_end} ({window_weeks} weeks)")
        print(f"  export: {result.export_path}")
        if result.coverage_warning:
            print(f"  warning: {result.coverage_warning}")

        if not args.ingest:
            return 0
        return _run_ingest(
            parser,
            Path(result.export_path),
            window_weeks=window_weeks,
            db_path=None,
            settings=settings,
        )

    if args.command == "ingest":
        settings = load_settings()
        window_weeks = args.window_weeks or settings.default_window_weeks
        window_weeks = _validate_window_weeks(parser, window_weeks)

        if args.file:
            export_path = Path(args.file)
        else:
            try:
                fetched = fetch_export(window_weeks=window_weeks, settings=settings)
            except PlayFetchError as exc:
                print(f"[reviewpulse] fetch failed: {exc}", file=sys.stderr)
                return 1
            print(f"[reviewpulse] Downloading reviews for {_describe_app(fetched)}")
            print(
                f"[reviewpulse] Downloaded {fetched.fetched_count} reviews "
                f"-> {fetched.export_path}"
            )
            if fetched.coverage_warning:
                print(f"[reviewpulse] warning: {fetched.coverage_warning}")
            export_path = Path(fetched.export_path)

        return _run_ingest(
            parser,
            export_path,
            window_weeks=window_weeks,
            db_path=args.db_path,
            settings=settings,
        )

    if args.command == "export":
        settings = load_settings()
        path, count = export_reviews(
            settings=settings,
            db_path=args.db_path,
            out_path=args.out,
        )
        print(f"[reviewpulse] Exported {count} stored reviews -> {path}")
        return 0

    if args.command == "cluster":
        settings = load_settings()
        window_weeks = args.window_weeks or settings.default_window_weeks
        window_weeks = _validate_window_weeks(parser, window_weeks)
        if args.k_max is not None and args.k_max < 1:
            parser.error("--k-max must be at least 1")
        try:
            result = run_cluster_stage(
                window_weeks=window_weeks,
                settings=settings,
                db_path=args.db_path,
                mode=args.mode,
                k_max=args.k_max,
                use_llm=False if args.no_llm else None,
            )
        except (ValueError, FileNotFoundError, AssertionError) as exc:
            print(f"[reviewpulse] cluster failed: {exc}", file=sys.stderr)
            return 1

        _print_cluster_result(result)
        return 0 if all(result.checks.values()) else 1

    if args.command == "pulse":
        settings = load_settings()
        window_weeks = args.window_weeks or settings.default_window_weeks
        window_weeks = _validate_window_weeks(parser, window_weeks)
        try:
            result = run_pulse_stage(
                window_weeks=window_weeks,
                settings=settings,
                db_path=args.db_path,
                mode=args.mode,
                use_llm=False if args.no_llm else None,
                cluster_use_llm=False if args.no_llm else None,
            )
        except (ValueError, FileNotFoundError, AssertionError) as exc:
            print(f"[reviewpulse] pulse failed: {exc}", file=sys.stderr)
            return 1

        _print_pulse_result(result, show_note=args.show)
        return 0 if result.passed else 1

    if args.command == "mcp-check":
        settings = load_settings()
        try:
            info = inspect_publish_servers(settings.mcp)
        except MCPError as exc:
            print(f"[reviewpulse] mcp-check failed: {exc}", file=sys.stderr)
            return 1
        print(f"[reviewpulse] MCP {info.get('transport')} ok")
        if info.get("url"):
            print(f"  url:      {info['url']}")
        if info.get("document_id"):
            print(f"  notebook: {info['document_id']}")
        tools = info.get("tools") or []
        if tools:
            print(f"  tools:    {', '.join(tools)}")
        if info.get("gdocs_tools"):
            print(f"  gdocs:    {', '.join(info['gdocs_tools'])}")
        if info.get("gmail_tools"):
            print(f"  gmail:    {', '.join(info['gmail_tools'])}")
        print(f"  draft:    {info.get('draft_tool') or settings.mcp.gmail.tools.create_draft}")
        print(f"  append:   {info.get('append_tool') or settings.mcp.gdocs.tools.append}")
        if info.get("send_email_present"):
            print(
                "  note:     send_email is on the server; called only with "
                "--send or reviewpulse schedule"
            )
        return 0

    if args.command == "schedule":
        settings = load_settings()
        window_weeks = args.window_weeks or settings.schedule.window_weeks
        window_weeks = _validate_window_weeks(parser, window_weeks)
        from reviewpulse.schedule.job import run_scheduled_job
        from reviewpulse.schedule.loop import run_schedule_loop

        try:
            if args.once:
                outcome = run_scheduled_job(
                    dry_run=args.dry_run,
                    window_weeks=window_weeks,
                    full_window=args.full_window,
                    settings=settings,
                )
                return outcome.exit_code
            return run_schedule_loop(
                dry_run=args.dry_run,
                window_weeks=window_weeks,
                full_window=args.full_window,
                settings=settings,
            )
        except (
            PlayFetchError,
            ValueError,
            FileNotFoundError,
            AssertionError,
            MCPError,
        ) as exc:
            print(f"[reviewpulse] schedule failed: {exc}", file=sys.stderr)
            return 1

    if args.command == "serve":
        settings = load_settings()
        try:
            bind = resolve_bind(
                args.host,
                args.port,
                settings_host=settings.console.api_host,
                settings_port=settings.console.api_port,
            )
            serve_api(bind.host, bind.port)
        except BindError as exc:
            print(f"[reviewpulse] {exc}", file=sys.stderr)
            return 1
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
