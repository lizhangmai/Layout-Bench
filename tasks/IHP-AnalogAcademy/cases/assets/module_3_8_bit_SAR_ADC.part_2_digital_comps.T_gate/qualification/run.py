"""Rebuild public reference/negative layouts and check the qualification matrix."""

import argparse
import json
import runpy
from pathlib import Path

from benchmarking.evaluate import run_evaluation
from benchmarking.files import Asset
from benchmarking.tasks import load_task
from benchmarking.toolchains import load_toolchain

TASK = Path(__file__).resolve().parents[1]
CONFIG = TASK.parent.parent / "module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate.toml"
EXPECTED = {"reference": "passed", "translated": "passed", "hierarchy": "passed",
            "slow": "performance", "outline": "geometry", "pin_size": "geometry",
            "missing_pin": "lvs", "short": "lvs", "open": "lvs", "wrong_size": "lvs",
            "drc": "drc", "empty": "artifact", "nested_labels": "geometry", "duplicate_label": "geometry"}


def qualify(view: Path, toolchain: Path, destination: Path):
    if destination.exists():
        raise FileExistsError(destination)
    task = load_task(CONFIG)
    backends = load_toolchain(toolchain)
    generate = runpy.run_path(str(TASK / "reference/generate.py"))["generate"]
    image = backends["layout.artifact"].tool.image_id
    reference = generate(view, destination / "reference", image=image)
    wrong = generate(view, destination / "wrong_size", n_width="2u", image=image)
    script = Asset(Path(__file__).with_name("variants.py").read_bytes(), "python")
    variants = [name for name in EXPECTED if name not in {"reference", "wrong_size"}]
    made = backends["layout.artifact"].tool.run(["python", "variants.py", "reference.gds", "variants"],
        {"variants.py": script, "reference.gds": reference}, {f"variants/{v}.gds": "gds" for v in variants})
    if made.reason:
        raise ValueError(made.reason)
    layouts = {"reference": reference, "wrong_size": wrong,
               **{v: made.files[f"variants/{v}.gds"] for v in variants}}
    reports, cases = {}, {}
    for name, layout in layouts.items():
        report = run_evaluation(task.evaluation, {**task.evaluation_inputs(), "candidate": layout},
                                backends, destination / name / "evaluation", task_sha256=task.digest)
        reports[name] = report
        expected = EXPECTED[name]
        if expected == "passed":
            ok = report["task_success"] is True and report["outcome"] == "passed"
        elif expected == "performance":
            ok = (report["physical_valid"] is True and report["jobs"]["geometry"]["status"] == "passed"
                  and report["specs_pass"] is False and report["task_success"] is False
                  and report["outcome"] == "failed")
        else:
            ok = report["jobs"][expected]["status"] == "failed" and report["outcome"] == "failed"
        cases[name] = {"expectation": expected, "verified": ok, "candidate": layout.identity(),
            "report_sha256": Asset((destination/name/"evaluation/report.json").read_bytes(),"json").sha256,
            "outcome": report["outcome"], "physical_valid": report["physical_valid"],
            "task_success": report["task_success"],
            "jobs": {k: {"status": j["status"], "reason": j["reason"]} for k,j in report["jobs"].items()},
            "metrics": report["metrics"]}
        print(f"{name}: {'verified' if ok else 'UNEXPECTED'} ({report['outcome']})", flush=True)
    summary = {"schema_version": 1, "task_sha256": task.digest,
        "environment": task.environment, "engine_sha256": reports["reference"]["engine_sha256"],
        "backends": reports["reference"]["backends"],
        "construction": {"reference": json.loads((destination/"reference/generation.json").read_text()),
                         "variants_sha256": script.sha256}, "cases": cases,
        "qualified": all(c["verified"] for c in cases.values())}
    (destination/"qualification.json").write_text(json.dumps(summary,indent=2)+"\n")
    return summary, reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("view",type=Path)
    parser.add_argument("destination",type=Path)
    parser.add_argument("--toolchain",type=Path,default=TASK/"qualification/toolchain.toml")
    args = parser.parse_args()
    summary,_ = qualify(args.view,args.toolchain,args.destination)
    raise SystemExit(0 if summary["qualified"] else 1)
