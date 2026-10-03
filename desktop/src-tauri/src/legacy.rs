//! Importing the committed CSVs under `results/`.
//!
//! The historical experiments were run by hand with `run_experiment.py`, and
//! their CSVs are the baseline the new pipeline has to be comparable against. To
//! make that comparison possible in one place, they are imported as runs whose
//! status is `imported` - visibly distinct from a run this app produced.
//!
//! Three header shapes are accepted, because all three exist in `results/`:
//!
//! - `ragas_results_<dataset>.csv` - 6 columns, metrics only
//! - `ragas_results_<dataset>_logged.csv` - the above plus token counts and timings
//! - `training_log_<dataset>.csv` - one row per DQN step
//!
//! Columns the file does not have stay `NULL`. They are never defaulted to zero:
//! an unmeasured metric must not read as "measured and terrible".

use std::collections::HashMap;
use std::path::Path;

use rusqlite::params;

use crate::store::Store;

/// Columns copied straight from a results CSV into `prompt_rows`.
const RESULT_COLUMNS: &[(&str, &str)] = &[
    ("prompt_id", "prompt_id"),
    ("system_id", "system_id"),
    ("retrieved_k", "retrieved_k"),
    ("faithfulness", "faithfulness"),
    ("answer_relevancy", "answer_relevancy"),
    ("context_recall", "context_recall"),
    ("prompt_tokens", "prompt_tokens"),
    ("completion_tokens", "completion_tokens"),
    ("total_tokens", "total_tokens"),
    ("judge_prompt_tokens", "judge_prompt_tokens"),
    ("judge_completion_tokens", "judge_completion_tokens"),
    ("retrieval_time_s", "retrieval_time_s"),
    ("generation_time_s", "generation_time_s"),
    ("judge_time_s", "judge_time_s"),
    ("total_time_s", "total_time_s"),
];

/// Columns copied from a training CSV into `training_steps`.
const TRAINING_COLUMNS: &[(&str, &str)] = &[
    ("step", "step"),
    ("k", "k"),
    ("faithfulness", "faithfulness"),
    ("answer_relevancy", "answer_relevancy"),
    ("context_recall", "context_recall"),
    ("reward", "reward"),
    ("loss", "loss"),
    ("epsilon", "epsilon"),
    ("q_values_k1", "q_values_k1"),
    ("q_values_k2", "q_values_k2"),
    ("q_values_k3", "q_values_k3"),
    ("q_values_k4", "q_values_k4"),
    ("q_values_k5", "q_values_k5"),
    ("prompt_tokens", "prompt_tokens"),
    ("completion_tokens", "completion_tokens"),
    ("total_tokens", "total_tokens"),
    ("judge_prompt_tokens", "judge_prompt_tokens"),
    ("judge_completion_tokens", "judge_completion_tokens"),
    ("embedding_time_s", "embedding_time_s"),
    ("retrieval_time_s", "retrieval_time_s"),
    ("generation_time_s", "generation_time_s"),
    ("judge_time_s", "judge_time_s"),
    ("total_time_s", "total_time_s"),
];

/// What one import attempt did.
#[derive(Debug, Clone, serde::Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ImportReport {
    pub runs: Vec<String>,
    pub prompt_rows: usize,
    pub training_rows: usize,
    pub skipped: Vec<String>,
}

impl ImportReport {
    fn new() -> Self {
        Self {
            runs: Vec::new(),
            prompt_rows: 0,
            training_rows: 0,
            skipped: Vec::new(),
        }
    }
}

/// One parsed CSV file.
struct Csv {
    header: Vec<String>,
    rows: Vec<HashMap<String, String>>,
}

impl Csv {
    /// Parse a CSV with a header row.
    ///
    /// Written by hand rather than pulled in as a dependency: the files have no
    /// embedded commas that need quoting in practice, and the numeric/empty
    /// handling below is the interesting part anyway.
    fn parse(text: &str) -> Result<Self, String> {
        let mut lines = text.lines().filter(|l| !l.trim().is_empty());
        let header: Vec<String> = lines
            .next()
            .ok_or_else(|| "file is empty".to_string())?
            .split(',')
            .map(|h| h.trim().to_string())
            .collect();
        let rows = lines
            .map(|line| {
                line.split(',')
                    .enumerate()
                    .filter_map(|(i, value)| {
                        header
                            .get(i)
                            .map(|key| (key.clone(), value.trim().to_string()))
                    })
                    .collect::<HashMap<_, _>>()
            })
            .collect();
        Ok(Csv { header, rows })
    }

