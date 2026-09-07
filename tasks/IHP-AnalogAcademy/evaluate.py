"""Evaluate original AnalogAcademy assets through the frozen KLayout API.

This maintainer entry point does not materialize or transform a task netlist.
It records physical checks only, not task qualification or task success.
"""

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from benchmarking.evaluate import run_evaluation
from benchmarking.evaluation import parse_evaluation
from benchmarking.files import Asset, read_file
from benchmarking.klayout import KLayoutDocker


def evaluate(case: Path, top_cell: str, support: Path, output: Path, image: str):
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    raw = case.read_bytes()
    data = tomllib.loads(raw.decode())
    if data.get("kind") != "layout_case" or data["origin"]["checkout"] != "third_party/IHP-AnalogAcademy":
        raise ValueError("Expected an AnalogAcademy layout case")
    checkout = ROOT / data["origin"]["checkout"]
    commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    if commit != data["origin"]["commit"]:
        raise ValueError("Upstream checkout differs from the case commit")
    inputs = {"input:case": Asset(raw, "toml")}
    for role, key, fmt in (("reference", "candidate", "gds"),
                           ("source-netlist", "input:netlist", "spice")):
        matches = [entry for entry in data["upstream_assets"] if entry["role"] == role]
        if len(matches) != 1:
            raise ValueError(f"Case requires one unambiguous {role} asset")
        entry = matches[0]
        asset = Asset(read_file(checkout, entry["path"]), fmt)
        if asset.sha256 != entry["sha256"]:
            raise ValueError(f"Upstream asset checksum mismatch: {entry['path']}")
        inputs[key] = asset
    plan = 'schema_version = 1\nmode = "physical"\nmetrics = []\n'
    backends = {}
    for check in ("artifact", "drc", "lvs"):
        params = {"top_cell": top_cell, "max_bytes": 10485760}
        refs = {"layout": "candidate"}
        if check == "lvs":
            params["subcircuit"] = top_cell
            refs["netlist"] = "input:netlist"
        plan += f'\n[[jobs]]\nid = "{check}"\nstage = "check"\noperation = "layout.{check}"\ngate = "{check}"\n'
        for name, values in (("inputs", refs), ("parameters", params)):
            plan += f"{name} = {{ " + ", ".join(f"{k} = {json.dumps(v)}" for k, v in values.items()) + " }\n"
        settings = {} if check == "artifact" else {
            "support": str(support),
            "profile": "drc-upstream.json" if check == "drc" else "lvs-analogacademy.json",
        }
        backends[f"layout.{check}"] = KLayoutDocker(image=image, check=check, **settings)
    return run_evaluation(parse_evaluation(plan.encode()), inputs, backends, output,
                          task_sha256=Asset(raw, "toml").sha256)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("--top-cell", required=True)
    parser.add_argument("--support", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="layout-bench-tools:local")
    args = parser.parse_args()
    try:
        report = evaluate(args.case, args.top_cell, args.support, args.output, args.image)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        print(f"Upstream evaluation error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    print(json.dumps({"outcome": report["outcome"], "physical_valid": report["physical_valid"],
                      "jobs": {name: {"status": value["status"], "reason": value["reason"]}
                               for name, value in report["jobs"].items()}}, indent=2))
    raise SystemExit(0 if report["outcome"] == "passed" else 2 if report["outcome"] == "error" else 1)
