"""Usage examples for MLE Heatmap Wrapper.

This module centralizes reproducible command examples for:
- listing available configurations
- running a batch execution on folder-based input
- running legacy single-file mode
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import List
from src.mle_heatmap_wrapper.cli.main import HeatmapWrapper


def build_batch_command(
    input_dir: Path,
    part_number: str,
    supplier: str,
    output_dir: Path,
    metrics: List[str] | None = None,
) -> List[str]:
    """Build a `mle-heatmap` batch command."""
    cmd = [
        "mle-heatmap",
        "--input-dir",
        str(input_dir),
        "--part-number",
        part_number,
        "--supplier",
        supplier,
        "--output",
        str(output_dir),
    ]
    if metrics:
        cmd.extend(["--metrics", *metrics])
    return cmd


def build_legacy_command(
    input_file: Path,
    part_number: str,
    supplier: str,
    output_dir: Path,
) -> List[str]:
    """Build a `mle-heatmap` legacy single-file command."""
    return [
        "mle-heatmap",
        "--input-file",
        str(input_file),
        "--part-number",
        part_number,
        "--supplier",
        supplier,
        "--output",
        str(output_dir),
    ]


def run_or_print(cmd: List[str], execute: bool) -> int:
    """Print command or execute it directly."""
    print("$", " ".join(cmd))
    if not execute:
        return 0
    completed = subprocess.run(cmd, check=False)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Examples runner for mle-heatmap")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute commands instead of only printing them",
    )
    parser.add_argument(
        "--mode",
        choices=["list-configs", "batch", "legacy"],
        default="batch",
        help="Example mode to print or execute",
    )
    args = parser.parse_args()

    if args.mode == "list-configs":
        return run_or_print(["mle-heatmap", "--list-configs"], args.execute)

    if args.mode == "batch":
        cmd = build_batch_command(
            input_dir=Path("data/in/mlx"),
            part_number="362",
            supplier="MLX",
            output_dir=Path("output"),
            metrics=["widthness", "tangent"],
        )
        return run_or_print(cmd, args.execute)

    cmd = build_legacy_command(
        input_file=Path("data/input.csv"),
        part_number="362",
        supplier="CZT",
        output_dir=Path("output"),
    )
    return run_or_print(cmd, args.execute)


if __name__ == "__main__":
    # raise SystemExit(main())
    wrapper = HeatmapWrapper()

    wrapper.run_single_file(
        piece_folder=Path("data/in/czt/HK147127-0"),
        part_number="362-850-019",
        supplier="CZT",
        operation="OP420",
        metrics=["widthness", "tangent"],
        output_dir=Path("data/out/czt"),
    )
