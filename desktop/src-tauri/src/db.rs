//! SQLite schema and migrations.
//!
//! The Rust side is the **single writer** for the run database. The Python
//! sidecar never touches SQLite; it only streams NDJSON events on stdout, and
//! [`crate::runner`] turns each event into a row here. That keeps concurrency
//! trivial and means every event is persisted exactly once, through one code
//! path.
//!
//! Schema changes must be additive and must never renumber or drop a column:
//! the committed CSVs under `results/` are imported into these tables by
//! [`crate::legacy`], so a reader has to keep understanding them.

use rusqlite::{Connection, Result};

/// Bumped whenever [`migrate`] adds statements. Kept in the `runs` table's
/// sibling table so an existing database can be checked at open time.
pub const SCHEMA_VERSION: i64 = 1;

/// Open (creating if needed) the run database and apply migrations.
///
/// WAL is enabled so the Results page can read while a run is streaming.
pub fn open(path: &std::path::Path) -> Result<Connection> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| {
            rusqlite::Error::SqliteFailure(
                rusqlite::ffi::Error::new(rusqlite::ffi::SQLITE_CANTOPEN),
                Some(format!("cannot create {}: {e}", parent.display())),
            )
        })?;
    }
    let conn = Connection::open(path)?;
    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "foreign_keys", "ON")?;
    conn.pragma_update(None, "busy_timeout", 5_000)?;
    migrate(&conn)?;
    Ok(conn)
}

/// Apply the schema. Idempotent: every statement is `IF NOT EXISTS`, and the
/// version row is upserted, so this is safe to call on every open.
/// Columns that were added to the schema after a table first shipped.
///
/// `CREATE TABLE IF NOT EXISTS` is a no-op when the table already exists, so
/// opening a database written by an older build would otherwise leave it
/// missing those columns and every later insert would fail with
/// "no such column". `add_missing_columns` closes that gap by comparing this
/// list against `PRAGMA table_info` and issuing `ALTER TABLE ... ADD COLUMN`
/// for whatever is absent.
///
/// SQLite's `ALTER TABLE ADD COLUMN` takes a bare column definition: it cannot
/// add a table constraint such as `UNIQUE` or a `NOT NULL` column without a
/// default. Anything listed here is therefore nullable or defaulted, which is
/// also why the existing rows stay valid - an older run's unknown metrics stay
/// `NULL` instead of being back-filled with a fabricated zero.
///
/// To add a column later: append it here and to `SCHEMA` above. Append it to
/// both, never only one - `SCHEMA` for a fresh database, this list for an
/// existing one.
const ADDED_COLUMNS: &[(&str, &str, &str)] = &[
    // runs: result paths and provenance, added with the persisted-results work.
    ("runs", "dry_run", "INTEGER NOT NULL DEFAULT 0"),
    ("runs", "prompt_rows", "INTEGER"),
    ("runs", "training_rows", "INTEGER"),
    ("runs", "result_csv_path", "TEXT"),
    ("runs", "training_csv_path", "TEXT"),
    ("runs", "analysis_txt_path", "TEXT"),
    ("runs", "duration_s", "REAL"),
    ("runs", "error", "TEXT"),
    ("runs", "notes", "TEXT"),
    ("runs", "git_sha", "TEXT"),
    ("runs", "python_version", "TEXT"),
    ("runs", "embed_model", "TEXT"),
    ("runs", "generator_model", "TEXT"),
    ("runs", "judge_model", "TEXT"),
    // prompt_rows: DQN reward plus per-stage timings and token counts.
    ("prompt_rows", "reward", "REAL"),
    ("prompt_rows", "retrieved_ids", "TEXT"),
    ("prompt_rows", "retrieved_distances", "TEXT"),
    ("prompt_rows", "embedding_time_s", "REAL"),
    ("prompt_rows", "retrieval_time_s", "REAL"),
    ("prompt_rows", "generation_time_s", "REAL"),
    ("prompt_rows", "judge_time_s", "REAL"),
    ("prompt_rows", "total_time_s", "REAL"),
    ("prompt_rows", "prompt_tokens", "INTEGER"),
    ("prompt_rows", "completion_tokens", "INTEGER"),
    ("prompt_rows", "total_tokens", "INTEGER"),
    ("prompt_rows", "judge_prompt_tokens", "INTEGER"),
    ("prompt_rows", "judge_completion_tokens", "INTEGER"),
    // training_steps: reward/loss/epsilon, the five q-values and timings.
    ("training_steps", "reward", "REAL"),
    ("training_steps", "loss", "REAL"),
    ("training_steps", "epsilon", "REAL"),
    ("training_steps", "q_values_k1", "REAL"),
    ("training_steps", "q_values_k2", "REAL"),
    ("training_steps", "q_values_k3", "REAL"),
    ("training_steps", "q_values_k4", "REAL"),
    ("training_steps", "q_values_k5", "REAL"),
    ("training_steps", "prompt_tokens", "INTEGER"),
    ("training_steps", "completion_tokens", "INTEGER"),
    ("training_steps", "total_tokens", "INTEGER"),
    ("training_steps", "judge_prompt_tokens", "INTEGER"),
    ("training_steps", "judge_completion_tokens", "INTEGER"),
    ("training_steps", "embedding_time_s", "REAL"),
    ("training_steps", "retrieval_time_s", "REAL"),
    ("training_steps", "generation_time_s", "REAL"),
    ("training_steps", "judge_time_s", "REAL"),
    ("training_steps", "total_time_s", "REAL"),
    // projections: point count and the raw float32 payload paths.
    ("projections", "n_points", "INTEGER NOT NULL DEFAULT 0"),
    ("projections", "explained_variance", "REAL"),
    ("projections", "source_count", "INTEGER"),
    ("projections", "collection", "TEXT NOT NULL DEFAULT ''"),
    ("projections", "dim", "INTEGER NOT NULL DEFAULT 0"),
    ("projections", "points_path", "TEXT NOT NULL DEFAULT ''"),
    ("projections", "meta_path", "TEXT NOT NULL DEFAULT ''"),
    // run_stats, keyed on run_id, was extended with the created_at stamp.
    ("run_stats", "created_at", "INTEGER NOT NULL DEFAULT 0"),
];

