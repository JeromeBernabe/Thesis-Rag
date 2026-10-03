//! The NDJSON event envelope spoken by the Python sidecar.
//!
//! This is a strict mirror of `bench_bridge/events.py`; the two must be changed
//! together. Keeping the payload as `serde_json::Value` rather than a set of
//! structs is deliberate: the Run page forwards events straight to the webview,
//! and Python already owns the per-event schema. Deserialising here is only for
//! the fields the host itself needs (identity and ordering), plus the handful of
//! fields [`crate::store`] reads when persisting.
//!
//! Events arrive one JSON object per line on stdout. Anything the host cannot
//! understand is reported as an error rather than skipped: a dropped event would
//! leave a chart quietly missing points, which is much harder to notice than a
//! failed run.
//!
//! Several items here are only read by the test suite or exist to document the
//! protocol for the TypeScript mirror; they are public API of this module rather
//! than dead code.

#![allow(dead_code)]

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Must equal `events.SCHEMA_VERSION`.
pub const SCHEMA_VERSION: u32 = 1;

/// Tauri event name used to push events into the webview.
pub const WEBVIEW_EVENT: &str = "bench://event";

/// Every event type the sidecar can emit.
///
/// Kept as `&str` constants for the same reason as in Python: the value on the
/// wire is the constant itself, and the TypeScript mirror in
/// `desktop/src/types/events.ts` can be checked against this list.
pub mod types {
    pub const RUN_STARTED: &str = "run_started";
    pub const PHASE: &str = "phase";
    pub const INDEX_PROGRESS: &str = "index_progress";
    pub const PROJECTION_READY: &str = "projection_ready";
    pub const PROMPT_STARTED: &str = "prompt_started";
    pub const EMBEDDING: &str = "embedding";
    pub const DECISION: &str = "decision";
    pub const RETRIEVAL: &str = "retrieval";
    pub const GENERATION: &str = "generation";
    pub const RAGAS: &str = "ragas";
    pub const REWARD: &str = "reward";
    pub const TRAIN_STEP: &str = "train_step";
    pub const PROMPT_COMPLETED: &str = "prompt_completed";
    pub const STATS: &str = "stats";
    pub const LOG: &str = "log";
    pub const RUN_FINISHED: &str = "run_finished";
    pub const RUN_FAILED: &str = "run_failed";

    /// Sorted, matching `EventType.all()` in Python.
    pub const ALL: &[&str] = &[
        DECISION,
        EMBEDDING,
        GENERATION,
        INDEX_PROGRESS,
        LOG,
        PHASE,
        PROJECTION_READY,
        PROMPT_COMPLETED,
        PROMPT_STARTED,
        RAGAS,
        RETRIEVAL,
        REWARD,
        RUN_FAILED,
        RUN_FINISHED,
        RUN_STARTED,
        STATS,
        TRAIN_STEP,
    ];
}

/// Coarse run phases, matching `events.PHASES`.
pub const PHASES: &[&str] = &[
    "preflight",
    "index",
    "projection",
    "system_a",
    "system_b_train",
    "system_b_infer",
    "stats",
    "done",
];

/// One decoded event.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RunEvent {
    pub v: u32,
    pub seq: u64,
    pub ts_ms: i64,
    pub run_id: String,
    #[serde(rename = "type")]
    pub event_type: String,
    #[serde(default)]
    pub data: Value,
}

