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
    codex = load_run_config(destination / "codex-sg13g2.toml")
    assert probe.image == codex.image == identity
    assert probe.files["protocol_probe.py"].content == (ROOT / "examples/agents/protocol_probe.py").read_bytes()
    assert (destination / "agent-resources").is_dir()


def test_existing_evidence_rejected_before_build_or_pdk_update(preview, tmp_path, monkeypatch):
    evidence = tmp_path / "run.json"
    evidence.write_text("retained evidence")
    monkeypatch.setattr(preview, "doctor", lambda: None)
    monkeypatch.setattr(preview, "call", lambda *args, **kwargs: pytest.fail("Must not run preparation commands"))
    with pytest.raises(ValueError, match="Output already exists"):
        preview.quickstart(tmp_path, preview.IMAGE, "default", False)
    assert evidence.read_text() == "retained evidence"
