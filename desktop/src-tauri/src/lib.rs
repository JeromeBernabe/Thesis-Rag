//! Application setup: shared state, the sidecar handshake, and the run list.

mod commands;
mod db;
mod events;
mod legacy;
mod runner;
mod store;

use std::sync::Arc;

use store::Store;
use tauri::Manager;

/// Build and run the Tauri application.
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let python = runner::PythonSetup::detect();
            let project_root = python.project_root.clone();
            let db_path = project_root.join("data").join("bench").join("runs.sqlite3");

            // Failing to open the database is worth refusing to start over: every
            // page depends on it, and a silent fallback would let a user start a
            // run whose results are then lost.
            let store = Store::open(&db_path).map_err(|e| {
                Box::<dyn std::error::Error>::from(format!(
                    "cannot open the run database at {}: {e}",
                    db_path.display()
                ))
            })?;

            app.manage(commands::AppState {
                store: Arc::new(store),
                python,
                db_path,
            });
            // Managed exactly once, here. Tauri ignores a second `manage` for a
            // type it already holds, so this slot - not the per-run `ActiveRun` -
            // is what makes a second and subsequent run cancelable. See
            // `runner::ActiveRunSlot`.
            app.manage(runner::ActiveRunSlot::new());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::app_info,
            commands::start_run,
            commands::cancel_run,
            commands::run_in_progress,
            commands::list_runs,
            commands::get_run,
            commands::get_run_detail,
            commands::get_run_events,
            commands::get_stats,
            commands::delete_run,
            commands::get_projection,
            commands::get_projection_data,
            commands::list_projections,
            commands::import_legacy,
        ])
        .run(tauri::generate_context!())
        .expect("error while running the benchmark application");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_setup_points_at_the_repository_root() {
        // The manifest dir is desktop/src-tauri, so the root is its parent.
        let setup = runner::PythonSetup::detect();
        assert!(setup.project_root.join("bench_bridge").exists());
        assert!(setup.project_root.join("run_experiment.py").exists());
    }

    #[test]
    fn db_path_is_under_data_bench() {
        let root = runner::PythonSetup::detect().project_root;
        let db_path = root.join("data").join("bench").join("runs.sqlite3");
        assert!(db_path.starts_with(&root));
    }
}