impl RunEvent {
    /// Parse and validate one NDJSON line.
    ///
    /// Mirrors `parse_envelope` in `bench_bridge/events.py`, including rejecting
    /// unknown schema versions: an old app must never silently mis-read a newer
    /// sidecar.
    pub fn parse(raw: &str) -> Result<Self, EventError> {
        let line = raw.trim();
        if line.is_empty() {
            return Err(EventError::Empty);
        }
        let value: Value =
            serde_json::from_str(line).map_err(|e| EventError::InvalidJson(e.to_string()))?;
        let obj = value.as_object().ok_or_else(|| EventError::NotAnObject)?;
        for key in ["v", "seq", "ts_ms", "run_id", "type"] {
            if !obj.contains_key(key) {
                return Err(EventError::MissingKey(key));
            }
        }
        let version = obj["v"]
            .as_u64()
            .ok_or_else(|| EventError::InvalidField("v must be an integer"))?;
        if version != u64::from(SCHEMA_VERSION) {
            return Err(EventError::UnsupportedVersion(version));
        }
        let data = match obj.get("data") {
            None | Some(Value::Null) => Value::Object(Default::default()),
            Some(v) if v.is_object() => v.clone(),
            Some(_) => return Err(EventError::InvalidField("data must be an object")),
        };
        let event = RunEvent {
            v: version as u32,
            seq: obj["seq"]
                .as_u64()
                .ok_or(EventError::InvalidField("seq must be an integer"))?,
            ts_ms: obj["ts_ms"]
                .as_i64()
                .ok_or(EventError::InvalidField("ts_ms must be an integer"))?,
            run_id: obj["run_id"]
                .as_str()
                .ok_or(EventError::InvalidField("run_id must be a string"))?
                .to_string(),
            event_type: obj["type"]
                .as_str()
                .ok_or(EventError::InvalidField("type must be a string"))?
                .to_string(),
            data,
        };
        Ok(event)
    }

    /// Serialize back to a single NDJSON line, without the trailing newline.
    ///
    /// This is what gets forwarded to the webview, so the payload is passed
    /// through unchanged - the frontend is the only place that interprets it.
    pub fn to_line(&self) -> String {
        serde_json::to_string(self).expect("RunEvent always serializes")
    }

    /// Read a string field from the payload.
    pub fn str_field(&self, key: &str) -> Option<&str> {
        self.data.get(key).and_then(Value::as_str)
    }

    /// Read a float field, rejecting non-finite values.
    ///
    /// The sidecar maps `NaN` to `null`, so a NaN reaching this point means the
    /// writer bypassed `sanitize`; treating it as absent is what keeps a single
    /// bad metric out of a SQL `REAL` column.
    pub fn f64_field(&self, key: &str) -> Option<f64> {
        self.data
            .get(key)
            .and_then(Value::as_f64)
            .filter(|v| v.is_finite())
    }

    /// Read an integer field, accepting a float that is exactly integral.
    pub fn i64_field(&self, key: &str) -> Option<i64> {
        let value = self.data.get(key)?;
        value.as_i64().or_else(|| {
            value
                .as_f64()
                .filter(|v| v.fract() == 0.0)
                .map(|v| v as i64)
        })
    }

    /// Read a boolean field, accepting `0`/`1`.
    pub fn bool_field(&self, key: &str) -> Option<bool> {
        self.data.get(key).and_then(|v| match v {
            Value::Bool(b) => Some(*b),
            Value::Number(n) => n.as_i64().map(|i| i != 0),
            _ => None,
        })
    }

    /// Read an array field.
    pub fn array_field(&self, key: &str) -> Option<&Vec<Value>> {
        self.data.get(key).and_then(Value::as_array)
    }

    /// A nested object field.
    ///
    /// `prompt_completed` carries its finished row under a `row` key, so the store
    /// reads one level down. `train_step` does not: its record is flat, which is why
    /// the two need different accessors. An older sidecar sent `prompt_completed`
    /// without `row` at all, and the store has to keep working for those runs.
    pub fn object_field(&self, key: &str) -> Option<&serde_json::Map<String, Value>> {
        self.data.get(key).and_then(Value::as_object)
    }

    /// Whether this event marks the end of a run, successfully or not.
    pub fn is_terminal(&self) -> bool {
        self.event_type == types::RUN_FINISHED || self.event_type == types::RUN_FAILED
    }
}

/// Read a string from a nested payload map.
pub(crate) fn map_str<'a>(map: &'a serde_json::Map<String, Value>, key: &str) -> Option<&'a str> {
    map.get(key).and_then(Value::as_str)
}

