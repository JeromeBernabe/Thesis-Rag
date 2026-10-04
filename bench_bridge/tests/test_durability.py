"""Tests for the two defect classes that silently cost completed work.

Both of these shipped and both were invisible for a long time: the logger
destroyed the previous run's results on construction, and the one-tailed
p-value used the wrong tail. Neither raised, so nothing in the existing suite
noticed. These tests are deliberately written to fail against the old
behaviour - each says what breaks, not just what the code returns.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pandas as pd
import pytest
import torch

# `src/` sits outside the package, and pytest.ini restricts collection to
# bench_bridge/tests, so the repo root has to be importable from here.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.logger import ResultLogger, promote  # noqa: E402
from src.stats_analysis import _paired_test  # noqa: E402


def read_rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def sample(prompt_id="p1", faithfulness=0.9, **kwargs):
    # `system_id` and friends may be overridden by callers, so they go last.
    row = dict(
        prompt_id=prompt_id,
        system_id="A",
        faithfulness=faithfulness,
        answer_relevancy=0.8,
        context_recall=0.7,
    )
    row.update(kwargs)
    return row


# --------------------------------------------------------------------------
# ResultLogger must not destroy the previous run
# --------------------------------------------------------------------------


def test_second_run_does_not_delete_the_first_runs_rows(tmp_path):
    """The defect: a header written with mode "w" wiped completed work.

    A benchmark run is six to nine hours per dataset. Constructing the logger
    for the next run used to truncate the file before a single prompt had been
    judged, and a crash after that left a header-only CSV - which is exactly
    what results/ragas_results_math.csv still is, at 78 bytes.
    """
    path = tmp_path / "results.csv"

    first = ResultLogger(path)
    first.log(**sample("p1", 0.9))
    first.log(**sample("p2", 0.6))
    assert len(read_rows(path)) == 2

    # This construction is the moment the old code destroyed everything.
    ResultLogger(path)

    rows = read_rows(path)
    assert len(rows) == 2, "starting a second run deleted the first run's results"
    assert {r["prompt_id"] for r in rows} == {"p1", "p2"}


def test_appending_across_runs_adds_rather_than_replaces(tmp_path):
    path = tmp_path / "results.csv"
    ResultLogger(path).log(**sample("p1", 0.9))
    ResultLogger(path).log(**sample("p2", 0.7))

    rows = read_rows(path)
    assert [r["prompt_id"] for r in rows] == ["p1", "p2"]


def test_header_is_written_exactly_once(tmp_path):
    """Appending must not stamp a second header into an existing file."""
    path = tmp_path / "results.csv"
    ResultLogger(path).log(**sample())
    ResultLogger(path).log(**sample("p2"))

    text = path.read_text(encoding="utf-8")
    assert text.count("prompt_id") == 1, "a second run appended a duplicate header row"
    # And the row count is data rows only.
    assert len(read_rows(path)) == 2


def test_fresh_is_the_way_to_deliberately_overwrite(tmp_path):
    """Appending is the safe default, but a real overwrite has to stay possible."""
    path = tmp_path / "results.csv"
    ResultLogger(path).log(**sample("old", 0.9))

    ResultLogger(path, fresh=True).log(**sample("new", 0.5))

    rows = read_rows(path)
    assert len(rows) == 1
    assert rows[0]["prompt_id"] == "new"


def test_rows_are_on_disk_before_the_logger_is_ever_closed(tmp_path):
    """A killed host must not take completed rows with it.

    The rows are worth hours of judge time each. If they sit in a buffer, a
    process that is killed outright loses everything - and both long runs in
    this repo's logs died exactly that way, mid-scoring, with no traceback.
    """
    path = tmp_path / "results.csv"
    logger = ResultLogger(path)

    for i in range(5):
        logger.log(**sample(f"p{i}", 0.5 + i / 10))

    # No close(), no flush() call: read the file as an outside observer would.
    assert len(read_rows(path)) == 5


def test_fsync_failure_does_not_lose_the_row(tmp_path, monkeypatch):
    """A filesystem that refuses fsync must degrade, not raise.

    Losing durability is bad; refusing to record the row at all is worse, and
    the row cannot be reconstructed once the judge has moved on.
    """
    path = tmp_path / "results.csv"

    def refuse(_fd):
        raise OSError("fsync unavailable on this handle")

    monkeypatch.setattr(os, "fsync", refuse)
    logger = ResultLogger(path)
    logger.log(**sample("p1", 0.42))

    assert len(read_rows(path)) == 1


def test_creates_missing_parent_directory(tmp_path):
    path = tmp_path / "nested" / "deeper" / "results.csv"
    ResultLogger(path).log(**sample())
    assert path.exists()


# --------------------------------------------------------------------------
# Trained checkpoints must survive an interrupted save
# --------------------------------------------------------------------------


def agent(checkpoint_path):
    from src.dqn_agent import DQNAgent

    return DQNAgent(checkpoint_path=checkpoint_path)


def interrupting_save(monkeypatch):
    """Make the next `torch.save` die after truncating its destination.

    Real `torch.save(obj, path)` opens the destination itself, which truncates
    it before the first byte is written. A fake that only raises would leave the
    old file untouched under *both* implementations and so would prove nothing,
    so this reproduces the truncation explicitly.
    """
    def _save(obj, f, *args, **kwargs):
        target = f if isinstance(f, (str, Path)) else f.name
        with open(target, "wb") as fh:
            fh.write(b"\x80\x02truncated-mid-save")
            fh.flush()
        raise OSError("killed mid-save")

    monkeypatch.setattr(torch, "save", _save)


def test_a_failed_save_leaves_the_previous_checkpoint_loadable(tmp_path, monkeypatch):
    """The defect: `torch.save` wrote straight to the live path.

    An interrupted save truncated the file and then died, so the checkpoint that
    was already there could not be loaded next run - the model was lost as
    collateral damage of an unrelated failure. Training saves after every
    episode, so this was reachable constantly.
    """
    path = tmp_path / "dqn_model_hotpot.pth"
    good = agent(path)
    good.epsilon = 0.5
    good.save(path, keep=0)

    interrupting_save(monkeypatch)
    with pytest.raises(OSError):
        good.save(path, keep=0)

    assert path.exists(), "the interrupted save destroyed the existing checkpoint"
    assert path.stat().st_size > 32, "the destination was left truncated"

    reloaded = agent(path)
    reloaded.load(path)
    assert reloaded.epsilon == pytest.approx(0.5)


def test_no_temp_file_is_left_to_be_mistaken_for_a_checkpoint(tmp_path, monkeypatch):
    path = tmp_path / "dqn.pth"
    a = agent(path)
    a.epsilon = 0.9
    a.save(path, keep=0)

    interrupting_save(monkeypatch)
    with pytest.raises(OSError):
        a.save(path, keep=0)

    assert list(tmp_path.glob("*.tmp")) == []
    # The next save must still work, i.e. no stale temp file was in the way.
    monkeypatch.undo()
    a.epsilon = 0.3
    a.save(path, keep=0)
    assert agent(path) is not None


def test_old_versions_are_kept_and_pruned(tmp_path):
    """Keep the last 3, so a bad run can be rolled back or compared."""
    path = tmp_path / "dqn_model_math.pth"
    a = agent(path)

    for i in range(6):
        a.epsilon = i / 10
        a.save(path, keep=3)

    versions = sorted(p.name for p in tmp_path.glob("dqn_model_math.*.pth"))
    assert len(versions) == 3, f"expected 3 kept versions, found {versions}"
    assert path.exists(), "rotation must never remove the live checkpoint"
    assert list(tmp_path.glob("*.tmp")) == []


def test_rotation_off_keeps_only_the_live_file(tmp_path):
    path = tmp_path / "dqn.pth"
    a = agent(path)
    for i in range(3):
        a.epsilon = i / 10
        a.save(path, keep=0)
    assert list(tmp_path.glob("*.pth")) == [path]


def test_rotation_does_not_touch_unrelated_files(tmp_path):
    """Only superseded copies of this checkpoint are pruning candidates."""
    path = tmp_path / "dqn_model_math.pth"
    sibling = tmp_path / "dqn_model_math_other.pth"
    unrelated = tmp_path / "dqn_model_math.json"
    sibling.write_bytes(b"keep me")
    unrelated.write_text("{}")

    a = agent(path)
    for i in range(5):
        a.epsilon = i / 10
        a.save(path, keep=2)

    assert sibling.exists(), "a similarly-named file was pruned"
    assert unrelated.exists(), "an unrelated file was pruned"


def test_save_load_round_trip_preserves_training_state(tmp_path):
    path = tmp_path / "dqn.pth"
    a = agent(path)
    a.epsilon = 0.125
    a.steps = 41
    a.save(path, keep=0)

    b = agent(path)
    b.epsilon, b.steps = 1.0, 0
    b.load(path)
    assert b.epsilon == pytest.approx(0.125)
    assert b.steps == 41
    for (ka, va), (kb, vb) in zip(a.q_net.state_dict().items(), b.q_net.state_dict().items()):
        assert ka == kb
        assert torch.equal(va.cpu(), vb.cpu())


# --------------------------------------------------------------------------
# A completed CSV must not be appended to, because it stops being analysable
# --------------------------------------------------------------------------


def test_two_runs_in_one_file_break_the_paired_analysis():
    """The constraint that rules out naive append.

    `_paired_test` pivots prompt_id against system_id. Two runs of the same
    dataset in one file repeat every key, so the pivot raises. Appending is
    therefore only safe *within* a run; across runs it converts a readable
    result into a crash at analysis time.
    """
    rows = []
    for i in range(3):
        for system, value in (("A", 0.60), ("B", 0.70)):
            rows.append({"prompt_id": f"q{i}", "system_id": system, "faithfulness": value})

    single = pd.DataFrame(rows)
    _paired_test(single, "faithfulness")  # fine: one complete run

    doubled = pd.DataFrame(rows + rows)
    with pytest.raises(ValueError, match="duplicate entries"):
        _paired_test(doubled, "faithfulness")


def test_staging_keeps_previous_results_intact_until_the_run_succeeds(tmp_path):
    """The property the drivers rely on.

    A crashed run must cost only its own hours, not the previous run's as well -
    which is the actual failure that produced the 78-byte math CSV.
    """
    final = tmp_path / "results.csv"
    ResultLogger(final).log(**sample("previous", 0.9))

    staged = final.with_name(final.name + ".partial")
    run = ResultLogger(staged)
    run.log(**sample("new-1", 0.5))

    # Mid-run: previous results still readable, this run's work already durable.
    assert {r["prompt_id"] for r in read_rows(final)} == {"previous"}
    assert {r["prompt_id"] for r in read_rows(staged)} == {"new-1"}

    promote(staged, final)

    rows = read_rows(final)
    assert {r["prompt_id"] for r in rows} == {"new-1"}
    assert not staged.exists()


def test_a_crashed_run_never_publishes_a_partial_file(tmp_path):
    """Promotion is the only thing that publishes, so failing before it is safe."""
    final = tmp_path / "results.csv"
    ResultLogger(final).log(**sample("previous", 0.9))

    staged = final.with_name(final.name + ".partial")
    try:
        run = ResultLogger(staged)
        run.log(**sample("new-1", 0.5))
        run.log(**sample("new-2", 0.6))
        raise RuntimeError("host killed mid-run")
    except RuntimeError:
        pass

    # Nothing was promoted, so the committed file is still the last good run.
    assert {r["prompt_id"] for r in read_rows(final)} == {"previous"}
    # And the aborted run is recoverable rather than gone.
    assert len(read_rows(staged)) == 2


def test_promoted_output_is_analysable(tmp_path):
    """End-to-end: promoting a finished run yields a file the analysis accepts."""
    final = tmp_path / "results.csv"
    staged = final.with_name(final.name + ".partial")
    run = ResultLogger(staged)
    for i in range(6):
        run.log(**sample(f"q{i}", 0.60, system_id="A"))
        run.log(**sample(f"q{i}", 0.70, system_id="B"))
    promote(staged, final)

    frame = pd.read_csv(final)
    result = _paired_test(frame, "faithfulness")

    assert len(frame) == 12
    assert result["mean_difference"] == pytest.approx(0.10)
    assert result["p_one_tailed"] < 0.05


# --------------------------------------------------------------------------
# The judge has to be asked not to think
# --------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def judge_scorer():
    from src.ragas_eval import RagasScorer

    return RagasScorer(judge_model="qwen3:8b", max_retries=0)


def test_judge_request_disables_thinking(monkeypatch):
    """The defect, pinned at the request boundary.

    A reasoning judge bills its scratchpad against `num_predict`, so the JSON
    never completes: 279 tokens of reasoning produced the literal text "{\\n\\n}"
    and cost 21s where 41 tokens and 5s produced correct verdicts. Faithfulness
    and context recall were silently empty for every prompt of every run.
    """
    sent = {}

    def fake_post(url, json=None, timeout=None):
        sent.update(json)
        return FakeResponse({"response": '{"verdicts": []}', "eval_count": 5,
                             "prompt_eval_count": 10})

    monkeypatch.setattr("src.ragas_eval.requests.post", fake_post)
    judge_scorer()._complete("Return JSON.", max_tokens=400)

    assert sent.get("think") is False, "judge was allowed to spend the token budget on reasoning"


def test_thinking_flag_is_dropped_if_the_server_rejects_it(monkeypatch):
    """A model or Ollama build without the field must not break the judge."""
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(dict(json))
        if "think" in json:
            return FakeResponse({}, status_code=400)
        return FakeResponse({"response": '{"verdicts": []}', "eval_count": 5,
                             "prompt_eval_count": 10})

    monkeypatch.setattr("src.ragas_eval.requests.post", fake_post)
    scorer = judge_scorer()
    scorer._complete("Return JSON.", max_tokens=400)

    assert calls[0].get("think") is False
    # Second call must not re-send a field the server already refused.
    scorer._complete("Return JSON.", max_tokens=400)
    assert "think" not in calls[-1]


def test_every_judge_call_carries_thinking_disabled(monkeypatch):
    """Guards the whole metric set, not just one code path."""
    seen = []

    def fake_post(url, json=None, timeout=None):
        seen.append(json.get("think", "ABSENT"))
        return FakeResponse({"response": '{"statements": ["a"], "verdicts": [{"statement": "a", "verdict": 1}], "questions": ["q?"]}'})

    monkeypatch.setattr("src.ragas_eval.requests.post", fake_post)
    scorer = judge_scorer()

    # Answer relevancy embeds the question and the generated ones through
    # langchain_ollama, which opens its own connection to Ollama and is not
    # covered by the mock above. Left real, it silently dialled localhost:11434
    # and leaked the socket, which pytest reports as an unraisable exception
    # against whichever test happens to run next - a failure that looks like it
    # belongs to an unrelated file.
    class FakeEmbeddings:
        def embed_query(self, text):
            return [1.0, 0.0, 0.0]

        def embed_documents(self, texts):
            return [[1.0, 0.0, 0.0] for _ in texts]

    scorer._embeddings = FakeEmbeddings()
    scorer.score_single(
        "What is the capital?",
        "Paris is the capital of France.",
        ["Paris is the capital of France."],
        reference="Paris.",
    )

    assert seen, "no judge calls were made"
    assert all(flag is False for flag in seen), f"thinking enabled on some calls: {seen}"


# --------------------------------------------------------------------------
# The one-tailed p-value has to point at the direction it names
# --------------------------------------------------------------------------


def frame(a_vals, b_vals):
    """A results frame shaped like the committed CSVs, two rows per prompt."""
    rows = []
    for i, (a, b) in enumerate(zip(a_vals, b_vals)):
        rows.append({"prompt_id": f"q{i}", "system_id": "A",
                     "faithfulness": a, "answer_relevancy": a, "context_recall": a})
        rows.append({"prompt_id": f"q{i}", "system_id": "B",
                     "faithfulness": b, "answer_relevancy": b, "context_recall": b})
    return pd.DataFrame(rows)


@pytest.fixture
def b_better():
    """System B clearly higher on every prompt, with realistic spread."""
    a = [0.60, 0.62, 0.64, 0.61, 0.63, 0.65, 0.62, 0.60, 0.64, 0.63,
         0.61, 0.62, 0.64, 0.63, 0.62, 0.61, 0.63, 0.65, 0.64, 0.62]
    b = [v + 0.09 for v in a]
    return a, b


@pytest.fixture
def b_worse():
    """System B clearly lower - the mirror image, and the case the bug inverted."""
    a = [0.60, 0.62, 0.64, 0.61, 0.63, 0.65, 0.62, 0.60, 0.64, 0.63,
         0.61, 0.62, 0.64, 0.63, 0.62, 0.61, 0.63, 0.65, 0.64, 0.62]
    b = [v - 0.09 for v in a]
    return a, b


def test_b_better_gives_a_small_one_tailed_p(b_better):
    """p(B > A) must be small when B is better. This is the whole contract."""
    a, b = b_better
    r = _paired_test(frame(a, b), "faithfulness")

    assert r["mean_difference"] > 0
    assert r["p_one_tailed"] == pytest.approx(r["p_two_tailed"] / 2)
    assert r["p_one_tailed"] < 0.05, "a clear improvement did not reach significance"


def test_b_worse_does_not_get_a_small_one_tailed_p(b_worse):
    """The defect, stated as a test.

    `stats.ttest_rel(a, b)` reports t for the contrast a-minus-b, so `t > 0`
    while B is worse. Keying the tail off `t` therefore handed back the p-value
    for "B is worse" under a label reading "B > A" - a large p-value dressed up
    as evidence of improvement, and a genuinely negative result rendered as a
    positive trend.
    """
    a, b = b_worse
    r = _paired_test(frame(a, b), "faithfulness")

    assert r["mean_difference"] < 0, "fixture is wrong: B should be worse here"
    assert r["p_one_tailed"] > 0.5, (
        "B scored worse on every prompt, yet the one-tailed p-value reports "
        "evidence that B is better"
    )
    assert r["p_one_tailed"] == pytest.approx(1 - r["p_two_tailed"] / 2)


def test_the_two_directions_are_mirror_images(b_better, b_worse):
    """Sanity check on the sign convention itself.

    Swapping A and B must map p(B>A) to 1 - p(B>A) of the original. A one-tailed
    test that fails this is reporting the tail it happened to be handed rather
    than the one it claims.
    """
    _, b_better_vals = b_better
    _, b_worse_vals = b_worse

    forward = _paired_test(frame(b_worse_vals, b_better_vals), "faithfulness")
    reverse = _paired_test(frame(b_better_vals, b_worse_vals), "faithfulness")

    assert forward["p_one_tailed"] == pytest.approx(1 - reverse["p_one_tailed"], abs=1e-9)


def test_significance_flag_follows_the_one_tailed_value(b_worse):
    """`sig_one_tailed` and `p_one_tailed` must not disagree.

    They are separate fields, so a fix to one that forgot the other would leave
    the report calling a significant result non-significant.
    """
    a, b = b_worse
    r = _paired_test(frame(a, b), "faithfulness")

    assert r["sig_one_tailed"] == (r["p_one_tailed"] < 0.05)
    assert r["sig_one_tailed"] is False