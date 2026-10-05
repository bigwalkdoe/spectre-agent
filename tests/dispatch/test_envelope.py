"""Tests for the run envelope: bounded output, the payload fence, and provenance.

Truncation is the part that earns this module its keep. Output arrives from a
script nobody controls, and the two five-minute Prometheus exporters alone
exceed the limit, so the record must stay bounded while keeping the *end* of the
run — which is where a failure explains itself.

Every case here is a string in memory. Nothing in this file runs an action, reads
the host's maintenance suite or touches a scheduler.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from packages.dispatch.envelope import (
    OUTPUT_LIMIT,
    PAYLOAD_LIMIT,
    Envelope,
    Status,
    build_envelope,
    parse_payload,
    status_for_exit_code,
    truncate_output,
)
from packages.dispatch.resolve import ResolvedAction
from tests.dispatch.conftest import make_job

_STARTED = datetime(2026, 10, 5, 3, 0, tzinfo=UTC)


def _resolved(tmp_path: Path, **overrides: Any) -> ResolvedAction:
    """A resolved action that never touched the filesystem: `ResolvedAction` is a
    plain frozen record, so building one directly keeps this file hermetic."""
    values: dict[str, Any] = {
        "job": make_job(),
        "path": tmp_path / "ok.sh",
        "git_commit": "abc1234",
        "git_dirty": True,
    }
    values.update(overrides)
    return ResolvedAction(**values)


def _fenced(body: str) -> str:
    """`body` as the trailing payload fence a script would print."""
    return f"doing work\n```spectre\n{body}\n```\n"


def test_status_comes_from_exit_code_not_output_text() -> None:
    """A script can print 'error' and exit 0, or stay silent and exit 1."""
    assert status_for_exit_code(0) is Status.SUCCESS
    assert status_for_exit_code(1) is Status.FAILED
    assert status_for_exit_code(127) is Status.FAILED


def test_status_values_are_the_words_the_store_persists() -> None:
    """The record is stored and compared by value, so the word is the contract
    between this module, the store and the CLI — not the member name."""
    assert Status.SUCCESS.value == "success"
    assert {member.value for member in Status} == {"success", "failed", "timeout", "missing", "refused"}
    assert Status("failed") is Status.FAILED


def test_truncate_keeps_head_and_tail() -> None:
    """Review Focus 2: the 5-minute exporters exceed the limit."""
    text = "A" * 100_000
    got = truncate_output(text, limit=1000)
    assert got.startswith("A")
    assert got.endswith("A")
    assert "elided" in got
    assert len(got) <= 1000


def test_truncate_is_a_noop_under_the_limit() -> None:
    assert truncate_output("short", limit=65536) == "short"


def test_truncate_leaves_input_at_the_limit_untouched() -> None:
    """Exactly at the limit is not over it. A marker here would claim bytes were
    dropped that are all still present."""
    text = "A" * 100
    got = truncate_output(text, limit=100)
    assert got == text
    assert "elided" not in got


def test_truncate_of_empty_output_is_empty() -> None:
    assert truncate_output("") == ""
    assert truncate_output("", limit=0) == ""


def test_truncate_with_no_room_returns_nothing() -> None:
    """A limit of zero must not slice with `-0`, which in Python means "from the
    start" and would return the whole string."""
    assert truncate_output("A" * 100, limit=0) == ""
    assert truncate_output("A" * 100, limit=-1) == ""


def test_truncate_keeps_the_actual_tail_not_a_second_head() -> None:
    """The tail is the reason truncation is allowed at all: it carries the
    exit-bearing lines. Both ends of the input differ, and one case puts them the
    same distance from the middle, so neither a dropped tail nor a second head can
    slip through — the all-`A` inputs elsewhere cannot tell head from tail."""
    for filler in (5000, 5008):
        text = "HEAD" + "x" * filler + "TAIL"
        got = truncate_output(text, limit=1000)
        assert got.startswith("HEAD")
        assert got.endswith("TAIL")
        # Whatever survived came from both ends, so the marker accounts for the rest.
        kept = got.count("x") + len("HEAD") + len("TAIL")
        assert f"[{len(text) - kept} bytes elided]" in got


