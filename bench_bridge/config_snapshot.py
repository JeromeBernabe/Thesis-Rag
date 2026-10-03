"""Snapshot of the experiment configuration a run was executed with.

Two jobs:

1. **Provenance.** Nothing in the repo records which hyperparameters produced a
   given CSV, so a run is only reproducible if its configuration is captured
   alongside it. The snapshot is stored verbatim in ``runs.config_json``.
2. **Regression guard.** :func:`assert_matches_settings` compares the snapshot's
   defaults against the live ``config/settings.py``. If someone retunes
   ``REWARD_W_FAITHFULNESS`` or ``BASELINE_K``, this fails loudly instead of
   silently producing a new run that is no longer comparable to the committed
   thesis results.

Only JSON-native scalars are captured. Anything non-serialisable (torch device
objects, Paths) is stringified, because a config blob that cannot be written to
the database is worse than a slightly lossy one.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

__all__ = [
    "RunConfig",
    "CONFIG_SCHEMA_VERSION",
    "capture_settings_snapshot",
    "assert_matches_settings",
]


#: Bumped when the set of captured keys changes.
CONFIG_SCHEMA_VERSION = 1

#: Settings whose values directly determine what a run produces. Changing any of
#: these makes new results incomparable to the committed ones, which is why they
#: are pinned by ``test_config.py``.
PINNED = {
    "BASELINE_K": 3,
    "ACTION_MIN_K": 1,
    "ACTION_MAX_K": 5,
    "NUM_ACTIONS": 5,
    "DQN_GAMMA": 0.99,
    "DQN_EPSILON_INIT": 1.0,
    "DQN_EPSILON_MIN": 0.05,
    "DQN_EPSILON_DECAY": 0.995,
    "DQN_BUFFER_SIZE": 5000,
    "DQN_BATCH_SIZE": 8,
    "DQN_LR": 0.001,
    "DQN_TARGET_REFRESH": 50,
    "DQN_HIDDEN_1": 128,
    "DQN_HIDDEN_2": 64,
    "REWARD_W_FAITHFULNESS": 0.35,
    "REWARD_W_RELEVANCY": 0.35,
    "REWARD_W_K": 0.0,
    "EMBED_MODEL": "nomic-embed-text",
    "EMBEDDING_DIM": 768,
    "GENERATOR_MODEL": "llama3.2",
    "JUDGE_MODEL": "qwen3:8b",
    "GENERATION_TEMPERATURE": 0.1,
    "GENERATION_MAX_TOKENS": 1024,
    "NUM_EVAL_PROMPTS": 50,
    "PROMPT_BUILD_SEED": 42,
    "RAGAS_MAX_WORKERS": 1,
    "MAX_CORPUS_DOCS": 30000,
}


@dataclass
class RunConfig:
    """Everything needed to interpret (and later re-run) a single run."""

    schema_version: int = CONFIG_SCHEMA_VERSION
    dataset: str = "hotpot"
    systems: list[str] = field(default_factory=lambda: ["A", "B"])
    limit: int | None = 50
    seed: int = 42
    reset_store: bool = False
    no_judge: bool = False
    fast: bool = False
    settings: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _jsonable(value: Any) -> Any:
    """Coerce a settings value into something ``json.dumps`` accepts."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def capture_settings_snapshot(settings_module=None) -> dict[str, Any]:
    """Read the live experiment settings into a JSON-safe dict."""
    if settings_module is None:
        from config import settings as settings_module  # imported lazily: slow

    keys = [
        "BASELINE_K",
        "ACTION_MIN_K",
        "ACTION_MAX_K",
        "NUM_ACTIONS",
        "DQN_GAMMA",
        "DQN_EPSILON_INIT",
        "DQN_EPSILON_MIN",
        "DQN_EPSILON_DECAY",
        "DQN_BUFFER_SIZE",
        "DQN_BATCH_SIZE",
        "DQN_LR",
        "DQN_TARGET_REFRESH",
        "DQN_HIDDEN_1",
        "DQN_HIDDEN_2",
        "REWARD_W_FAITHFULNESS",
        "REWARD_W_RELEVANCY",
        "REWARD_W_K",
        "EMBED_MODEL",
        "EMBEDDING_DIM",
        "GENERATOR_MODEL",
        "JUDGE_MODEL",
        "GENERATION_TEMPERATURE",
        "GENERATION_MAX_TOKENS",
        "NUM_EVAL_PROMPTS",
        "PROMPT_BUILD_SEED",
        "RAGAS_MAX_WORKERS",
        "MAX_CORPUS_DOCS",
        "OLLAMA_BASE_URL",
    ]

    snapshot: dict[str, Any] = {}
    for key in keys:
        snapshot[key] = _jsonable(getattr(settings_module, key, None))

    snapshot["REWARD_W_CONTEXT_RECALL"] = 0.30  # hardcoded in src/reward.py:14
    return snapshot


def git_sha(project_root=None) -> str | None:
    """Best-effort current git SHA; ``None`` outside a repo or if git is absent."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root) if project_root else None,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = proc.stdout.strip()
    return sha or None


def environment_snapshot() -> dict[str, Any]:
    """Non-secret runtime facts worth recording next to a run."""
    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "git_sha": git_sha(),
    }


class ConfigDrift(RuntimeError):
    """Raised when a captured setting no longer matches the pinned value."""


def assert_matches_settings(
    snapshot: dict[str, Any], settings_module=None
) -> list[str]:
    """Compare a snapshot against :data:`PINNED`.

    Returns the list of drifted keys; raises :class:`ConfigDrift` if any differ.
    Run by the test suite rather than at runtime - a drift should block a
    release, not stop a long experiment mid-flight.
    """
    drifted = []
    for key, expected in PINNED.items():
        actual = snapshot.get(key)
        if isinstance(expected, float) and isinstance(actual, (int, float)):
            same = abs(float(actual) - expected) < 1e-12
        else:
            same = actual == expected
        if not same:
            drifted.append(f"{key}: expected {expected!r}, snapshot has {actual!r}")

    if drifted:
        raise ConfigDrift(
            "captured settings drifted from the pinned experiment protocol:\n  "
            + "\n  ".join(drifted)
        )
    return drifted