"""A trial run must not be able to overwrite the thesis checkpoints.

`run_experiment*.py` trains and rewrites `dqn_model_<dataset>.pth` in place as it
scores, because the reward is the DQN's next training signal. The checkpoints
under `checkpoints/` are committed evidence for every number in the report, with
recorded hashes, so a smoke test pointed at the real directory silently replaces
one of them - which is exactly what happened here: a two-prompt hotpot smoke test
overwrote `dqn_model_hotpot.pth` and left two rotated copies behind.

Recoverable only because git tracks them. `BENCH_CHECKPOINTS_DIR` is the fix, and
these tests exist so it keeps working and keeps defaulting to the thesis path.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

import config.settings as settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_settings_with(env: dict[str, str] | None):
    """Import `config.settings` with a patched environment, in a subprocess.

    Module-level `os.makedirs` and path constants mean the value is fixed at
    import time, so it cannot be re-read by patching an attribute afterwards.
    """
    code = (
        "import config.settings as s;"
        "print(s.CHECKPOINTS_DIR);"
        "print(s.DATASET_CHECKPOINT_PATH['hotpot'])"
    )
    environ = {**os.environ, **(env or {})}
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env=environ,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = out.stdout.strip().splitlines()
    return Path(lines[0]), Path(lines[1])


class TestCheckpointIsolation:
    def test_defaults_to_the_thesis_checkpoint_directory(self):
        resolved, hotpot = _load_settings_with({})

        assert resolved == (PROJECT_ROOT / "checkpoints").resolve()
        assert hotpot.name == "dqn_model_hotpot.pth"
        assert hotpot.parent == resolved

    def test_env_override_redirects_every_dataset_checkpoint(self, tmp_path):
        resolved, hotpot = _load_settings_with(
            {"BENCH_CHECKPOINTS_DIR": str(tmp_path / "trial")}
        )

        assert resolved == (tmp_path / "trial").resolve()
        assert hotpot.parent == resolved
        assert hotpot == (tmp_path / "trial" / "dqn_model_hotpot.pth").resolve()

    def test_override_creates_the_directory(self, tmp_path):
        target = tmp_path / "made-on-demand"
        _load_settings_with({"BENCH_CHECKPOINTS_DIR": str(target)})

        assert target.is_dir(), "an override pointing somewhere new must not crash the run"

    def test_every_dataset_is_redirected_not_just_hotpot(self, tmp_path):
        code = (
            "import config.settings as s;"
            "print(';'.join(sorted(str(p) for p in s.DATASET_CHECKPOINT_PATH.values())))"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_ROOT,
            env={**os.environ, "BENCH_CHECKPOINTS_DIR": str(tmp_path / "trial")},
            capture_output=True,
            text=True,
            check=True,
        )
        paths = [Path(p) for p in out.stdout.strip().split(";")]

        assert paths, "expected a checkpoint path per dataset"
        assert all(p.parent == (tmp_path / "trial").resolve() for p in paths), (
            f"a dataset checkpoint escaped the override: {paths}"
        )

    def test_override_is_documented_where_a_runner_would_be_invoked(self):
        readme = (PROJECT_ROOT / "README.md")
        if not readme.exists():
            pytest.skip("no root README.md to document the escape hatch in")
        assert "BENCH_CHECKPOINTS_DIR" in readme.read_text(encoding="utf-8")


class TestSettingsAreImportable:
    def test_settings_module_imports(self):
        importlib.reload(settings)
        assert settings.VALID_DATASETS