def test_truncate_marker_names_the_bytes_it_dropped() -> None:
    """The marker is what makes the gap auditable, so its format and its count are
    both pinned — and the whole result, marker included, fits the limit."""
    limit = 100
    marker = "\n... [246 bytes elided] ...\n"
    got = truncate_output("A" * 300, limit=limit)
    assert marker in got
    assert got == "A" * 27 + marker + "A" * 27
    assert len(got) <= limit


def test_truncate_stays_within_its_limit_wherever_there_is_room_for_a_marker() -> None:
    """The invariant: the result is at most `limit`. Below the width the marker
    itself needs, no room is left for content on both sides, so the marker is
    returned whole and the bound becomes `max(limit, len(marker) + 2)` — the gap
    must be announced even when there is no room for what surrounds it."""
    text = "A" * 5_000
    floor = len("\n... [5000 bytes elided] ...\n") + 2
    for limit in (1, 8, 29, 47, 48, 100, 1_000, OUTPUT_LIMIT):
        got = truncate_output(text, limit=limit)
        assert len(got) <= max(limit, floor), f"limit={limit} gave {len(got)}"
    for limit in (48, 100, 1_000, OUTPUT_LIMIT):
        assert len(truncate_output(text, limit=limit)) <= limit, f"limit={limit}"


def test_truncate_returns_the_marker_alone_when_the_limit_cannot_hold_it() -> None:
    """Too small for head + marker + tail: the marker wins. A record that silently
    drops the notice that output was elided is the one outcome this function exists
    to prevent, so the notice is kept and the surrounding output is not."""
    text = "H" * 500 + "EXIT-1-AT-THE-END"
    got = truncate_output(text, limit=8)
    assert got == "\n... [517 bytes elided] ...\n"
    assert "elided" in got


def test_truncate_does_not_split_a_multibyte_character() -> None:
    """A byte budget rarely divides by the character width, so a cut lands inside a
    character. Half a character in a stored record is corruption, not truncation."""
    text = "→" * 1000  # three bytes each
    total = len(text.encode())
    for limit in (300, 302):
        got = truncate_output(text, limit=limit)
        assert "�" not in got
        assert got.startswith("→")
        assert got.endswith("→")
        kept = got.count("→")
        assert 0 < kept <= limit // 3
        # Whatever survives is whole characters, so the marker accounts for exactly
        # the rest of the bytes — a count taken at the cut points would overstate it.
        assert f"[{total - kept * 3} bytes elided]" in got
        assert len(got.encode()) <= limit


def test_parse_payload_reads_trailing_fence() -> None:
    out = "doing work\n```spectre\n" + json.dumps({"metrics": {"bytes": 42}}) + "\n```\n"
    assert parse_payload(out) == {"metrics": {"bytes": 42}}


def test_parse_payload_returns_none_when_absent() -> None:
    assert parse_payload("plain output\n") is None


def test_parse_payload_returns_none_when_invalid_json() -> None:
    assert parse_payload("```spectre\n{not json}\n```\n") is None


def test_parse_payload_ignores_a_non_final_fence() -> None:
    out = '```spectre\n{"a": 1}\n```\ntrailing prose\n'
    assert parse_payload(out) is None


def test_parse_payload_rejects_a_non_object_payload() -> None:
    """The field is a dict, so a JSON array or string is not a payload however
    validly it is encoded."""
    assert parse_payload("```spectre\n[1, 2]\n```\n") is None
    assert parse_payload('```spectre\n"just a string"\n```\n') is None


def test_parse_payload_does_not_raise_on_pathological_json() -> None:
    """Deeply nested input overflows the JSON decoder. A payload is optional, so
    this yields None like any other unparseable fence instead of taking the run
    record down with it."""
    assert parse_payload("```spectre\n" + "[" * 100_000 + "\n```\n") is None


def test_parse_payload_keeps_a_payload_just_under_the_limit() -> None:
    blob = "z" * (PAYLOAD_LIMIT - 64)
    assert parse_payload(_fenced(json.dumps({"blob": blob}))) == {"blob": blob}


def test_parse_payload_drops_a_payload_over_the_limit() -> None:
    """Half a JSON object is not a payload, so an oversized one is dropped whole
    rather than truncated into something unparseable."""
    blob = "z" * PAYLOAD_LIMIT
    assert parse_payload(_fenced(json.dumps({"blob": blob}))) is None