    fn has(&self, column: &str) -> bool {
        self.header.iter().any(|h| h == column)
    }

    fn has_all(&self, columns: &[&str]) -> bool {
        columns.iter().all(|c| self.has(c))
    }
}

/// Read a value as SQL text, mapping empty and `nan`/`NaN` to NULL.
///
/// A RAGAS score of NaN means "the judge could not extract statements", which is
/// missing data, not a measurement of zero.
fn sql_value(value: &str) -> Option<&str> {
    let trimmed = value.trim();
    if trimmed.is_empty() || trimmed.eq_ignore_ascii_case("nan") {
        None
    } else {
        Some(trimmed)
    }
}

/// Recover the dataset from a filename.
///
/// `ragas_results_hotpot_lam0.csv` -> `hotpot`; the trailing variant suffix
/// (`_lam0`, `_old`, `_logged`) is dropped.
fn dataset_from_name(name: &str) -> Option<String> {
    let stem = name.strip_suffix(".csv")?;
    for prefix in ["ragas_results_", "training_log_"] {
        if let Some(rest) = stem.strip_prefix(prefix) {
            let dataset = rest
                .strip_suffix("_logged")
                .or_else(|| rest.strip_suffix("_old"))
                .or_else(|| rest.strip_suffix("_lam0"))
                .unwrap_or(rest);
            if !dataset.is_empty() {
                return Some(dataset.to_string());
            }
        }
    }
    None
}

/// Import every recognised CSV in `dir`.
pub fn import_directory(store: &Store, dir: &Path) -> Result<ImportReport, String> {
    if !dir.exists() {
        return Err(format!("{} does not exist", dir.display()));
    }
    let mut entries: Vec<_> = std::fs::read_dir(dir)
        .map_err(|e| format!("cannot read {}: {e}", dir.display()))?
        .filter_map(Result::ok)
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|e| e == "csv"))
        .collect();
    entries.sort();

    let mut report = ImportReport::new();
    for path in entries {
        let Some(name) = path.file_name().and_then(|n| n.to_str()) else {
            continue;
        };
        match import_file(store, &path, name) {
            Ok(Some(stats)) => {
                report.runs.push(stats.run_id);
                report.prompt_rows += stats.prompt_rows;
                report.training_rows += stats.training_rows;
            }
            Ok(None) => report.skipped.push(name.to_string()),
            Err(err) => report.skipped.push(format!("{name}: {err}")),
        }
    }
    Ok(report)
}

/// Per-file counts.
struct FileStats {
    run_id: String,
    prompt_rows: usize,
    training_rows: usize,
}

/// Import one file, or return `None` if it is not a benchmark CSV.
fn import_file(store: &Store, path: &Path, name: &str) -> Result<Option<FileStats>, String> {
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let csv = Csv::parse(&text)?;
    let dataset = dataset_from_name(name)
        .ok_or_else(|| format!("unrecognised name (not a benchmark csv)"))?;

    // A results CSV and a training CSV become separate runs: they measure
    // different things (inference quality vs learning progress) and merging them
    // would make the run list lie about what happened.
    if csv.has("step") && csv.has_all(&["step", "k"]) {
        return import_training(store, &csv, &dataset, name).map(Some);
    }
    if csv.has("prompt_id") && csv.has("system_id") {
        return import_results(store, &csv, &dataset, name).map(Some);
    }
    Err("unrecognised columns".into())
}

