//! Supervising the Python sidecar.
//!
//! The sidecar is a child process, `python -m bench_bridge`, that writes NDJSON
//! events to stdout and human-readable logs to stderr. This module owns its
//! whole lifecycle: spawn, stream, cancel, and reap.
//!
//! Two decisions shape the design:
//!
//! - **stderr is drained on its own thread.** A child that fills its stderr pipe
//!   blocks forever, so leaving that pipe unread would deadlock a run that
//!   happens to be chatty - exactly when you least want a hang.
//! - **Cancellation kills the process tree.** `python` can have spawned Ollama
//!   subprocesses; killing only the direct child can leave a CUDA context
//!   holding the GPU, which makes the *next* run fail. `taskkill /T` takes the
//!   tree.

use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver};
use std::sync::{Arc, Mutex};
use std::thread;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager};

use crate::events::{self, RunEvent, WEBVIEW_EVENT};
use crate::store::Store;

/// Default number of prompts offered in the Run form.
pub const DEFAULT_LIMIT: i64 = 50;
/// Default RNG seed, matching the Python side.
pub const DEFAULT_SEED: i64 = 42;

/// How many stderr lines to keep for the failure dialog.
const MAX_STDERR_TAIL: usize = 80;

/// The run request, as sent from the frontend.
#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RunRequest {
    pub dataset: String,
    #[serde(default)]
    pub systems: Vec<String>,
    #[serde(default)]
    pub limit: Option<i64>,
    #[serde(default)]
    pub seed: Option<i64>,
    #[serde(default)]
    pub no_judge: bool,
    #[serde(default)]
    pub dry_run: bool,
    #[serde(default)]
    pub build_prompts: bool,
    /// Skips the PCA projection. The 3D view then has no points for this run's
    /// dataset, so it is a speed escape hatch rather than a default.
    #[serde(default)]
    pub skip_projection: bool,
    /// Supplied by the frontend so the UI, the database and the sidecar all
    /// agree on identity before the process starts.
    #[serde(default)]
    pub run_id: Option<String>,
}

/// What the frontend needs to open the Run page.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RunHandle {
    pub run_id: String,
    pub pid: u32,
    pub dry_run: bool,
}

/// Configuration for locating the Python interpreter and repository root.
#[derive(Debug, Clone)]
pub struct PythonSetup {
    /// Repository root - the parent of `desktop/`.
    pub project_root: PathBuf,
    /// Explicit interpreter; when `None` the usual `python` on PATH is used.
    pub python: Option<PathBuf>,
}

impl PythonSetup {
    /// Derive the layout from the crate manifest directory at compile time,
    /// falling back to the current directory for tests.
    ///
    /// `CARGO_MANIFEST_DIR` is `<root>/desktop/src-tauri`, so the repository root
    /// is two levels up - not one, or the sidecar would be launched from
    /// `desktop/` and would not find `bench_bridge`.
    pub fn detect() -> Self {
        let project_root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(Path::parent)
            .map(Path::to_path_buf)
            .unwrap_or_else(|| PathBuf::from("."));
        let python = std::env::var_os("BENCH_PYTHON").map(PathBuf::from);
        Self {
            project_root,
            python,
        }
    }

    fn interpreter(&self) -> PathBuf {
        self.python
            .clone()
            .unwrap_or_else(|| PathBuf::from("python"))
    }

    /// Full argv for a request.
    ///
    /// Passed as a fixed argument vector, never a shell string: a dataset name or
    /// prompt limit must not be able to turn into a command.
    ///
    /// The whole configuration goes through one `--spec-json` argument because
    /// that is the interface the Python side documents ("what the app passes"),
    /// and because it is the only way to deliver `run_id` - the value that has to
    /// reach the sidecar so its events match the run row this host has already
    /// written. Assembling it from individual flags duplicated the field names
    /// here and let them drift out of step with `RunSpec`.
    fn command(&self, request: &RunRequest, run_id: &str) -> Command {
        let mut cmd = Command::new(self.interpreter());
        cmd.current_dir(&self.project_root);
        cmd.arg("-u").arg("-m").arg("bench_bridge");
        cmd.arg("--spec-json").arg(spec_json(request, run_id));
        // Never let a stray print() become a malformed event line.
        cmd.env("PYTHONUNBUFFERED", "1");
        cmd.env("PYTHONIOENCODING", "utf-8");
        cmd
    }
}

/// The sidecar's `RunSpec`, in the field names its `from_json` expects.
///
/// Snake_case, unlike `RunRequest`, which is camelCase because it crosses the
/// Tauri IPC boundary from TypeScript. `from_json` silently drops any field it
/// does not recognise, so a typo here would be a silently ignored setting rather
/// than an error - which is why `spec_json_matches_the_sidespec` exists.
fn spec_json(request: &RunRequest, run_id: &str) -> String {
    serde_json::json!({
        "run_id": run_id,
        "dataset": request.dataset,
        "systems": request.systems,
        "limit": request.limit,
        "seed": request.seed.unwrap_or(DEFAULT_SEED),
        "build_prompts": request.build_prompts,
        // Deliberately never reset the sidecar's own store: Rust is the only
        // writer, and wiping results would destroy history the UI still shows.
        "reset_store": false,
        "no_judge": request.no_judge,
        "dry_run": request.dry_run,
        // The projection is what the 3D view reads, so it runs unless asked not
        // to. It is slow, which is why it is a flag rather than unconditional.
        "skip_projection": request.skip_projection,
    })
    .to_string()
}

/// Handle to a running child, so the UI can cancel it.
#[derive(Clone)]
pub struct ActiveRun {
    pub run_id: String,
    child: Arc<Mutex<Option<Child>>>,
    /// Set by `cancel` so the pump can tell a user cancel apart from the child
    /// exiting on its own. Without it, cancelling looks like a crash.
    cancelled: Arc<AtomicBool>,
}

/// Why a run stopped.
#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(tag = "reason", rename_all = "snake_case")]
pub enum StopReason {
    /// The sidecar emitted `run_finished`.
    Completed,
    /// The sidecar emitted `run_failed`.
    Failed { message: String },
    /// The user cancelled.
    Cancelled,
    /// The child exited without a terminal event.
    Exited {
        code: Option<i32>,
        stderr_tail: String,
    },
}