/// Brings an existing database up to the current schema.
///
/// Only additive changes are handled: a new table is picked up by `SCHEMA`, and
/// a new column by `ADDED_COLUMNS`. Anything destructive (a rename, a narrowed
/// type) needs an explicit migration and a `SCHEMA_VERSION` bump, because it
/// cannot be done safely here.
fn add_missing_columns(conn: &Connection) -> Result<()> {
    for (table, column, definition) in ADDED_COLUMNS {
        if table_exists(conn, table)? && !column_exists(conn, table, column)? {
            // Identifiers are compile-time constants from ADDED_COLUMNS, never
            // user input, so the interpolation below is not an injection point.
            conn.execute_batch(&format!(
                "ALTER TABLE {table} ADD COLUMN {column} {definition};"
            ))?;
        }
    }
    Ok(())
}

fn table_exists(conn: &Connection, table: &str) -> Result<bool> {
    let count: i64 = conn.query_row(
        "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = ?1",
        [table],
        |row| row.get(0),
    )?;
    Ok(count > 0)
}

fn column_exists(conn: &Connection, table: &str, column: &str) -> Result<bool> {
    let mut stmt = conn.prepare(&format!("PRAGMA table_info({table})"))?;
    let mut rows = stmt.query([])?;
    while let Some(row) = rows.next()? {
        let name: String = row.get(1)?;
        if name == column {
            return Ok(true);
        }
    }
    Ok(false)
}

pub fn migrate(conn: &Connection) -> Result<()> {
    conn.execute_batch(SCHEMA)?;
    // `SCHEMA` above cannot add columns to a table that already exists, so the
    // additive changes are applied separately. Runs after `execute_batch` so a
    // brand-new database already has every column and this is a no-op.
    add_missing_columns(conn)?;
    // Recorded so a future reader can tell which schema it is looking at.
    // `ON CONFLICT DO UPDATE` rather than `INSERT OR IGNORE`: a database created
    // by a newer build must be flagged here rather than silently left at the
    // version the older binary happens to write.
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?1)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [SCHEMA_VERSION.to_string()],
    )?;
    Ok(())
}

