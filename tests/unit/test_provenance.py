"""Source provenance: what changes the fingerprint, what does not, and that it is deterministic."""
import ast
import shutil
import subprocess
from pathlib import Path

import pytest

from src.research import provenance
from src.research.provenance import REPO_ROOT, source_files, source_fingerprint, source_revision
from src.research.showcase import METHODOLOGY_DOCUMENT, METHODOLOGY_VERSION

SCOPE = ("scripts/generate.py", "src/pkg/**/*.py")
SOURCE = {
    "scripts/generate.py": "from src.pkg import model\n",
    "src/pkg/__init__.py": "",
    "src/pkg/model.py": "RATE = 0.05\n",
    "src/pkg/sub/helpers.py": "def f():\n    return 1\n",
}
ARTIFACTS = {  # what a report run writes, plus caches and temporary files
    "docs/assets/tearsheet-dark.png": b"\x89PNG\r\n\x1a\n\x00\x00",
    "docs/reports/showcase.md": "# Showcase report\n",
    "docs/reports/showcase/manifest.json": '{"provenance": {}}\n',
    "docs/reports/showcase/engineering.json": '{"median_seconds": 1.23}\n',
    "README.md": "<!-- showcase:metrics:start -->\n",
    "src/pkg/__pycache__/model.cpython-311.pyc": b"\x00\x01",
    "data/demo/prices.csv": "date,symbol,close\n",
    "build/tmp/scratch.txt": "temporary\n",
}


def write(root: Path, files: dict) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return root


def fingerprint(root: Path) -> str:
    return source_fingerprint(root, SCOPE)[0]


def test_scope_selects_source_files_only(tmp_path):
    write(tmp_path, {**SOURCE, **ARTIFACTS})

    assert source_files(tmp_path, SCOPE) == sorted(SOURCE)


def test_changing_relevant_source_changes_the_fingerprint(tmp_path):
    write(tmp_path, SOURCE)
    original = fingerprint(tmp_path)
    write(tmp_path, {"src/pkg/sub/helpers.py": "def f():\n    return 2\n"})
    edited = fingerprint(tmp_path)
    write(tmp_path, {"src/pkg/new_module.py": "X = 1\n"})
    added = fingerprint(tmp_path)

    assert len({original, edited, added}) == 3


def test_regenerating_artifacts_alone_does_not_change_the_fingerprint(tmp_path):
    write(tmp_path, SOURCE)
    before = fingerprint(tmp_path)
    write(tmp_path, ARTIFACTS)
    first_run = fingerprint(tmp_path)
    write(tmp_path, {name: (b"other bytes" if isinstance(content, bytes) else content + "rerun\n")
                     for name, content in ARTIFACTS.items()})
    second_run = fingerprint(tmp_path)

    assert before == first_run == second_run


def test_line_endings_and_byte_order_mark_do_not_change_the_fingerprint(tmp_path):
    lf = write(tmp_path / "lf", SOURCE)
    crlf = write(tmp_path / "crlf", {name: text.replace("\n", "\r\n") for name, text in SOURCE.items()})
    bom = write(tmp_path / "bom", {name: "﻿" + text.replace("\n", "\r\n") for name, text in SOURCE.items()})

    assert fingerprint(lf) == fingerprint(crlf) == fingerprint(bom)


def test_identical_source_and_inputs_give_identical_provenance(tmp_path):
    first = write(tmp_path / "checkout-a", SOURCE)
    second = write(tmp_path / "checkout-b", SOURCE)
    assert source_fingerprint(first, SCOPE) == source_fingerprint(second, SCOPE)  # location does not matter

    inputs = {"dataset": "fixture", "files": {"prices.csv": "0" * 64}}
    versions = {"strategy": "tsmom-1.0", "methodology": METHODOLOGY_VERSION}
    assert provenance.collect(inputs, versions) == provenance.collect(inputs, versions)


def test_repository_scope_excludes_generated_outputs():
    files = source_files()

    assert {"scripts/generate_readme_assets.py", "src/research/provenance.py", "src/backtesting/engine.py"} <= set(files)
    assert all(name.endswith(".py") for name in files)
    assert not [name for name in files if name.startswith(("docs/", "data/", "tests/")) or name == "README.md"]


def _src_imports(path: Path):
    """Every module name an import statement in path could load, function-level imports included."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


def _module_file(name: str):
    base = REPO_ROOT.joinpath(*name.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate.relative_to(REPO_ROOT).as_posix()
    return None


def test_scope_covers_every_module_the_generator_imports():
    pending, seen = ["scripts/generate_readme_assets.py"], set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for name in _src_imports(REPO_ROOT / current):
            parts = name.split(".")
            if parts[0] != "src":
                continue
            for depth in range(2, len(parts) + 1):  # importing src.a.b also runs src/a/__init__.py
                path = _module_file(".".join(parts[:depth]))
                if path:
                    pending.append(path)

    assert len(seen) > 20  # the walk reached the engine, services, research and reporting code
    assert sorted(seen - set(source_files())) == []


def test_methodology_documents_the_scope_and_version():
    text = (REPO_ROOT / METHODOLOGY_DOCUMENT).read_text(encoding="utf-8")

    assert [p for p in provenance.SOURCE_SCOPE + provenance.DEPENDENCY_SPECS if f"`{p}`" not in text] == []
    assert f"Methodology version {METHODOLOGY_VERSION}" in text


def git(repo: Path, *args: str) -> str:
    hooks = repo.parent / "no-hooks"  # isolate the throwaway repository from any configured hooks
    hooks.mkdir(exist_ok=True)
    command = ["git", "-c", "user.name=Provenance Test", "-c", "user.email=provenance@test.invalid",
               "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={hooks}", *args]
    return subprocess.run(command, cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_source_commit_is_the_last_commit_that_changed_the_scope(tmp_path):
    repo = write(tmp_path / "repo", SOURCE)
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "source")
    source_commit = git(repo, "rev-parse", "HEAD")
    clean = {"commit": source_commit, "clean": True, "uncommitted_files": []}
    assert source_revision(repo, SCOPE) == clean

    write(repo, ARTIFACTS)  # regenerated outputs committed on top leave the source commit alone
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "artifacts")
    assert git(repo, "rev-parse", "HEAD") != source_commit
    assert source_revision(repo, SCOPE) == clean

    write(repo, {"src/pkg/model.py": "RATE = 0.06\n", "src/pkg/draft.py": "Y = 2\n"})
    assert source_revision(repo, SCOPE) == {"commit": source_commit, "clean": False,
                                            "uncommitted_files": ["src/pkg/draft.py", "src/pkg/model.py"]}


def test_without_git_the_fingerprint_still_identifies_the_source(tmp_path, monkeypatch):
    write(tmp_path, SOURCE)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))  # not inside any repository

    assert source_revision(tmp_path, SCOPE) == {"commit": None, "clean": None, "uncommitted_files": []}
    assert len(fingerprint(tmp_path)) == 64
