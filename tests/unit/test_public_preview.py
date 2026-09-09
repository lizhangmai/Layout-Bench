"""Preview configuration stays usable with just one arbitrarily named image."""

import importlib.util
import json
import re
import tomllib
from pathlib import Path

import pytest
from protocol_helpers import write_protocol_task

from benchmarking import environment, prepare_support
from benchmarking.tasks import load_task

pytestmark = [pytest.mark.unit, pytest.mark.acceptance, pytest.mark.acceptance_fast]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def preview():
    spec = importlib.util.spec_from_file_location("public_preview", ROOT / "scripts/public_preview.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_build_network_explains_loopback_proxy(preview, monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:25127")

    with pytest.raises(ValueError, match="loopback proxy"):
        preview._check_build_network("default")

    preview._check_build_network("host")


@pytest.fixture
def preview_case(preview, tmp_path, monkeypatch, circuit_case):
    root = tmp_path / "checkout with spaces"
    source = root / "tasks/IHP-AnalogAcademy/cases/synthetic"
    task_path = write_protocol_task(source)
    body = task_path.read_text().split("[inputs.netlist]", 1)[1]
    body = re.sub(r"^(\[\[?)", r"\1task.", "[inputs.netlist]" + body, flags=re.MULTILINE)
    config = circuit_case.read_text().replace('status = "candidate"', 'status = "qualified"')
    config += '\n[task]\nkind = "netlist_to_gds"\nfamily = "protocol"\nenvironment = "no-eda"\n' + body
    config += '''
[qualification]
reference = "reference.gds"
evidence = "README.md"
[toolchain]
schema_version = 1
[toolchain.backends.rules]
type = "klayout-docker"
settings = {image = "synthetic-image", support = "source-rules", check = "drc", profile = "reviewed.json"}
[toolchain.backends.simulation]
type = "ngspice-docker"
settings = {image = "synthetic-image", support = "source-models"}
[toolchain.bindings]
check = "rules"
simulate = "simulation"
'''
    (source / "case.toml").write_text(config)
    (source / "reference.gds").write_bytes(b"Maintainer-only witness")
    (source / "README.md").write_text("Maintainer-only provenance")
    (root / "third_party/IHP-Open-PDK/ihp-sg13g2").mkdir(parents=True)
    monkeypatch.setattr(preview, "ROOT", root)
    monkeypatch.setattr(preview, "CASE_MODELS", {"synthetic": "models"})
    return root, source


def test_preparation_binds_image_and_support_without_delivering_reference(preview, preview_case, monkeypatch):
    root, source = preview_case
    monkeypatch.setattr(environment, "prepare_pdk_bundle", lambda source, output: output.mkdir())
    inspected, compilers = [], []
    identity = "sha256:" + "a" * 64

    def inspect(command, **kwargs):
        inspected.append(command[-1])
        return identity + "\n"

    def support(source, profile, output, *, compiler_image):
        compilers.append(compiler_image)
        output.mkdir()

    monkeypatch.setattr(preview.subprocess, "check_output", inspect)
    monkeypatch.setattr(prepare_support, "prepare_support", support)
    destination = root / "prepared"
    preview.prepare(destination, "my-unified-image:reviewed", "synthetic")
    assert inspected == ["my-unified-image:reviewed"]
    assert set(compilers) == {identity}
    bound_case = destination / "case/case.toml"
    toolchain = tomllib.loads(bound_case.read_text())["toolchain"]
    for backend in toolchain["backends"].values():
        assert backend["settings"]["image"] == identity
        path = Path(backend["settings"]["support"])
        assert path.is_dir() and path.parent == destination
    assert toolchain["backends"]["rules"]["settings"]["profile"] == "reviewed.json"
    task = load_task(bound_case)
    assert task.evaluation.description() == load_task(source / "case.toml").evaluation.description()
    task.materialize(root / "solver")
    assert (root / "solver/input.spice").read_bytes() == (source / "input.spice").read_bytes()
    assert not (root / "solver/reference.gds").exists()
    assert not (root / "solver/README.md").exists()
    assert not (root / "solver/case.toml").exists()
    assert (bound_case.parent / "reference.gds").read_bytes() == b"Maintainer-only witness"


@pytest.mark.parametrize("success", [True, False])
def test_reference_run_requires_actual_task_success(preview, preview_case, monkeypatch, success):
    root, source = preview_case
    prepared = root / "prepared"
    prepared.mkdir()
    source.rename(prepared / "case")

    def evaluate(*args, **kwargs):
        report_dir = Path(args[args.index("--output") + 1])
        report_dir.mkdir()
        (report_dir / "report.json").write_text(json.dumps({
            "outcome": "passed" if success else "failed", "task_success": success,
        }))

    monkeypatch.setattr(preview, "python", evaluate)
    output = root / "run"
    if not success:
        with pytest.raises(ValueError, match="complete evaluation"):
            preview.run(prepared, output)
        assert not (output / "preview.json").exists()
    else:
        preview.run(prepared, output)
        summary = json.loads((output / "preview.json").read_text())
        assert summary["reference"] == "passed" and summary["model_called"] is False


def test_existing_evidence_rejected_before_build_or_pdk_update(preview, tmp_path, monkeypatch):
    evidence = tmp_path / "run.json"
    evidence.write_text("retained evidence")
    monkeypatch.setattr(preview, "doctor", lambda: None)
    monkeypatch.setattr(preview, "_check_build_network", lambda network: None)
    monkeypatch.setattr(preview, "call", lambda *args, **kwargs: pytest.fail("Must not run preparation commands"))
    with pytest.raises(ValueError, match="Output already exists"):
        preview.quickstart(tmp_path, preview.IMAGE, "default", False)
    assert evidence.read_text() == "retained evidence"