/// Statement executed once on every open.
const SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per benchmark run. `run_id` is a UUID4 minted by the frontend so the
-- sidecar, the database and the UI all agree before the process starts.
CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    created_at          INTEGER NOT NULL,
    started_at          INTEGER,
    finished_at         INTEGER,
    status              TEXT NOT NULL DEFAULT 'queued',
    dataset             TEXT NOT NULL,
    systems             TEXT NOT NULL DEFAULT '["A","B"]',
    prompt_limit        INTEGER,
    prompt_count        INTEGER NOT NULL DEFAULT 0,
    completed_prompts   INTEGER NOT NULL DEFAULT 0,
    corpus_count        INTEGER,
    projection_ready    INTEGER NOT NULL DEFAULT 0,
    seed                INTEGER,
    config_json         TEXT NOT NULL DEFAULT '{}',
    git_sha             TEXT,
    python_version      TEXT,
    embed_model         TEXT,
    generator_model     TEXT,
    judge_model         TEXT,
    no_judge            INTEGER NOT NULL DEFAULT 0,
    -- A fake run's numbers must never be shown as a measurement, so the flag is
    -- persisted and the Results page filters or badges on it.
    dry_run             INTEGER NOT NULL DEFAULT 0,
    prompt_rows         INTEGER,
    training_rows       INTEGER,
    result_csv_path     TEXT,
    training_csv_path   TEXT,
    analysis_txt_path   TEXT,
    duration_s          REAL,
    error               TEXT,
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status  ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_dataset ON runs(dataset);

-- One row per (run, system, prompt). Column names mirror
-- src/logger.py::CSV_COLUMNS so an imported legacy CSV and a live run produce
-- identical rows.
CREATE TABLE IF NOT EXISTS prompt_rows (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    system_id             TEXT NOT NULL,
    prompt_id             TEXT NOT NULL,
    prompt_index          INTEGER,
    phase                 TEXT,
    question              TEXT,
    ground_truth          TEXT,
    answer                TEXT,
    retrieved_k           INTEGER,
    -- JSON arrays of the retrieved chunk ids and distances, so the Results page
    -- can place the exact chunks on the 3D map without re-running retrieval.
    retrieved_ids         TEXT,
    retrieved_distances   TEXT,
    faithfulness          REAL,
    answer_relevancy      REAL,
    context_recall        REAL,
    prompt_tokens         INTEGER,
    completion_tokens     INTEGER,
    total_tokens          INTEGER,
    judge_prompt_tokens   INTEGER,
    judge_completion_tokens INTEGER,
    embedding_time_s      REAL,
    retrieval_time_s      REAL,
    generation_time_s     REAL,
    judge_time_s          REAL,
    total_time_s          REAL,
    reward                REAL,
    UNIQUE(run_id, system_id, prompt_id)
);
CREATE INDEX IF NOT EXISTS idx_rows_run    ON prompt_rows(run_id);
CREATE INDEX IF NOT EXISTS idx_rows_system ON prompt_rows(run_id, system_id);

-- One row per DQN training step (System B phase B.1). Column names mirror
-- run_experiment_logged.py::TRAINING_CSV_COLUMNS.
CREATE TABLE IF NOT EXISTS training_steps (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                  TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    step                    INTEGER NOT NULL,
    prompt_id               TEXT,
    k                       INTEGER,
    faithfulness            REAL,
    answer_relevancy        REAL,
    context_recall          REAL,
    reward                  REAL,
    loss                    REAL,
    epsilon                 REAL,
    q_values_k1             REAL,
    q_values_k2             REAL,
    q_values_k3             REAL,
    q_values_k4             REAL,
    q_values_k5             REAL,
    prompt_tokens           INTEGER,
    completion_tokens       INTEGER,
    total_tokens            INTEGER,
    judge_prompt_tokens     INTEGER,
    judge_completion_tokens INTEGER,
    embedding_time_s        REAL,
    retrieval_time_s        REAL,
    generation_time_s       REAL,
    judge_time_s            REAL,
    total_time_s            REAL,
    UNIQUE(run_id, step)
);
CREATE INDEX IF NOT EXISTS idx_steps_run ON training_steps(run_id, step);

-- The raw event stream, verbatim. Stored even for events the app does not
-- understand, for two reasons: a mapping bug can be fixed later by replaying
-- history, and a run can be re-rendered after the app restarts. Keyed on
-- (run_id, seq) so a re-delivered line replaces rather than duplicates.
CREATE TABLE IF NOT EXISTS run_events (
    run_id        TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,
    ts_ms         INTEGER NOT NULL,
    type          TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id, seq);

-- Descriptive stats + paired tests + k-distribution, computed once at the end
-- of a run by src/stats_analysis.py and stored as one opaque JSON payload.
CREATE TABLE IF NOT EXISTS run_stats (
    run_id        TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
    payload_json  TEXT NOT NULL,
    created_at    INTEGER NOT NULL
);

