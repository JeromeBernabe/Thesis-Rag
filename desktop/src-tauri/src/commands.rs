//! Tauri commands exposed to the webview.
//!
//! Every command returns `Result<_, String>` so a failure reaches the frontend
//! as a rejected promise with a readable message, rather than as an opaque
//! "invalid args" the user cannot act on.

use std::sync::Arc;

use serde::Serialize;
use tauri::{AppHandle, Manager, State};

use crate::db;
use crate::runner::{self, PythonSetup, RunRequest};
use crate::store::Store;

/// Shared application state.
pub struct AppState {
    pub store: Arc<Store>,
    pub python: PythonSetup,
    pub db_path: std::path::PathBuf,
}

/// Datasets and other choices the Run form offers.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AppInfo {
    pub datasets: Vec<String>,
    pub default_dataset: String,
    pub default_limit: i64,
    pub default_seed: i64,
    pub python: String,
    pub project_root: String,
    pub db_path: String,
    pub schema_version: i64,
}

/// The datasets the Run form offers.
///
/// The source of truth is `VALID_DATASETS` in config/settings.py. It is
/// duplicated rather than imported because the dropdown has to be populated
/// before a run starts, and `run_started` only reports the list once there is
/// already a run in flight. `dataset_list_matches_the_python_source_of_truth`
/// pins the two together.
pub fn app_info_datasets() -> Vec<String> {
    vec![
        "hotpot".into(),
        "fintech".into(),
        "math".into(),
        "ragtruth".into(),
    ]
}

/// Which Python interpreter and repository the app resolved to.
#[tauri::command]
pub fn app_info(state: State<'_, AppState>) -> Result<AppInfo, String> {
    Ok(AppInfo {
        datasets: app_info_datasets(),
        default_dataset: "hotpot".into(),
        default_limit: runner::DEFAULT_LIMIT,
        default_seed: runner::DEFAULT_SEED,
        python: state
            .python
            .python
            .clone()
            .unwrap_or_else(|| "python".into())
            .display()
            .to_string(),
        project_root: state.python.project_root.display().to_string(),
        db_path: state.db_path.display().to_string(),
        schema_version: db::SCHEMA_VERSION,
    })
}

/// Start a benchmark run.
///
/// The run row is created before the process spawns, so a failed launch is still
/// visible in the run list with its error.
#[tauri::command]
pub fn start_run(
    app: AppHandle,
    state: State<'_, AppState>,
    request: RunRequest,
) -> Result<runner::RunHandle, String> {
    // Liveness, not mere presence of a managed handle: the slot is emptied when a
    // run ends, but the check still has to be about the process, not the entry.
    if app
        .try_state::<runner::ActiveRunSlot>()
        .is_some_and(|slot| slot.is_running())
    {
        return Err("a run is already in progress - cancel it first".into());
    }
    runner::start(app, state.store.clone(), state.python.clone(), request)
}

/// Whether a run is in progress, answered from the slot.
///
/// Takes the slot rather than the whole `AppHandle` so the state type is part of
/// the signature. The bug this guards was a lookup that disagreed with what
/// `start` published - the commands asked for an `ActiveRun` while `start`
/// installed an `ActiveRunSlot`, which compiled, type-checked, and quietly sent
/// every cancel after the first run to a dead process. Here the two cannot
/// disagree: passing anything but a slot does not build.
fn slot_is_running(slot: Option<State<'_, runner::ActiveRunSlot>>) -> bool {
    slot.is_some_and(|slot| slot.is_running())
}

/// Cancel whatever run the slot is holding, returning its id.
///
/// Split from the command for the same reason as [`slot_is_running`].
fn cancel_slot(slot: Option<State<'_, runner::ActiveRunSlot>>) -> Result<String, String> {
    match slot {
        Some(slot) => match slot.current() {
            Some(active) => {
                let run_id = active.run_id.clone();
                active.cancel();
                Ok(run_id)
            }
            None => Err("no run is in progress".into()),
        },
        None => Err("the active run slot was never managed".into()),
    }
}

