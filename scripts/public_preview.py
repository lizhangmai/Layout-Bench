"""Prepare and evaluate published SG13G2 case witnesses without a model account."""

import argparse
import ipaddress
import json
import os
import platform
import shlex
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
# These public cases have ready-to-use witnesses and nominal RC evaluation.
# The case owns all rule bindings; this table selects its simulation resources.
CASE_MODELS = {"comparator": "analog-models", "full_OTA": "analog-models"}
IMAGE = "layout-bench-tools:local"
RUNS = "build/runs"
PDK_PATH = Path("third_party/IHP-Open-PDK")

# The public PDK contains several optional nested submodules.  The reviewed
# view only consumes the two Python libraries below; initializing the complete
# recursive tree is both unnecessary and fragile when a checkout already has
# unpacked (but untracked) optional directories.
PDK_REQUIRED_SUBMODULES = {
    Path("ihp-sg13g2/libs.tech/klayout/python/pycell4klayout-api"):
        Path("source/python/cni/box.py"),
    Path("ihp-sg13g2/libs.tech/klayout/python/pypreprocessor"):
        Path("pypreprocessor/__init__.py"),
}


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


def _proxy_hostname(value):
    """Return a proxy hostname from a URL or a host:port value."""
    if not value:
        return None
    candidate = value if "://" in value else f"//{value}"
    try:
        return urlparse(candidate).hostname
    except ValueError:
        return None


def _loopback_proxy_variables():
    variables = []
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        value = os.environ.get(name)
        hostname = _proxy_hostname(value)
        if hostname == "localhost":
            variables.append(name)
            continue
        try:
            if hostname and ipaddress.ip_address(hostname).is_loopback:
                variables.append(name)
        except ValueError:
            pass
    return variables


def _check_build_network(network):
    if network != "default":
        return
    variables = _loopback_proxy_variables()
    if variables:
        names = ", ".join(variables)
        raise ValueError(
            f"{names} point to a loopback proxy, which the default Docker build network cannot reach. "
            "Rerun with --network host, or unset the proxy variables if direct access is allowed.")


def build(image, network):
    _check_build_network(network)
    call("docker", "build", "--network", network, "--build-arg", "HTTP_PROXY", "--build-arg", "HTTPS_PROXY",
         "--build-arg", "NO_PROXY", "--target", "tools", "-t", image, ".")


def _git_metadata(path):
    metadata = path / ".git"
    return metadata.is_dir() or metadata.is_file()


def ensure_pdk():
    """Initialize only the pinned PDK and nested libraries used by the view.

    A populated directory without Git metadata is common in source archives
    and cached workspaces.  Git cannot clone a submodule over such a directory,
    so reuse it when the reviewed files are present and let ``prepare`` verify
    every byte.  An empty directory is a normal uninitialized submodule and
    can be cloned into.  A non-empty incomplete directory is rejected before
    Git is invoked so the user gets a recovery path instead of Git's clone error.
    """
    pdk = ROOT / PDK_PATH
    if not pdk.is_dir() or _git_metadata(pdk) or not any(pdk.iterdir()):
        # This is intentionally not recursive: optional nested PDK projects
        # are not part of the reviewed public view.
        call("git", "submodule", "update", "--init", "--depth", "1", str(PDK_PATH))
    if not pdk.is_dir():
        raise ValueError(f"PDK checkout missing after initialization: {pdk}. "
                         f"Run: git submodule update --init --depth 1 {PDK_PATH}")
    if not _git_metadata(pdk) and any(
            not (pdk / relative / marker).is_file()
            for relative, marker in PDK_REQUIRED_SUBMODULES.items()):
        raise ValueError(
            f"PDK checkout {pdk} has no Git metadata and is missing files required by the reviewed view. "
            f"Use a Git checkout, then run: git submodule update --init --depth 1 {PDK_PATH}")

    missing = []
    for relative, marker in PDK_REQUIRED_SUBMODULES.items():
        path = pdk / relative
        if (path / marker).is_file():
            continue
        if path.is_dir() and any(path.iterdir()) and not _git_metadata(path):
            command = (f"git -C {PDK_PATH} submodule update --init --depth 1 "
                       f"{relative}")
            raise ValueError(
                f"Required PDK dependency {relative} is a non-empty directory without Git metadata "
                f"and is incomplete. Move it aside (preserving any local files), then run: {command}")
        missing.append(str(relative))
    if missing:
        call("git", "-C", pdk, "submodule", "update", "--init", "--depth", "1", *missing)
    incomplete = [str(relative) for relative, marker in PDK_REQUIRED_SUBMODULES.items()
                  if not (pdk / relative / marker).is_file()]
    if incomplete:
        command = f"git -C {PDK_PATH} submodule update --init --depth 1 {' '.join(incomplete)}"
        raise ValueError(f"Required PDK files are still missing: {', '.join(incomplete)}. Run: {command}")


