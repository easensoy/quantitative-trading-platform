#!/usr/bin/env python
"""Regenerate the README figures and the showcase report from source data.

    python scripts/generate_readme_assets.py                     # everything, about 2 minutes
    python scripts/generate_readme_assets.py --reuse-engineering # keep the stored benchmark results
    python scripts/generate_readme_assets.py --dataset DIR --assets-dir build/report/assets --reports-dir build/report

Outputs have stable names, so a rerun on unchanged inputs rewrites the same files:
    docs/assets/<figure>-dark.png and <figure>-light.png
    docs/reports/showcase.md and docs/reports/showcase/ (manifest.json, CSV tables, engineering.json)
    generated blocks in README.md (only for the default synthetic dataset): every number in the
    README's prose and tables comes from these blocks

The run stops with exit code 1 if a consistency check fails (see docs/methodology.md).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.reporting.theme import THEMES, themed, save_figure  # noqa: E402  (sets the headless backend)
from src.reporting import documents  # noqa: E402
from src.reporting.figures import FIGURES  # noqa: E402
from src.research.datasets import generate_synthetic_universe, load_dataset, write_dataset  # noqa: E402
from src.research.showcase import ShowcaseConfig, attach_engineering, build_showcase  # noqa: E402

DEFAULT_DATASET = ROOT / "data" / "demo" / "synthetic_universe_v1"


def href(target: Path, start: Path, directory: bool = False) -> str:
    """Relative link from a Markdown file in start to target; empty if there is none (another drive)."""
    try:
        link = os.path.relpath(target, start).replace(os.sep, "/")
    except ValueError:
        return ""
    return link + "/" if directory else link


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET,
                        help="dataset directory: prices.csv (+ instruments.csv, manifest.json); see docs/methodology.md")
    parser.add_argument("--regenerate-dataset", action="store_true",
                        help="rebuild the synthetic demo dataset from its specification before running")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1),
                        help="worker processes for the parameter sweep and walk-forward (results do not depend on it)")
    engineering = parser.add_mutually_exclusive_group()
    engineering.add_argument("--reuse-engineering", action="store_true",
                             help="reuse docs/reports/showcase/engineering.json instead of re-measuring")
    engineering.add_argument("--skip-engineering", action="store_true", help="omit the engineering figure")
    parser.add_argument("--themes", default="dark,light", help="comma-separated: dark,light")
    parser.add_argument("--only", default="", help="comma-separated figure names to render")
    parser.add_argument("--assets-dir", type=Path, default=ROOT / "docs" / "assets")
    parser.add_argument("--reports-dir", type=Path, default=ROOT / "docs" / "reports")
    parser.add_argument("--no-readme", action="store_true", help="leave README.md untouched")
    args = parser.parse_args(argv)

    logging.disable(logging.INFO)  # the trading services log every initialization at INFO
    started = time.perf_counter()

    def log(message: str) -> None:
        print(f"[{time.perf_counter() - started:6.1f}s] {message}", flush=True)

    if args.regenerate_dataset:
        dataset = generate_synthetic_universe()
        write_dataset(dataset, DEFAULT_DATASET)
        log(f"regenerated {DEFAULT_DATASET.relative_to(ROOT)} (prices sha256 {dataset.fingerprint[:16]})")

    dataset = load_dataset(args.dataset)
    report_dir = args.reports_dir / "showcase"
    engineering_path = report_dir / "engineering.json"
    results = build_showcase(ShowcaseConfig(dataset_dir=args.dataset), dataset, jobs=args.jobs,
                             include_engineering=not (args.reuse_engineering or args.skip_engineering), log=log)
    if args.reuse_engineering:
        if not engineering_path.exists():
            print(f"error: {engineering_path} not found; run once without --reuse-engineering", file=sys.stderr)
            return 2
        attach_engineering(results, documents.engineering_from_json(engineering_path))
        log(f"reused engineering results from {engineering_path.relative_to(ROOT)}")

    failed = [c for c in results.checks if not c.passed]
    for check in results.checks:
        log(f"{'PASS' if check.passed else 'FAIL'}  {check.name}: {check.detail}")
    if failed:
        print(f"error: {len(failed)} consistency check(s) failed; no artifacts written", file=sys.stderr)
        return 1

    names = [n for n in (args.only.split(",") if args.only else FIGURES) if n]
    if results.engineering is None:
        names = [n for n in names if n != "engineering"]
    unknown = set(names) - set(FIGURES)
    if unknown:
        print(f"error: unknown figure(s): {sorted(unknown)}; choose from {sorted(FIGURES)}", file=sys.stderr)
        return 2
    written = []
    for theme_name in [t for t in args.themes.split(",") if t]:
        theme = THEMES[theme_name]
        with themed(theme):
            for name in names:
                written.append(save_figure(FIGURES[name](results, theme), args.assets_dir, name, theme))
    log(f"rendered {len(written)} figures into {args.assets_dir}")

    report_dir.mkdir(parents=True, exist_ok=True)
    documents.write_tables(results, report_dir)
    documents.write_manifest(results, report_dir / "manifest.json", names)
    if results.engineering is not None and not args.reuse_engineering:
        documents.engineering_to_json(results.engineering, engineering_path)
    report = documents.full_report(results, href(args.assets_dir, args.reports_dir),
                                   dataset_href=href(args.dataset, args.reports_dir, directory=True),
                                   methodology_href=href(ROOT / "docs" / "methodology.md", args.reports_dir))
    (args.reports_dir / "showcase.md").write_text(report, encoding="utf-8")
    log(f"wrote {(args.reports_dir / 'showcase.md')} and tables in {report_dir}")

    if not args.no_readme and args.dataset.resolve() == DEFAULT_DATASET.resolve():
        blocks = {
            "metrics": documents.metrics_table(results),
            "summary": documents.interpretation(results),
            "attribution": documents.attribution_line(results),
            "walk-forward": documents.walk_forward_summary(results),
            "robustness": documents.robustness_summary(results),
            "checks": documents.checks_summary(results, href(args.reports_dir / "showcase.md", ROOT)),
            "benchmarks": documents.benchmark_table(results),
            "console": "```text\n" + documents.console_summary(results) + "\n```",
        }
        updated = documents.update_readme_blocks(ROOT / "README.md", blocks)
        log(f"README.md generated blocks updated: {', '.join(updated) or 'none found'}")

    print()
    print(documents.console_summary(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
