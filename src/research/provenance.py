"""Provenance of generated reports: the source code, dependencies and inputs behind them.

Every fingerprint is the SHA-256 of a file after text normalization (normalize_text): a
UTF-8 byte-order mark is removed and CRLF and CR line endings become LF. A Windows checkout
(core.autocrlf=true) and a Linux checkout of the same commit therefore give the same values.

Source fingerprint
    Covers the files matched by SOURCE_SCOPE: the README asset generator and every package it
    runs (backtest engine, the live services timed by the latency benchmarks, research,
    analytics and reporting). tests/unit/test_provenance.py checks that every src module the
    generator imports, directly or not, is in scope. The fingerprint is the SHA-256 of the
    sorted lines "<path>NUL<file sha256>LF" over repository-relative POSIX paths, so it depends
    on file names and contents only: not on timestamps, the checkout location or Git.

    Nothing the generator writes is in scope: figures and reports (docs/), the run manifest,
    README.md (it contains generated blocks), datasets (fingerprinted separately, as inputs),
    runtime measurements, caches (__pycache__) and temporary files. Regenerating artifacts
    leaves the fingerprint unchanged, and no recorded hash covers a file that records it.

Source commit
    The most recent commit that changed a file in scope (git log -1 -- <scope>), and whether
    the files in scope match it exactly. It is deliberately not HEAD: committing regenerated
    artifacts on top does not change it, so identical source and inputs give identical
    provenance. If files in scope have uncommitted changes they are listed, and the
    fingerprint, not the commit, identifies the code.
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

SOURCE_SCOPE: Tuple[str, ...] = (
    "scripts/generate_readme_assets.py",
    "src/analytics/**/*.py",
    "src/backtesting/**/*.py",
    "src/core/**/*.py",
    "src/reporting/**/*.py",
    "src/research/**/*.py",
    "src/services/**/*.py",
)
# The generator's dependency specifications; requirements_dev.txt only adds Django and test
# tools on top of these.
DEPENDENCY_SPECS: Tuple[str, ...] = ("pyproject.toml", "requirements_engine.txt", "requirements_reports.txt")
# Installed distributions whose versions can change computed results or rendered figures.
DISTRIBUTIONS: Tuple[str, ...] = ("numpy", "pandas", "scipy", "matplotlib", "pillow", "contourpy", "kiwisolver",
                                  "fonttools")
NORMALIZATION = ("SHA-256 of the file contents after removing a UTF-8 byte-order mark and converting CRLF and CR "
                 "line endings to LF")


def normalize_text(data: bytes) -> bytes:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def normalized_sha256(path: Path) -> str:
    return hashlib.sha256(normalize_text(Path(path).read_bytes())).hexdigest()


def file_fingerprints(root: Path, names: Iterable[str]) -> Dict[str, Optional[str]]:
    """normalized_sha256 of each named file under root; None for a missing file."""
    root = Path(root)
    return {name: normalized_sha256(root / name) if (root / name).is_file() else None for name in names}


def source_files(root: Path = REPO_ROOT, scope: Sequence[str] = SOURCE_SCOPE) -> List[str]:
    """Repository-relative POSIX paths of the files in scope, sorted."""
    root = Path(root)
    found = set()
    for pattern in scope:
        for path in root.glob(pattern):
            relative = path.relative_to(root)
            if path.is_file() and "__pycache__" not in relative.parts:
                found.add(relative.as_posix())
    return sorted(found)


def source_fingerprint(root: Path = REPO_ROOT, scope: Sequence[str] = SOURCE_SCOPE) -> Tuple[str, Dict[str, str]]:
    """(fingerprint, {path: sha256}) for the files in scope."""
    root = Path(root)
    files = {name: normalized_sha256(root / name) for name in source_files(root, scope)}
    listing = "".join(f"{name}\0{digest}\n" for name, digest in files.items())
    return hashlib.sha256(listing.encode("utf-8")).hexdigest(), files


def _git(root: Path, *args: str) -> Optional[str]:
    try:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, encoding="utf-8", errors="replace",
                              check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return done.stdout


def _status_paths(porcelain: str) -> List[str]:
    """Paths in `git status --porcelain=v1 -z` output; a rename or copy lists its new path."""
    entries = porcelain.split("\0")
    paths, i = set(), 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.add(entry[3:])
        if "R" in entry[:2] or "C" in entry[:2]:
            i += 1  # the original path follows as its own entry
    return sorted(paths)


def source_revision(root: Path = REPO_ROOT, scope: Sequence[str] = SOURCE_SCOPE) -> Dict:
    """The last commit that changed a file in scope and whether the files in scope match it.

    Without Git (or outside a repository) every field is None or empty; the fingerprint still
    identifies the code.
    """
    pathspecs = [f":(glob){pattern}" for pattern in scope]
    log = _git(Path(root), "log", "-1", "--format=%H", "--", *pathspecs)
    status = _git(Path(root), "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *pathspecs)
    if log is None or status is None:
        return {"commit": None, "clean": None, "uncommitted_files": []}
    commit = log.strip() or None
    changed = _status_paths(status)
    return {"commit": commit, "clean": commit is not None and not changed, "uncommitted_files": changed}


def installed_versions(distributions: Iterable[str] = DISTRIBUTIONS) -> Dict[str, str]:
    versions = {"python": f"{platform.python_implementation()} {platform.python_version()}"}
    for name in distributions:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not installed"
    try:
        from matplotlib import ft2font
        versions["freetype (bundled with matplotlib)"] = ft2font.__freetype_version__
    except ImportError:
        pass
    return versions


def collect(inputs: Dict, versions: Dict, root: Path = REPO_ROOT) -> Dict:
    """The provenance block of a report manifest.

    inputs: fingerprints of the data the run read; versions: strategy and methodology versions.
    """
    fingerprint, files = source_fingerprint(root)
    return {
        "normalization": NORMALIZATION,
        "source": {"fingerprint": fingerprint, **source_revision(root), "scope": list(SOURCE_SCOPE),
                   "files": files},
        "dependencies": {"specifications": file_fingerprints(root, DEPENDENCY_SPECS),
                         "installed": installed_versions()},
        "inputs": inputs,
        "versions": versions,
    }
