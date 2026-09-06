"""Build and reproduce the public academy-tgate preview without a model account."""

import argparse
import hashlib
import json
import platform
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "tasks/IHP-AnalogAcademy/module_3_8_bit_SAR_ADC/part_2_digital_comps/T_gate"
IMAGE = "layout-bench-tools:local"
RUNS = "build/runs"
SUPPORT = "build/support"


def call(*command, expected=0, log=None):
    arguments = [str(arg) for arg in command]
    print("+ " + shlex.join(arguments), flush=True)
    if log is None:
        result = subprocess.run(arguments, cwd=ROOT, check=False)
    else:
        with log.open("w") as stream:
            result = subprocess.run(arguments, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False)
    if result.returncode != expected:
        details = f"Inspect {log}." if log else "See the output above."
        raise RuntimeError(f"Step exited {result.returncode}; expected {expected}. {details}")


def python(*arguments, **options):
    call(sys.executable, *arguments, **options)


def new_directory(path):
    path = path.absolute()
    if path.exists() or path.is_symlink():
        raise ValueError(f"Output already exists: {path}. Choose a new --output directory; existing evidence is retained.")
    path.mkdir(parents=True, mode=0o700)
    return path


def doctor():
    if sys.version_info < (3, 12) or platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise ValueError("The preview requires Linux x86-64 and Python 3.12+. See README.md for the supported environment.")
    call("git", "--version")
    call("docker", "version", "--format", "{{.Server.Version}}")
    print("Host prerequisites OK.", flush=True)


def build(image, network):
    call("docker", "build", "--network", network, "--build-arg", "HTTP_PROXY", "--build-arg", "HTTPS_PROXY",
         "--build-arg", "NO_PROXY", "--target", "tools", "-t", image, ".")


def prepare(destination, image=IMAGE):
    from benchmarking.environment import prepare_pdk, prepare_pdk_bundle
    from benchmarking.prepare_support import prepare_support

    pdk = ROOT / "third_party/IHP-Open-PDK"
    if not (pdk / "ihp-sg13g2").is_dir():
        raise ValueError("PDK missing. Run: git submodule update --init --recursive --depth 1 third_party/IHP-Open-PDK")
    # Resolve once: compilation, agents and all judge backends use the same image.
    image_id = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True).strip()
    destination = new_directory(destination)
    prepare_pdk(pdk, destination / "pdk-view")
    prepare_pdk_bundle(pdk, destination / "agent-resources")
    for name in ("magic", "mos-models", "klayout"):
        print(f"Preparing {name} from the reviewed PDK files", flush=True)
        prepare_support(pdk, ROOT / f"technology/sg13g2/{name}.json", destination / name, compiler_image=image_id)
    # This example composes this public task's existing configuration; the framework
    # still accepts arbitrary task/toolchain files and has no academy-tgate branches.
    config = (TASK / "qualification/toolchain.toml").read_text()
    for old, name in (("magic", "magic"), ("mos-models", "mos-models"), ("klayout-ports", "klayout")):
        # Accept the historical .cache paths while new task templates use the
        # repository-wide build/support output namespace.
        for prefix in (SUPPORT, ".cache"):
            config = config.replace(f'"{prefix}/sg13g2-{old}"', json.dumps(str(destination / name)))
    config = config.replace('"layout-bench-tools:local"', json.dumps(image_id))
    (destination / "toolchain.toml").write_text(config)
    for name in ("protocol-probe",):
        config = (ROOT / f"examples/agents/{name}.toml").read_text()
        config = config.replace('"layout-bench-tools:local"', json.dumps(image_id))
        (destination / f"{name}.toml").write_text(config)
    (destination / "protocol_probe.py").write_bytes((ROOT / "examples/agents/protocol_probe.py").read_bytes())
    print(f"Prepared public task tools: {destination / 'toolchain.toml'}", flush=True)



def calibration_summary(output, qualification):
    """Reproduce the public calibration digest/metrics summary from retained reports."""
    raw = (output / "calibration/measurements/report.json").read_bytes()
    pre = json.loads(raw)
    post = qualification["cases"]["reference"]
    result = {"schema_version": 1, "task_sha256": qualification["task_sha256"],
              "environment": qualification["environment"],
              "preparation": json.loads((output / "calibration/preparation.json").read_text()),
              "pre_layout": {"engine_sha256": pre["engine_sha256"], "backends": pre["backends"],
                             "report_sha256": hashlib.sha256(raw).hexdigest(), "metrics": pre["metrics"]},
              "post_layout": {key: post[key] for key in ("candidate", "report_sha256", "metrics")}}
    (output / "calibration.json").write_text(json.dumps(result, indent=2) + "\n")


