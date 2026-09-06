"""Harness profiles share one session protocol and stay independently identifiable."""

import pytest

from benchmarking.files import Asset
from benchmarking.harnesses import SESSION_PROTOCOL, prepare_harness
from benchmarking.model_config import load_run_config

pytestmark = pytest.mark.unit


def _config(tmp_path, harness, *, command='["python", "/agent/cli.py"]'):
    script = Asset(b"print('ok')", "python")
    (tmp_path / "cli.py").write_bytes(script.content)
    command_line = "" if command is None else f"command = {command}\n"
    path = tmp_path / "agent.toml"
    path.write_text(
        f'''schema_version = 1
id = "test-agent"
image = "synthetic:tag"
{command_line}
wall_seconds = 10
memory_mb = 128
cpus = 1
pids = 16
workspace_mb = 4
{harness}
[[files]]
path = "cli.py"
target = "cli.py"
sha256 = "{script.sha256}"
'''
    )
    return path


def test_external_harness_is_the_default_opaque_profile(tmp_path):
    config = load_run_config(_config(tmp_path, ""))

    assert config.harness.identity() == {
        "id": "external-cli",
        "version": "1",
        "protocol": SESSION_PROTOCOL,
        "mode": "opaque",
        "capabilities": [],
        "wire_api": None,
    }


def test_custom_harness_metadata_does_not_change_command_contract(tmp_path):
    config = load_run_config(
        _config(
            tmp_path,
            '''[harness]
id = "custom-runner"
version = "2026.1"
protocol = "layout-session.v1"
mode = "managed"
capabilities = ["tools"]
''',
        )
    )

    assert config.command == ("python", "/agent/cli.py")
    assert config.harness.mode == "managed"
    assert config.harness.capabilities == ("tools",)


def test_harness_table_can_use_external_defaults(tmp_path):
    config = load_run_config(_config(tmp_path, '''[harness]
mode = "managed"
'''))

    assert config.harness.id == "external-cli"
    assert config.harness.mode == "managed"


def test_builtin_codex_profile_is_only_a_harness_preparation(tmp_path):
    config = load_run_config(
        _config(
            tmp_path,
            '''[harness]
id = "codex"
''',
            command=None,
        )
    )

    assert config.command == ("python", "/agent/codex_cli.py")
    assert config.harness.mode == "native"
    assert config.harness.wire_api == "responses"
    assert "codex_cli.py" in config.files


def test_legacy_adapter_spelling_is_migrated_without_entering_run_config(tmp_path):
    path = _config(tmp_path, "")
    path.write_text(path.read_text().replace("[\"python\", \"/agent/cli.py\"]", "[\"python\", \"/agent/codex_cli.py\"]")
                     .replace("command = [\"python\", \"/agent/codex_cli.py\"]\n", "adapter = \"codex\"\n"))
    config = load_run_config(path)

    assert config.harness.id == "codex"
    assert config.command == ("python", "/agent/codex_cli.py")


def test_unknown_legacy_adapter_requires_the_generic_harness_table(tmp_path):
    path = _config(tmp_path, "")
    path.write_text(path.read_text().replace("command = [\"python\", \"/agent/cli.py\"]\n", "adapter = \"custom\"\n"))
    with pytest.raises(ValueError, match="Legacy adapter"):
        load_run_config(path)


@pytest.mark.parametrize("mode", ["", "unsupported"])
def test_unknown_harness_mode_is_rejected(tmp_path, mode):
    with pytest.raises(ValueError, match="harness.mode"):
        load_run_config(_config(tmp_path, f'''[harness]\nid = "runner"\nmode = "{mode}"\n'''))


def test_unknown_harness_protocol_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="harness.protocol"):
        load_run_config(_config(tmp_path, '''[harness]
id = "runner"
protocol = "other-session.v1"
'''))


def test_harness_preparation_rejects_codex_command_override():
    with pytest.raises(ValueError, match="supplies its own command"):
        prepare_harness(
            {"harness": {"id": "codex"}, "command": ["custom"]},
            "/tmp",
        )