/// Read a float from a nested payload map; JSON `null` and non-numbers give `None`.
///
/// This is what keeps "the judge did not run" stored as `NULL` rather than `0.0`.
pub(crate) fn map_f64(map: &serde_json::Map<String, Value>, key: &str) -> Option<f64> {
    map.get(key).and_then(Value::as_f64)
}

/// Read an integer from a nested payload map.
///
/// `as_i64` rejects a float like `3.0` that survived JSON round-tripping as a
/// real, so a numeric float is coerced rather than dropped.
pub(crate) fn map_i64(map: &serde_json::Map<String, Value>, key: &str) -> Option<i64> {
    match map.get(key) {
        Some(Value::Number(n)) => n.as_i64().or_else(|| n.as_f64().map(|v| v as i64)),
        _ => None,
    }
}

/// Serialise a nested array field for storage as JSON text.
///
/// `None` for both "absent" and "explicitly null", which keeps the column `NULL`
/// rather than an empty array - the two mean different things downstream.
pub(crate) fn map_json(map: &serde_json::Map<String, Value>, key: &str) -> Option<String> {
    let value = map.get(key)?;
    if value.is_null() {
        return None;
    }
    serde_json::to_string(value).ok()
}

/// Why a line could not be read as an event.
#[derive(Debug, thiserror::Error, PartialEq)]
pub enum EventError {
    #[error("empty line")]
    Empty,
    #[error("invalid JSON: {0}")]
    InvalidJson(String),
    #[error("expected a JSON object")]
    NotAnObject,
    #[error("missing key: {0}")]
    MissingKey(&'static str),
    #[error("unsupported schema version {0}")]
    UnsupportedVersion(u64),
    #[error("invalid field: {0}")]
    InvalidField(&'static str),
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn envelope(event_type: &str, data: Value) -> String {
        json!({
            "v": 1,
            "seq": 12,
            "ts_ms": 1_750_000_000_000i64,
            "run_id": "abc",
            "type": event_type,
            "data": data,
        })
        .to_string()
    }

    #[test]
    fn parses_a_well_formed_event() {
        let event = RunEvent::parse(&envelope("retrieval", json!({"k": 3}))).unwrap();
        assert_eq!(event.seq, 12);
        assert_eq!(event.run_id, "abc");
        assert_eq!(event.event_type, "retrieval");
        assert_eq!(event.i64_field("k"), Some(3));
    }

    #[test]
    fn data_defaults_to_empty_when_absent() {
        let line = json!({"v": 1, "seq": 1, "ts_ms": 0, "run_id": "r", "type": "log"}).to_string();
        let event = RunEvent::parse(&line).unwrap();
        assert!(event.data.as_object().unwrap().is_empty());
    }

    #[test]
    fn null_data_is_treated_as_empty() {
        let line =
            json!({"v": 1, "seq": 1, "ts_ms": 0, "run_id": "r", "type": "log", "data": null})
                .to_string();
        assert!(RunEvent::parse(&line)
            .unwrap()
            .data
            .as_object()
            .unwrap()
            .is_empty());
    }

    #[test]
    fn rejects_a_bare_nan_token() {
        // serde_json is strict by default, which is the point of sanitizing on
        // the Python side: a RAGAS NaN must never reach this parser.
        let line = r#"{"v":1,"seq":1,"ts_ms":0,"run_id":"r","type":"ragas","data":{"x":NaN}}"#;
        assert!(matches!(
            RunEvent::parse(line),
            Err(EventError::InvalidJson(_))
        ));
    }

    #[test]
    fn rejects_an_empty_line() {
        assert_eq!(RunEvent::parse("   \n"), Err(EventError::Empty));
    }

    #[test]
    fn rejects_a_future_schema_version() {
        let line = envelope("log", json!({})).replace(r#""v":1"#, r#""v":2"#);
        assert_eq!(
            RunEvent::parse(&line),
            Err(EventError::UnsupportedVersion(2))
        );
    }

    #[test]
    fn rejects_a_missing_key() {
        let line = json!({"v": 1, "seq": 1, "ts_ms": 0, "run_id": "r"}).to_string();
        assert_eq!(RunEvent::parse(&line), Err(EventError::MissingKey("type")));
    }

    #[test]
    fn rejects_a_non_object_payload() {
        let line = envelope("log", json!([]));
        assert!(matches!(
            RunEvent::parse(&line),
            Err(EventError::InvalidField(_))
        ));
    }

    #[test]
    fn rejects_a_top_level_array() {
        assert_eq!(RunEvent::parse("[1,2,3]"), Err(EventError::NotAnObject));
    }

    #[test]
    fn round_trips_through_a_line() {
        let event = RunEvent::parse(&envelope("generation", json!({"answer": "x"}))).unwrap();
        let again = RunEvent::parse(&event.to_line()).unwrap();
        assert_eq!(event, again);
    }

    #[test]
    fn f64_field_drops_non_finite_values() {
        // `f64::NAN` cannot be written as a JSON literal, so this exercises the
        // path that matters: serde_json rejecting a non-finite value, and the
        // field read returning None rather than a poisoned REAL column.
        let event = RunEvent::parse(&envelope("ragas", json!({"faithfulness": 0.5}))).unwrap();
        assert_eq!(event.f64_field("faithfulness"), Some(0.5));

        let mut with_nan = event.data.as_object().unwrap().clone();
        with_nan.insert("other".into(), Value::Null);
        let null_event = RunEvent {
            data: serde_json::Value::Object(with_nan),
            ..event
        };
        assert_eq!(null_event.f64_field("other"), None);
        assert_eq!(null_event.f64_field("faithfulness"), Some(0.5));
    }

    #[test]
    fn non_finite_values_cannot_be_deserialized_at_all() {
        // serde_json is strict: Infinity is not representable, so a sidecar that
        // forgot to sanitize produces a parse error rather than a silent NaN.
        for token in ["NaN", "Infinity", "-Infinity"] {
            let line = format!(
                r#"{{"v":1,"seq":1,"ts_ms":0,"run_id":"r","type":"ragas","data":{{"x":{token}}}}}"#
            );
            assert!(
                matches!(RunEvent::parse(&line), Err(EventError::InvalidJson(_))),
                "{token} must be rejected"
            );
        }
    }

    #[test]
    fn i64_field_accepts_an_integral_float() {
        let event = RunEvent::parse(&envelope("log", json!({"n": 7.0}))).unwrap();
        assert_eq!(event.i64_field("n"), Some(7));
    }

    #[test]
    fn bool_field_accepts_one_and_zero() {
        let event = RunEvent::parse(&envelope("log", json!({"a": 1, "b": 0, "c": true}))).unwrap();
        assert_eq!(event.bool_field("a"), Some(true));
        assert_eq!(event.bool_field("b"), Some(false));
        assert_eq!(event.bool_field("c"), Some(true));
        assert_eq!(event.bool_field("missing"), None);
    }

    #[test]
    fn terminal_events_are_identified() {
        for t in ["run_finished", "run_failed"] {
            let event = RunEvent::parse(&envelope(t, json!({}))).unwrap();
            assert!(event.is_terminal(), "{t} should be terminal");
        }
        let event = RunEvent::parse(&envelope("retrieval", json!({}))).unwrap();
        assert!(!event.is_terminal());
    }

    #[test]
    fn type_list_matches_the_python_order() {
        // EventType.all() sorts by attribute name, which is alphabetical, and
        // includes REWARD (17 types in total).
        assert_eq!(types::ALL.len(), 17);
        let mut sorted = types::ALL.to_vec();
        sorted.sort_unstable();
        assert_eq!(&sorted[..], types::ALL, "ALL must stay sorted");
        assert!(types::ALL.contains(&types::RUN_STARTED));
        assert!(types::ALL.contains(&types::RUN_FAILED));
    }

    #[test]
    fn phase_list_matches_python() {
        assert_eq!(
            PHASES,
            &[
                "preflight",
                "index",
                "projection",
                "system_a",
                "system_b_train",
                "system_b_infer",
                "stats",
                "done"
            ]
        );
    }
}
