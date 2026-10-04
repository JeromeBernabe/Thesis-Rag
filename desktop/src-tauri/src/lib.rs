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
        // Registered first, and before anything else exists, because the second
        // instance must be stopped *before* it reaches the reconcile sweep below.
        //
        // That sweep treats every `running` row as abandoned, which is only true
        // of the process that just exited. A second instance launching while a
        // benchmark is in flight would close that live run, and two instances
        // would also put two writers and two Ollama sidecars on one database and
        // one GPU. The plugin makes the second process focus the existing window
        // and exit, which is also what a user double-clicking the icon expects.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            // Every window, rather than a hard-coded "main": the label is not
            // set in tauri.conf.json, and focusing nothing would silently make
            // the second launch look like it did nothing at all.
            for (_label, window) in app.webview_windows() {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // Refusing to start beats starting wrong. Every page reads the run
            // database, so an app that could not find the checkout would
            // otherwise present an empty Results list and quietly create a
            // `data/bench` tree wherever it guessed.
            let python =
                runner::PythonSetup::detect().map_err(|e| Box::<dyn std::error::Error>::from(e))?;
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

            // Runs whose host was killed outright never reach any settlement
            // path, because all of them run inside the host. Sweep them here,
            // while a `running` row is guaranteed stale: the process that owned it
            // is the one that just exited. Left alone they are not merely wrong,
            // they block every future run. See `Store::reconcile_interrupted_runs`.
            match store.reconcile_interrupted_runs() {
                Ok(stale) if !stale.is_empty() => {
                    eprintln!(
                        "closed {} run(s) left running by a previous session: {}",
                        stale.len(),
                        stale.join(", ")
                    );
                }
                Ok(_) => {}
                Err(e) => {
                    // Not fatal. The database opened, so the app can still work;
                    // failing to start over a sweep would be a worse outcome than
                    // the phantom runs it is trying to clear.
                    eprintln!("could not reconcile interrupted runs: {e}");
                }
            }

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
    use std::path::{Path, PathBuf};

    /// The checkout this test binary was compiled inside.
    fn build_root() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(Path::parent)
            .expect("repo root")
            .to_path_buf()
    }

    #[test]
    fn python_setup_points_at_the_repository_root() {
        let setup = runner::PythonSetup::detect().expect("checkout next to the crate");
        assert!(setup.project_root.join("bench_bridge").exists());
        assert!(setup.project_root.join("run_experiment.py").exists());
    }

    #[test]
    fn db_path_is_under_data_bench() {
        let root = runner::PythonSetup::detect()
            .expect("checkout next to the crate")
            .project_root;
        let db_path = root.join("data").join("bench").join("runs.sqlite3");
        assert!(db_path.starts_with(&root));
    }

    #[test]
    fn bench_root_is_honoured_and_validated() {
        let root = build_root();

        let found =
            runner::PythonSetup::resolve(Some(PathBuf::from("C:\\nowhere")), Some(root.clone()))
                .expect("a real checkout is accepted");
        assert_eq!(found.project_root, root);

        // An explicit request that is wrong is an error naming the variable,
        // not a quiet fallback to some other root - the user asked for this one.
        let err = runner::PythonSetup::resolve(
            None,
            Some(PathBuf::from("C:\\definitely-not-a-checkout")),
        )
        .expect_err("bogus BENCH_ROOT rejected");
        assert!(err.contains("BENCH_ROOT"), "unhelpful message: {err}");
    }

    #[test]
    fn a_root_without_the_sidecar_is_not_a_checkout() {
        let empty = std::env::temp_dir().join("bench-root-empty");
        std::fs::create_dir_all(&empty).expect("temp dir");
        let err = runner::PythonSetup::resolve(None, Some(empty.clone()))
            .expect_err("an empty directory is not a checkout");
        assert!(
            err.contains("run_experiment.py"),
            "unhelpful message: {err}"
        );
        let _ = std::fs::remove_dir_all(&empty);
    }

    #[test]
    fn an_executable_deep_inside_the_checkout_finds_it() {
        let root = build_root();
        let nested = root
            .join("desktop")
            .join("src-tauri")
            .join("target")
            .join("release");
        let setup = runner::PythonSetup::resolve(Some(nested), None)
            .expect("walking up from target/release reaches the root");
        assert_eq!(setup.project_root, root);
    }
}
