"""The record one dispatch produces: what ran, from where, and at which commit.

An envelope is the only durable evidence a maintenance suite leaves, so it is
built in one place — `build_envelope` — rather than assembled field by field by
each caller. Two of its fields are bounded, and that bounding is the reason this
module exists.

Output is truncated, never rejected. A script that emits more than `OUTPUT_LIMIT`
is running, not misbehaving: the two five-minute Prometheus exporters alone
exceed it. Both ends are kept because the head says what the run was doing and
the *tail* is where a failure states itself — a record that kept only the head
would report every overrun as a silent success. The marker between them names how
many bytes went missing, so the gap is greppable instead of merely shorter.

A script may also report structured data by ending its stdout with a
` ```spectre ` fenced JSON object. The fence must be last, because a fence
followed by prose is a code block someone quoted rather than a payload — and
treating it as one would let ordinary output shape a record. A payload that is
absent, misplaced, not an object, not valid JSON or simply too large is not an
error: the run still happened, and discarding the payload would be a worse lie
than a record without one — the fence is still there in the tail to be read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from packages.dispatch.resolve import ResolvedAction

# Bytes of each stream kept in a record. Sixty-four KiB holds any diagnostic a
# human reads — a stack trace, a failing command, a diffstat — and the exporters
# that overrun it are still fully diagnosable from their tail.
OUTPUT_LIMIT = 65536

# Bytes of JSON in a payload. The same bound as a stream, so a record's payload is
# no bigger than its output and Task 6 can size one column instead of guessing.
PAYLOAD_LIMIT = OUTPUT_LIMIT

# The fence a payload arrives in, and the fence that must close it last.
_FENCE_OPEN = "```spectre"
_FENCE_CLOSE = "```"


class Status(StrEnum):
    """How a run ended.

    A string enum whose value is the lowercase word, because the value is the
    contract: the store writes `status.value` and the CLI compares against it, so
    renaming a member must not change a stored record's meaning. Only SUCCESS and
    FAILED come from an exit code; TIMEOUT, MISSING and REFUSED are the ways a
    run ends without ever reaching an exit code.

    `StrEnum` rather than `str, Enum` — the latter is deprecated by the `UP` lint
    rules, and it also renders as `Status.SUCCESS` inside an f-string, where a
    status printed into a record or a log line should read `success`.
    """

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    MISSING = "missing"
    REFUSED = "refused"


@dataclass(frozen=True)
class Envelope:
    """What one dispatch did, in a form that can be stored and compared.

    The job is its name rather than the `Job` it came from: a record outlives the
    registry entry, and one that held the object would be rewritten every time a
    field was added to the registry.
    """

    job: str
    trigger: str
    started_at: datetime
    duration_ms: int
    exit_code: int | None
    resolved_path: str
    git_commit: str
    git_dirty: bool
    stdout_tail: str
    stderr_tail: str
    status: Status
    payload: dict[str, Any] | None


def status_for_exit_code(code: int) -> Status:
    """SUCCESS for zero, FAILED for everything else.

    From the exit code alone: a script may print `error` and exit 0, or print
    nothing and exit 1, and reading the verdict out of the text would let either
    one lie.
    """
    return Status.SUCCESS if code == 0 else Status.FAILED


def marker(elided: int) -> str:
    """The line that stands in for the bytes dropped from the middle.

    Public because the runner builds the same head-and-tail window while it reads,
    and a second copy of this format would be a second definition of what an elision
    looks like — the notice a record carries has to be the same one either way.
    """
    return f"\n... [{elided} bytes elided] ...\n"


# An upper bound on any marker, derived from the format itself so it cannot drift
# from it: 10**20 is 21 digits, which no host can emit, so this is as wide as a
# marker gets. `truncate_output` budgets the content against *this* rather than
# against the count it will print, which it cannot know until it has sliced:
# reserving the widest marker makes the bound provable in one pass, at the cost of a
# few bytes of tail.
MAX_MARKER_LEN = len(marker(10**20))


def byte_len(text: str) -> int:
    """How many bytes `text` occupies encoded, which is the unit bounded here.

    Encoded the same way `truncate_output` encodes, so the count cannot disagree
    with what is kept — invalid bytes are dropped rather than raising, because
    this module's contract is to bound whatever a script wrote, including output
    that is not valid text.
    """
    return len(text.encode("utf-8", "ignore"))


def truncate_output(text: str, limit: int = OUTPUT_LIMIT) -> str:
    """`text` bounded to `limit` bytes, head and tail kept around an elision marker.

    The marker is inside the budget, so the result is at most `limit` bytes and the
    limit is a bound a column can be trusted to hold. The one floor on that claim is
    a limit too small for head + marker + tail at all: there the marker is returned
    whole and nothing else, because a record that silently drops the notice that
    output was elided is the one outcome this function exists to prevent. So the
    result is at most `max(limit, len(marker) + 2)` — exactly `limit` for any limit
    that can hold the marker at all.

    A non-positive `limit` is the one budget that gets nothing at all, not even the
    marker: it is a caller asking for no output, and returning the notice would
    return more than was asked for. Every limit from 1 up gets at least the notice.

    The *tail* is never dropped where there is room for it, because that is where a
    failure states itself.

    Slicing is by bytes, since a limit is a size on disk and the marker counts bytes:
    a cut that lands inside a multi-byte character drops the partial bytes and the
    character is dropped whole, so a stored record never carries half a one.
    """
    if limit <= 0:
        return ""
    data = text.encode("utf-8", "ignore")
    if len(data) <= limit:
        return text

    # The marker comes out of the budget before the content does, so `per_side` is
    # what is left after reserving room for the widest marker. Decided before any
    # slicing: with no room for a byte on each side there is nothing to put the
    # marker between, and a zero-width slice would be the whole string, not empty.
    per_side = (limit - MAX_MARKER_LEN) // 2
    if per_side < 1:
        return marker(len(data))

    head = data[:per_side].decode("utf-8", "ignore")
    tail = data[-per_side:].decode("utf-8", "ignore")
    # Counted from what survives rather than from the cut points, so a cut inside a
    # multi-byte character cannot make the marker overstate what is still shown.
    elided = len(data) - byte_len(head) - byte_len(tail)
    return f"{head}{marker(elided)}{tail}"


def parse_payload(stdout: str) -> dict[str, Any] | None:
    """The JSON object in a trailing ` ```spectre ` fence, or None.

    None for absent, misplaced, non-object and unparseable fences alike, and it
    never raises: a payload is an optional extra, and one that cannot be read must
    not take down the record of a run that actually happened. The fence must be
    the final non-empty content, so quoted code blocks and trailing prose cannot
    inject one.

    A payload larger than `PAYLOAD_LIMIT` is dropped whole rather than truncated,
    because half a JSON object is not a payload and the run is still recorded by its
    exit code either way — the fence is still in the tail for an operator to read.

    One cost of finding the fence by scanning lines: `str.splitlines()` also breaks
    on `\\v \\f \\x1c \\x1d \\x1e \\x85` and U+2028/U+2029, and the JSON decoder
    accepts those raw inside a string, so a payload containing one is lost. A loss,
    never a crash, and never the run itself.
    """
    lines = stdout.splitlines()

    last = len(lines) - 1
    while last >= 0 and not lines[last].strip():
        last -= 1
    if last < 0 or lines[last].strip() != _FENCE_CLOSE:
        return None

    first = -1
    for index in range(last - 1, -1, -1):
        if lines[index].strip() == _FENCE_OPEN:
            first = index
            break
    if first < 0:
        return None

    body = "\n".join(lines[first + 1 : last])
    if byte_len(body) > PAYLOAD_LIMIT:
        return None

    try:
        decoded = json.loads(body)
    # RecursionError is json's own overflow on deeply nested untrusted text, and
    # belongs to "unparseable" for the same reason JSONDecodeError does.
    except (ValueError, RecursionError):
        return None
    return decoded if isinstance(decoded, dict) else None


def build_envelope(
    resolved: ResolvedAction,
    trigger: str,
    started_at: datetime,
    duration_ms: int,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    status: Status,
) -> Envelope:
    """The record of one finished run.

    The single way to build an `Envelope`, so a caller cannot store unbounded
    output or skip payload parsing by assembling the fields itself. Every text field
    is bounded — both streams by `OUTPUT_LIMIT`, the payload by `PAYLOAD_LIMIT` — so
    no single field can inflate a record past what the store sized for it.
    """
    return Envelope(
        job=resolved.job.name,
        trigger=trigger,
        started_at=started_at,
        duration_ms=duration_ms,
        exit_code=exit_code,
        resolved_path=str(resolved.path),
        git_commit=resolved.git_commit,
        git_dirty=resolved.git_dirty,
        stdout_tail=truncate_output(stdout),
        stderr_tail=truncate_output(stderr),
        status=status,
        # Read from the whole stdout, not the tail: bounding what is *stored* must
        # not lose what the run actually emitted.
        payload=parse_payload(stdout),
    )
