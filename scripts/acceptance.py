"""Run the repeatable public black-box acceptance suites.

The fast and container suites use deterministic fixtures only.  The preview
and EDA suites are intentionally separate because they need Docker, the
reviewed PDK, and long-running EDA tools.  Unless an output directory is
explicitly supplied, preview evidence is written below a temporary directory
outside the checkout.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = os.environ.get("LAYOUT_BENCH_TEST_IMAGE", "layout-bench-tools:local")


def _pytest(marker, image=None):
    environment = os.environ.copy()
    if image:
        environment["LAYOUT_BENCH_TEST_IMAGE"] = image
    command = [sys.executable, "-m", "pytest", "-m", marker]
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=environment, check=True)


def _preview_evidence_is_complete(output):
    output = Path(output)
    summary = json.loads((output / "run/preview.json").read_text())
    report = json.loads((output / "run/reference/report.json").read_text())
    if (summary["run_kind"] != "public_case_reference" or summary["reference"] != "passed"
            or summary["model_called"] is not False or report["task_success"] is not True
            or report["outcome"] != "passed"):
        raise ValueError(f"Public case reference evaluation failed: {summary}")


def _preview(output, image, network, *, skip_build):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError(f"Acceptance output already exists: {output}")
    command = [sys.executable, "scripts/public_preview.py", "quickstart",
               "--image", image, "--network", network, "--output", str(output)]
    if skip_build:
        command.append("--skip-build")
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)
    _preview_evidence_is_complete(output)


def _run_preview_pair(image, network):
    with tempfile.TemporaryDirectory(prefix="layout-bench-acceptance-") as temporary:
        root = Path(temporary)
        _preview(root / "preview-build", image, network, skip_build=False)
        _preview(root / "preview-skip-build", image, network, skip_build=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=("fast", "container", "eda", "preview", "all"))
    parser.add_argument("--image", default=DEFAULT_IMAGE,
                        help="Prepared Docker image for container/EDA suites")
    parser.add_argument("--network", choices=("default", "host"), default="host",
                        help="Docker build network for the preview suite (default: %(default)s)")
    parser.add_argument("--output", type=Path,
                        help="Preview output directory; default is a temporary directory")
    parser.add_argument("--skip-build", action="store_true",
                        help="Reuse the image for the preview suite")
    args = parser.parse_args()

    if args.suite == "fast":
        _pytest("acceptance_fast")
    elif args.suite == "container":
        _pytest("acceptance_container", args.image)
    elif args.suite == "eda":
        _pytest("acceptance_eda", args.image)
    elif args.suite == "preview":
        if args.output is None:
            with tempfile.TemporaryDirectory(prefix="layout-bench-acceptance-") as temporary:
                _preview(Path(temporary) / "preview", args.image, args.network, skip_build=args.skip_build)
        else:
            _preview(args.output, args.image, args.network, skip_build=args.skip_build)
    else:
        _pytest("acceptance_fast")
        _pytest("acceptance_container", args.image)
        _run_preview_pair(args.image, args.network)
        _pytest("acceptance_eda", args.image)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Acceptance suite stopped: {error}") from error
