"""Build and reproduce the public SG13G2 integration preview without a model account."""

import argparse
import ipaddress
import json
import os
import platform
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CASE_ID = "sg13g2-checked-switch-fixture"
FIXTURES = ROOT / "tests/fixtures"
TASK = FIXTURES / "sg13g2/checked-switch"
CONFIG = TASK / "task.toml"
IMAGE = "layout-bench-tools:local"
RUNS = "build/runs"
SUPPORT = "build/support"
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
    every byte.  An incomplete directory is rejected before Git is invoked so
    the user gets a recovery path instead of Git's opaque clone error.
    """
    pdk = ROOT / PDK_PATH
    if not pdk.is_dir():
        call("git", "submodule", "update", "--init", "--depth", "1", str(PDK_PATH))
    elif _git_metadata(pdk):
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


def prepare(destination, image=IMAGE):
    from benchmarking.environment import prepare_pdk, prepare_pdk_bundle
    from benchmarking.prepare_support import prepare_support

    pdk = ROOT / PDK_PATH
    if not (pdk / "ihp-sg13g2").is_dir():
        raise ValueError("PDK missing. Run quickstart, or initialize it with: "
                         "git submodule update --init --depth 1 third_party/IHP-Open-PDK")
    # Resolve once: compilation, agents and all judge backends use the same image.
    image_id = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True).strip()
    destination = new_directory(destination)
    prepare_pdk(pdk, destination / "pdk-view")
    prepare_pdk_bundle(pdk, destination / "agent-resources")
    for name in ("magic", "mos-models", "klayout"):
        print(f"Preparing {name} from the reviewed PDK files", flush=True)
        prepare_support(pdk, ROOT / f"technology/sg13g2/{name}.json", destination / name, compiler_image=image_id)
    # This preview composes the repository's generic checked-switch fixture;
    # the framework still accepts arbitrary task/toolchain files and has no
    # task-specific branches.
    config = (TASK / "toolchain.toml").read_text()
    for old, name in (("magic", "magic"), ("mos-models", "mos-models"), ("klayout", "klayout")):
        # Accept the historical .cache paths while new task templates use the
        # repository-wide build/support output namespace.
        for prefix in (SUPPORT, ".cache"):
            config = config.replace(f'"{prefix}/sg13g2-{old}"', json.dumps(str(destination / name)))
    config = config.replace('"layout-bench-tools:local"', json.dumps(image_id))
    (destination / "toolchain.toml").write_text(config)
    probes = {
        "protocol-probe": ("protocol_probe.py",),
        "canonical-probe": ("canonical_harness.py", "canonical_probe_adapter.py"),
    }
    for name, files in probes.items():
        config = (FIXTURES / f"agents/{name}.toml").read_text()
        config = config.replace('"layout-bench-tools:local"', json.dumps(image_id))
        (destination / f"{name}.toml").write_text(config)
        for filename in files:
            (destination / filename).write_bytes((FIXTURES / "agents" / filename).read_bytes())
    print(f"Prepared public task tools: {destination / 'toolchain.toml'}", flush=True)



def run(prepared, output, qualification):
    toolchain = prepared.absolute() / "toolchain.toml"
    if not toolchain.is_file():
        raise ValueError(f"Prepared tools missing: {toolchain}. Run 'prepare' first, or set --prepared.")
    output = new_directory(output)
    if qualification:
        print("Running the same deterministic fixture checks under the 'qualify' alias.", flush=True)
    python(FIXTURES / "sg13g2/generate.py", prepared / "pdk-view", output / "fixtures", "--suite", "checks")
    python(ROOT / "main.py", "evaluate", CONFIG, output / "fixtures/valid.gds",
           "--toolchain", toolchain, "--output", output / "reference", log=output / "reference.log")
    agent = prepared.absolute() / "protocol-probe.toml"
    python(ROOT / "main.py", "run", CONFIG, "--agent", agent,
           "--toolchain", toolchain, "--output", output / "probe", expected=1, log=output / "probe.log")
    probe = json.loads((output / "probe/run.json").read_text())
    if probe["termination"] != "completed" or probe["outcome"] != "failed" or not probe["candidate"]:
        raise ValueError("Expected a completed protocol probe with a rejected rectangular layout.")
    canonical_agent = prepared.absolute() / "canonical-probe.toml"
    python(ROOT / "main.py", "run", CONFIG, "--agent", canonical_agent,
           "--toolchain", toolchain, "--output", output / "canonical-probe", expected=1,
           log=output / "canonical-probe.log")
    canonical = json.loads((output / "canonical-probe/run.json").read_text())
    if (canonical["termination"] != "completed" or canonical["outcome"] != "failed"
            or not canonical["candidate"]):
        raise ValueError("Expected a completed canonical probe with a rejected rectangular layout.")
    plan = (FIXTURES / "plans/protocol-probe.toml").read_text()
    for old, path in (("../sg13g2/checked-switch/task.toml", CONFIG),
                      ("../sg13g2/checked-switch/toolchain.toml", toolchain),
                      ("../agents/protocol-probe.toml", agent)):
        plan = plan.replace(json.dumps(old), json.dumps(str(path)))
    (output / "plan.toml").write_text(plan)
    python(ROOT / "main.py", "batch", output / "plan.toml", "--output", output / "batch", log=output / "batch.log")
    python(ROOT / "main.py", "summarize", output / "batch", log=output / "recomputed-summary.json")
    batch = json.loads((output / "batch/batch.json").read_text())
    if not batch["summary"]["complete"] or any(g["success_rate"] != 0 for g in batch["summary"]["groups"]):
        raise ValueError("Expected complete batch coverage and zero protocol-probe task successes.")
    summary = {"run_kind": "public_preview_smoke", "task": CASE_ID, "reference": "passed",
               "protocol_probe": "expected_failure", "canonical_probe": "expected_failure",
               "batch": "complete", "model_called": False}
    (output / "preview.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"PASS: reference, explicit submission and batch statistics. No model was called. Summary: {output / 'preview.json'}")


def quickstart(output, image, network, skip_build):
    doctor()
    if not skip_build:
        _check_build_network(network)
    output = new_directory(output or ROOT / RUNS / datetime.now(UTC).strftime("preview-%Y%m%dT%H%M%S%fZ"))
    print(f"Preview directory: {output}", flush=True)
    if not skip_build:
        build(image, network)
    ensure_pdk()
    prepare(output / "prepared", image)
    run(output / "prepared", output / "run", False)
    print(f"Ready with the bundled harness probes: {output / 'prepared/protocol-probe.toml'} and "
          f"{output / 'prepared/canonical-probe.toml'}\n"
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
        command = commands.add_parser(name, help="Run public reference/probe/batch checks" if name == "run" else "Repeat the public fixture checks as a qualification smoke test")
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
