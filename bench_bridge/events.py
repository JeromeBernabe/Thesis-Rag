"""Versioned NDJSON event protocol between the sidecar and the desktop app.

The sidecar writes one JSON object per line to stdout. The Rust host parses each
line, persists whatever it needs, and re-emits it to the webview so the Run page
can animate while the experiment is still running.

Envelope
--------
Every line is::

    {"v": 1, "seq": 12, "ts_ms": 1750000000000,
     "run_id": "…", "type": "retrieval", "data": {…}}

``v`` is the schema version. It is bumped only for incompatible changes, and
the Rust side refuses events whose major version it does not know, so an old
app can never silently mis-read a newer sidecar.

Non-finite floats
-----------------
The RAGAS judge legitimately produces ``NaN`` when it cannot extract statements
(``src/ragas_eval.py`` logs "score = NaN"). ``json.dump`` would emit the bare
token ``NaN``, which is **invalid JSON** and makes ``serde_json`` reject the
whole line - taking down the live view over one missing metric. Every value
therefore goes through :func:`sanitize`, which maps non-finite floats to
``null`` and recurses through lists/dicts/tuples.
"""

from __future__ import annotations

import json
import math
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TextIO

__all__ = [
    "SCHEMA_VERSION",
    "EventType",
    "PHASES",
    "RunEvent",
    "EventEmitter",
    "sanitize",
    "parse_envelope",
    "EnvelopeError",
]

#: Schema version. Bump the major part only for breaking changes.
SCHEMA_VERSION = 1

#: Document ids are truncated to this length before being put on the wire.
#: FinTech ids look like ``MRO/2006/page_93.pdf-4``; the full corpus id is not
#: needed to match a retrieved chunk against its 3D coordinate.
MAX_ID_LEN = 200


class EventType:
    """Every event type the sidecar can emit.

    Kept as plain string constants rather than an ``Enum`` so the value written
    to the wire is exactly the constant, and so the TypeScript mirror in
    ``desktop/src/types/events.ts`` is a trivially checkable 1:1 list.
    """

    RUN_STARTED = "run_started"
    PHASE = "phase"
    INDEX_PROGRESS = "index_progress"
    PROJECTION_READY = "projection_ready"
    PROMPT_STARTED = "prompt_started"
    EMBEDDING = "embedding"
    DECISION = "decision"
    RETRIEVAL = "retrieval"
    GENERATION = "generation"
    RAGAS = "ragas"
    REWARD = "reward"
    TRAIN_STEP = "train_step"
    PROMPT_COMPLETED = "prompt_completed"
    STATS = "stats"
    LOG = "log"
    RUN_FINISHED = "run_finished"
    RUN_FAILED = "run_failed"

    @classmethod
    def all(cls) -> list[str]:
        return [
            value
            for name, value in sorted(vars(cls).items())
            if not name.startswith("_") and isinstance(value, str)
        ]


#: Coarse run phases, reported via ``EventType.PHASE``.
PHASES = (
    "preflight",
    "index",
    "projection",
    "system_a",
    "system_b_train",
    "system_b_infer",
    "stats",
    "done",
)


class EnvelopeError(ValueError):
    """Raised when a line cannot be read as a valid event envelope."""


def sanitize(value: Any) -> Any:
    """Recursively make ``value`` safe for ``json.dumps``.

    - ``NaN`` / ``+Inf`` / ``-Inf`` become ``None``.
    - floats are coerced to plain Python floats so numpy scalars serialise.
    - ``bytes`` are decoded with replacement rather than raising.
    - dict keys are coerced to ``str``.
    """
    if value is None or isinstance(value, (bool, str)):
        return value

    # numpy scalars expose .item(); avoid importing numpy here since the
    # emitter must work in the slim projection-only code path too.
    if hasattr(value, "item") and hasattr(value, "dtype"):
        try:
            return sanitize(value.item())
        except (ValueError, AttributeError):
            return str(value)

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value

    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")

    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [sanitize(v) for v in value]

    return str(value)


