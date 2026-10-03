"""Tests for the NDJSON event protocol.

The critical behaviour is NaN handling. `src/ragas_eval.py` deliberately returns
``None`` for an unscoreable metric, but any float NaN that does reach the
encoder would be written as the bare token ``NaN`` - invalid JSON - and
``serde_json`` on the Rust side rejects the whole line. A single missing metric
would then blank the live Run page.
"""

from __future__ import annotations

import io
import json
import math
import threading

import pytest

from bench_bridge.events import (
    SCHEMA_VERSION,
    EnvelopeError,
    EventEmitter,
    EventType,
    PHASES,
    RunEvent,
    parse_envelope,
    sanitize,
    short_id,
)


class TestSanitize:
    def test_nan_becomes_none(self):
        assert sanitize(float("nan")) is None

    @pytest.mark.parametrize("value", [float("inf"), float("-inf")])
    def test_infinities_become_none(self, value):
        assert sanitize(value) is None

    def test_finite_floats_pass_through(self):
        assert sanitize(0.35) == 0.35

    def test_recurses_into_lists_and_dicts(self):
        out = sanitize({"a": [1, float("nan")], "b": {"c": float("inf")}})
        assert out == {"a": [1, None], "b": {"c": None}}

    def test_tuples_and_sets_become_lists(self):
        assert sanitize((1, 2)) == [1, 2]
        assert sorted(sanitize({1, 2})) == [1, 2]

    def test_coerces_numpy_scalars(self):
        numpy = pytest.importorskip("numpy")
        assert sanitize(numpy.float32(0.5)) == pytest.approx(0.5)
        assert sanitize(numpy.int64(7)) == 7
        assert sanitize(numpy.float32("nan")) is None

    def test_keys_are_stringified(self):
        assert sanitize({1: "a"}) == {"1": "a"}

    def test_bytes_are_decoded(self):
        assert sanitize(b"ok") == "ok"
        assert sanitize(b"\xff\xfe") == "\ufffd\ufffd"

    def test_unknown_objects_become_strings(self):
        class Thing:
            def __repr__(self) -> str:
                return "a thing"

        assert sanitize(Thing()) == "a thing"

    def test_output_is_json_encodable_without_nan(self):
        """The whole point: strict json.dumps must succeed."""
        payload = {"f": float("nan"), "i": float("inf"), "l": [float("nan")]}
        json.dumps(sanitize(payload), allow_nan=False)


class TestShortId:
    def test_leaves_short_ids_alone(self):
        assert short_id("doc-1") == "doc-1"

    def test_truncates_long_ids(self):
        out = short_id("x" * 500)
        assert len(out) == 200
        assert out.endswith("\u2026")


class TestParseEnvelope:
    def _line(self, **overrides):
        payload = {
            "v": SCHEMA_VERSION,
            "seq": 1,
            "ts_ms": 1700000000000,
            "run_id": "abc",
            "type": "phase",
            "data": {"phase": "index"},
        }
        payload.update(overrides)
        return json.dumps(payload)

    def test_round_trips_a_valid_line(self):
        event = parse_envelope(self._line())
        assert event == RunEvent(
            v=1, seq=1, ts_ms=1700000000000, run_id="abc",
            type="phase", data={"phase": "index"},
        )

    def test_accepts_bytes(self):
        assert parse_envelope(self._line().encode("utf-8")).type == "phase"

    def test_data_defaults_to_empty(self):
        line = json.dumps({"v": 1, "seq": 1, "ts_ms": 1, "run_id": "r", "type": "log"})
        assert parse_envelope(line).data == {}

    @pytest.mark.parametrize("missing", ["v", "seq", "ts_ms", "run_id", "type"])
    def test_missing_keys_are_rejected(self, missing):
        payload = json.loads(self._line())
        del payload[missing]
        with pytest.raises(EnvelopeError, match="missing keys"):
            parse_envelope(json.dumps(payload))

    def test_unknown_version_is_rejected(self):
        with pytest.raises(EnvelopeError, match="unsupported schema version"):
            parse_envelope(self._line(v=99))

    def test_non_integer_version_is_rejected(self):
        with pytest.raises(EnvelopeError, match="v must be int"):
            parse_envelope(self._line(v="1"))

    @pytest.mark.parametrize("raw", ["", "   ", "not json", "[1,2,3]", '"a string"'])
    def test_malformed_input_is_rejected(self, raw):
        with pytest.raises(EnvelopeError):
            parse_envelope(raw)

    def test_non_object_data_is_rejected(self):
        with pytest.raises(EnvelopeError, match="data must be an object"):
            parse_envelope(self._line(data=[1, 2]))


