"""Preview configuration stays usable with just one arbitrarily named image."""

import importlib.util
import shutil
import tomllib
from pathlib import Path

import pytest

from benchmarking import environment, prepare_support
from benchmarking.model_config import load_run_config

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def preview():
    spec = importlib.util.spec_from_file_location("public_preview", ROOT / "scripts/public_preview.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_one_resolved_image_for_compilation_judge_and_agents(preview, tmp_path, monkeypatch):
    root = tmp_path / "checkout with spaces"
    (root / "third_party/IHP-Open-PDK/ihp-sg13g2").mkdir(parents=True)
    shutil.copytree(ROOT / "examples/agents", root / "examples/agents")
    monkeypatch.setattr(preview, "ROOT", root)
    monkeypatch.setattr(environment, "prepare_pdk", lambda source, output: output.mkdir())
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
    preview.prepare(destination, "my-unified-image:reviewed")
    assert inspected == ["my-unified-image:reviewed"]
    assert set(compilers) == {identity}
    toolchain = tomllib.loads((destination / "toolchain.toml").read_text())
    for backend in toolchain["backends"].values():
        assert backend["settings"]["image"] == identity
        if path := backend["settings"].get("support"):
            assert Path(path).is_dir() and Path(path).parent == destination
    probe = load_run_config(destination / "protocol-probe.toml")
    assert probe.image == identity
    assert probe.files["protocol_probe.py"].content == (ROOT / "examples/agents/protocol_probe.py").read_bytes()
    canonical = load_run_config(destination / "canonical-probe.toml")
    assert canonical.image == identity
    assert canonical.files["canonical_harness.py"].content == (ROOT / "examples/agents/canonical_harness.py").read_bytes()
    assert canonical.files["canonical_probe_adapter.py"].content == (
        ROOT / "examples/agents/canonical_probe_adapter.py"
    ).read_bytes()
    assert (destination / "agent-resources").is_dir()


def test_existing_evidence_rejected_before_build_or_pdk_update(preview, tmp_path, monkeypatch):
    evidence = tmp_path / "run.json"
    evidence.write_text("retained evidence")
    monkeypatch.setattr(preview, "doctor", lambda: None)
    monkeypatch.setattr(preview, "call", lambda *args, **kwargs: pytest.fail("Must not run preparation commands"))
    with pytest.raises(ValueError, match="Output already exists"):
        preview.quickstart(tmp_path, preview.IMAGE, "default", False)
    assert evidence.read_text() == "retained evidence"


def _populate_required_pdk(root, preview, *, complete=True):
    pdk = root / preview.PDK_PATH
    pdk.mkdir(parents=True)
    (pdk / ".git").write_text("gitdir: synthetic\n")
    for relative, marker in preview.PDK_REQUIRED_SUBMODULES.items():
        path = pdk / relative
        path.mkdir(parents=True)
        if complete:
            (path / marker).parent.mkdir(parents=True, exist_ok=True)
            (path / marker).write_bytes(b"synthetic")
    return pdk


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