/// Cancel the active run.
///
/// Returns the id of the run that was cancelled, so the Run page can mark the
/// right row rather than whichever run it happened to have selected.
///
/// `async` on purpose. A synchronous Tauri command runs on the main thread, and
/// cancelling waits for the sidecar to actually die - which can take a moment on
/// a busy machine. Doing that on the main thread freezes the window, so the
/// button appears dead and the app stops responding until the run ends. The run
/// row is closed out by the pump thread once it observes the cancellation, so
/// there is nothing here that needs to block the UI.
#[tauri::command]
pub async fn cancel_run(app: AppHandle) -> Result<String, String> {
    cancel_slot(app.try_state())
}

/// Whether a run is currently in progress.
#[tauri::command]
pub fn run_in_progress(app: AppHandle) -> bool {
    slot_is_running(app.try_state())
}

/// Every stored run, newest first.
#[tauri::command]
pub fn list_runs(state: State<'_, AppState>) -> Result<Vec<serde_json::Value>, String> {
    state.store.list_runs().map_err(|e| e.to_string())
}

/// One run's metadata.
#[tauri::command]
pub fn get_run(
    state: State<'_, AppState>,
    run_id: String,
) -> Result<Option<serde_json::Value>, String> {
    state.store.get_run(&run_id).map_err(|e| e.to_string())
}

/// Everything the Results page needs for one run, in a single round trip.
///
/// One command rather than four: the page renders as soon as this resolves, and
/// it avoids showing a chart built from half the data.
#[tauri::command]
pub fn get_run_detail(
    state: State<'_, AppState>,
    run_id: String,
) -> Result<serde_json::Value, String> {
    let store = &state.store;
    let run = store
        .get_run(&run_id)
        .map_err(|e| e.to_string())?
        .ok_or_else(|| format!("unknown run {run_id}"))?;
    Ok(serde_json::json!({
        "run": run,
        "stats": store.get_stats(&run_id).map_err(|e| e.to_string())?,
        "promptRows": store.get_prompt_rows(&run_id).map_err(|e| e.to_string())?,
        "trainingRows": store.get_training_rows(&run_id).map_err(|e| e.to_string())?,
    }))
}

/// The recorded event timeline for a run, used to rebuild a finished run's view.
#[tauri::command]
pub fn get_run_events(
    state: State<'_, AppState>,
    run_id: String,
) -> Result<Vec<serde_json::Value>, String> {
    state.store.get_events(&run_id).map_err(|e| e.to_string())
}

/// Statistics only, for the Results page after a live run finishes.
#[tauri::command]
pub fn get_stats(
    state: State<'_, AppState>,
    run_id: String,
) -> Result<Option<serde_json::Value>, String> {
    state.store.get_stats(&run_id).map_err(|e| e.to_string())
}

/// Delete a run and everything that cascades from it.
#[tauri::command]
pub fn delete_run(state: State<'_, AppState>, run_id: String) -> Result<(), String> {
    state.store.delete_run(&run_id).map_err(|e| e.to_string())
}

/// Stored projection metadata for a dataset, so the 3D view can find its files.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProjectionInfo {
    pub dataset: String,
    pub collection: String,
    pub dim: i64,
    pub n_points: i64,
    pub points_path: String,
    pub meta_path: String,
    pub explained_variance: Option<f64>,
    pub source_count: Option<i64>,
    pub created_at: i64,
}

