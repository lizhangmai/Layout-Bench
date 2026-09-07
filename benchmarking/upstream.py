"""Evaluate original case assets through the frozen KLayout API.

This maintainer entry point does not materialize or transform a task netlist.
It records physical checks only, not task qualification or task success.
"""

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

from .evaluate import run_evaluation
from .evaluation import parse_evaluation
from .files import Asset, read_file, relative
from .klayout import KLayoutDocker
from .tasks import _validate_case


def evaluate(case: Path, support: Path, output: Path, image: str, *, root: Path,
             top_cell: str | None = None, timeout_seconds: float = 600):
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    raw = case.read_bytes()
    data = tomllib.loads(raw.decode())
    _validate_case(data)
    mapping = data.get("upstream_evaluation")
    if mapping is None:
        raise ValueError("Case does not declare upstream_evaluation")
    if top_cell is not None and top_cell != mapping["top_cell"]:
        raise ValueError("CLI top cell conflicts with the case mapping")
    top_cell = mapping["top_cell"]
    checkout = root / relative(data["origin"]["checkout"], "upstream checkout")
    commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    if commit != data["origin"]["commit"]:
        raise ValueError("Upstream checkout differs from the case commit")
    inputs = {}
    by_id = {entry["id"]: entry for entry in data["upstream_assets"]}
    for field, key, fmt in (("layout", "candidate", "gds"), ("netlist", "input:netlist", "spice")):
        entry = by_id[mapping[field]]
        asset = Asset(read_file(checkout, entry["path"]), fmt)
        if asset.sha256 != entry["sha256"]:
            raise ValueError(f"Upstream asset checksum mismatch: {entry['path']}")
        inputs[key] = asset
    plan = 'schema_version = 1\nmode = "physical"\nmetrics = []\n'
    backends = {}
    for check in ("artifact", "drc", "lvs"):
        params = {"top_cell": top_cell, "max_bytes": 67108864}
        refs = {"layout": "candidate"}
        if check == "lvs":
            params["subcircuit"] = mapping["subcircuit"]
            refs["netlist"] = "input:netlist"
        plan += f'\n[[jobs]]\nid = "{check}"\nstage = "check"\noperation = "layout.{check}"\ngate = "{check}"\n'
        for name, values in (("inputs", refs), ("parameters", params)):
            plan += f"{name} = {{ " + ", ".join(f"{k} = {json.dumps(v)}" for k, v in values.items()) + " }\n"
        settings = {} if check == "artifact" else {
            "support": str(support),
            "profile": mapping[f"{check}_profile"],
        }
        backends[f"layout.{check}"] = KLayoutDocker(image=image, check=check, timeout_seconds=timeout_seconds, **settings)
    report = run_evaluation(parse_evaluation(plan.encode()), inputs, backends, output,
                          task_sha256=Asset(raw, "toml").sha256)
    (output / "case.toml").write_bytes(raw)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("--top-cell", help="Optional assertion against case metadata")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Workspace checkout root")
    parser.add_argument("--timeout-seconds", type=float, default=600)
    parser.add_argument("--support", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="layout-bench-tools:local")
    args = parser.parse_args()
    try:
        report = evaluate(args.case, args.support, args.output, args.image, root=args.root,
                          top_cell=args.top_cell, timeout_seconds=args.timeout_seconds)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        print(f"Upstream evaluation error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    print(json.dumps({"outcome": report["outcome"], "physical_valid": report["physical_valid"],
                      "jobs": {name: {"status": value["status"], "reason": value["reason"]}
                               for name, value in report["jobs"].items()}}, indent=2))
    raise SystemExit(0 if report["outcome"] == "passed" else 2 if report["outcome"] == "error" else 1)


if __name__ == "__main__":
    main()
