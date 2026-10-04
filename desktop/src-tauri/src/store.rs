//! Turning streamed events into database rows.
//!
//! Each event that arrives from the sidecar is persisted here and nowhere else,
//! so this module owns the mapping from event payloads to SQL. The rules that
//! matter:
//!
//! - **Rows are keyed by (run, system, prompt)**, so an event that re-delivers a
//!   prompt updates the existing row instead of inserting a duplicate.
//! - **Nothing is dropped.** The raw event JSON is kept in `run_events` so a
//!   mapping bug can be fixed later by replaying history, and so the Run page can
//!   rebuild a timeline for a run that is no longer in memory.
//! - **Absent is not zero.** A metric the judge never produced stays `NULL`; it
//!   must not become `0.0`, which would drag means down on the Results page.

use std::path::Path;
use std::sync::{Mutex, MutexGuard};

use rusqlite::{params, Connection, OptionalExtension};

use crate::events::{map_f64, map_i64, map_json, map_str, types, RunEvent};

/// Persists events and run metadata.
///
/// The connection sits behind a [`Mutex`] because `rusqlite::Connection` is
/// `Send` but not `Sync`: the pump thread writes events while Tauri commands read
/// on other threads, and the database must still be a single writer. SQLite's
/// own locking makes the mutex cheap - it is uncontended for the whole duration
/// of any one call.
pub struct Store {
    conn: Mutex<Connection>,
}

impl Store {
    /// Open the database at `path`, applying migrations.
    pub fn open(path: &Path) -> rusqlite::Result<Self> {
        Ok(Self::from_connection(crate::db::open(path)?))
    }

    /// Construct from an already-open connection (tests, in-memory runs).
    pub fn from_connection(conn: Connection) -> Self {
        Self {
            conn: Mutex::new(conn),
        }
    }

