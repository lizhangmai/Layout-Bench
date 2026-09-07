"""Reproduce pre-layout measurements from the authoritative native-reader netlist."""

import argparse
import json
from pathlib import Path

from benchmarking.bundles import load_bundle
from benchmarking.docker import DockerTool
from benchmarking.evaluate import run_evaluation
from benchmarking.evaluation import parse_evaluation
from benchmarking.files import Asset
from benchmarking.tasks import load_task
from benchmarking.toolchains import load_toolchain

TASK = Path(__file__).resolve().parents[1]
CONFIG = TASK.parent.parent / "module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate.toml"


def calibrate(toolchain: Path, support: Path, destination: Path):
    if destination.exists():
        raise FileExistsError(destination)
    task = load_task(CONFIG)
    bundle = load_bundle(support)
    backends = load_toolchain(toolchain)
    tool = DockerTool(backends["layout.artifact"].tool.image_id, ["klayout", "-v"], 60)
    source = Asset(Path(__file__).with_name("schematic.rb").read_bytes(), "ruby")
    result = tool.run(["klayout", "-b", "-r", "schematic.rb"], {**bundle.mounted_files(),
        "schematic.rb": source, "source.spice": task.evaluation_inputs()["input:netlist"]},
        {"schematic.spice": "spice"})
    destination.mkdir(parents=True)
    for name, a in result.evidence.items():
        (destination / f"{name}.log").write_bytes(a.content)
    if result.reason:
        raise ValueError(result.reason)
    (destination / "schematic.spice").write_bytes(result.files["schematic.spice"].content)
    # Reuse the exact simulation job declarations; replace only the DUT data input.
    raw = task.evaluation.raw.decode()
    jobs_start = raw.index('[[jobs]]\nid = "on_')
    raw = 'schema_version = 1\nmode = "characterization"\n\n' + raw[jobs_start:]
    raw = raw[:raw.index('[[metrics]]\nid = "area"')]
    raw = raw.replace('job:parasitics:netlist', 'input:dut')
    # TOML rewriting is only configuration composition, never netlist editing.
    plan = parse_evaluation(raw.encode())
    report = run_evaluation(plan, {**task.evaluation_inputs(), "input:dut": result.files["schematic.spice"]},
                            backends, destination / "measurements")
    (destination / "preparation.json").write_text(json.dumps({"task_sha256": task.digest,
        "source_sha256": task.evaluation_inputs()["input:netlist"].sha256,
        "writer_sha256": source.sha256, "support_sha256": bundle.manifest.sha256,
        "output": result.files["schematic.spice"].identity(), "tool": tool.identity}, indent=2)+"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--toolchain", type=Path, default=TASK / "qualification/toolchain.toml")
    parser.add_argument("--support", type=Path, default=Path("build/support/sg13g2-klayout-ports"))
    args = parser.parse_args()
    calibrate(args.toolchain, args.support, args.destination)