def run(prepared, output, qualification):
    toolchain = prepared.absolute() / "toolchain.toml"
    if not toolchain.is_file():
        raise ValueError(f"Prepared tools missing: {toolchain}. Run 'prepare' first, or set --prepared.")
    output = new_directory(output)
    if qualification:
        python(TASK / "qualification/run.py", prepared / "pdk-view", output / "qualification", "--toolchain", toolchain)
        python(TASK / "qualification/calibrate.py", output / "calibration", "--toolchain", toolchain,
               "--support", prepared / "klayout")
        summary = json.loads((output / "qualification/qualification.json").read_text())
        calibration = json.loads((output / "calibration/measurements/report.json").read_text())
        if summary["qualified"] is not True or calibration["outcome"] != "passed":
            raise ValueError("Public qualification or calibration did not pass; inspect the retained reports.")
        calibration_summary(output, summary)
        print(f"PASS: {len(summary['cases'])} qualification scenarios and schematic calibration. No model was called.")
        return
    python(ROOT / "main.py", "evaluate", TASK / "task.toml", TASK / "reference/reference.gds",
           "--toolchain", toolchain, "--output", output / "reference", log=output / "reference.log")
    agent = prepared.absolute() / "protocol-probe.toml"
    python(ROOT / "main.py", "run", TASK / "task.toml", "--agent", agent,
           "--toolchain", toolchain, "--output", output / "probe", expected=1, log=output / "probe.log")
    probe = json.loads((output / "probe/run.json").read_text())
    if probe["termination"] != "completed" or probe["outcome"] != "failed" or not probe["candidate"]:
        raise ValueError("Expected a completed protocol probe with a rejected rectangular layout.")
    plan = (ROOT / "examples/plans/protocol-probe.toml").read_text()
    for old, path in (("../../tasks/IHP-AnalogAcademy/module_3_8_bit_SAR_ADC/part_2_digital_comps/T_gate/task.toml", TASK / "task.toml"),
                      ("../../tasks/IHP-AnalogAcademy/module_3_8_bit_SAR_ADC/part_2_digital_comps/T_gate/qualification/toolchain.toml", toolchain),
                      ("../agents/protocol-probe.toml", agent)):
        plan = plan.replace(json.dumps(old), json.dumps(str(path)))
    (output / "plan.toml").write_text(plan)
    python(ROOT / "main.py", "batch", output / "plan.toml", "--output", output / "batch", log=output / "batch.log")
    python(ROOT / "main.py", "summarize", output / "batch", log=output / "recomputed-summary.json")
    batch = json.loads((output / "batch/batch.json").read_text())
    if not batch["summary"]["complete"] or any(g["success_rate"] != 0 for g in batch["summary"]["groups"]):
        raise ValueError("Expected complete batch coverage and zero protocol-probe task successes.")
    summary = {"run_kind": "public_preview_smoke", "task": "academy-tgate", "reference": "passed",
               "protocol_probe": "expected_failure", "batch": "complete", "model_called": False}
    (output / "preview.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"PASS: reference, explicit submission and batch statistics. No model was called. Summary: {output / 'preview.json'}")


def quickstart(output, image, network, skip_build):
    doctor()
    output = new_directory(output or ROOT / RUNS / datetime.now(UTC).strftime("preview-%Y%m%dT%H%M%S%fZ"))
    print(f"Preview directory: {output}", flush=True)
    if not skip_build:
        build(image, network)
    call("git", "submodule", "update", "--init", "--recursive", "--depth", "1", "third_party/IHP-Open-PDK")
    prepare(output / "prepared", image)
    run(output / "prepared", output / "run", False)
    print(f"Ready with the bundled harness example: {output / 'prepared/protocol-probe.toml'}\n"
          f"Reviewed resources: {output / 'prepared/agent-resources'}\n"
          f"Judge configuration: {output / 'prepared/toolchain.toml'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check the supported host and Docker access")
    for name, help_text in (("quickstart", "Build one image, fetch the pinned PDK, prepare resources and run no-key checks"),
                            ("build", "Build the unified public tool image; downloads required")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--image", default=IMAGE, help="Tool image tag (default: %(default)s)")
        command.add_argument("--network", choices=("default", "host"), default="default", help="Build network; host can reach local proxy services")
        if name == "quickstart":
            command.add_argument("--output", type=Path, help=f"New directory; default is a timestamped directory under {RUNS}")
            command.add_argument("--skip-build", action="store_true", help="Use an already available --image; still prepare and verify fresh resources")
    preparation = commands.add_parser("prepare", help="Create reviewed PDK/tool bundles in a new directory")
    preparation.add_argument("--output", type=Path, default=ROOT / RUNS / "preview")
    preparation.add_argument("--image", default=IMAGE)
    for name in ("run", "qualify"):
        command = commands.add_parser(name, help="Run public reference/probe/batch checks" if name == "run" else "Rebuild and verify the 14 qualification scenarios and calibration")
        command.add_argument("--prepared", type=Path, default=ROOT / RUNS / "preview")
        command.add_argument("--output", type=Path, required=True, help="New directory for reports; existing evidence is never overwritten")
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            doctor()
        elif args.command == "build":
            doctor()
            build(args.image, args.network)
        elif args.command == "quickstart":
            quickstart(args.output, args.image, args.network, args.skip_build)
        elif args.command == "prepare":
            prepare(args.output, args.image)
        else:
            run(args.prepared.absolute(), args.output, args.command == "qualify")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(2, f"Public preview stopped: {error}\n")


if __name__ == "__main__":
    main()