    /// Lock the connection for a query or write.
    ///
    /// A poisoned lock is recovered from rather than propagated: a panic partway
    /// through one write leaves the database consistent (each statement is
    /// atomic), so refusing every later command would be a worse outcome than
    /// continuing.
    fn lock(&self) -> MutexGuard<'_, Connection> {
        self.conn.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Borrow the connection for read-only queries.
    pub fn connection(&self) -> MutexGuard<'_, Connection> {
        self.lock()
    }

    // ------------------------------------------------------------------- runs

    /// Insert the run row before the sidecar starts, so a crash mid-run leaves a
    /// `running` record rather than nothing at all.
    pub fn create_run(&self, run_id: &str, created_at: i64, dataset: &str) -> rusqlite::Result<()> {
        let conn = self.lock();
        conn.execute(
            "INSERT OR IGNORE INTO runs (run_id, created_at, status, dataset) VALUES (?1, ?2, 'running', ?3)",
            params![run_id, created_at, dataset],
        )?;
        Ok(())
    }

    /// Mark a run failed without a sidecar event.
    ///
    /// For the failure that happens before the sidecar can emit anything - the
    /// interpreter missing, the module failing to import. Those runs have a row
    /// but will never produce `run_failed`, so without this they stay `running`.
    pub fn fail_run(&self, run_id: &str, message: &str) -> rusqlite::Result<()> {
        self.finish_run_without_event(run_id, "failed", Some(message))
    }

    /// Close out runs left `running` by a host that is no longer alive.
    ///
    /// Settlement everywhere else - `fail_run`, `cancel_run`, the event-driven
    /// terminal handlers - runs *inside* the host, so it only ever sees outcomes
    /// it was still around to observe. A host that is killed outright (`taskkill
    /// /F`, a crash, a power cut) never reaches any of them, and the row stays
    /// `running` forever. That is not cosmetic: the Run page refuses to start
    /// while anything looks in progress, so one phantom run wedges the app
    /// permanently, and `run_in_progress` reports a run nobody is running.
    ///
    /// Hence this sweep at startup. By the time it runs, the host that owned any
    /// `running` row is gone - the row is not describing a process this
    /// application can still see - so every one of them is stale by definition.
    ///
    /// That argument depends on there being only one host against a database, the
    /// same assumption the single `ActiveRunSlot` and the single-writer SQLite
    /// connection already make. A second instance starting alongside a live one
    /// would fail this reasoning, so a genuine deployment needs
    /// `tauri-plugin-single-instance` in front of `setup`.
    ///
    /// Returns the ids it closed, so the caller can log them.
    pub fn reconcile_interrupted_runs(&self) -> rusqlite::Result<Vec<String>> {
        let conn = self.lock();
        let stale: Vec<String> = {
            let mut stmt = conn.prepare("SELECT run_id FROM runs WHERE status = 'running'")?;
            let ids = stmt
                .query_map([], |row| row.get::<_, String>(0))?
                .collect::<rusqlite::Result<Vec<_>>>()?;
            ids
        };
        if stale.is_empty() {
            return Ok(stale);
        }
        // `failed` rather than `cancelled`: nothing asked for this to stop, and
        // the error column is where a user looks to find out what happened. The
        // finished time is when the sweep noticed, which is the best available
        // answer - the real end is unknowable once the host is gone.
        let finished_at = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_millis() as i64)
            .unwrap_or(0);
        for run_id in &stale {
            // The `status = 'running'` predicate duplicates the SELECT above, and
            // deliberately so. There is one writer, so it cannot change the
            // outcome here; it is there for the case the sweep does not yet
            // exclude, where a second host is running against the same database
            // and legitimately owns the row. See the note about
            // `tauri-plugin-single-instance` on this function.
            conn.execute(
                "UPDATE runs
                    SET status = 'failed',
                        error = 'the application exited while this run was in flight',
                        finished_at = ?2
                  WHERE run_id = ?1 AND status = 'running'",
                params![run_id, finished_at],
            )?;
        }
        Ok(stale)
    }

    /// Mark a run cancelled.
    ///
    /// Cancelling kills the sidecar, so it never gets to emit `run_finished` and
    /// the row would otherwise stay `running` forever - which also blocks the
    /// next run from being started, because the Run page refuses while anything
    /// looks in progress.
    pub fn cancel_run(&self, run_id: &str) -> rusqlite::Result<()> {
        self.finish_run_without_event(run_id, "cancelled", None)
    }

    /// Move a run out of `running` when there is no terminal event to do it.
    ///
    /// Distinct from the event-driven `finish_run`, which fills in the counts and
    /// duration a `run_finished` payload carries. This one only knows what the
    /// host observed, so the counts keep whatever was true when the run stopped.
    /// Kept in one place so the timestamp and error column cannot drift between
    /// the failure and cancellation paths.
    ///
    /// Guarded on the row still being `running`: the first terminal outcome is
    /// the real one, and a late second attempt must not restamp the finish time
    /// or overwrite a `run_failed` that the sidecar did manage to emit.
    fn finish_run_without_event(
        &self,
        run_id: &str,
        status: &str,
        error: Option<&str>,
    ) -> rusqlite::Result<()> {
        let conn = self.lock();
        let finished_at = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_millis() as i64)
            .unwrap_or(0);
        conn.execute(
            "UPDATE runs SET status = ?2, error = ?3, finished_at = ?4
             WHERE run_id = ?1 AND status = 'running'",
            params![run_id, status, error, finished_at],
        )?;
        Ok(())
    }

    /// Apply one event to the database.
    ///
    /// Returns `true` if the event changed stored state. Unknown event types are
    /// recorded in `run_events` but otherwise ignored, so adding a type on the
    /// Python side cannot break an older app.
    pub fn apply(&self, event: &RunEvent) -> rusqlite::Result<bool> {
        let mut changed = match event.event_type.as_str() {
            types::RUN_STARTED => self.apply_run_started(event)?,
            types::PROJECTION_READY => self.apply_projection(event)?,
            types::PROMPT_COMPLETED => self.apply_prompt_completed(event)?,
            types::TRAIN_STEP => self.apply_train_step(event)?,
            types::REWARD => self.apply_reward(event)?,
            types::STATS => self.apply_stats(event)?,
            types::RUN_FINISHED => {
                self.finish_run(event, "completed")?;
                true
            }
            types::RUN_FAILED => {
                self.finish_run(event, "failed")?;
                true
            }
            // Phases, logs, per-prompt progress and decisions are timeline-only:
            // they are recorded in `run_events` but carry no stored state.
            _ => false,
        };
        changed |= self.record_event(event)?;
        Ok(changed)
    }

    fn record_event(&self, event: &RunEvent) -> rusqlite::Result<bool> {
        let conn = self.lock();
        conn.execute(
            "INSERT OR REPLACE INTO run_events (run_id, seq, ts_ms, type, payload_json)
             VALUES (?1, ?2, ?3, ?4, ?5)",
            params![
                event.run_id,
                event.seq as i64,
                event.ts_ms,
                event.event_type,
                serde_json::to_string(&event.data).unwrap_or_else(|_| "{}".into())
            ],
        )?;
        Ok(true)
    }

    fn apply_run_started(&self, event: &RunEvent) -> rusqlite::Result<bool> {
        let systems: Vec<String> = event
            .array_field("systems")
            .map(|items| {
                items
                    .iter()
                    .filter_map(|v| v.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default();
        let conn = self.lock();
        conn.execute(
            "UPDATE runs SET
                status = 'running',
                started_at = ?2,
                dataset = ?3,
                systems = ?4,
                prompt_count = ?5,
                corpus_count = ?6,
                seed = ?7,
                no_judge = ?8,
                dry_run = ?9,
                embed_model = ?10,
                generator_model = ?11,
                judge_model = ?12,
                python_version = ?13,
                git_sha = ?14,
                config_json = ?15
             WHERE run_id = ?1",
            params![
                event.run_id,
                event.ts_ms,
                event.str_field("dataset").unwrap_or_default(),
                serde_json::to_string(&systems).unwrap_or_else(|_| "[]".into()),
                event.i64_field("prompt_count").unwrap_or(0),
                event.i64_field("corpus_count"),
                event.i64_field("seed"),
                event.bool_field("no_judge").unwrap_or(false) as i64,
                event.bool_field("dry_run").unwrap_or(false) as i64,
                event.str_field("embed_model"),
                event.str_field("generator_model"),
                event.str_field("judge_model"),
                event.str_field("python_version"),
                event.str_field("git_sha"),
                event.str_field("config_json").unwrap_or("{}"),
            ],
        )?;
        Ok(true)
    }

    fn apply_projection(&self, event: &RunEvent) -> rusqlite::Result<bool> {
        let dataset = match event.str_field("dataset") {
            Some(d) => d.to_string(),
            None => return Ok(false),
        };
        let conn = self.lock();
        conn.execute(
            "INSERT INTO projections
                (dataset, collection, dim, n_points, points_path, meta_path,
                 explained_variance, source_count, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
             ON CONFLICT(dataset) DO UPDATE SET
                collection = excluded.collection,
                dim = excluded.dim,
                n_points = excluded.n_points,
                points_path = excluded.points_path,
                meta_path = excluded.meta_path,
                explained_variance = excluded.explained_variance,
                source_count = excluded.source_count,
                created_at = excluded.created_at",
            params![
                dataset,
                event.str_field("collection").unwrap_or_default(),
                event.i64_field("dim").unwrap_or(0),
                event.i64_field("n_points").unwrap_or(0),
                event.str_field("points_path").unwrap_or_default(),
                event.str_field("meta_path").unwrap_or_default(),
                event.f64_field("explained_variance"),
                event.i64_field("source_count"),
                event.ts_ms,
            ],
        )?;
        conn.execute(
            "UPDATE runs SET projection_ready = 1 WHERE run_id = ?1",
            [&event.run_id],
        )?;
        Ok(true)
    }

    /// Persist a finished prompt row.
    ///
    /// The sidecar sends the whole row on `prompt_completed`, because metrics, token
    /// counts and per-stage timings cannot be reconstructed from the thin progress
    /// events. The insert is an upsert on `(run, system, prompt)` so a re-delivered
    /// row - a replay, or a run resumed after a crash - updates rather than
    /// duplicating.
    fn apply_prompt_completed(&self, event: &RunEvent) -> rusqlite::Result<bool> {
        let Some(row) = event.object_field("row") else {
            // An older sidecar that predates the `row` payload. Nothing to persist,
            // but the event is still recorded in `run_events`.
            return Ok(false);
        };
        let Some(system) = map_str(row, "system").or_else(|| event.str_field("system")) else {
            return Ok(false);
        };
        let prompt_id = map_str(row, "prompt_id")
            .map(str::to_string)
            .or_else(|| event.str_field("prompt_id").map(str::to_string))
            .unwrap_or_default();

        let conn = self.lock();
        conn.execute(
            "INSERT INTO prompt_rows (
            run_id, system_id, prompt_id, prompt_index, phase, question, ground_truth,
            answer, retrieved_k, retrieved_ids, retrieved_distances,
            faithfulness, answer_relevancy, context_recall,
            prompt_tokens, completion_tokens, total_tokens,
            judge_prompt_tokens, judge_completion_tokens,
            embedding_time_s, retrieval_time_s, generation_time_s,
            judge_time_s, total_time_s, reward
         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11,
                   ?12, ?13, ?14, ?15, ?16, ?17, ?18, ?19, ?20, ?21, ?22, ?23, ?24, ?25)
         ON CONFLICT(run_id, system_id, prompt_id) DO UPDATE SET
            prompt_index = excluded.prompt_index,
            phase = excluded.phase,
            question = excluded.question,
            ground_truth = excluded.ground_truth,
            answer = excluded.answer,
            retrieved_k = excluded.retrieved_k,
            retrieved_ids = excluded.retrieved_ids,
            retrieved_distances = excluded.retrieved_distances,
            faithfulness = excluded.faithfulness,
            answer_relevancy = excluded.answer_relevancy,
            context_recall = excluded.context_recall,
            prompt_tokens = excluded.prompt_tokens,
            completion_tokens = excluded.completion_tokens,
            total_tokens = excluded.total_tokens,
            judge_prompt_tokens = excluded.judge_prompt_tokens,
            judge_completion_tokens = excluded.judge_completion_tokens,
            embedding_time_s = excluded.embedding_time_s,
            retrieval_time_s = excluded.retrieval_time_s,
            generation_time_s = excluded.generation_time_s,
            judge_time_s = excluded.judge_time_s,
            total_time_s = excluded.total_time_s,
            reward = excluded.reward",
            params![
                event.run_id,
                system,
                prompt_id,
                // `index` lives on the event envelope, not in the row: it is the
                // position in the prompt list, identical for A and B, which is what
                // lets the Results page pair the two systems per question.
                event
                    .i64_field("index")
                    .or_else(|| map_i64(row, "prompt_index")),
                map_str(row, "phase").map(str::to_string),
                map_str(row, "question").map(str::to_string),
                map_str(row, "ground_truth").map(str::to_string),
                map_str(row, "answer").map(str::to_string),
                map_i64(row, "retrieved_k"),
                map_json(row, "retrieved_ids"),
                map_json(row, "retrieved_distances"),
                map_f64(row, "faithfulness"),
                map_f64(row, "answer_relevancy"),
                map_f64(row, "context_recall"),
                map_i64(row, "prompt_tokens"),
                map_i64(row, "completion_tokens"),
                map_i64(row, "total_tokens"),
                map_i64(row, "judge_prompt_tokens"),
                map_i64(row, "judge_completion_tokens"),
                map_f64(row, "embedding_time_s"),
                map_f64(row, "retrieval_time_s"),
                map_f64(row, "generation_time_s"),
                map_f64(row, "judge_time_s"),
                map_f64(row, "total_time_s"),
                map_f64(row, "reward"),
            ],
        )?;
        Ok(true)
    }

    /// Persist one DQN training step.
    ///
    /// `q_values` arrives as a five-element array and is spread across the five
    /// `q_values_k*` columns, so the Results page can plot the value estimates and
    /// see which action the greedy policy actually favours.
    fn apply_train_step(&self, event: &RunEvent) -> rusqlite::Result<bool> {
        let step = match event.i64_field("step") {
            Some(step) => step,
            None => return Ok(false),
        };
        let q: Vec<Option<f64>> = event
            .array_field("q_values")
            .map(|items| items.iter().map(|v| v.as_f64()).collect())
            .unwrap_or_default();
        let q_at = |i: usize| -> Option<f64> { q.get(i).copied().flatten() };

        let conn = self.lock();
        conn.execute(
            "INSERT INTO training_steps (
            run_id, step, prompt_id, k,
            faithfulness, answer_relevancy, context_recall,
            reward, loss, epsilon,
            q_values_k1, q_values_k2, q_values_k3, q_values_k4, q_values_k5,
            prompt_tokens, completion_tokens, total_tokens,
            judge_prompt_tokens, judge_completion_tokens,
            embedding_time_s, retrieval_time_s, generation_time_s,
            judge_time_s, total_time_s
         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15,
                   ?16, ?17, ?18, ?19, ?20, ?21, ?22, ?23, ?24, ?25)
         ON CONFLICT(run_id, step) DO UPDATE SET
            prompt_id = excluded.prompt_id,
            k = excluded.k,
            faithfulness = excluded.faithfulness,
            answer_relevancy = excluded.answer_relevancy,
            context_recall = excluded.context_recall,
            reward = excluded.reward,
            loss = excluded.loss,
            epsilon = excluded.epsilon,
            q_values_k1 = excluded.q_values_k1,
            q_values_k2 = excluded.q_values_k2,
            q_values_k3 = excluded.q_values_k3,
            q_values_k4 = excluded.q_values_k4,
            q_values_k5 = excluded.q_values_k5,
            total_time_s = excluded.total_time_s",
            params![
                event.run_id,
                step,
                event.str_field("prompt_id").map(str::to_string),
                event.i64_field("k"),
                event.f64_field("faithfulness"),
                event.f64_field("answer_relevancy"),
                event.f64_field("context_recall"),
                event.f64_field("reward"),
                event.f64_field("loss"),
                event.f64_field("epsilon"),
                q_at(0),
                q_at(1),
                q_at(2),
                q_at(3),
                q_at(4),
                event.i64_field("prompt_tokens"),
                event.i64_field("completion_tokens"),
                event.i64_field("total_tokens"),
                event.i64_field("judge_prompt_tokens"),
                event.i64_field("judge_completion_tokens"),
                event.f64_field("embedding_time_s"),
                event.f64_field("retrieval_time_s"),
                event.f64_field("generation_time_s"),
                event.f64_field("judge_time_s"),
                event.f64_field("total_time_s"),
            ],
        )?;
        Ok(true)
    }

    fn apply_reward(&self, event: &RunEvent) -> rusqlite::Result<bool> {
        // Rewards are per-episode summaries; keep only the latest for the run so
        // the Results page can show the final mean without replaying events.
        let Some(reward) = event.f64_field("reward") else {
            return Ok(false);
        };
        let conn = self.lock();
        let n = conn.execute(
            "UPDATE prompt_rows SET reward = ?2
             WHERE run_id = ?1 AND system_id = ?3 AND prompt_id = ?4",
            params![
                event.run_id,
                reward,
                event.str_field("system").unwrap_or_default(),
                event.str_field("prompt_id").unwrap_or_default(),
            ],
        )?;
        Ok(n > 0)
    }

    fn apply_stats(&self, event: &RunEvent) -> rusqlite::Result<bool> {
        let payload = event
            .data
            .as_object()
            .filter(|o| !o.is_empty())
            .ok_or(rusqlite::Error::InvalidQuery)?;
        let conn = self.lock();
        conn.execute(
            "INSERT INTO run_stats (run_id, payload_json, created_at) VALUES (?1, ?2, ?3)
             ON CONFLICT(run_id) DO UPDATE SET
                payload_json = excluded.payload_json,
                created_at = excluded.created_at",
            params![
                event.run_id,
                serde_json::to_string(payload).unwrap_or_else(|_| "{}".into()),
                event.ts_ms
            ],
        )?;
        Ok(true)
    }

    fn finish_run(&self, event: &RunEvent, status: &str) -> rusqlite::Result<()> {
        let conn = self.lock();
        conn.execute(
            "UPDATE runs SET
                status = ?2,
                finished_at = ?3,
                duration_s = ?4,
                completed_prompts = ?5,
                prompt_rows = ?6,
                training_rows = ?7,
                error = ?8
             WHERE run_id = ?1",
            params![
                event.run_id,
                status,
                event.ts_ms,
                event.f64_field("duration_s"),
                event.i64_field("prompt_count").unwrap_or(0),
                event.i64_field("prompt_rows"),
                event.i64_field("training_rows"),
                event.str_field("error"),
            ],
        )?;
        Ok(())
    }

    // ------------------------------------------------------------------ reads

    /// All runs, newest first, as JSON for the frontend.
    pub fn list_runs(&self) -> rusqlite::Result<Vec<serde_json::Value>> {
        let conn = self.lock();
        let mut stmt = conn.prepare(
            "SELECT run_id, created_at, started_at, finished_at, status, dataset,
                    systems, prompt_count, corpus_count, seed, no_judge, dry_run,
                    duration_s, error
             FROM runs ORDER BY created_at DESC",
        )?;
        let rows = stmt.query_map([], |row| {
            Ok(serde_json::json!({
                "run_id": row.get::<_, String>(0)?,
                "created_at": row.get::<_, i64>(1)?,
                "started_at": row.get::<_, Option<i64>>(2)?,
                "finished_at": row.get::<_, Option<i64>>(3)?,
                "status": row.get::<_, String>(4)?,
                "dataset": row.get::<_, String>(5)?,
                "systems": serde_json::from_str::<serde_json::Value>(&row.get::<_, String>(6)?)
                    .unwrap_or(serde_json::Value::Null),
                "prompt_count": row.get::<_, i64>(7)?,
                "corpus_count": row.get::<_, Option<i64>>(8)?,
                "seed": row.get::<_, Option<i64>>(9)?,
                "no_judge": row.get::<_, i64>(10)? != 0,
                "dry_run": row.get::<_, i64>(11)? != 0,
                "duration_s": row.get::<_, Option<f64>>(12)?,
                "error": row.get::<_, Option<String>>(13)?,
            }))
        })?;
        rows.collect()
    }

    /// One run's metadata, or `None` if unknown.
    pub fn get_run(&self, run_id: &str) -> rusqlite::Result<Option<serde_json::Value>> {
        let conn = self.lock();
        conn
            .query_row(
                "SELECT run_id, created_at, started_at, finished_at, status, dataset,
                        systems, prompt_count, corpus_count, seed, no_judge, dry_run,
                        duration_s, error, projection_ready, config_json,
                        embed_model, generator_model, judge_model, python_version, git_sha,
                        prompt_rows, training_rows, result_csv_path, training_csv_path, notes
                 FROM runs WHERE run_id = ?1",
                [run_id],
                |row| {
                    Ok(serde_json::json!({
                        "run_id": row.get::<_, String>(0)?,
                        "created_at": row.get::<_, i64>(1)?,
                        "started_at": row.get::<_, Option<i64>>(2)?,
                        "finished_at": row.get::<_, Option<i64>>(3)?,
                        "status": row.get::<_, String>(4)?,
                        "dataset": row.get::<_, String>(5)?,
                        "systems": serde_json::from_str::<serde_json::Value>(&row.get::<_, String>(6)?)
                            .unwrap_or(serde_json::Value::Null),
                        "prompt_count": row.get::<_, i64>(7)?,
                        "corpus_count": row.get::<_, Option<i64>>(8)?,
                        "seed": row.get::<_, Option<i64>>(9)?,
                        "no_judge": row.get::<_, i64>(10)? != 0,
                        "dry_run": row.get::<_, i64>(11)? != 0,
                        "duration_s": row.get::<_, Option<f64>>(12)?,
                        "error": row.get::<_, Option<String>>(13)?,
                        "projection_ready": row.get::<_, i64>(14)? != 0,
                        "config_json": serde_json::from_str::<serde_json::Value>(&row.get::<_, String>(15)?)
                            .unwrap_or(serde_json::Value::Null),
                        "embed_model": row.get::<_, Option<String>>(16)?,
                        "generator_model": row.get::<_, Option<String>>(17)?,
                        "judge_model": row.get::<_, Option<String>>(18)?,
                        "python_version": row.get::<_, Option<String>>(19)?,
                        "git_sha": row.get::<_, Option<String>>(20)?,
                        "prompt_rows": row.get::<_, Option<i64>>(21)?,
                        "training_rows": row.get::<_, Option<i64>>(22)?,
                        "result_csv_path": row.get::<_, Option<String>>(23)?,
                        "training_csv_path": row.get::<_, Option<String>>(24)?,
                        "notes": row.get::<_, Option<String>>(25)?,
                    }))
                },
            )
            .optional()
    }

    /// Stored statistics payload for a run.
    pub fn get_stats(&self, run_id: &str) -> rusqlite::Result<Option<serde_json::Value>> {
        let conn = self.lock();
        conn.query_row(
            "SELECT payload_json FROM run_stats WHERE run_id = ?1",
            [run_id],
            |row| row.get::<_, String>(0),
        )
        .optional()?
        .map(|raw| {
            serde_json::from_str(&raw).map_err(|e| {
                rusqlite::Error::FromSqlConversionFailure(
                    0,
                    rusqlite::types::Type::Text,
                    Box::new(e),
                )
            })
        })
        .transpose()
    }

    /// One row per prompt per inference system.
    pub fn get_prompt_rows(&self, run_id: &str) -> rusqlite::Result<Vec<serde_json::Value>> {
        let conn = self.lock();
        let mut stmt = conn.prepare(
            "SELECT system_id, prompt_id, prompt_index, phase, question, ground_truth,
                    answer, retrieved_k, retrieved_ids, retrieved_distances,
                    faithfulness, answer_relevancy, context_recall,
                    prompt_tokens, completion_tokens, total_tokens,
                    judge_prompt_tokens, judge_completion_tokens,
                    embedding_time_s, retrieval_time_s, generation_time_s,
                    judge_time_s, total_time_s, reward
             FROM prompt_rows WHERE run_id = ?1 ORDER BY prompt_index, system_id",
        )?;
        let rows = stmt.query_map(&[&run_id], |row| {
            Ok(serde_json::json!({
                "system": row.get::<_, String>(0)?,
                "prompt_id": row.get::<_, String>(1)?,
                "prompt_index": row.get::<_, Option<i64>>(2)?,
                "phase": row.get::<_, Option<String>>(3)?,
                "question": row.get::<_, Option<String>>(4)?,
                "ground_truth": row.get::<_, Option<String>>(5)?,
                "answer": row.get::<_, Option<String>>(6)?,
                "retrieved_k": row.get::<_, Option<i64>>(7)?,
                "retrieved_ids": serde_json::from_str::<serde_json::Value>(
                    &row.get::<_, Option<String>>(8)?.unwrap_or_else(|| "[]".into()))
                    .unwrap_or(serde_json::Value::Null),
                "retrieved_distances": serde_json::from_str::<serde_json::Value>(
                    &row.get::<_, Option<String>>(9)?.unwrap_or_else(|| "[]".into()))
                    .unwrap_or(serde_json::Value::Null),
                "faithfulness": row.get::<_, Option<f64>>(10)?,
                "answer_relevancy": row.get::<_, Option<f64>>(11)?,
                "context_recall": row.get::<_, Option<f64>>(12)?,
                "prompt_tokens": row.get::<_, Option<i64>>(13)?,
                "completion_tokens": row.get::<_, Option<i64>>(14)?,
                "total_tokens": row.get::<_, Option<i64>>(15)?,
                "judge_prompt_tokens": row.get::<_, Option<i64>>(16)?,
                "judge_completion_tokens": row.get::<_, Option<i64>>(17)?,
                "embedding_time_s": row.get::<_, Option<f64>>(18)?,
                "retrieval_time_s": row.get::<_, Option<f64>>(19)?,
                "generation_time_s": row.get::<_, Option<f64>>(20)?,
                "judge_time_s": row.get::<_, Option<f64>>(21)?,
                "total_time_s": row.get::<_, Option<f64>>(22)?,
                "reward": row.get::<_, Option<f64>>(23)?,
            }))
        })?;
        rows.collect()
    }

    /// One row per DQN training step.
    pub fn get_training_rows(&self, run_id: &str) -> rusqlite::Result<Vec<serde_json::Value>> {
        let conn = self.lock();
        let mut stmt = conn.prepare(
            "SELECT step, prompt_id, k, faithfulness, answer_relevancy, context_recall,
                    reward, loss, epsilon, q_values_k1, q_values_k2, q_values_k3,
                    q_values_k4, q_values_k5, total_time_s
             FROM training_steps WHERE run_id = ?1 ORDER BY step",
        )?;
        let rows = stmt.query_map(&[&run_id], |row| {
            let q: Vec<Option<f64>> = (9..14)
                .map(|i| row.get::<_, Option<f64>>(i))
                .collect::<rusqlite::Result<_>>()?;
            Ok(serde_json::json!({
                "step": row.get::<_, i64>(0)?,
                "prompt_id": row.get::<_, Option<String>>(1)?,
                "k": row.get::<_, Option<i64>>(2)?,
                "faithfulness": row.get::<_, Option<f64>>(3)?,
                "answer_relevancy": row.get::<_, Option<f64>>(4)?,
                "context_recall": row.get::<_, Option<f64>>(5)?,
                "reward": row.get::<_, Option<f64>>(6)?,
                "loss": row.get::<_, Option<f64>>(7)?,
                "epsilon": row.get::<_, Option<f64>>(8)?,
                "q_values": q,
                "total_time_s": row.get::<_, Option<f64>>(14)?,
            }))
        })?;
        rows.collect()
    }

    /// Recorded events for a run, oldest first - used to rebuild a timeline.
    pub fn get_events(&self, run_id: &str) -> rusqlite::Result<Vec<serde_json::Value>> {
        let conn = self.lock();
        let mut stmt = conn.prepare(
            "SELECT seq, ts_ms, type, payload_json FROM run_events
             WHERE run_id = ?1 ORDER BY seq",
        )?;
        let rows = stmt.query_map(&[&run_id], |row| {
            Ok(serde_json::json!({
                "seq": row.get::<_, i64>(0)?,
                "ts_ms": row.get::<_, i64>(1)?,
                "type": row.get::<_, String>(2)?,
                "data": serde_json::from_str::<serde_json::Value>(&row.get::<_, String>(3)?)
                    .unwrap_or(serde_json::Value::Null),
            }))
        })?;
        rows.collect()
    }

    /// Delete a run and everything that cascades from it.
    pub fn delete_run(&self, run_id: &str) -> rusqlite::Result<()> {
        let conn = self.lock();
        conn.execute("DELETE FROM runs WHERE run_id = ?1", [&run_id])?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn store() -> Store {
        let conn = Connection::open_in_memory().unwrap();
        crate::db::migrate(&conn).unwrap();
        Store::from_connection(conn)
    }

    fn run_status(store: &Store, run_id: &str) -> String {
        store.get_run(run_id).unwrap().unwrap()["status"]
            .as_str()
            .unwrap()
            .to_string()
    }

    /// Events for one run, in order.
    ///
    /// `seq` is unique per run, so the counter is per-instance in the same way
    /// the sidecar's is per-process. `event()` hands out 1, 2, 3... from a
    /// per-test counter, because `run_events` is keyed on `(run_id, seq)` with
    /// `INSERT OR REPLACE`: two events sharing a seq silently collapse into one,
    /// which would make an event-count assertion pass for the wrong reason.
    fn event(event_type: &str, data: serde_json::Value) -> RunEvent {
        let seq = NEXT_SEQ.with(|cell| {
            let next = cell.get();
            cell.set(next + 1);
            next
        });
        event_seq(seq, event_type, data)
    }

    thread_local! {
        static NEXT_SEQ: std::cell::Cell<u64> = const { std::cell::Cell::new(1) };
    }

    fn event_seq(seq: u64, event_type: &str, data: serde_json::Value) -> RunEvent {
        RunEvent::parse(
            &json!({
                "v": 1, "seq": seq, "ts_ms": 1000, "run_id": "run1",
                "type": event_type, "data": data,
            })
            .to_string(),
        )
        .unwrap()
    }

    #[test]
    fn records_every_event_in_order() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .apply(&event("run_started", json!({"dataset": "hotpot"})))
            .unwrap();
        store
            .apply(&event_seq(2, "prompt_completed", json!({"system": "A"})))
            .unwrap();
        let events = store.get_events("run1").unwrap();
        assert_eq!(events.len(), 2);
        assert_eq!(events[0]["type"], "run_started");
        assert_eq!(events[1]["type"], "prompt_completed");
    }

    #[test]
    fn re_delivered_seq_replaces_rather_than_duplicates() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        // Same seq twice: the sidecar re-sent a line, or the host replayed it.
        for _ in 0..2 {
            store
                .apply(&event_seq(1, "run_started", json!({"dataset": "hotpot"})))
                .unwrap();
        }
        assert_eq!(store.get_events("run1").unwrap().len(), 1);
    }

    #[test]
    fn unknown_event_types_are_still_recorded() {
        // An older app must survive a newer sidecar emitting a new type.
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store.apply(&event("a_brand_new_event", json!({}))).unwrap();
        assert_eq!(store.get_events("run1").unwrap().len(), 1);
    }

    #[test]
    fn run_started_populates_metadata() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .apply(&event(
                "run_started",
                json!({
                    "dataset": "hotpot",
                    "systems": ["A", "B"],
                    "prompt_count": 3,
                    "corpus_count": 400,
                    "seed": 42,
                    "no_judge": true,
                    "dry_run": true,
                }),
            ))
            .unwrap();
        let run = store.get_run("run1").unwrap().unwrap();
        assert_eq!(run["status"], "running");
        assert_eq!(run["prompt_count"], 3);
        assert_eq!(run["corpus_count"], 400);
        assert_eq!(run["seed"], 42);
        assert_eq!(run["no_judge"], true);
        assert_eq!(run["systems"][1], "B");
    }

    #[test]
    fn missing_counts_stay_null_not_zero() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .apply(&event("run_started", json!({"dataset": "hotpot"})))
            .unwrap();
        let run = store.get_run("run1").unwrap().unwrap();
        assert_eq!(run["corpus_count"], serde_json::Value::Null);
        assert_eq!(run["duration_s"], serde_json::Value::Null);
    }

    #[test]
    fn projection_ready_is_recorded_and_marked_on_the_run() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .apply(&event(
                "projection_ready",
                json!({
                    "dataset": "hotpot", "collection": "hotpot",
                    "dim": 768, "n_points": 400,
                    "points_path": "p.bin", "meta_path": "p.json",
                    "explained_variance": 0.42,
                }),
            ))
            .unwrap();
        assert_eq!(
            store.get_run("run1").unwrap().unwrap()["projection_ready"],
            true
        );
        let path: String = store
            .connection()
            .query_row(
                "SELECT points_path FROM projections WHERE dataset='hotpot'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(path, "p.bin");
    }

    #[test]
    fn a_second_projection_for_the_same_dataset_replaces_the_first() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        for points in ["p1.bin", "p2.bin"] {
            store
                .apply(&event(
                    "projection_ready",
                    json!({
                        "dataset": "hotpot", "collection": "hotpot",
                        "dim": 768, "n_points": 1,
                        "points_path": points, "meta_path": "m.json",
                    }),
                ))
                .unwrap();
        }
        let n: i64 = store
            .connection()
            .query_row("SELECT count(*) FROM projections", [], |r| r.get(0))
            .unwrap();
        assert_eq!(n, 1, "projections are keyed by dataset");
    }

    #[test]
    fn run_finished_marks_the_run_completed() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .apply(&event(
                "run_finished",
                json!({"duration_s": 5.5, "prompt_count": 3, "prompt_rows": 6, "training_rows": 3}),
            ))
            .unwrap();
        let run = store.get_run("run1").unwrap().unwrap();
        assert_eq!(run["status"], "completed");
        assert_eq!(run["duration_s"], 5.5);
        assert_eq!(run["prompt_rows"], 6);
    }

    #[test]
    fn fail_run_closes_a_run_that_never_got_its_sidecar() {
        // The interpreter can be missing or the module can fail to import, in
        // which case no `run_failed` event will ever arrive and the row would stay
        // `running` for good.
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        assert_eq!(store.get_run("run1").unwrap().unwrap()["status"], "running");

        store
            .fail_run("run1", "cannot start python: not found")
            .unwrap();

        let run = store.get_run("run1").unwrap().unwrap();
        assert_eq!(run["status"], "failed");
        assert_eq!(run["error"], "cannot start python: not found");
        assert!(
            run["finished_at"].as_i64().is_some(),
            "a failed run must be closed with a finish time"
        );
    }

    #[test]
    fn fail_run_on_an_unknown_run_is_a_no_op() {
        // Cancelling a run whose row was deleted must not error; the UI treats this
        // call as cleanup, not as something the user needs to be told about.
        let store = store();
        store.fail_run("nope", "gone").unwrap();
        assert!(store.get_run("nope").unwrap().is_none());
    }

    #[test]
    fn reconciliation_closes_runs_orphaned_by_a_dead_host() {
        // A host killed outright runs none of its own settlement paths, so the row
        // is still `running` next time anyone opens the database.
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store.create_run("run2", 2, "hotpot").unwrap();

        let closed = store.reconcile_interrupted_runs().unwrap();
        assert_eq!(closed, vec!["run1".to_string(), "run2".to_string()]);

        for id in ["run1", "run2"] {
            let run = store.get_run(id).unwrap().unwrap();
            assert_eq!(run["status"], "failed");
            assert!(
                run["error"].as_str().unwrap().contains("exited"),
                "the reason has to be visible: {:?}",
                run["error"]
            );
            assert!(run["finished_at"].as_i64().is_some());
        }
    }

    #[test]
    fn reconciliation_leaves_finished_runs_alone() {
        // The sweep must not restamp a run that already reached a real outcome -
        // a completed 20k-prompt run took hours, and rewriting it would destroy
        // the only honest record of when it ended.
        let store = store();
        store.create_run("done", 1, "hotpot").unwrap();
        store.cancel_run("done").unwrap();
        let before = store.get_run("done").unwrap().unwrap();
        let finished_at = before["finished_at"].as_i64().unwrap();

        store.create_run("running", 2, "hotpot").unwrap();
        store.reconcile_interrupted_runs().unwrap();

        let after = store.get_run("done").unwrap().unwrap();
        assert_eq!(after["status"], "cancelled");
        assert_eq!(after["finished_at"].as_i64().unwrap(), finished_at);
        assert!(after["error"].as_str().unwrap_or("").is_empty());
    }

    #[test]
    fn reconciliation_is_idempotent_and_a_no_op_when_nothing_is_running() {
        // Runs at every startup, so a second sweep must find nothing to do rather
        // than re-stamping rows it already closed.
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store.reconcile_interrupted_runs().unwrap();
        let after_first = store.get_run("run1").unwrap().unwrap();

        assert!(store.reconcile_interrupted_runs().unwrap().is_empty());
        let after_second = store.get_run("run1").unwrap().unwrap();
        assert_eq!(after_first, after_second);
    }

    #[test]
    fn reconciliation_does_not_disturb_a_run_started_by_this_host() {
        // The sweep runs once, before anything can be started, so the only way a
        // `running` row exists at that point is a leftover. Locking the behaviour
        // down: a run created after the sweep must not be retroactively closed.
        let store = store();
        store.reconcile_interrupted_runs().unwrap();
        store.create_run("fresh", 1, "hotpot").unwrap();

        assert!(store
            .reconcile_interrupted_runs()
            .unwrap()
            .contains(&"fresh".to_string()));
    }

    #[test]
    fn run_failed_records_the_error_message() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .apply(&event(
                "run_failed",
                json!({"error": "unknown dataset 'nope'", "traceback": "Traceback (most recent call last): KeyError: 'nope'"}),
            ))
            .unwrap();
        let run = store.get_run("run1").unwrap().unwrap();
        assert_eq!(run["status"], "failed");
        assert_eq!(run["error"], "unknown dataset 'nope'");
    }

    /// Cancelling kills the sidecar, so no `run_finished` ever arrives and the
    /// row has to be closed out by the host. Left `running`, it also blocks the
    /// next run, because the Run page refuses while anything looks in progress.
    #[test]
    fn a_cancelled_run_does_not_stay_running() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        assert_eq!(run_status(&store, "run1"), "running");

        store.cancel_run("run1").unwrap();

        let run = store.get_run("run1").unwrap().unwrap();
        assert_eq!(run["status"], "cancelled");
        assert!(
            run["finished_at"].is_number(),
            "a closed-out run needs a finish time: {run}"
        );
        // Cancelling is not an error, so nothing should be reported as one.
        assert_eq!(run["error"], json!(null));
    }

    /// A sidecar that dies without emitting `run_failed` leaves the same hole,
    /// and unlike a cancellation this one genuinely needs the message.
    #[test]
    fn a_run_that_died_without_an_event_is_recorded_as_failed() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();

        store
            .fail_run("run1", "sidecar exited with code 1: boom")
            .unwrap();

        let run = store.get_run("run1").unwrap().unwrap();
        assert_eq!(run["status"], "failed");
        assert_eq!(run["error"], "sidecar exited with code 1: boom");
        assert!(run["finished_at"].is_number());
    }

    /// Re-running the close-out must not move the finish time, so a second
    /// attempt cannot make a cancelled run look like it ran longer.
    #[test]
    fn closing_a_run_out_twice_keeps_the_first_finish_time() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store.cancel_run("run1").unwrap();
        let first = store.get_run("run1").unwrap().unwrap()["finished_at"]
            .as_i64()
            .unwrap();

        std::thread::sleep(std::time::Duration::from_millis(5));
        store.cancel_run("run1").unwrap();

        let second = store.get_run("run1").unwrap().unwrap()["finished_at"]
            .as_i64()
            .unwrap();
        assert_eq!(first, second);
    }

    #[test]
    fn stats_are_stored_once_per_run() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        for mean in [0.5, 0.7] {
            store
                .apply(&event(
                    "stats",
                    json!({"per_system": {"A": {"mean": mean}}}),
                ))
                .unwrap();
        }
        let payload = store.get_stats("run1").unwrap().unwrap();
        assert_eq!(payload["per_system"]["A"]["mean"], 0.7);
        let n: i64 = store
            .connection()
            .query_row("SELECT count(*) FROM run_stats", [], |r| r.get(0))
            .unwrap();
        assert_eq!(n, 1);
    }

    #[test]
    fn deleting_a_run_cascades() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .apply(&event("run_started", json!({"dataset": "hotpot"})))
            .unwrap();
        store.delete_run("run1").unwrap();
        assert_eq!(store.get_events("run1").unwrap().len(), 0);
        assert!(store.get_run("run1").unwrap().is_none());
    }

    #[test]
    fn list_runs_is_newest_first() {
        let store = store();
        store.create_run("old", 100, "hotpot").unwrap();
        store.create_run("new", 200, "math").unwrap();
        let runs = store.list_runs().unwrap();
        assert_eq!(runs[0]["run_id"], "new");
        assert_eq!(runs[1]["run_id"], "old");
    }

    #[test]
    fn unknown_run_reads_are_none_not_an_error() {
        let store = store();
        assert!(store.get_run("nope").unwrap().is_none());
        assert!(store.get_stats("nope").unwrap().is_none());
        assert!(store.get_prompt_rows("nope").unwrap().is_empty());
    }

    #[test]
    fn every_event_type_applies_without_deadlocking() {
        // A handler that locks twice self-deadlocks the non-reentrant mutex, and
        // a deadlock shows up as a hung test run rather than a failure. Every
        // event type is therefore applied from a worker thread with a timeout.
        for (event_type, data) in [
            (
                "run_started",
                json!({"dataset": "hotpot", "systems": ["A"]}),
            ),
            (
                "projection_ready",
                json!({"dataset": "hotpot", "points_path": "p.bin", "meta_path": "p.json"}),
            ),
            (
                "reward",
                json!({"reward": 0.5, "system": "A", "prompt_id": "p1"}),
            ),
            ("stats", json!({"per_system": {}})),
            ("run_finished", json!({"duration_s": 1.0})),
            ("run_failed", json!({"error": "boom"})),
        ] {
            let store = std::sync::Arc::new(store());
            store.create_run("run1", 1, "hotpot").unwrap();
            let handle = {
                let store = store.clone();
                let event = event(event_type, data);
                std::thread::spawn(move || store.apply(&event).unwrap())
            };
            assert!(
                handle
                    .join_timeout(std::time::Duration::from_secs(5))
                    .is_some(),
                "applying a {event_type} event deadlocked"
            );
        }
    }

    /// `JoinHandle::join_timeout` does not exist, so provide the bounded wait.
    trait JoinTimeout<T> {
        fn join_timeout(self, limit: std::time::Duration) -> Option<T>;
    }

    impl<T: Send + 'static> JoinTimeout<T> for std::thread::JoinHandle<T> {
        fn join_timeout(self, limit: std::time::Duration) -> Option<T> {
            // A finished thread parks its result in a channel; an unfinished one
            // fails the timeout instead of blocking the test suite forever.
            let (tx, rx) = std::sync::mpsc::channel();
            std::thread::spawn(move || {
                let _ = tx.send(self.join());
            });
            rx.recv_timeout(limit)
                .ok()
                .map(|result| result.expect("worker panicked"))
        }
    }

    /// A `prompt_completed` row as the sidecar sends it for system A.
    fn prompt_completed_row() -> serde_json::Value {
        json!({
            "system": "A",
            "index": 3,
            "prompt_id": "p3",
            "k": 3,
            "row": {
                "system": "A",
                "prompt_id": "p3",
                "phase": "system_a",
                "question": "Who won?",
                "ground_truth": "Samuel Osei Kuffour",
                "answer": "Samuel Kuffour.",
                "retrieved_k": 3,
                "retrieved_ids": ["doc-a", "doc-b", "doc-c"],
                "retrieved_distances": [0.21, 0.28, 0.4],
                "faithfulness": 0.92,
                "answer_relevancy": 0.77,
                "context_recall": 0.85,
                "total_tokens": 1234,
                "retrieval_time_s": 0.031,
                "generation_time_s": 2.5,
                "judge_time_s": 91.4,
                "total_time_s": 93.9,
            }
        })
    }

    #[test]
    fn prompt_completed_persists_a_full_row() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .apply(&event("run_started", json!({"dataset": "hotpot"})))
            .unwrap();
        store
            .apply(&event("prompt_completed", prompt_completed_row()))
            .unwrap();

        let rows = store.get_prompt_rows("run1").unwrap();
        assert_eq!(
            rows.len(),
            1,
            "the row must be persisted, not just the event"
        );
        let row = &rows[0];
        assert_eq!(row["system"], "A");
        assert_eq!(row["prompt_id"], "p3");
        assert_eq!(row["answer"], "Samuel Kuffour.");
        assert_eq!(row["faithfulness"], 0.92);
        assert_eq!(row["total_tokens"], 1234);
        assert_eq!(row["retrieved_k"], 3);
        // The retrieved chunks must survive as JSON so the 3D map can place them.
        assert_eq!(row["retrieved_ids"][0], "doc-a");
        assert_eq!(row["retrieved_distances"][2], 0.4);
        assert_eq!(row["prompt_index"], 3, "index comes off the event envelope");
    }

    #[test]
    fn prompt_completed_upserts_instead_of_duplicating() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .apply(&event("run_started", json!({"dataset": "hotpot"})))
            .unwrap();
        store
            .apply(&event("prompt_completed", prompt_completed_row()))
            .unwrap();

        // Same prompt again with a corrected score, as a resumed run would send.
        let mut revised = prompt_completed_row();
        revised["row"]["faithfulness"] = json!(0.5);
        store.apply(&event("prompt_completed", revised)).unwrap();

        let rows = store.get_prompt_rows("run1").unwrap();
        assert_eq!(rows.len(), 1, "one row per (run, system, prompt)");
        assert_eq!(rows[0]["faithfulness"], 0.5, "the newer value wins");
    }

    #[test]
    fn unjudged_prompt_row_stores_null_metrics_not_zero() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .apply(&event("run_started", json!({"dataset": "hotpot"})))
            .unwrap();
        let mut row = prompt_completed_row();
        row["row"]["faithfulness"] = json!(null);
        row["row"]["judge_time_s"] = json!(null);
        store.apply(&event("prompt_completed", row)).unwrap();

        let rows = store.get_prompt_rows("run1").unwrap();
        // A missing judge score must not become 0.0: it would drag the mean down and
        // make an unjudged run look worse than a bad one.
        assert_eq!(rows[0]["faithfulness"], serde_json::Value::Null);
        assert_eq!(rows[0]["judge_time_s"], serde_json::Value::Null);
    }

    #[test]
    fn train_step_persists_with_q_values_spread_across_columns() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .apply(&event("run_started", json!({"dataset": "hotpot"})))
            .unwrap();
        store
            .apply(&event(
                "train_step",
                json!({
                    "step": 1, "prompt_id": "p1", "k": 4,
                    "reward": 0.75, "loss": 0.21, "epsilon": 1.0,
                    "q_values": [0.1, 0.2, 0.35, 0.3, 0.25],
                    "faithfulness": 0.8, "total_time_s": 4.2,
                }),
            ))
            .unwrap();

        let rows = store.get_training_rows("run1").unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0]["k"], 4);
        assert_eq!(rows[0]["reward"], 0.75);
        assert_eq!(rows[0]["epsilon"], 1.0);
        // Five discrete actions, so a five-element q_values array.
        assert_eq!(rows[0]["q_values"], json!([0.1, 0.2, 0.35, 0.3, 0.25]));
    }

    #[test]
    fn train_step_upserts_on_replayed_step() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .apply(&event("run_started", json!({"dataset": "hotpot"})))
            .unwrap();
        let step = json!({"step": 1, "prompt_id": "p1", "k": 1, "reward": 0.1});
        store.apply(&event("train_step", step.clone())).unwrap();
        let mut again = step;
        again["reward"] = json!(0.9);
        store.apply(&event("train_step", again)).unwrap();

        let rows = store.get_training_rows("run1").unwrap();
        assert_eq!(rows.len(), 1, "steps are unique per (run, step)");
        assert_eq!(rows[0]["reward"], 0.9);
    }

    #[test]
    fn prompt_completed_without_a_row_is_recorded_but_not_persisted() {
        // An older sidecar predates the `row` payload. The event must still be kept
        // in the timeline rather than rejected, so a mixed-version run stays visible.
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .apply(&event_seq(1, "run_started", json!({"dataset": "hotpot"})))
            .unwrap();
        let changed = store
            .apply(&event_seq(
                2,
                "prompt_completed",
                json!({"system": "A", "prompt_id": "p1", "k": 3}),
            ))
            .unwrap();
        assert!(store.get_prompt_rows("run1").unwrap().is_empty());
        assert_eq!(store.get_events("run1").unwrap().len(), 2);
        assert!(changed, "recording the event counts as a change");
    }

    #[test]
    fn reward_event_updates_the_matching_prompt_row() {
        let store = store();
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .apply(&event("run_started", json!({"dataset": "hotpot"})))
            .unwrap();
        store
            .apply(&event("prompt_completed", prompt_completed_row()))
            .unwrap();
        let changed = store
            .apply(&event(
                "reward",
                json!({
                    "system": "A", "prompt_id": "p3", "reward": 0.6, "k_distribution": {"3": 1}
                }),
            ))
            .unwrap();
        assert!(changed, "a reward that lands on a row is a state change");
        let rows = store.get_prompt_rows("run1").unwrap();
        assert_eq!(rows[0]["reward"], 0.6);
    }

    #[test]
    fn null_means_absent_metric_for_a_read() {
        let conn = Connection::open_in_memory().unwrap();
        crate::db::migrate(&conn).unwrap();
        let store = Store::from_connection(conn);
        store.create_run("run1", 1, "hotpot").unwrap();
        store
            .connection()
            .execute(
                "INSERT INTO prompt_rows (run_id, system_id, prompt_id, faithfulness)
                 VALUES ('run1','A','p1', 0.9), ('run1','A','p2', NULL)",
                [],
            )
            .unwrap();
        let rows = store.get_prompt_rows("run1").unwrap();
        assert_eq!(rows[0]["faithfulness"], 0.9);
        assert_eq!(rows[1]["faithfulness"], serde_json::Value::Null);
    }
}