def short_id(value: Any, limit: int = MAX_ID_LEN) -> str:
    """Stringify a document/prompt id and bound its length."""
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


@dataclass(frozen=True)
class RunEvent:
    """One decoded event."""

    v: int
    seq: int
    ts_ms: int
    run_id: str
    type: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "v": self.v,
            "seq": self.seq,
            "ts_ms": self.ts_ms,
            "run_id": self.run_id,
            "type": self.type,
            "data": self.data,
        }


def parse_envelope(raw: str | bytes) -> RunEvent:
    """Parse and validate one NDJSON line.

    Raises :class:`EnvelopeError` for anything the Rust side must not trust.
    Kept deliberately strict: a malformed event is a bug worth surfacing, and
    silently dropping it would leave a chart quietly missing points.
    """
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8", errors="replace")
    line = raw.strip()
    if not line:
        raise EnvelopeError("empty line")

    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        raise EnvelopeError(f"invalid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise EnvelopeError(f"expected object, got {type(obj).__name__}")

    missing = [k for k in ("v", "seq", "ts_ms", "run_id", "type") if k not in obj]
    if missing:
        raise EnvelopeError(f"missing keys: {','.join(missing)}")

    version = obj["v"]
    if not isinstance(version, int):
        raise EnvelopeError(f"v must be int, got {type(version).__name__}")
    if version != SCHEMA_VERSION:
        raise EnvelopeError(f"unsupported schema version {version}")

    data = obj.get("data", {})
    if not isinstance(data, dict):
        raise EnvelopeError("data must be an object")

    return RunEvent(
        v=version,
        seq=int(obj["seq"]),
        ts_ms=int(obj["ts_ms"]),
        run_id=str(obj["run_id"]),
        type=str(obj["type"]),
        data=data,
    )


class EventEmitter:
    """Writes sequenced NDJSON events to a text stream.

    Every ``emit`` takes the stream lock, writes one line and flushes
    immediately. Flushing per line matters: this is the transport the Run page
    renders from, so an unflushed buffer would show the experiment as stalled.
    """

    def __init__(
        self,
        run_id: str,
        stream: TextIO | None = None,
        clock: Callable[[], float] = time.time,
        on_error: Callable[[Exception, str], None] | None = None,
    ):
        self.run_id = str(run_id)
        self._stream = stream if stream is not None else sys.stdout
        self._clock = clock
        self._seq = 0
        self._lock = threading.Lock()
        self._on_error = on_error

    @property
    def seq(self) -> int:
        """Sequence number of the most recently emitted event."""
        return self._seq

    def emit(self, event_type: str, data: dict | None = None) -> RunEvent:
        """Write one event. Never raises on I/O problems - a dead pipe must not
        abort an hours-long experiment; it is reported via ``on_error``."""
        with self._lock:
            self._seq += 1
            event = RunEvent(
                v=SCHEMA_VERSION,
                seq=self._seq,
                ts_ms=int(self._clock() * 1000),
                run_id=self.run_id,
                type=str(event_type),
                data=sanitize(data or {}),
            )
            try:
                self._stream.write(json.dumps(event.to_dict(), allow_nan=False))
                self._stream.write("\n")
                self._stream.flush()
            except Exception as exc:  # noqa: BLE001 - transport must not kill the run
                if self._on_error is not None:
                    self._on_error(exc, event.type)
            return event

    # ------------------------------------------------------------------ sugar

    def log(self, level: str, message: str) -> RunEvent:
        return self.emit(EventType.LOG, {"level": level, "message": message})

    def info(self, message: str) -> RunEvent:
        return self.log("info", message)

    def warning(self, message: str) -> RunEvent:
        return self.log("warning", message)

    def error(self, message: str) -> RunEvent:
        return self.log("error", message)

    def phase(self, phase: str, detail: str = "") -> RunEvent:
        return self.emit(EventType.PHASE, {"phase": phase, "detail": detail})


def now_ms() -> int:
    """Current wall-clock time in milliseconds since the epoch."""
    return int(time.time() * 1000)