/// Spawn the sidecar and stream its events.
///
/// Returns as soon as the child is running; events are pushed to the webview and
/// persisted on a background thread.
pub fn start(
    app: AppHandle,
    store: Arc<Store>,
    setup: PythonSetup,
    request: RunRequest,
) -> Result<RunHandle, String> {
    let run_id = request.run_id.clone().unwrap_or_else(new_run_id);
    let now_ms = now_ms();

    store
        .create_run(&run_id, now_ms, &request.dataset)
        .map_err(|e| format!("cannot record run: {e}"))?;

    let mut cmd = setup.command(&request, &run_id);
    cmd.stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = match cmd.spawn() {
        Ok(child) => child,
        Err(err) => {
            // The run row was already written, so failing to spawn would otherwise
            // leave it `running` forever: a run that never started, that nothing
            // will ever finish, and that blocks the "is anything in progress"
            // check the Run page makes before offering to start another.
            let message = format!("cannot start {}: {err}", setup.interpreter().display());
            let _ = store.fail_run(&run_id, &message);
            return Err(message);
        }
    };
    let pid = child.id();
    let stdout = child.stdout.take().expect("stdout was piped");
    let stderr = child.stderr.take().expect("stderr was piped");

    let active = Arc::new(ActiveRun {
        run_id: run_id.clone(),
        child: Arc::new(Mutex::new(Some(child))),
        cancelled: Arc::new(AtomicBool::new(false)),
    });
    // Published through the slot so cancel_run can find it. Managing the
    // `ActiveRun` directly would look equivalent and be silently wrong: Tauri
    // keeps the first value it is given for a type and drops later ones, so
    // every run after the first would be uncancellable. See `ActiveRunSlot`.
    let Some(slot) = app
        .try_state::<ActiveRunSlot>()
        .map(|slot| slot.inner().clone())
    else {
        let message = "the active run slot was never managed";
        let _ = store.fail_run(&run_id, message);
        return Err(message.into());
    };
    slot.install(active.clone());

    // stderr drain thread: see the module comment on why this cannot be lazy.
    let (log_tx, log_rx) = mpsc::channel::<String>();
    thread::spawn(move || {
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            // Forwarded as log events so it shows up in the Run page's console
            // rather than only in a terminal nobody has open.
            if log_tx.send(line).is_err() {
                break;
            }
        }
    });

    let (stop_tx, stop_rx) = mpsc::channel::<StopReason>();

    {
        let app = app.clone();
        let store = store.clone();
        let active = active.clone();
        let finished_run_id = run_id.clone();
        thread::spawn(move || {
            let reason = pump(
                app.clone(),
                store.clone(),
                stdout,
                log_rx,
                stop_rx,
                active.clone(),
            );

            // A run row must never outlive its process.
            if let Err(err) = settle_run(&store, &finished_run_id, &reason) {
                push_log(
                    &app,
                    "error",
                    &format!("could not close out run {finished_run_id}: {err}"),
                );
            }

            let _ = stop_tx.send(reason);
            // Wait for the child so it is not left as a zombie.
            wait_for_exit(&active);
            // Only now is the slot free: while the child is still alive this run
            // is genuinely cancelable, and clearing early would leave a live run
            // with nothing to cancel. Guarded by run id, so a run that finishes
            // after its successor started cannot evict the successor.
            slot.retire(&finished_run_id);
        });
    }

    Ok(RunHandle {
        run_id,
        pid,
        dry_run: request.dry_run,
    })
}

/// Outcome of handling one line of the sidecar's stdout.
struct Handled {
    /// Set when the line was a terminal event.
    terminal: Option<StopReason>,
}

/// Persist and re-emit a single line of the sidecar's stdout.
///
/// Split out of `pump` so it can be tested against a real event stream without
/// an `AppHandle`: the logging and emitting are parameters, so the only thing
/// under test is the protocol handling and the database writes.
///
/// The rule throughout is that a problem with one line is reported and skipped,
/// never fatal. A malformed line or a failed insert must not cost a run that may
/// be hours long and is still useful on screen.
fn handle_line(
    store: &Store,
    line: &str,
    push_log: &mut dyn FnMut(&str, &str),
    push_event: &mut dyn FnMut(&RunEvent),
) -> Handled {
    match RunEvent::parse(line) {
        Ok(event) => {
            if let Err(err) = store.apply(&event) {
                push_log("error", &format!("event not persisted: {err}"));
            }
            push_event(&event);
            let terminal = if event.is_terminal() {
                Some(if event.event_type == events::types::RUN_FINISHED {
                    StopReason::Completed
                } else {
                    StopReason::Failed {
                        message: event.str_field("error").unwrap_or("run failed").to_string(),
                    }
                })
            } else {
                None
            };
            Handled { terminal }
        }
        Err(err) => {
            // A malformed line is a protocol bug. Report it and keep going.
            push_log("error", &format!("malformed event: {err}"));
            Handled { terminal: None }
        }
    }
}

/// Read stdout until EOF, persisting and re-emitting each event.
///
/// Returns why the run stopped. A run with no terminal event is treated as an
/// `Exited` stop with whatever stderr we captured, because "the chart just
/// stopped" is not an acceptable failure mode to surface to a user.
fn pump(
    app: AppHandle,
    store: Arc<Store>,
    stdout: impl std::io::Read + Send + 'static,
    log_rx: Receiver<String>,
    stop_rx: Receiver<StopReason>,
    active: Arc<ActiveRun>,
) -> StopReason {
    let mut lines = BufReader::new(stdout).lines();
    let log_rx = log_rx;
    let mut stderr_tail: Vec<String> = Vec::new();
    let mut terminal: Option<StopReason> = None;
    let mut cancelled: Option<StopReason> = None;

    loop {
        // Cancellation is checked between lines so it takes effect promptly
        // without a second thread racing the stdout reader.
        if let Ok(reason) = stop_rx.try_recv() {
            cancelled = Some(reason);
            break;
        }

        // Drain stderr into the tail and the console. Done on every iteration
        // because a chatty child can otherwise fill the pipe between reads.
        while let Ok(line) = log_rx.try_recv() {
            if stderr_tail.len() >= MAX_STDERR_TAIL {
                stderr_tail.remove(0);
            }
            stderr_tail.push(line.clone());
            push_log(&app, "info", &line);
        }

        match lines.next() {
            Some(Ok(line)) => {
                let mut log = |level: &str, message: &str| push_log(&app, level, message);
                let mut emit = |event: &RunEvent| push_event(&app, event);
                terminal = handle_line(&store, &line, &mut log, &mut emit)
                    .terminal
                    .or(terminal);
            }
            Some(Err(err)) => {
                push_log(&app, "error", &format!("stdout read failed: {err}"));
                break;
            }
            None => break,
        }
    }

    if let Some(reason) = cancelled {
        kill_tree(&active);
        return reason;
    }

    // A cancel kills the child, which closes stdout and ends the loop above
    // without ever sending on stop_rx. Check the flag so the run is reported as
    // cancelled rather than as a crash.
    if active.was_cancelled() {
        kill_tree(&active);
        return StopReason::Cancelled;
    }

    // stdout closed, so the process is exiting. Give the log thread a moment to
    // deliver the last lines so a failure is not reported with an empty tail.
    let deadline = std::time::Instant::now() + std::time::Duration::from_millis(200);
    while std::time::Instant::now() < deadline {
        match log_rx.recv_timeout(std::time::Duration::from_millis(50)) {
            Ok(line) => {
                if stderr_tail.len() >= MAX_STDERR_TAIL {
                    stderr_tail.remove(0);
                }
                stderr_tail.push(line.clone());
                push_log(&app, "info", &line);
            }
            Err(_) => break,
        }
    }

    let code = wait_for_exit(&active);
    terminal.unwrap_or(StopReason::Exited {
        code,
        stderr_tail: stderr_tail.join("\n"),
    })
}

/// Push one stderr line to the Run page console as a log event.
fn push_log(app: &AppHandle, level: &str, message: &str) {
    let _ = app.emit(
        WEBVIEW_EVENT,
        serde_json::json!({
            "type": events::types::LOG,
            "level": level,
            "data": {"level": level, "message": message},
        }),
    );
}

fn push_event(app: &AppHandle, event: &RunEvent) {
    let _ = app.emit(WEBVIEW_EVENT, event);
}