/// Look up a precomputed 3D projection.
#[tauri::command]
pub fn get_projection(
    state: State<'_, AppState>,
    dataset: String,
) -> Result<Option<ProjectionInfo>, String> {
    use rusqlite::OptionalExtension;
    state
        .store
        .connection()
        .query_row(
            "SELECT dataset, collection, dim, n_points, points_path, meta_path,
                    explained_variance, source_count, created_at
             FROM projections WHERE dataset = ?1",
            [&dataset],
            |row| {
                Ok(ProjectionInfo {
                    dataset: row.get(0)?,
                    collection: row.get(1)?,
                    dim: row.get(2)?,
                    n_points: row.get(3)?,
                    points_path: row.get(4)?,
                    meta_path: row.get(5)?,
                    explained_variance: row.get(6)?,
                    source_count: row.get(7)?,
                    created_at: row.get(8)?,
                })
            },
        )
        .optional()
        .map_err(|e| e.to_string())
}

/// Datasets that have a projection ready.
#[tauri::command]
pub fn list_projections(state: State<'_, AppState>) -> Result<Vec<String>, String> {
    let conn = state.store.connection();
    let mut stmt = conn
        .prepare("SELECT dataset FROM projections ORDER BY dataset")
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(|e| e.to_string())?;
    rows.collect::<rusqlite::Result<Vec<String>>>()
        .map_err(|e| e.to_string())
}

/// A projection, ready for the 3D view.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProjectionData {
    /// The parsed JSON sidecar: ids, components, mean, bounds, variance.
    pub meta: serde_json::Value,
    /// Flat XYZ triples as little-endian float32, ready for `THREE.BufferAttribute`.
    pub points: Vec<f32>,
}

/// Read a stored projection for the 3D view.
///
/// The sidecar writes two files: raw little-endian float32 XYZ triples and a JSON
/// sidecar. Rust reads both and hands the webview parsed numbers, because the
/// webview cannot read them itself - a webview has no filesystem access to
/// arbitrary paths, and on Windows `C:\...` is not a URL that `fetch` can open.
/// Going through a command also means no filesystem plugin and no asset-scope
/// permission, which keeps the sandbox as small as the feature requires.
///
/// `points` is flattened rather than nested so it crosses IPC as a plain number
/// array, which is what `BufferAttribute` wants with no conversion in JS.
#[tauri::command]
pub fn get_projection_data(
    state: State<'_, AppState>,
    dataset: String,
) -> Result<Option<ProjectionData>, String> {
    let (points_path, meta_path) = {
        let conn = state.store.connection();
        // "No row" is a normal answer - the caller asks about a dataset the user
        // may simply never have projected - so it must not be reported as an error.
        match conn.query_row(
            "SELECT points_path, meta_path FROM projections WHERE dataset = ?1",
            rusqlite::params![dataset],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
        ) {
            Ok(paths) => paths,
            Err(rusqlite::Error::QueryReturnedNoRows) => return Ok(None),
            Err(e) => return Err(e.to_string()),
        }
    };

    let meta_text = std::fs::read_to_string(&meta_path).map_err(|e| format!("{meta_path}: {e}"))?;
    let meta: serde_json::Value =
        serde_json::from_str(&meta_text).map_err(|e| format!("{meta_path}: {e}"))?;

    let bytes = std::fs::read(&points_path).map_err(|e| format!("{points_path}: {e}"))?;
    let points = decode_xyz(&bytes).ok_or_else(|| {
        format!(
            "{points_path}: {} bytes is not a whole number of XYZ float32 triples",
            bytes.len()
        )
    })?;

    Ok(Some(ProjectionData { meta, points }))
}

/// Decode raw little-endian float32 XYZ triples into floats.
///
/// Returns `None` when the buffer does not divide into whole triples: a truncated
/// write must fail loudly rather than yield a point cloud that is silently
/// missing its last coordinate.
fn decode_xyz(bytes: &[u8]) -> Option<Vec<f32>> {
    if bytes.len() % 12 != 0 {
        return None;
    }
    Some(
        bytes
            .chunks_exact(4)
            .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
            .collect(),
    )
}