fn import_results(
    store: &Store,
    csv: &Csv,
    dataset: &str,
    name: &str,
) -> Result<FileStats, String> {
    let run_id = format!("import-{dataset}-{}", short_hash(name));
    let now = now_ms();
    let store_conn = store.connection();

    store_conn
        .execute(
            "INSERT OR REPLACE INTO runs
                (run_id, created_at, started_at, finished_at, status, dataset, systems,
                 prompt_count, completed_prompts, result_csv_path, notes)
             VALUES (?1, ?2, NULL, NULL, 'imported', ?3, '[\"A\",\"B\"]', 0, 0, ?4, ?5)",
            params![run_id, now, dataset, name, "Imported from results/"],
        )
        .map_err(|e| e.to_string())?;
    store_conn
        .execute("DELETE FROM prompt_rows WHERE run_id = ?1", [&run_id])
        .map_err(|e| e.to_string())?;

    // Build the INSERT from the file's own header so a missing column simply is
    // not part of the statement, rather than being bound to NULL by position.
    // ?1 is the run_id and ?2 the prompt index, so columns start at ?3.
    let available: Vec<(&str, &str)> = RESULT_COLUMNS
        .iter()
        .copied()
        .filter(|(source, _)| csv.has(source))
        .collect();
    let placeholders: Vec<String> = (3..=available.len() + 2).map(|i| format!("?{i}")).collect();
    let columns: Vec<&str> = available.iter().map(|(_, target)| *target).collect();
    let sql = format!(
        "INSERT OR REPLACE INTO prompt_rows (run_id, prompt_index, {}) VALUES (?1, ?2, {})",
        columns.join(", "),
        placeholders.join(", ")
    );

    let mut inserted = 0;
    // prompt_index is per *prompt*, not per (prompt, system): both systems
    // answering prompt 0 must share index 0, which is what lets the Results page
    // pair A and B rows for the same question.
    let mut prompt_index_by_id: HashMap<String, i64> = HashMap::new();
    let mut systems_seen: HashMap<(String, String), ()> = HashMap::new();
    for row in &csv.rows {
        let Some(prompt_id) = row.get("prompt_id").and_then(|v| sql_value(v)) else {
            continue;
        };
        let Some(system) = row.get("system_id").and_then(|v| sql_value(v)) else {
            continue;
        };
        let next = prompt_index_by_id.len() as i64;
        let prompt_index = *prompt_index_by_id
            .entry(prompt_id.to_string())
            .or_insert(next);
        systems_seen.insert((prompt_id.to_string(), system.to_string()), ());

        let mut bind: Vec<Box<dyn rusqlite::ToSql>> =
            vec![Box::new(run_id.clone()), Box::new(prompt_index)];
        for (source, _) in &available {
            bind.push(Box::new(
                row.get(*source)
                    .and_then(|v| sql_value(v))
                    .map(str::to_string),
            ));
        }
        let params: Vec<&dyn rusqlite::ToSql> = bind.iter().map(|p| p.as_ref()).collect();
        store_conn
            .execute(&sql, params.as_slice())
            .map_err(|e| e.to_string())?;
        inserted += 1;
    }

    store_conn
        .execute(
            "UPDATE runs SET prompt_count = ?2, completed_prompts = ?2 WHERE run_id = ?1",
            params![run_id, prompt_index_by_id.len() as i64],
        )
        .map_err(|e| e.to_string())?;

    Ok(FileStats {
        run_id,
        prompt_rows: inserted,
        training_rows: 0,
    })
}