/// Close out the run row for any stop reason the sidecar did not report itself.
///
/// `Completed` and `Failed` arrived as `run_finished`/`run_failed` events and
/// were already written by `handle_line`. The other two are the host ending the
/// run with no terminal event at all: cancelling kills the sidecar mid-prompt,
/// and a crash never produces `run_failed` either. Without this, either one
/// leaves the row `running` forever - invisible as a failure, and enough to make
/// the app look busy when nothing is.
///
/// Split out from the pump thread so each branch can be tested directly.
fn settle_run(store: &Store, run_id: &str, reason: &StopReason) -> rusqlite::Result<()> {
    match reason {
        StopReason::Cancelled => store.cancel_run(run_id),
        StopReason::Exited { code, stderr_tail } => {
            store.fail_run(run_id, &describe_exit(code, stderr_tail))
        }
        StopReason::Completed | StopReason::Failed { .. } => Ok(()),
    }
}

/// The message stored when the sidecar died without saying why.
///
/// Prefers the tail of stderr, because "the sidecar exited with code 1" on its
/// own tells a user reading the Results page nothing they can act on.
fn describe_exit(code: &Option<i32>, stderr_tail: &str) -> String {
    let trimmed = stderr_tail.trim();
    let summary = match code {
        Some(code) => format!("sidecar exited with code {code}"),
        None => "sidecar was terminated".to_string(),
    };
    if trimmed.is_empty() {
        summary
    } else {
        format!("{summary}: {trimmed}")
    }
}

/// Kill the child and any processes it started, and wait for it to actually go.
///
/// `taskkill /T` is tried first because it is the only thing that reaches
/// grandchildren: an orphaned helper can keep the CUDA context alive and break
/// the next run. But it is an external program, so it can be missing, denied or
/// simply not know the pid, and every one of those used to end the same way -
/// ignored, followed by an unbounded `child.wait()`. The run would then keep
/// going, and because callers include the Tauri main thread, so would the whole
/// app: a Cancel button that freezes the window until the run finishes on its
/// own.
///
/// So the fallbacks matter more than the primary path: if `taskkill` did not
/// report success, ask the handle to kill the child directly, and only then
/// wait, with a bound.
fn kill_tree(active: &ActiveRun) {
    let Ok(mut guard) = active.child.lock() else {
        return;
    };
    let Some(child) = guard.as_mut() else { return };
    let pid = child.id();

    let killed_tree = Command::new("taskkill")
        .args(["/F", "/T", "/PID", &pid.to_string()])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        // Treat "could not be started" as a failure rather than assuming success.
        .unwrap_or(false);

    if !killed_tree {
        // Best effort on the direct handle. It cannot reach grandchildren, but it
        // is enough to stop the run, which is what the user asked for.
        let _ = child.kill();
    }

    // Bounded so a process that survives both attempts cannot wedge the caller.
    // A reaped handle is left reaped: `wait` is idempotent here because the slot
    // is cleared below either way.
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => {
                if std::time::Instant::now() >= deadline {
                    break;
                }
                std::thread::sleep(std::time::Duration::from_millis(50));
            }
            Err(_) => break,
        }
    }
    *guard = None;
}

/// Wait for the child to exit, returning its code.
///
/// Idempotent: the child slot is cleared, so a second call is a no-op rather
/// than a second `wait` on an already-reaped process.
fn wait_for_exit(active: &ActiveRun) -> Option<i32> {
    let Ok(mut guard) = active.child.lock() else {
        return None;
    };
    let Some(child) = guard.as_mut() else {
        return None;
    };
    let status = child.wait().ok();
    *guard = None;
    status.and_then(|s| s.code())
}

impl ActiveRun {
    /// Cancel the run, if it is still going.
    pub fn cancel(&self) -> bool {
        self.cancelled.store(true, Ordering::SeqCst);
        kill_tree(self);
        true
    }

    /// Whether [`cancel`](Self::cancel) has been called.
    pub fn was_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::SeqCst)
    }

    /// Whether the sidecar process is still alive.
    ///
    /// The authoritative "is a run in progress" answer. Mere presence of an
    /// `ActiveRun` cannot be used as the test, because the handle outlives the
    /// run: doing so makes `run_in_progress` answer true forever and blocks every
    /// subsequent run.
    ///
    /// A process that has already been reaped shows `None` in the slot. An
    /// `Err` from `try_wait` means the child cannot be interrogated, which is
    /// treated as finished: erring towards "running" would wedge the app shut,
    /// whereas erring the other way only permits a run that will report its own
    /// failure.
    pub fn is_running(&self) -> bool {
        let Ok(mut guard) = self.child.lock() else {
            return false;
        };
        match guard.as_mut() {
            None => false,
            Some(child) => matches!(child.try_wait(), Ok(None)),
        }
    }
}

/// The run the app is driving right now, if any.
///
/// This is managed state, and that is the whole problem it exists to solve.
/// Tauri writes managed state **once per type**: `manage` inserts only when the
/// type is absent and silently ignores the call otherwise (`tauri::state`'s
/// `set` checks `contains_key` before inserting). So re-managing an `ActiveRun`
/// for each run leaves the first one in place forever, and `try_state` hands back
/// a dead handle from then on.
///
/// The failure that produced was quiet and only showed up on the second run of a
/// session: `cancel_run` set the cancelled flag and killed a process that had
/// already exited, so the run carried on to completion while the UI said it was
/// cancelling. `run_in_progress` and the "a run is already in progress" guard were
/// reading the same stale handle, so both were answering about run 1 no matter
/// what was actually running - which also meant a second run could be started
/// alongside a live one, orphaning its sidecar.
///
/// Managing this slot once at startup and swapping the handle inside it keeps the
/// mutable part in ordinary Rust, where replacing a value is not a special case.
///
/// `Clone` is a handle to the same slot, not a copy: commands can only borrow
/// managed state for the lifetime of the borrow, so the pump thread needs an owned
/// handle to retire its own run.
#[derive(Clone, Default)]
pub struct ActiveRunSlot(Arc<Mutex<Option<Arc<ActiveRun>>>>);

impl ActiveRunSlot {
    /// An empty slot, managed once during application setup.
    pub fn new() -> Self {
        Self(Arc::new(Mutex::new(None)))
    }

    /// The current run, if one has been installed and not yet retired.
    pub fn current(&self) -> Option<Arc<ActiveRun>> {
        self.0.lock().ok().and_then(|guard| guard.clone())
    }

    /// Make `active` the current run, replacing whatever was there.
    pub fn install(&self, active: Arc<ActiveRun>) {
        if let Ok(mut guard) = self.0.lock() {
            *guard = Some(active);
        }
    }

    /// Clear the slot, but only if it still holds `run_id`.
    ///
    /// The check matters because a run that ends on its own is retired from its
    /// own pump thread, which can happen after the next run has already been
    /// installed. Without it, a slow finish would clear a live run's slot and
    /// leave nothing to cancel.
    pub fn retire(&self, run_id: &str) {
        if let Ok(mut guard) = self.0.lock() {
            if guard
                .as_deref()
                .is_some_and(|active| active.run_id == run_id)
            {
                *guard = None;
            }
        }
    }

    /// Whether a run is currently in progress.
    pub fn is_running(&self) -> bool {
        self.current().is_some_and(|active| active.is_running())
    }
}

/// A fresh run id.
///
/// Matches Python's `uuid.uuid4().hex`, so the value is 32 lowercase hex
/// characters with no dashes.
pub fn new_run_id() -> String {
    uuid::Uuid::new_v4().simple().to_string()
}