/// Import committed CSVs from `results/` as a run.
///
/// Lets the historical experiments appear in the Results page next to live runs,
/// which is the only way to compare the new pipeline against what came before.
#[tauri::command]
pub fn import_legacy(
    state: State<'_, AppState>,
    source_dir: Option<String>,
) -> Result<serde_json::Value, String> {
    let dir = match source_dir {
        Some(dir) => std::path::PathBuf::from(dir),
        None => state.python.project_root.join("results"),
    };
    let report = crate::legacy::import_directory(&state.store, &dir)?;
    serde_json::to_value(report).map_err(|e| e.to_string())
}
#[cfg(test)]
mod tests {
    use super::{app_info_datasets, decode_xyz};
    use std::path::Path;

    /// Pack XYZ triples the way `numpy.astype("<f4").tofile` does.
    fn pack(values: &[f32]) -> Vec<u8> {
        values.iter().flat_map(|v| v.to_le_bytes()).collect()
    }

    #[test]
    fn decodes_xyz_triples_in_order() {
        let bytes = pack(&[1.0, 2.0, 3.0, -4.5, 0.0, 6.25]);
        assert_eq!(
            decode_xyz(&bytes),
            Some(vec![1.0, 2.0, 3.0, -4.5, 0.0, 6.25])
        );
    }

    #[test]
    fn little_endian_is_the_sidecars_format() {
        // A big-endian writer emits 1.0 as 00 00 80 3f; little-endian is
        // 00 00 80 3f only when read back with `from_le_bytes`. If the decoder
        // respected host order instead of the file's, this would be a denormal
        // around 1.4e-45 rather than 1.0.
        assert_eq!(
            decode_xyz(&pack(&[1.0, 0.0, 0.0])),
            Some(vec![1.0, 0.0, 0.0])
        );
        // 0.5 is exactly representable, so this distinguishes order unambiguously.
        assert_eq!(
            decode_xyz(&pack(&[0.5, 0.25, 0.125])),
            Some(vec![0.5, 0.25, 0.125])
        );
    }

    #[test]
    fn a_truncated_buffer_is_rejected() {
        // 14 bytes is one whole triple plus a half-written coordinate. Accepting
        // it would drop a point silently.
        let mut bytes = pack(&[1.0, 2.0, 3.0]);
        bytes.extend_from_slice(&[0, 0]);
        assert_eq!(decode_xyz(&bytes), None);
    }

    #[test]
    fn an_empty_buffer_decodes_to_no_points() {
        assert_eq!(decode_xyz(&[]), Some(Vec::new()));
    }

    /// The Run form's dataset dropdown must not offer anything `RunSpec.validate`
    /// would reject, and must not omit anything it would accept.
    ///
    /// The list is hand-kept in sync with `VALID_DATASETS` in
    /// config/settings.py, because it has to exist before a run starts. Reading
    /// the Python file here is deliberate rather than duplicating the tuple a
    /// third time: this is the test that fails when someone adds a dataset on the
    /// Python side and forgets the host.
    #[test]
    fn dataset_list_matches_the_python_source_of_truth() {
        let settings = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("config")
            .join("settings.py");
        let text = std::fs::read_to_string(&settings)
            .unwrap_or_else(|e| panic!("cannot read {}: {e}", settings.display()));

        let declared = text
            .lines()
            .find_map(|line| {
                let rest = line.trim().strip_prefix("VALID_DATASETS")?;
                let tuple = rest.split_once('(')?.1.split_once(')')?.0;
                Some(
                    tuple
                        .split(',')
                        .map(|s| s.trim().trim_matches(|c| c == '"' || c == '\'').to_string())
                        .filter(|s| !s.is_empty())
                        .collect::<Vec<_>>(),
                )
            })
            .expect("VALID_DATASETS tuple in config/settings.py");

        let offered = app_info_datasets();
        let mut expected = declared.clone();
        let mut actual = offered.clone();
        expected.sort();
        actual.sort();
        assert_eq!(
            actual, expected,
            "the Run form offers {offered:?} but config/settings.py declares {declared:?}"
        );
    }
}