fn import_training(
    store: &Store,
    csv: &Csv,
    dataset: &str,
    name: &str,
) -> Result<FileStats, String> {
    let run_id = format!("import-{dataset}-train-{}", short_hash(name));
    let now = now_ms();
    let conn = store.connection();

    conn.execute(
        "INSERT OR REPLACE INTO runs
            (run_id, created_at, started_at, finished_at, status, dataset, systems,
             prompt_count, completed_prompts, training_csv_path, notes)
         VALUES (?1, ?2, NULL, NULL, 'imported', ?3, '[\"B\"]', 0, 0, ?4, ?5)",
        params![
            run_id,
            now,
            dataset,
            name,
            "Training log imported from results/"
        ],
    )
    .map_err(|e| e.to_string())?;
    conn.execute("DELETE FROM training_steps WHERE run_id = ?1", [&run_id])
        .map_err(|e| e.to_string())?;

    // ?1 is the run_id and ?2 the step, so the remaining columns start at ?3.
    // `step` is excluded from `available` because it is already bound to ?2 -
    // including it twice would leave the statement with an unbound placeholder.
    let available: Vec<(&str, &str)> = TRAINING_COLUMNS
        .iter()
        .copied()
        .filter(|(source, _)| *source != "step" && csv.has(source))
        .collect();
    let placeholders: Vec<String> = (3..=available.len() + 2).map(|i| format!("?{i}")).collect();
    let columns: Vec<&str> = available.iter().map(|(_, target)| *target).collect();
    let sql = format!(
        "INSERT OR REPLACE INTO training_steps (run_id, step, {}) VALUES (?1, ?2, {})",
        columns.join(", "),
        placeholders.join(", ")
    );

    let mut inserted = 0;
    for row in &csv.rows {
        let Some(step) = row.get("step").and_then(|v| sql_value(v)) else {
            continue;
        };
        let mut bind: Vec<Box<dyn rusqlite::ToSql>> =
            vec![Box::new(run_id.clone()), Box::new(step.to_string())];
        for (source, _) in &available {
            bind.push(Box::new(
                row.get(*source)
                    .and_then(|v| sql_value(v))
                    .map(str::to_string),
            ));
        }
        let params: Vec<&dyn rusqlite::ToSql> = bind.iter().map(|p| p.as_ref()).collect();
        conn.execute(&sql, params.as_slice())
            .map_err(|e| e.to_string())?;
        inserted += 1;
    }

    Ok(FileStats {
        run_id,
        prompt_rows: 0,
        training_rows: inserted,
    })
}