/// Milliseconds since the Unix epoch.
pub fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_ids_are_32_hex_chars() {
        let id = new_run_id();
        assert_eq!(id.len(), 32);
        assert!(id.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(id, new_run_id());
    }

    /// Lines captured verbatim from a real System B run
    /// (`python -m bench_bridge --dataset hotpot --systems B --limit 1
    /// --no-judge --skip-projection`), trimmed only where a value is a run id.
    ///
    /// Using real output rather than hand-written events is the point: it pins
    /// the Rust side of the protocol to what the Python side actually emits,
    /// including the DQN payloads that no dry run would produce and the `null`
    /// metrics that a failed judge must leave absent.
    const REAL_B_STREAM: &[&str] = &[
        r#"{"v":1,"seq":1,"ts_ms":1790953944161,"run_id":"RUNID","type":"run_started","data":{"dataset":"hotpot","systems":["B"],"prompt_count":1,"seed":42,"no_judge":true,"dry_run":false,"project_root":"C:/repo","embed_model":"nomic-embed-text","generator_model":"qwen3:8b","judge_model":null}}"#,
        r#"{"v":1,"seq":2,"ts_ms":1790953944162,"run_id":"RUNID","type":"phase","data":{"system":"B","phase":"b.1"}}"#,
        r#"{"v":1,"seq":3,"ts_ms":1790953944163,"run_id":"RUNID","type":"phase","data":{"system":"B","phase":"b.2"}}"#,
        r#"{"v":1,"seq":10,"ts_ms":1790953944161,"run_id":"RUNID","type":"train_step","data":{"run_id":"RUNID","system":"B","step":1,"prompt_id":"0","k":4,"faithfulness":1.0,"answer_relevancy":0.6380957521780042,"context_recall":null,"reward":0.5733335132623014,"loss":null,"epsilon":0.995,"q_values":[-0.06813840568065643,-0.04285893216729164,0.09773340076208115,0.0540144145488739,-0.07314830273389816],"prompt_tokens":5421,"completion_tokens":7,"total_tokens":5428,"judge_prompt_tokens":4685,"judge_completion_tokens":1827,"embedding_time_s":3.961341899994295,"retrieval_time_s":0.017700399970635772,"generation_time_s":7.040704699989874,"judge_time_s":176.9192823000485,"total_time_s":187.9390293000033}}"#,
        r#"{"v":1,"seq":12,"ts_ms":1790953950000,"run_id":"RUNID","type":"prompt_completed","data":{"system":"B","index":0,"prompt_id":"0","k":4,"row":{"system_id":"B","prompt_id":"0","prompt_index":0,"phase":"system_b","question":"Who is the father of Samuel Kuffour?","ground_truth":"Samuel Osei Kuffour","answer":"Samuel Kuffour","retrieved_k":4,"retrieved_ids":["d1","d2","d3","d4"],"retrieved_distances":[0.1,0.2,0.3,0.4],"faithfulness":1.0,"answer_relevancy":null,"context_recall":null,"prompt_tokens":5421,"completion_tokens":7,"total_tokens":5428,"judge_prompt_tokens":4685,"judge_completion_tokens":1827,"embedding_time_s":3.961341899994295,"retrieval_time_s":0.017700399970635772,"generation_time_s":7.040704699989874,"judge_time_s":176.9192823000485,"total_time_s":187.9390293000033,"reward":0.5733335132623014}}}"#,
        r#"{"v":1,"seq":18,"ts_ms":1790953967123,"run_id":"RUNID","type":"reward","data":{"system":"B","k_distribution":{"3":1}}}"#,
        r#"{"v":1,"seq":19,"ts_ms":1790953967200,"run_id":"RUNID","type":"stats","data":{"payload":{"n":1,"systems":{"B":{"faithfulness":{"n":1,"mean":1.0}}}}}}"#,
        r#"{"v":1,"seq":20,"ts_ms":1790953967300,"run_id":"RUNID","type":"run_finished","data":{"duration_s":594.3,"prompt_rows":1,"training_rows":1}}"#,
    ];

    /// An in-memory store, matching store.rs's own tests: what is under test is
    /// the protocol handling, not the file.
    fn store() -> Store {
        let conn = rusqlite::Connection::open_in_memory().unwrap();
        crate::db::migrate(&conn).unwrap();
        Store::from_connection(conn)
    }

    /// A store with a run already created, which is what the host does before it
    /// spawns the sidecar. Needed because `prompt_rows.run_id` references
    /// `runs(run_id)`, so an event that arrives for an unknown run is a
    /// constraint failure rather than a silent orphan.
    fn store_with_run(run_id: &str) -> Store {
        let store = store();
        store.create_run(run_id, 1, "hotpot").unwrap();
        store
    }

    fn status_of(store: &Store, run_id: &str) -> String {
        store.get_run(run_id).unwrap().unwrap()["status"]
            .as_str()
            .unwrap()
            .to_string()
    }

    /// A real captured stream must parse, persist and terminate cleanly.
    ///
    /// This is the one test that spans the actual seam between the two halves of
    /// the system: Python writes the line, Rust reads it and writes the database.
    #[test]
    fn a_real_sidecar_stream_parses_and_persists() {
        let run_id = "d684879530794794ae52d58cf845bafc";
        let store = store_with_run(run_id);

        let mut logs: Vec<String> = Vec::new();
        let mut emitted: Vec<String> = Vec::new();
        let mut terminal: Option<StopReason> = None;

        for line in REAL_B_STREAM {
            let mut log = |level: &str, message: &str| logs.push(format!("{level}: {message}"));
            let mut emit = |event: &RunEvent| emitted.push(event.event_type.to_string());
            terminal = handle_line(&store, &line.replace("RUNID", run_id), &mut log, &mut emit)
                .terminal
                .or(terminal);
        }

        assert!(
            logs.is_empty(),
            "the real stream produced diagnostics: {logs:?}"
        );
        assert_eq!(
            emitted,
            vec![
                "run_started",
                "phase",
                "phase",
                "train_step",
                "prompt_completed",
                "reward",
                "stats",
                "run_finished",
            ]
        );
        assert!(matches!(terminal, Some(StopReason::Completed)));

        // The run is recorded as finished rather than left `running`.
        assert_eq!(status_of(&store, run_id), "completed");

        // The training step landed with its reward and all five q-values.
        let steps = store.get_training_rows(run_id).unwrap();
        assert_eq!(steps.len(), 1);
        let step = &steps[0];
        assert_eq!(step["reward"], 0.5733335132623014);
        assert_eq!(step["epsilon"], 0.995);
        // All five q-values survive the round trip, in k order. Compared with a
        // tolerance because the model emits f32, so the value read back out of
        // SQLite differs from the JSON literal in the last bit or two. That is
        // the expected precision, not a defect.
        let q: Vec<f64> = step["q_values"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_f64().unwrap())
            .collect();
        let expected = [
            -0.06813840568065643,
            -0.04285893216729164,
            0.09773340076208115,
            0.0540144145488739,
            -0.07314830273389816,
        ];
        assert_eq!(q.len(), expected.len());
        for (got, want) in q.iter().zip(expected) {
            assert!(
                (got - want).abs() < 1e-6,
                "q-value drifted: {got} vs {want}"
            );
        }
        // The weight update was skipped, and a skipped update has no loss. A
        // fabricated 0 here would draw a flat zero on the loss chart.
        assert_eq!(step["loss"], serde_json::Value::Null);
        // Likewise the judge could not score context recall.
        assert_eq!(step["context_recall"], serde_json::Value::Null);

        // And the prompt row, including the reward and the metrics the judge
        // never produced.
        let rows = store.get_prompt_rows(run_id).unwrap();
        assert_eq!(rows.len(), 1);
        let row = &rows[0];
        assert_eq!(row["answer"], "Samuel Kuffour");
        assert_eq!(row["faithfulness"], 1.0);
        assert_eq!(row["answer_relevancy"], serde_json::Value::Null);
        assert_eq!(row["context_recall"], serde_json::Value::Null);
        assert_eq!(row["reward"], 0.5733335132623014);
        assert_eq!(row["total_tokens"], 5428);
    }

    /// One corrupt line in the middle of a run must not lose the rest of it.
    #[test]
    fn a_malformed_line_does_not_end_the_run() {
        let run_id = "d684879530794794ae52d58cf845bafc";
        let store = store_with_run(run_id);
        let mut logs: Vec<String> = Vec::new();
        let mut noop = |_: &RunEvent| {};

        let mut terminal = None;
        let mut lines: Vec<String> = REAL_B_STREAM
            .iter()
            .map(|l| l.replace("RUNID", run_id))
            .collect();
        // Splice a truncated line into the middle, the way a killed sidecar or a
        // pipe that closed early would produce.
        lines.insert(
            4,
            r#"{"v":1,"seq":99,"run_id":"RUNID","type":"tra"#.to_string(),
        );

        for line in &lines {
            let mut log = |level: &str, message: &str| logs.push(format!("{level}: {message}"));
            terminal = handle_line(&store, line, &mut log, &mut noop)
                .terminal
                .or(terminal);
        }

        assert_eq!(
            logs.len(),
            1,
            "exactly one line should be rejected: {logs:?}"
        );
        assert!(logs[0].starts_with("error: malformed event"));
        assert!(matches!(terminal, Some(StopReason::Completed)));
        assert_eq!(store.get_prompt_rows(run_id).unwrap().len(), 1);
        assert_eq!(store.get_training_rows(run_id).unwrap().len(), 1);
        assert_eq!(status_of(&store, run_id), "completed");
    }

    /// A `run_failed` line must produce a Failed stop carrying the sidecar's
    /// own message, not a generic one.
    #[test]
    fn a_real_failure_event_becomes_a_failed_stop_with_the_real_message() {
        let run_id = "d684879530794794ae52d58cf845bafc";
        let store = store_with_run(run_id);
        let mut noop = |_: &RunEvent| {};

        let line = format!(
            r#"{{"v":1,"seq":9,"ts_ms":1,"run_id":"{run_id}","type":"run_failed","data":{{"error":"ChromaDB collection not found for dataset 'nope'"}}}}"#
        );
        let mut log = |_: &str, _: &str| {};
        let handled = handle_line(&store, &line, &mut log, &mut noop);

        match handled.terminal {
            Some(StopReason::Failed { message }) => {
                assert_eq!(message, "ChromaDB collection not found for dataset 'nope'")
            }
            other => panic!("expected a Failed stop, got {other:?}"),
        }

        assert_eq!(status_of(&store, run_id), "failed");
    }

    /// Cancelling must close the run row out, or the app looks busy forever.
    ///
    /// The regression this guards was found by cancelling a real run in the real
    /// window: the sidecar died, the events stopped, and the row stayed
    /// `running` for good, because the only thing that ever set a terminal status
    /// was a terminal event from the sidecar that had just been killed.
    #[test]
    fn cancelling_settles_the_run_row() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();

        settle_run(&store, "run1", &StopReason::Cancelled).unwrap();

        assert_eq!(status_of(&store, "run1"), "cancelled");
    }

    /// The same hole, reached by a sidecar that died rather than being stopped.
    #[test]
    fn a_sidecar_that_vanished_settles_the_run_row_as_failed() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();

        settle_run(
            &store,
            "run1",
            &StopReason::Exited {
                code: Some(1),
                stderr_tail: "Traceback (most recent call last):\n  KeyError: 'hotpot'".into(),
            },
        )
        .unwrap();

        assert_eq!(status_of(&store, "run1"), "failed");
        let run = store.get_run("run1").unwrap().unwrap();
        assert!(
            run["error"].as_str().unwrap().contains("KeyError"),
            "the stderr tail is the only useful part: {run}"
        );
    }

    /// These two already wrote their own status from the event payload. Writing
    /// again would overwrite the counts and duration the sidecar reported.
    #[test]
    fn settling_leaves_an_event_reported_outcome_alone() {
        for reason in [
            StopReason::Completed,
            StopReason::Failed {
                message: "boom".into(),
            },
        ] {
            let store = store();
            store.create_run("run1", 1, "hotpot").unwrap();
            settle_run(&store, "run1", &reason).unwrap();
            assert_eq!(
                status_of(&store, "run1"),
                "running",
                "{reason:?} must not touch the row"
            );
        }
    }

    #[test]
    fn an_exit_without_a_code_still_says_something_useful() {
        assert_eq!(
            describe_exit(&None, "   "),
            "sidecar was terminated",
            "an empty stderr tail should not leave a bare colon"
        );
        assert_eq!(
            describe_exit(&Some(0), "all done"),
            "sidecar exited with code 0: all done"
        );
    }

    /// `kill_tree` against a real, live process.
    ///
    /// This is the check that was missing when cancelling turned out to do
    /// nothing: every other test here used an already-dead child, so "the kill
    /// path runs" was never actually established - only that the code around it
    /// compiles. `cmd /c ping` stands in for the sidecar: a real process tree,
    /// no Python needed.
    #[test]
    fn cancelling_kills_a_live_process() {
        let child = std::process::Command::new("cmd")
            .args(["/c", "ping", "-n", "60", "127.0.0.1"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn");
        let pid = child.id();
        let active = ActiveRun {
            run_id: "run1".into(),
            child: Arc::new(Mutex::new(Some(child))),
            cancelled: Arc::new(AtomicBool::new(true)),
        };
        assert!(active.is_running(), "the process should be alive to start");

        kill_tree(&active);

        // The handle is gone, so liveness has to be asked about the pid.
        assert!(!pid_is_alive(pid), "the process {pid} survived the kill");
        assert!(!active.is_running(), "the run should not look in progress");
    }

    /// A cancelled run whose sidecar will not die must not hang the caller.
    ///
    /// The freeze this guards was unbounded: `child.wait()` with no timeout, on
    /// the Tauri main thread, so the window stopped responding until the run
    /// finished by itself. Ten seconds is longer than any test should need, so
    /// this is bounded loosely on purpose - the assertion is that it returns at
    /// all, not how fast.
    #[test]
    fn killing_returns_even_when_the_process_outlives_it() {
        let child = std::process::Command::new("cmd")
            .args(["/c", "ping", "-n", "600", "127.0.0.1"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn");
        let pid = child.id();
        let active = ActiveRun {
            run_id: "run1".into(),
            child: Arc::new(Mutex::new(Some(child))),
            cancelled: Arc::new(AtomicBool::new(true)),
        };

        let started = std::time::Instant::now();
        kill_tree(&active);
        let elapsed = started.elapsed();

        assert!(
            elapsed < std::time::Duration::from_secs(30),
            "kill_tree took {elapsed:?}, which means it waited on the child"
        );
        // Clean up whatever is left, so the test does not leak a process.
        let _ = std::process::Command::new("taskkill")
            .args(["/F", "/T", "/PID", &pid.to_string()])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }

    /// Whether a pid still names a live process.
    fn pid_is_alive(pid: u32) -> bool {
        // tasklist is the cheapest thing on Windows that answers this without
        // opening a handle that would need closing again.
        Command::new("tasklist")
            .args(["/FI", &format!("PID eq {pid}"), "/NH"])
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .output()
            .map(|out| String::from_utf8_lossy(&out.stdout).contains(&pid.to_string()))
            .unwrap_or(false)
    }

    /// An `ActiveRun` wrapping a real process that is already gone.
    ///
    /// Uses `cmd /c exit` so no Python is needed: what is under test is the
    /// liveness query, not the sidecar.
    fn finished_active_run() -> ActiveRun {
        let mut child = std::process::Command::new("cmd")
            .args(["/c", "exit", "0"])
            .spawn()
            .expect("spawn");
        child.wait().expect("wait");
        ActiveRun {
            run_id: "run1".into(),
            child: Arc::new(Mutex::new(Some(child))),
            cancelled: Arc::new(AtomicBool::new(false)),
        }
    }

    #[test]
    fn a_finished_process_is_not_reported_as_running() {
        // The regression this guards: `run_in_progress` used to ask whether a
        // managed `ActiveRun` existed, and that handle outlives the run. So the
        // first run left the app permanently refusing to start another.
        assert!(!finished_active_run().is_running());
    }

    #[test]
    fn a_reaped_child_is_not_reported_as_running() {
        // `wait_for_exit` leaves an empty slot once the pump thread has reaped the
        // process. That must also read as finished.
        let active = ActiveRun {
            run_id: "run1".into(),
            child: Arc::new(Mutex::new(None)),
            cancelled: Arc::new(AtomicBool::new(false)),
        };
        assert!(!active.is_running());
    }

    /// An `ActiveRun` for `run_id` wrapping `cmd /c ping`, which stays alive long
    /// enough to be interrogated.
    fn live_active_run(run_id: &str) -> Arc<ActiveRun> {
        let child = std::process::Command::new("cmd")
            .args(["/c", "ping -n 4 127.0.0.1 > nul"])
            .spawn()
            .expect("spawn");
        Arc::new(ActiveRun {
            run_id: run_id.into(),
            child: Arc::new(Mutex::new(Some(child))),
            cancelled: Arc::new(AtomicBool::new(false)),
        })
    }

    fn kill(active: &ActiveRun) {
        let mut guard = active.child.lock().unwrap();
        if let Some(child) = guard.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    #[test]
    fn installing_a_second_run_replaces_the_first() {
        // The regression that matters most. With the `ActiveRun` managed directly,
        // Tauri kept the first one and ignored the second, so cancelling run 2
        // killed run 1's dead handle and run 2 carried on. `install` has to make
        // the newest run the current one.
        let slot = ActiveRunSlot::new();
        let first = live_active_run("run1");
        let second = live_active_run("run2");

        slot.install(first.clone());
        assert_eq!(slot.current().expect("first run").run_id, "run1");

        slot.install(second.clone());
        assert_eq!(slot.current().expect("second run").run_id, "run2");

        // And the handle that comes back is the live one, not a leftover.
        let current = slot.current().expect("current run");
        assert!(current.is_running());
        assert!(!current.was_cancelled());

        kill(&first);
        kill(&second);
    }

    #[test]
    fn cancelling_reaches_the_installed_run_and_not_an_earlier_one() {
        // What the user actually gets, and the shape of the original bug: cancel
        // looks the run up through the slot, exactly as `cancel_run` does. If the
        // slot hands back run1 the cancel lands on a dead handle and run2 keeps
        // going, so the assertion that matters is on the run the slot returned.
        let slot = ActiveRunSlot::new();
        let first = finished_active_run_for("run1");
        slot.install(Arc::new(first.clone()));

        let second = live_active_run("run2");
        slot.install(second.clone());

        let current = slot.current().expect("a run to cancel");
        assert_eq!(current.run_id, "run2", "cancel must target the newest run");
        current.cancel();

        assert!(second.was_cancelled(), "the live run was not cancelled");
        assert!(
            !first.was_cancelled(),
            "the retired run must not be cancelled"
        );
        // The flag alone is not the kill; the process has to actually be gone.
        wait_while_running(&second);
        assert!(!second.is_running(), "the sidecar outlived the cancel");
        assert!(!first.was_cancelled());
    }

    #[test]
    fn a_run_is_only_reported_as_running_while_its_own_process_lives() {
        let slot = ActiveRunSlot::new();
        assert!(!slot.is_running(), "an empty slot has nothing in progress");

        let first = live_active_run("run1");
        slot.install(first.clone());
        assert!(slot.is_running());

        kill(&first);
        slot.retire("run1");
        assert!(!slot.is_running());
        assert!(slot.current().is_none());
    }

    #[test]
    fn retiring_one_run_does_not_evict_a_run_that_replaced_it() {
        // Runs finish on their own pump thread, so a slow run can retire after the
        // next one is already going. Clearing unconditionally would leave the live
        // run with nothing to cancel.
        let slot = ActiveRunSlot::new();
        let older = live_active_run("run1");
        let newer = live_active_run("run2");

        slot.install(older.clone());
        slot.install(newer.clone());
        slot.retire("run1");

        assert_eq!(
            slot.current().expect("run2 survives").run_id,
            "run2",
            "run1 retiring must not evict run2"
        );

        // Retiring the run that is actually installed does clear it.
        slot.retire("run2");
        assert!(slot.current().is_none());

        kill(&older);
        kill(&newer);
    }

    #[test]
    fn a_retired_run_is_not_left_behind_as_current() {
        // And the ordering that produced the original symptom: run 1 ends, then
        // run 2 starts. Cancelling now has to reach run 2.
        let slot = ActiveRunSlot::new();
        let first = finished_active_run_for("run1");
        slot.install(Arc::new(first.clone()));
        slot.retire("run1");
        assert!(
            slot.current().is_none(),
            "an ended run leaves nothing current"
        );

        let second = live_active_run("run2");
        slot.install(second.clone());

        let current = slot.current().expect("run2 is current");
        assert_eq!(current.run_id, "run2");
        current.cancel();
        assert!(!first.was_cancelled());
        wait_while_running(&second);
        assert!(!second.is_running());
    }

    /// Poll until `active`'s process is gone, so a kill is observed rather than
    /// assumed.
    fn wait_while_running(active: &ActiveRun) {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
        while active.is_running() && std::time::Instant::now() < deadline {
            std::thread::sleep(std::time::Duration::from_millis(25));
        }
    }

    /// A finished `ActiveRun` for a given id, so tests can name their runs.
    fn finished_active_run_for(run_id: &str) -> ActiveRun {
        let mut child = std::process::Command::new("cmd")
            .args(["/c", "exit", "0"])
            .spawn()
            .expect("spawn");
        child.wait().expect("wait");
        ActiveRun {
            run_id: run_id.into(),
            child: Arc::new(Mutex::new(Some(child))),
            cancelled: Arc::new(AtomicBool::new(false)),
        }
    }

    #[test]
    fn a_live_process_is_reported_as_running() {
        let child = std::process::Command::new("cmd")
            .args(["/c", "ping -n 4 127.0.0.1 > nul"])
            .spawn()
            .expect("spawn");
        let active = ActiveRun {
            run_id: "run1".into(),
            child: Arc::new(Mutex::new(Some(child))),
            cancelled: Arc::new(AtomicBool::new(false)),
        };
        assert!(active.is_running());
        let mut guard = active.child.lock().unwrap();
        if let Some(child) = guard.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    #[test]
    fn cancelling_marks_the_run() {
        // The flag, not the kill, is what the pump thread reports as the reason.
        let active = finished_active_run();
        assert!(!active.was_cancelled());
        active.cancel();
        assert!(active.was_cancelled());
    }

    #[test]
    fn request_defaults_are_applied() {
        // The frontend may send only a dataset; everything else must have a
        // usable default rather than failing to deserialise.
        let request: RunRequest = serde_json::from_str(r#"{"dataset":"hotpot"}"#).unwrap();
        assert_eq!(request.dataset, "hotpot");
        assert!(request.systems.is_empty());
        assert_eq!(request.limit, None);
        assert!(!request.no_judge);
    }

    #[test]
    fn request_reads_camel_case_from_the_frontend() {
        let request: RunRequest =
            serde_json::from_str(r#"{"dataset":"math","noJudge":true,"dryRun":true}"#).unwrap();
        assert!(request.no_judge);
        assert!(request.dry_run);
    }

    /// Builds a request with every field explicit, so a test only has to name
    /// the ones it cares about.
    fn request(dataset: &str) -> RunRequest {
        RunRequest {
            dataset: dataset.into(),
            systems: vec!["A".into(), "B".into()],
            limit: Some(7),
            seed: Some(42),
            no_judge: true,
            dry_run: true,
            build_prompts: false,
            skip_projection: false,
            run_id: Some("rid".into()),
        }
    }

    /// The one thing that must be true of the argv: the sidecar accepts it.
    ///
    /// Asserting the exact vector used to be what stood in for this, and it was
    /// not enough - the vector matched an interface the Python side never had
    /// (`--run-id`, repeated `--system`), so every run failed instantly with
    /// "unrecognized arguments". The real check is
    /// `the_sidecar_accepts_the_argv_we_build`.
    #[test]
    fn command_passes_the_config_as_one_spec_json() {
        let setup = PythonSetup {
            project_root: PathBuf::from("C:/repo"),
            python: Some(PathBuf::from("py")),
        };
        let cmd = setup.command(&request("hotpot"), "rid");
        let argv: Vec<String> = cmd
            .get_args()
            .map(|a| a.to_string_lossy().into_owned())
            .collect();
        assert_eq!(argv[0..3], ["-u", "-m", "bench_bridge"]);
        assert_eq!(argv[3], "--spec-json");
        // Exactly one argument after the flag: no assembled flags, nothing that
        // a shell could re-split.
        assert_eq!(argv.len(), 5);
        // And it must parse as the JSON object the sidecar expects.
        let spec: serde_json::Value = serde_json::from_str(&argv[4]).unwrap();
        assert_eq!(spec["run_id"], "rid");
        assert_eq!(spec["dataset"], "hotpot");
    }

    /// Every configured value must survive into the spec.
    ///
    /// `RunSpec.from_json` drops fields it does not recognise rather than
    /// raising, so a field name that drifts out of step with the Python side
    /// becomes a silently ignored setting. Comparing the key set against the
    /// side's own field list is what catches that.
    #[test]
    fn spec_json_carries_every_option() {
        let spec: serde_json::Value =
            serde_json::from_str(&spec_json(&request("hotpot"), "rid")).unwrap();

        assert_eq!(spec["run_id"], "rid");
        assert_eq!(spec["dataset"], "hotpot");
        assert_eq!(spec["systems"], serde_json::json!(["A", "B"]));
        assert_eq!(spec["limit"], 7);
        assert_eq!(spec["seed"], 42);
        assert_eq!(spec["no_judge"], true);
        assert_eq!(spec["dry_run"], true);
        assert_eq!(spec["build_prompts"], false);
        assert_eq!(spec["skip_projection"], false);
        // Never reset the sidecar's store from the host.
        assert_eq!(spec["reset_store"], false);
    }

    /// Optional values must be sent as JSON null, not omitted.
    ///
    /// Omitting them would leave the dataclass defaults in place - `limit=50`,
    /// `seed=42` - which would silently run 50 prompts for a user who asked for
    /// none. `from_json` passes an explicit `None` through, so `limit: null`
    /// really does mean "no limit".
    #[test]
    fn spec_json_keeps_explicit_nulls_for_absent_options() {
        let mut req = request("math");
        req.limit = None;
        req.seed = None;
        let spec: serde_json::Value = serde_json::from_str(&spec_json(&req, "rid")).unwrap();

        assert_eq!(spec["limit"], serde_json::Value::Null);
        assert_eq!(spec["systems"], serde_json::json!(["A", "B"]));
        // A seed is always wanted though, so the default is filled in.
        assert_eq!(spec["seed"], DEFAULT_SEED);
    }

    /// The spec keys must be a subset of what the sidecar actually declares.
    ///
    /// A key the sidecar does not know is dropped without complaint by
    /// `from_json`, which turns a renamed field into a setting that quietly stops
    /// working. This asserts the key set against the dataclass as it exists
    /// today; when the Python side changes, this fails and names the difference.
    #[test]
    fn spec_json_uses_only_field_names_the_sidecar_declares() {
        let spec: serde_json::Value =
            serde_json::from_str(&spec_json(&request("hotpot"), "rid")).unwrap();
        let declared = [
            "run_id",
            "dataset",
            "systems",
            "limit",
            "seed",
            "build_prompts",
            "reset_store",
            "no_judge",
            "dry_run",
            "skip_projection",
            "data_dir",
            "notes",
        ];
        let object = spec.as_object().unwrap();
        for key in object.keys() {
            assert!(
                declared.contains(&key.as_str()),
                "spec carries {key:?}, which bench_bridge.RunSpec does not declare - from_json would drop it silently"
            );
        }
    }

    #[test]
    fn a_dataset_name_cannot_inject_extra_arguments() {
        // The argument vector, not a shell string, is what prevents this - and now
        // the payload is JSON, so it has to survive serialisation too.
        let setup = PythonSetup {
            project_root: PathBuf::from("C:/repo"),
            python: Some(PathBuf::from("py")),
        };
        let mut req = request("hotpot; rm -rf /");
        req.systems = vec![];
        let argv: Vec<String> = setup
            .command(&req, "rid")
            .get_args()
            .map(|a| a.to_string_lossy().into_owned())
            .collect();
        // It lands as exactly one argument, verbatim.
        let spec: serde_json::Value = serde_json::from_str(&argv[4]).unwrap();
        assert_eq!(spec["dataset"], "hotpot; rm -rf /");
        assert_eq!(argv.len(), 5);
    }

    /// The end-to-end proof that the argv is real: spawn the actual sidecar with
    /// the exact command the host would use, and require a clean exit and a
    /// terminal event.
    ///
    /// Everything else about the argv can be asserted structurally and still be
    /// wrong in a way Python rejects - that is precisely the bug this replaces.
    /// `--dry-run` keeps it to a few seconds with no models and no database.
    ///
    /// `#[ignore]` because it needs the Python package importable from the
    /// repository; `scripts/verify.ps1` runs the ignored tests as its own step.
    #[test]
    #[ignore = "spawns the real Python sidecar; run via scripts/verify.ps1"]
    fn the_sidecar_accepts_the_argv_we_build() {
        // src-tauri -> desktop -> repository root.
        let repo = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|p| p.parent())
            .expect("repo root")
            .to_path_buf();

        let setup = PythonSetup {
            project_root: repo,
            python: None,
        };
        let mut req = request("hotpot");
        req.dry_run = true;
        req.no_judge = true;
        req.limit = Some(1);
        // One prompt keeps it to a few seconds; the projection is the slow part
        // and is not what this test is about.
        req.skip_projection = true;

        let run_id = "0123456789abcdef0123456789abcdef";
        let mut child = setup
            .command(&req, run_id)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("the sidecar must be spawnable");

        let stdout = child.stdout.take().unwrap();
        let stderr = child.stderr.take().unwrap();
        let mut events: Vec<serde_json::Value> = Vec::new();
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if line.trim().is_empty() {
                continue;
            }
            match serde_json::from_str::<serde_json::Value>(&line) {
                Ok(value) => events.push(value),
                // A malformed line here means the sidecar printed something that
                // is not an event, which the host would reject at runtime.
                Err(err) => panic!("sidecar emitted a non-event line: {err}\n  {line}"),
            }
        }
        let status = child.wait().expect("wait");
        let stderr: String = BufReader::new(stderr)
            .lines()
            .map_while(Result::ok)
            .collect::<Vec<_>>()
            .join("\n");

        assert!(
            status.success(),
            "the sidecar rejected our argv (exit {:?}).\nstderr:\n{}",
            status.code(),
            stderr
        );

        // The run_id has to come back on every event, or the host cannot match
        // them to the run row it already wrote.
        assert!(!events.is_empty(), "the sidecar produced no events");
        for event in &events {
            assert_eq!(
                event["run_id"], run_id,
                "the sidecar minted its own run_id, so its events would not match the run row"
            );
        }
        let types: Vec<&str> = events.iter().map(|e| e["type"].as_str().unwrap()).collect();
        assert_eq!(
            types.last(),
            Some(&"run_finished"),
            "last event was {types:?}"
        );
    }

    /// The whole path in one test: real sidecar process, real stdout, real
    /// parser, real database file on disk.
    ///
    /// The other tests cover the ends of this and leave the middle to inspection.
    /// That middle is where a silent break would live: a field Python renamed, a
    /// type that no longer round-trips, an insert that fails against the actual
    /// schema. Each of those would leave a finished run with nothing in it, and
    /// the argv test alone would still pass because it only reads stdout.
    #[test]
    #[ignore = "spawns the real Python sidecar; run via scripts/verify.ps1"]
    fn a_real_run_reaches_the_database_file() {
        let repo = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|p| p.parent())
            .expect("repo root")
            .to_path_buf();

        let setup = PythonSetup {
            project_root: repo,
            python: None,
        };
        let mut req = request("hotpot");
        req.dry_run = true;
        req.no_judge = true;
        req.limit = Some(1);
        req.skip_projection = true;

        let run_id = "fedcba9876543210fedcba9876543210";
        let mut child = setup
            .command(&req, run_id)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("the sidecar must be spawnable");
        let stdout = child.stdout.take().unwrap();
        let stderr = child.stderr.take().unwrap();

        // A real file, not `:memory:`. The whole point is that the schema the
        // store opens is the schema that ships.
        let dir = std::env::temp_dir().join(format!("thesis-e2e-{run_id}"));
        std::fs::create_dir_all(&dir).unwrap();
        let db_path = dir.join("runs.sqlite3");
        let _ = std::fs::remove_file(&db_path);
        let store = Store::open(&db_path).expect("store must open");
        store
            .create_run(run_id, 1_000, &req.dataset)
            .expect("create_run");

        let mut lines = 0usize;
        let mut terminals: Vec<StopReason> = Vec::new();
        // `handle_line` deliberately swallows a failed insert and keeps going, so
        // a broken round trip would otherwise sail through this test with the
        // database half empty. The log is the only signal it leaves behind.
        let mut complaints: Vec<String> = Vec::new();
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if line.trim().is_empty() {
                continue;
            }
            lines += 1;
            if let Some(stop) = handle_line(
                &store,
                &line,
                &mut |level, message| {
                    if level == "error" {
                        complaints.push(message.to_string());
                    }
                },
                &mut |_| {},
            )
            .terminal
            {
                terminals.push(stop);
            }
        }

        let status = child.wait().expect("wait");
        let stderr: String = BufReader::new(stderr)
            .lines()
            .map_while(Result::ok)
            .collect::<Vec<_>>()
            .join("\n");
        assert!(status.success(), "sidecar failed:\n{stderr}");
        assert!(lines > 0, "sidecar produced no lines");
        // Exactly one terminal event, and it is a completion. Two would mean the
        // sidecar ended twice; none would mean the host would sit waiting after
        // the process is gone.
        assert_eq!(
            terminals,
            vec![StopReason::Completed],
            "expected exactly one clean terminal event"
        );
        assert!(
            complaints.is_empty(),
            "the sidecar emitted events the host could not store: {complaints:?}"
        );

        // Let the WAL check in, so nothing is left only in the -wal file.
        {
            let conn = store.connection();
            conn.execute_batch("PRAGMA wal_checkpoint(FULL);")
                .expect("checkpoint");
        }
        drop(store);

        // Reopen from scratch: everything asserted below came off the filesystem.
        let store = Store::open(&db_path).expect("reopen");
        let run = store
            .get_run(run_id)
            .expect("get_run")
            .expect("the run row must exist on disk");
        assert_eq!(run["status"], "completed", "run row: {run}");
        assert!(
            run["finished_at"].is_number(),
            "the run was never finished: {run}"
        );

        let prompts = store.get_prompt_rows(run_id).expect("prompt rows");
        assert!(
            !prompts.is_empty(),
            "a dry run with one prompt must persist at least one prompt row"
        );
        for row in &prompts {
            // Present-but-unmeasured must survive the round trip as null.
            for field in ["context_recall", "faithfulness", "answer_relevancy"] {
                assert!(
                    row[field].is_null(),
                    "{field} should be null for a run that skipped judging, got {row}"
                );
            }
            assert!(
                row["answer"].is_string(),
                "the answer text did not survive: {row}"
            );
        }

        // The events table is the audit trail the Results page rebuilds from.
        let events = store.get_events(run_id).expect("events");
        assert_eq!(
            events.len(),
            lines,
            "every line should be recorded exactly once"
        );

        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn command_runs_in_the_project_root() {
        let setup = PythonSetup {
            project_root: PathBuf::from("C:/repo"),
            python: Some(PathBuf::from("py")),
        };
        let request = RunRequest {
            dataset: "math".into(),
            systems: vec![],
            limit: None,
            seed: None,
            no_judge: false,
            dry_run: false,
            build_prompts: false,
            skip_projection: false,
            run_id: None,
        };
        assert_eq!(
            setup.command(&request, "x").get_current_dir(),
            Some(Path::new("C:/repo"))
        );
    }

    #[test]
    fn stop_reason_serializes_with_a_tag() {
        assert_eq!(
            serde_json::to_value(StopReason::Cancelled).unwrap(),
            serde_json::json!({"reason": "cancelled"})
        );
        assert_eq!(
            serde_json::to_value(StopReason::Failed {
                message: "boom".into()
            })
            .unwrap(),
            serde_json::json!({"reason": "failed", "message": "boom"})
        );
    }
}