def test_parse_payload_loses_a_payload_containing_a_line_separator() -> None:
    """`str.splitlines()` breaks on U+2028 as well as on newlines, and the JSON
    decoder accepts that character raw inside a string. The payload is lost, not the
    run — the documented cost of finding the fence by scanning lines."""
    separator = "\u2028"
    body = f'{{"note": "a{separator}b"}}'
    assert json.loads(body) == {"note": f"a{separator}b"}
    assert parse_payload(_fenced(body)) is None


def test_envelope_is_immutable() -> None:
    e = Envelope(
        job="backups/backup-all",
        trigger="cli",
        started_at=datetime.now(UTC),
        duration_ms=1,
        exit_code=0,
        resolved_path="/x",
        git_commit="abc",
        git_dirty=False,
        stdout_tail="",
        stderr_tail="",
        status=Status.SUCCESS,
        payload=None,
    )
    try:
        e.status = Status.FAILED  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("expected frozen")


def test_build_envelope_records_the_job_name_and_provenance(tmp_path: Path) -> None:
    """The store keeps the action name and the commit it ran from, so both must
    come from the resolution rather than from what the caller passes."""
    got = build_envelope(
        _resolved(tmp_path),
        trigger="cron",
        started_at=_STARTED,
        duration_ms=12,
        exit_code=0,
        stdout="",
        stderr="",
        status=Status.SUCCESS,
    )
    assert got.job == "ok"
    assert got.resolved_path == str(tmp_path / "ok.sh")
    assert (got.git_commit, got.git_dirty) == ("abc1234", True)
    assert got.trigger == "cron"
    assert got.status is Status.SUCCESS


def test_build_envelope_bounds_both_streams_and_reads_the_payload(tmp_path: Path) -> None:
    """One constructor, so truncation and payload parsing cannot be skipped, and the
    tail survives: for an overrun run the last lines are the whole diagnosis."""
    payload = {"metrics": {"bytes": 42}}
    stdout = "head\n" + "A" * 200_000 + "\n```spectre\n" + json.dumps(payload) + "\n```\n"
    got = build_envelope(
        _resolved(tmp_path),
        trigger="cli",
        started_at=_STARTED,
        duration_ms=5,
        exit_code=1,
        stdout=stdout,
        stderr="E" * 200_000,
        status=Status.FAILED,
    )
    assert got.payload == payload
    assert got.stdout_tail.endswith("```\n")
    assert got.stderr_tail.startswith("E") and got.stderr_tail.endswith("E")
    assert len(got.stdout_tail) <= OUTPUT_LIMIT
    assert len(got.stderr_tail) <= OUTPUT_LIMIT


def test_build_envelope_drops_an_oversized_payload_but_keeps_the_run(tmp_path: Path) -> None:
    """An oversized payload must not make this the one unbounded field in a record
    every other field of is bounded. Dropping it still loses nothing silently: the
    exit code decides the status, and the fence is still there in the tail for an
    operator to see."""
    stdout = "working\n" + "x" * 200_000 + "\n```spectre\n" + json.dumps({"blob": "z" * PAYLOAD_LIMIT}) + "\n```\n"
    got = build_envelope(
        _resolved(tmp_path),
        trigger="cli",
        started_at=_STARTED,
        duration_ms=5,
        exit_code=0,
        stdout=stdout,
        stderr="",
        status=status_for_exit_code(0),
    )
    assert got.payload is None
    assert got.status is Status.SUCCESS
    assert got.exit_code == 0
    assert got.stdout_tail.endswith("```\n")
    assert len(got.stdout_tail) <= OUTPUT_LIMIT


def test_build_envelope_keeps_a_missing_exit_code(tmp_path: Path) -> None:
    """An action that was refused or killed never exited, and the record must not
    invent an exit code for it."""
    got = build_envelope(
        _resolved(tmp_path),
        trigger="cron",
        started_at=_STARTED,
        duration_ms=0,
        exit_code=None,
        stdout="",
        stderr="no such action",
        status=Status.MISSING,
    )
    assert got.exit_code is None
    assert got.status is Status.MISSING
