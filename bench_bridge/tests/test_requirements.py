"""`requirements.txt` must match what the code actually imports.

The file drifted for most of the project's life: it declared six packages
nothing imported, and omitted two that everything depends on, so a clean
install could not run the code. Neither mistake announces itself - the suite
passes against whatever happens to be installed.

Checked in both directions, because both failure modes are real:

  * an import with no declaration - a fresh clone cannot run;
  * a declaration with no import - dead weight that can break an install on its
    own (ragas did exactly that).
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / "requirements.txt"

# Import name -> distribution name, where they differ.
DISTRIBUTION_NAMES = {
    "langchain_ollama": "langchain-ollama",
    "langchain_core": "langchain-core",
    "yaml": "pyyaml",
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "attr": "attrs",
    "bs4": "beautifulsoup4",
    "serial": "pyserial",
}


def _first_party() -> set[str]:
    """Modules that live in this repo rather than coming from a distribution.

    Root-level scripts are importable by name (`from probe_metrics import ...`,
    `from run_experiment_logged import ...`) and local directories are packages,
    so neither should be reported as a missing dependency.
    """
    local = {path.stem for path in ROOT.glob("*.py")}
    for path in ROOT.iterdir():
        if path.is_dir() and (path / "__init__.py").exists():
            local.add(path.name)
    return local - {".git"}


def _python_files() -> list[Path]:
    """Python sources belonging to the repository.

    Scoped to tracked files where git is available, so a script someone happens
    to have lying in the working tree does not dictate the dependency list. The
    full scan is the fallback, which is stricter rather than laxer.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "*.py"],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout.splitlines()
        paths = [ROOT / rel for rel in out if rel.strip()]
        if paths:
            return paths
    except (OSError, subprocess.SubprocessError):
        pass
    return [
        p for p in ROOT.rglob("*.py")
        if not set(p.parts) & {".venv", "node_modules", "target", ".git", "gen"}
    ]


def _declared() -> set[str]:
    """Distributions named in requirements.txt, ignoring comments/options."""
    names: set[str] = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        # Strip extras and any version specifier.
        name = re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0]
        if name:
            names.add(name.lower().replace("_", "-"))
    return names


def _third_party_imports() -> set[str]:
    """Top-level modules imported anywhere in the tracked Python sources."""
    found: set[str] = set()
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import, always local
                    continue
                if node.module:
                    found.add(node.module.split(".")[0])
    return found - set(sys.stdlib_module_names) - _first_party()


@pytest.fixture(scope="module")
def declared() -> set[str]:
    return _declared()


@pytest.fixture(scope="module")
def imported() -> set[str]:
    return _third_party_imports()


def test_requirements_file_exists(declared):
    assert declared, "requirements.txt declared no distributions"


def test_every_import_is_declared(imported, declared):
    missing = set()
    for module in imported:
        dist = DISTRIBUTION_NAMES.get(module, module).lower().replace("_", "-")
        if dist not in declared:
            missing.add(f"{module} (distribution {dist})")
    assert not missing, (
        "imported but not declared in requirements.txt: " + ", ".join(sorted(missing))
    )


def test_nothing_is_declared_that_is_unused(declared, imported):
    unused = set()
    for dist in declared:
        # A distribution matches if any of its import names is imported.
        candidates = {dist.replace("-", "_")}
        candidates |= {
            module for module, d in DISTRIBUTION_NAMES.items()
            if d.lower().replace("_", "-") == dist
        }
        if not candidates & imported:
            unused.add(dist)
    assert not unused, (
        "declared in requirements.txt but imported nowhere: " + ", ".join(sorted(unused))
    )


def test_known_bad_dependencies_are_gone(declared):
    """Regression on the specific packages that broke the install.

    `ragas` in particular raised ImportError for
    langchain_community.chat_models.vertexai on import, from a clean
    environment, taking every test with it.
    """
    assert "ragas" not in declared
    assert "langchain" not in declared
    assert "langchain-community" not in declared


def test_ollama_client_is_reachable_through_langchain_ollama(declared, imported):
    """`ollama` is not imported directly but must still be installed."""
    assert "langchain-ollama" in declared
    assert "ollama" in imported or "langchain_ollama" in imported