class TestEventEmitter:
    @pytest.fixture
    def stream(self):
        return io.StringIO()

    @pytest.fixture
    def emitter(self, stream):
        return EventEmitter("run-1", stream=stream, clock=lambda: 1_700_000_000.5)

    def test_emits_one_json_object_per_line(self, emitter, stream):
        emitter.emit(EventType.PHASE, {"phase": "index"})
        emitter.emit(EventType.LOG, {"level": "info"})
        lines = stream.getvalue().strip().split("\n")
        assert len(lines) == 2
        assert [json.loads(line)["type"] for line in lines] == ["phase", "log"]

    def test_sequence_numbers_start_at_one_and_increment(self, emitter, stream):
        for _ in range(3):
            emitter.emit(EventType.LOG, {})
        seqs = [json.loads(line)["seq"] for line in stream.getvalue().strip().split("\n")]
        assert seqs == [1, 2, 3]

    def test_timestamp_comes_from_the_injected_clock(self, emitter, stream):
        emitter.emit(EventType.LOG, {})
        assert json.loads(stream.getvalue())["ts_ms"] == 1_700_000_000_500

    def test_run_id_is_stamped_on_every_event(self, emitter, stream):
        emitter.emit(EventType.LOG, {})
        assert json.loads(stream.getvalue())["run_id"] == "run-1"

    def test_nan_in_payload_is_encoded_as_null(self, emitter, stream):
        emitter.emit(EventType.RAGAS, {"faithfulness": float("nan")})
        line = stream.getvalue()
        assert "NaN" not in line
        assert json.loads(line)["data"]["faithfulness"] is None

    def test_emit_flushes_so_the_ui_sees_events_immediately(self, emitter, stream):
        """The Run page renders from this stream; an unflushed buffer stalls it."""
        emitter.emit(EventType.LOG, {})
        assert stream.getvalue() != ""

    def test_emit_returns_the_decoded_event(self, emitter):
        event = emitter.emit(EventType.PHASE, {"phase": "index"})
        assert isinstance(event, RunEvent)
        assert event.type == EventType.PHASE

    def test_write_failure_is_reported_not_raised(self):
        """A dead pipe must not abort a multi-hour experiment."""

        class BrokenStream(io.StringIO):
            def write(self, _data):
                raise OSError("pipe closed")

        seen = []
        emitter = EventEmitter(
            "run-1",
            stream=BrokenStream(),
            on_error=lambda exc, kind: seen.append((exc, kind)),
        )
        emitter.emit(EventType.LOG, {"level": "info"})  # must not raise
        assert len(seen) == 1
        assert isinstance(seen[0][0], OSError)

    def test_write_failure_without_a_handler_still_does_not_raise(self):
        class BrokenStream(io.StringIO):
            def write(self, _data):
                raise OSError("pipe closed")

        EventEmitter("run-1", stream=BrokenStream()).emit(EventType.LOG, {})

    def test_concurrent_emits_produce_well_formed_unique_lines(self, emitter, stream):
        """Two phases of a run can log from different threads."""

        def worker(tag: int):
            for _ in range(20):
                emitter.emit(EventType.LOG, {"tag": tag})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        lines = stream.getvalue().strip().split("\n")
        assert len(lines) == 80
        parsed = [json.loads(line) for line in lines]
        assert sorted(p["seq"] for p in parsed) == list(range(1, 81))


class TestProtocolConstants:
    def test_all_lists_every_event_type(self):
        types = EventType.all()
        assert EventType.PHASE in types
        assert EventType.RUN_FINISHED in types
        assert EventType.RUN_FAILED in types
        assert len(types) == len(set(types)), "duplicate event type constant"

    def test_event_type_names_match_the_wire_values(self):
        assert EventType.PROMPT_COMPLETED == "prompt_completed"
        assert EventType.PROJECTION_READY == "projection_ready"

    def test_phases_are_ordered_preflight_to_done(self):
        assert PHASES[0] == "preflight"
        assert PHASES[-1] == "done"