/// Short stable hash of a filename, used to keep run ids deterministic.
///
/// Re-importing the same file must land on the same `run_id`, otherwise every
/// import would add another near-duplicate run to the list.
fn short_hash(input: &str) -> String {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in input.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x1000_0000_01b3);
    }
    format!("{hash:016x}")
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::Connection;
    use std::collections::HashSet;

    fn store() -> Store {
        let conn = Connection::open_in_memory().unwrap();
        crate::db::migrate(&conn).unwrap();
        Store::from_connection(conn)
    }

    fn write(dir: &Path, name: &str, contents: &str) {
        std::fs::write(dir.join(name), contents).unwrap();
    }

    const SHORT_RESULTS: &str =
        "prompt_id,system_id,retrieved_k,faithfulness,answer_relevancy,context_recall\n\
p1,A,3,0.9,0.8,0.7\n\
p2,A,3,0.6,0.5,0.4\n\
p1,B,4,0.8,0.7,0.6\n\
p2,B,4,NaN,0.5,0.4\n";

    const LOGGED_RESULTS: &str = "prompt_id,system_id,retrieved_k,faithfulness,answer_relevancy,context_recall,prompt_tokens,completion_tokens,total_tokens,judge_prompt_tokens,judge_completion_tokens,retrieval_time_s,generation_time_s,judge_time_s,total_time_s\n\
p1,A,3,0.9,0.8,0.7,10,20,30,5,6,0.1,0.2,0.3,0.6\n";

    const TRAINING: &str = "step,k,faithfulness,answer_relevancy,context_recall,reward,loss,epsilon,q_values_k1,q_values_k2,q_values_k3,q_values_k4,q_values_k5,total_time_s\n\
1,3,0.5,0.5,0.5,0.4,0.2,1.0,0.1,0.2,0.9,0.3,0.05,1.0\n\
2,4,0.6,0.6,0.6,0.5,0.15,0.9,0.1,0.2,0.8,0.5,0.05,1.1\n";

    #[test]
    fn imports_a_short_results_csv() {
        let dir = tempfile::tempdir().unwrap();
        write(dir.path(), "ragas_results_hotpot.csv", SHORT_RESULTS);
        let store = store();
        let report = import_directory(&store, dir.path()).unwrap();
        assert_eq!(
            report.runs.len(),
            1,
            "nothing imported; skipped: {:?}",
            report.skipped
        );
        assert_eq!(report.prompt_rows, 4);
        assert_eq!(report.skipped, Vec::<String>::new());

        let run_id = &report.runs[0];
        let rows = store.get_prompt_rows(run_id).unwrap();
        assert_eq!(rows.len(), 4);
        assert_eq!(rows[0]["system"], "A");
        assert_eq!(rows[0]["faithfulness"], 0.9);
        assert_eq!(rows[0]["retrieved_k"], 3);
    }

    #[test]
    fn nan_becomes_null_not_zero() {
        let dir = tempfile::tempdir().unwrap();
        write(dir.path(), "ragas_results_hotpot.csv", SHORT_RESULTS);
        let store = store();
        let report = import_directory(&store, dir.path()).unwrap();
        let rows = store.get_prompt_rows(&report.runs[0]).unwrap();
        let nan_row = rows
            .iter()
            .find(|r| r["prompt_id"] == "p2" && r["system"] == "B")
            .unwrap();
        assert_eq!(nan_row["faithfulness"], serde_json::Value::Null);
        // The other metrics on that row are still imported.
        assert_eq!(nan_row["answer_relevancy"], 0.5);
    }

    #[test]
    fn absent_columns_are_null() {
        let dir = tempfile::tempdir().unwrap();
        write(dir.path(), "ragas_results_hotpot.csv", SHORT_RESULTS);
        let store = store();
        let report = import_directory(&store, dir.path()).unwrap();
        let rows = store.get_prompt_rows(&report.runs[0]).unwrap();
        // The short CSV has no token or timing columns at all.
        assert_eq!(rows[0]["prompt_tokens"], serde_json::Value::Null);
        assert_eq!(rows[0]["total_time_s"], serde_json::Value::Null);
    }

    #[test]
    fn imports_a_logged_results_csv_with_tokens() {
        let dir = tempfile::tempdir().unwrap();
        write(dir.path(), "ragas_results_math_logged.csv", LOGGED_RESULTS);
        let store = store();
        let report = import_directory(&store, dir.path()).unwrap();
        let rows = store.get_prompt_rows(&report.runs[0]).unwrap();
        assert_eq!(rows[0]["prompt_tokens"], 10);
        assert_eq!(rows[0]["total_time_s"], 0.6);
        assert_eq!(rows[0]["judge_completion_tokens"], 6);
    }

    #[test]
    fn imports_a_training_csv() {
        let dir = tempfile::tempdir().unwrap();
        write(dir.path(), "training_log_hotpot.csv", TRAINING);
        let store = store();
        let report = import_directory(&store, dir.path()).unwrap();
        assert_eq!(
            report.training_rows, 2,
            "training file skipped: {:?}",
            report.skipped
        );
        let steps = store.get_training_rows(&report.runs[0]).unwrap();
        assert_eq!(steps.len(), 2);
        assert_eq!(steps[0]["step"], 1);
        assert_eq!(steps[0]["reward"], 0.4);
        assert_eq!(steps[0]["q_values"][2], 0.9);
    }

    #[test]
    fn results_and_training_become_separate_runs() {
        let dir = tempfile::tempdir().unwrap();
        write(dir.path(), "ragas_results_hotpot.csv", SHORT_RESULTS);
        write(dir.path(), "training_log_hotpot.csv", TRAINING);
        let store = store();
        let report = import_directory(&store, dir.path()).unwrap();
        assert_eq!(report.runs.len(), 2);
        assert_eq!(report.prompt_rows, 4);
        assert_eq!(report.training_rows, 2);
        let detail: HashSet<String> = store
            .list_runs()
            .unwrap()
            .into_iter()
            .map(|r| r["run_id"].as_str().unwrap().to_string())
            .collect();
        // A run that mixes inference rows and training steps would be a
        // category error in the Results page.
        assert!(detail.iter().any(|id| id.contains("train")));
        assert!(detail.iter().any(|id| !id.contains("train")));
    }

    #[test]
    fn reimporting_the_same_file_does_not_duplicate() {
        let dir = tempfile::tempdir().unwrap();
        write(dir.path(), "ragas_results_hotpot.csv", SHORT_RESULTS);
        let store = store();
        let first = import_directory(&store, dir.path()).unwrap();
        let second = import_directory(&store, dir.path()).unwrap();
        assert_eq!(first.runs, second.runs);
        assert_eq!(store.list_runs().unwrap().len(), 1);
        assert_eq!(store.get_prompt_rows(&first.runs[0]).unwrap().len(), 4);
    }

    #[test]
    fn imported_runs_are_marked_imported() {
        let dir = tempfile::tempdir().unwrap();
        write(dir.path(), "ragas_results_hotpot.csv", SHORT_RESULTS);
        let store = store();
        let report = import_directory(&store, dir.path()).unwrap();
        let run = store.get_run(&report.runs[0]).unwrap().unwrap();
        assert_eq!(run["status"], "imported");
        assert_eq!(run["dataset"], "hotpot");
        assert_eq!(run["result_csv_path"], "ragas_results_hotpot.csv");
    }

    #[test]
    fn prompt_index_is_assigned_per_prompt_not_per_row() {
        let dir = tempfile::tempdir().unwrap();
        write(dir.path(), "ragas_results_hotpot.csv", SHORT_RESULTS);
        let store = store();
        let report = import_directory(&store, dir.path()).unwrap();
        let rows = store.get_prompt_rows(&report.runs[0]).unwrap();
        let p1: Vec<i64> = rows
            .iter()
            .filter(|r| r["prompt_id"] == "p1")
            .map(|r| r["prompt_index"].as_i64().unwrap())
            .collect();
        assert_eq!(p1, vec![0, 0], "both systems share a prompt index");
    }

    #[test]
    fn unrelated_csv_is_skipped_not_fatal() {
        let dir = tempfile::tempdir().unwrap();
        write(dir.path(), "ragas_results_hotpot.csv", SHORT_RESULTS);
        write(
            dir.path(),
            "token_counts_hotpot.csv",
            "prompt_id,tokens\np1,10\n",
        );
        let store = store();
        let report = import_directory(&store, dir.path()).unwrap();
        assert_eq!(report.runs.len(), 1);
        assert_eq!(report.skipped.len(), 1);
        assert!(report.skipped[0].contains("token_counts"));
    }

    #[test]
    fn a_missing_directory_is_an_error() {
        let store = store();
        let err = import_directory(&store, Path::new("C:/definitely/not/here")).unwrap_err();
        assert!(err.contains("does not exist"));
    }

    #[test]
    fn dataset_is_recovered_from_various_names() {
        for (name, expected) in [
            ("ragas_results_hotpot.csv", "hotpot"),
            ("ragas_results_hotpot_logged.csv", "hotpot"),
            ("ragas_results_hotpot_old.csv", "hotpot"),
            ("ragas_results_ragtruth_lam0.csv", "ragtruth"),
            ("ragas_results_math.csv", "math"),
            ("training_log_fintech.csv", "fintech"),
        ] {
            assert_eq!(
                dataset_from_name(name).as_deref(),
                Some(expected),
                "for {name}"
            );
        }
    }

    #[test]
    fn non_benchmark_filenames_are_rejected_by_name() {
        // token_counts_*.csv shares no benchmark prefix, so it must not be
        // mistaken for a dataset called "token_counts_hotpot".
        assert_eq!(dataset_from_name("token_counts_hotpot.csv"), None);
        assert_eq!(dataset_from_name("analysis_report.csv"), None);
        assert_eq!(dataset_from_name("readme.md"), None);
    }

    #[test]
    fn empty_values_are_null() {
        assert_eq!(sql_value(""), None);
        assert_eq!(sql_value("   "), None);
        assert_eq!(sql_value("NaN"), None);
        assert_eq!(sql_value("nan"), None);
        assert_eq!(sql_value("0.5"), Some("0.5"));
        // A real zero must survive - it is a measurement.
        assert_eq!(sql_value("0"), Some("0"));
    }

    #[test]
    fn short_hash_is_deterministic() {
        assert_eq!(short_hash("a.csv"), short_hash("a.csv"));
        assert_ne!(short_hash("a.csv"), short_hash("b.csv"));
        assert_eq!(short_hash("a.csv").len(), 16);
    }
}