-- Precomputed 3D PCA projection of a corpus, produced by
-- bench_bridge/projection.py. `points_path` holds raw little-endian float32
-- XYZ triples; `meta_path` holds ids, components, mean and bounds.
CREATE TABLE IF NOT EXISTS projections (
    dataset             TEXT PRIMARY KEY,
    collection          TEXT NOT NULL,
    dim                 INTEGER NOT NULL,
    n_points            INTEGER NOT NULL,
    points_path         TEXT NOT NULL,
    meta_path           TEXT NOT NULL,
    explained_variance  REAL,
    source_count        INTEGER,
    created_at          INTEGER NOT NULL
);
"#;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn migrate_records_the_schema_version() {
        let conn = Connection::open_in_memory().unwrap();
        migrate(&conn).unwrap();
        let v: String = conn
            .query_row(
                "SELECT value FROM schema_meta WHERE key='schema_version'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(v, SCHEMA_VERSION.to_string());
    }

    #[test]
    fn migrate_is_idempotent() {
        let conn = Connection::open_in_memory().unwrap();
        migrate(&conn).unwrap();
        migrate(&conn).unwrap();
        let n: i64 = conn
            .query_row(
                "SELECT count(*) FROM schema_meta WHERE key='schema_version'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(
            n, 1,
            "re-running migrate must not duplicate the version row"
        );
    }

    #[test]
    fn creates_all_expected_tables() {
        let conn = Connection::open_in_memory().unwrap();
        migrate(&conn).unwrap();
        let mut stmt = conn
            .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            .unwrap();
        let names: Vec<String> = stmt
            .query_map([], |r| r.get::<_, String>(0))
            .unwrap()
            .map(|r| r.unwrap())
            .collect();
        for expected in [
            "projections",
            "prompt_rows",
            "run_events",
            "run_stats",
            "runs",
            "schema_meta",
            "training_steps",
        ] {
            assert!(names.contains(&expected.to_string()), "missing {expected}");
        }
    }

    /// The schema a much older build would have written: the same tables, but
    /// without any of the columns added since.
    const LEGACY_SCHEMA: &str = r#"
        CREATE TABLE runs (
            run_id     TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            status     TEXT NOT NULL DEFAULT 'queued',
            dataset    TEXT NOT NULL
        );
        CREATE TABLE prompt_rows (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id       TEXT NOT NULL,
            system_id    TEXT NOT NULL,
            prompt_id    TEXT NOT NULL,
            answer       TEXT,
            retrieved_k  INTEGER,
            faithfulness REAL
        );
        CREATE TABLE training_steps (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id   TEXT NOT NULL,
            step     INTEGER NOT NULL,
            k        INTEGER
        );
        CREATE TABLE projections (
            dataset TEXT PRIMARY KEY
        );
        CREATE TABLE run_stats (
            run_id       TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL
        );
    "#;

    /// Opening a database written by an older build must not lose the rows it
    /// already holds, and must leave it able to accept everything the current
    /// code writes. Without the additive migration every insert of a newer
    /// column fails with "no such column".
    #[test]
    fn migrate_upgrades_a_legacy_database_in_place() {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(LEGACY_SCHEMA).unwrap();
        // A row from the old world, including a real metric that must survive.
        conn.execute(
            "INSERT INTO runs (run_id, created_at, dataset) VALUES ('old', 100, 'hotpot')",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO prompt_rows (run_id, system_id, prompt_id, answer, retrieved_k, faithfulness)
             VALUES ('old', 'A', 'p1', 'legacy answer', 3, 0.8)",
            [],
        )
        .unwrap();

        migrate(&conn).unwrap();

        // The pre-existing row is still there, with its value intact and the
        // columns added later left NULL rather than back-filled with a zero.
        let row: (String, Option<i64>, Option<f64>, Option<f64>, Option<f64>) = conn
            .query_row(
                "SELECT answer, retrieved_k, faithfulness, reward, total_time_s
                 FROM prompt_rows WHERE prompt_id = 'p1'",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
            )
            .unwrap();
        assert_eq!(row.0, "legacy answer");
        assert_eq!(row.1, Some(3));
        assert_eq!(row.2, Some(0.8));
        assert_eq!(
            row.3, None,
            "reward did not exist before and must not be invented"
        );
        assert_eq!(row.4, None);

        // And the upgraded database accepts a current-shaped insert.
        conn.execute(
            "INSERT INTO runs (run_id, created_at, dataset, dry_run, git_sha)
             VALUES ('new', 200, 'math', 0, 'abc123')",
            [],
        )
        .unwrap();
        let dry_run: i64 = conn
            .query_row("SELECT dry_run FROM runs WHERE run_id = 'new'", [], |r| {
                r.get(0)
            })
            .unwrap();
        assert_eq!(dry_run, 0);
        let sha: String = conn
            .query_row("SELECT git_sha FROM runs WHERE run_id = 'new'", [], |r| {
                r.get(0)
            })
            .unwrap();
        assert_eq!(sha, "abc123");
    }

    #[test]
    fn migrate_upgrades_a_legacy_training_and_projection_database() {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(LEGACY_SCHEMA).unwrap();
        conn.execute(
            "INSERT INTO training_steps (run_id, step, k) VALUES ('old', 1, 4)",
            [],
        )
        .unwrap();
        conn.execute("INSERT INTO projections (dataset) VALUES ('hotpot')", [])
            .unwrap();

        migrate(&conn).unwrap();

        // The five q-values and the loss are what the Results charts read; an old
        // step has no measurement for them, so they must be NULL.
        let (q3, loss): (Option<f64>, Option<f64>) = conn
            .query_row(
                "SELECT q_values_k3, loss FROM training_steps WHERE step = 1",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(q3, None);
        assert_eq!(loss, None);

        let (n_points, points_path): (i64, String) = conn
            .query_row(
                "SELECT n_points, points_path FROM projections WHERE dataset = 'hotpot'",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(n_points, 0);
        assert_eq!(points_path, "");
    }

    /// Re-running the migration over an already-upgraded database must be a
    /// no-op rather than an "duplicate column" error, since migrate() runs on
    /// every open.
    #[test]
    fn migrate_is_idempotent_over_a_legacy_database() {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(LEGACY_SCHEMA).unwrap();
        migrate(&conn).unwrap();
        migrate(&conn).unwrap();
        migrate(&conn).unwrap();
        assert!(column_exists(&conn, "runs", "dry_run").unwrap());
    }

    #[test]
    fn prompt_rows_keeps_one_row_per_run_system_prompt() {
        let conn = Connection::open_in_memory().unwrap();
        migrate(&conn).unwrap();
        conn.execute(
            "INSERT INTO runs (run_id, created_at, dataset) VALUES ('r1', 1, 'hotpot')",
            [],
        )
        .unwrap();
        let insert = "INSERT INTO prompt_rows (run_id, system_id, prompt_id) VALUES (?1, ?2, ?3)";
        conn.execute(insert, ["r1", "A", "p1"]).unwrap();
        // Same (run, system, prompt) again must be rejected by the UNIQUE index.
        let err = conn.execute(insert, ["r1", "A", "p1"]).unwrap_err();
        assert!(matches!(err, rusqlite::Error::SqliteFailure(_, _)));
        // A different system for the same prompt is fine.
        conn.execute(insert, ["r1", "B", "p1"]).unwrap();
        let n: i64 = conn
            .query_row("SELECT count(*) FROM prompt_rows", [], |r| r.get(0))
            .unwrap();
        assert_eq!(n, 2);
    }

    #[test]
    fn prompt_rows_cascade_when_run_deleted() {
        let conn = Connection::open_in_memory().unwrap();
        migrate(&conn).unwrap();
        conn.execute(
            "INSERT INTO runs (run_id, created_at, dataset) VALUES ('r1', 1, 'hotpot')",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO prompt_rows (run_id, system_id, prompt_id) VALUES ('r1','A','p1')",
            [],
        )
        .unwrap();
        conn.execute("DELETE FROM runs WHERE run_id='r1'", [])
            .unwrap();
        let n: i64 = conn
            .query_row("SELECT count(*) FROM prompt_rows", [], |r| r.get(0))
            .unwrap();
        assert_eq!(n, 0, "foreign_keys pragma must cascade");
    }

    #[test]
    fn open_creates_parent_directory() {
        let dir = tempfile::tempdir().unwrap();
        let nested = dir.path().join("a").join("b").join("runs.sqlite3");
        let conn = open(&nested).unwrap();
        let n: i64 = conn
            .query_row("SELECT count(*) FROM runs", [], |r| r.get(0))
            .unwrap();
        assert_eq!(n, 0);
        assert!(nested.exists());
    }
}