def prepare(destination, image=IMAGE, case="comparator"):
    from benchmarking.environment import prepare_pdk_bundle
    from benchmarking.files import Asset, read_file
    from benchmarking.prepare_support import prepare_support
    from benchmarking.tasks import load_task

    source = ROOT / "tasks/IHP-AnalogAcademy/cases" / case
    config = read_file(source, "case.toml").decode()
    data = tomllib.loads(config)
    task = load_task(source / "case.toml")
    if data["status"] != "qualified" or task.evaluation.mode != "post_layout":
        raise ValueError("The preview requires a qualified case with post-layout evaluation")
    reference = data["qualification"]["reference"]
    witness = Asset(read_file(source, reference), "gds")
    for asset in data.get("assets", []):
        if asset["path"] == reference and witness.sha256 != asset["sha256"]:
            raise ValueError("Reference witness checksum mismatch")
    pdk = ROOT / PDK_PATH
    if not (pdk / "ihp-sg13g2").is_dir():
        raise ValueError("PDK missing. Run quickstart, or initialize it with: "
                         "git submodule update --init --depth 1 third_party/IHP-Open-PDK")
    image_id = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True).strip()
    destination = new_directory(destination)
    prepare_pdk_bundle(pdk, destination / "agent-resources")
    profiles = {"klayout-docker": "klayout", "magic-rc-docker": "magic",
                "ngspice-docker": CASE_MODELS[case]}
    prepared = set()
    for backend in data["toolchain"]["backends"].values():
        settings = backend["settings"]
        config = config.replace(json.dumps(settings["image"]), json.dumps(image_id))
        if "support" not in settings:
            continue
        profile = profiles[backend["type"]]
        if profile not in prepared:
            print(f"Preparing {profile} from the reviewed PDK files", flush=True)
            prepare_support(pdk, ROOT / f"technology/sg13g2/{profile}.json", destination / profile,
                            compiler_image=image_id)
            prepared.add(profile)
        config = config.replace(json.dumps(settings["support"]), json.dumps(str(destination / profile)))
    # Host-side assembly: the solver loader still delivers only task.inputs.
    task.materialize(destination / "case")
    bound_case = destination / "case/case.toml"
    bound_case.write_text(config)
    target = bound_case.parent / reference
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(witness.content)
    evidence = data["qualification"]["evidence"]
    target = bound_case.parent / evidence
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(read_file(source, evidence))
    print(f"Prepared case: {bound_case}", flush=True)


def run(prepared, output):
    from benchmarking.tasks import load_task

    config = prepared.absolute() / "case/case.toml"
    task = load_task(config)
    data = tomllib.loads(config.read_text())
    reference = config.parent / data["qualification"]["reference"]
    output = new_directory(output)
    python(ROOT / "main.py", "evaluate", config, reference,
           "--output", output / "reference", log=output / "reference.log")
    report = json.loads((output / "reference/report.json").read_text())
    if report["outcome"] != "passed" or report["task_success"] is not True:
        raise ValueError("The case witness did not pass its complete evaluation")
    summary = {"run_kind": "public_case_reference", "task": task.id,
               "reference": "passed", "model_called": False}
    (output / "preview.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"PASS: {task.id} reference passed its declared evaluation. No model was called. "
          f"Report: {output / 'reference/report.json'}")


def quickstart(output, image, network, skip_build, case="comparator"):
    doctor()
    if not skip_build:
        _check_build_network(network)
    output = new_directory(output or ROOT / RUNS / datetime.now(UTC).strftime("preview-%Y%m%dT%H%M%S%fZ"))
    print(f"Preview directory: {output}", flush=True)
    if not skip_build:
        build(image, network)
    ensure_pdk()
    prepare(output / "prepared", image, case)
    run(output / "prepared", output / "run")
    print(f"Reviewed solver resources: {output / 'prepared/agent-resources'}\n"
          f"Prepared case: {output / 'prepared/case/case.toml'}", flush=True)


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
            command.add_argument("--case", choices=CASE_MODELS, default="comparator")
            command.add_argument("--skip-build", action="store_true", help="Use an already available --image; still prepare and verify fresh resources")
    preparation = commands.add_parser("prepare", help="Create reviewed PDK/tool bundles in a new directory")
    preparation.add_argument("--output", type=Path, default=ROOT / RUNS / "preview/prepared")
    preparation.add_argument("--image", default=IMAGE)
    preparation.add_argument("--case", choices=CASE_MODELS, default="comparator")
    command = commands.add_parser("run", help="Evaluate the prepared case witness with its complete declared plan")
    command.add_argument("--prepared", type=Path, default=ROOT / RUNS / "preview/prepared")
    command.add_argument("--output", type=Path, required=True, help="New directory for reports; existing evidence is never overwritten")
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            doctor()
        elif args.command == "build":
            doctor()
            build(args.image, args.network)
        elif args.command == "quickstart":
            quickstart(args.output, args.image, args.network, args.skip_build, args.case)
        elif args.command == "prepare":
            prepare(args.output, args.image, args.case)
        else:
            run(args.prepared.absolute(), args.output)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(2, f"Public preview stopped: {error}\n")


if __name__ == "__main__":
    main()