def test_quickstart_skip_build_reuses_prepared_resources(preview, tmp_path, monkeypatch):
    monkeypatch.setattr(preview, "doctor", lambda: None)
    monkeypatch.setattr(preview, "build", lambda *args: pytest.fail("--skip-build must not build an image"))
    monkeypatch.setattr(preview, "ensure_pdk", lambda: None)
    completed = []

    def prepare(destination, image, case):
        assert case == "comparator"
        assert image == "synthetic-tools:local"
        destination.mkdir()
        (destination / "sentinel").write_text("prepared resources")

    def run(prepared, output):
        assert (prepared / "sentinel").read_text() == "prepared resources"
        assert output.is_relative_to(tmp_path / "skip-build")
        completed.append(output)

    monkeypatch.setattr(preview, "prepare", prepare)
    monkeypatch.setattr(preview, "run", run)

    output = tmp_path / "skip-build"
    preview.quickstart(output, "synthetic-tools:local", "host", True)

    assert len(completed) == 1


def _populate_required_pdk(root, preview, *, complete=True):
    pdk = root / preview.PDK_PATH
    pdk.mkdir(parents=True, exist_ok=True)
    (pdk / ".git").write_text("gitdir: synthetic\n")
    for relative, marker in preview.PDK_REQUIRED_SUBMODULES.items():
        path = pdk / relative
        path.mkdir(parents=True)
        if complete:
            (path / marker).parent.mkdir(parents=True, exist_ok=True)
            (path / marker).write_bytes(b"synthetic")
    return pdk


@pytest.mark.parametrize("empty_directory", [False, True], ids=["absent", "empty-checkout"])
def test_pdk_initializes_an_unpopulated_checkout(preview, tmp_path, monkeypatch, empty_directory):
    root = tmp_path / "checkout"
    if empty_directory:
        # A Git checkout without submodule initialization leaves this directory.
        (root / preview.PDK_PATH).mkdir(parents=True)
    monkeypatch.setattr(preview, "ROOT", root)
    commands = []

    def update(*args, **kwargs):
        commands.append(args)
        _populate_required_pdk(root, preview)

    monkeypatch.setattr(preview, "call", update)
    preview.ensure_pdk()

    assert commands == [("git", "submodule", "update", "--init", "--depth", "1",
                         "third_party/IHP-Open-PDK")]


@pytest.mark.parametrize("complete", [False, True], ids=["incomplete", "complete"])
def test_pdk_preserves_populated_directories_without_git_metadata(preview, tmp_path, monkeypatch, complete):
    pdk = _populate_required_pdk(tmp_path, preview, complete=complete)
    (pdk / ".git").unlink()
    local_file = pdk / "local.txt"
    local_file.write_text("Retain local contents")
    monkeypatch.setattr(preview, "ROOT", tmp_path)
    monkeypatch.setattr(preview, "call", lambda *args, **kwargs: pytest.fail("Must not clone over local files"))

    if complete:
        preview.ensure_pdk()
    else:
        with pytest.raises(ValueError, match="no Git metadata"):
            preview.ensure_pdk()
    assert local_file.read_text() == "Retain local contents"


def test_pdk_update_does_not_recurse_into_optional_nested_submodules(preview, tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    pdk = _populate_required_pdk(root, preview)
    optional = pdk / "ihp-sg13g2/libs.tech/digital"
    optional.mkdir(parents=True)
    (optional / "README").write_text("untracked optional checkout")
    monkeypatch.setattr(preview, "ROOT", root)
    commands = []
    monkeypatch.setattr(preview, "call", lambda *args, **kwargs: commands.append(args))

    preview.ensure_pdk()

    assert commands == [("git", "submodule", "update", "--init", "--depth", "1",
                         "third_party/IHP-Open-PDK")]


def test_pdk_update_explains_incomplete_non_git_nested_directory(preview, tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    pdk = _populate_required_pdk(root, preview, complete=False)
    nested = pdk / next(iter(preview.PDK_REQUIRED_SUBMODULES))
    (nested / "untracked.txt").write_text("partial checkout")
    monkeypatch.setattr(preview, "ROOT", root)
    commands = []
    monkeypatch.setattr(preview, "call", lambda *args, **kwargs: commands.append(args))

    with pytest.raises(ValueError, match="non-empty directory without Git metadata") as error:
        preview.ensure_pdk()

    assert "git -C third_party/IHP-Open-PDK submodule update --init --depth 1" in str(error.value)
    assert not any("--recursive" in command for args in commands for command in args)


def test_pdk_update_initializes_only_missing_required_nested_submodules(preview, tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    pdk = _populate_required_pdk(root, preview, complete=False)
    monkeypatch.setattr(preview, "ROOT", root)
    commands = []

    def update(*args, **kwargs):
        commands.append(args)
        if args[1:3] == ("-C", pdk):
            for relative in args[8:]:
                relative = Path(relative)
                marker = preview.PDK_REQUIRED_SUBMODULES[relative]
                target = pdk / relative / marker
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"synthetic")

    monkeypatch.setattr(preview, "call", update)
    preview.ensure_pdk()

    assert commands[0][-1] == "third_party/IHP-Open-PDK"
    assert commands[1][:7] == ("git", "-C", pdk, "submodule", "update", "--init", "--depth")
    assert set(commands[1][8:]) == {str(path) for path in preview.PDK_REQUIRED_SUBMODULES}
    assert "--recursive" not in commands[1]
