"""Harness profiles share one session protocol and stay independently identifiable."""

import pytest

from benchmarking.files import Asset
from benchmarking.harnesses import SESSION_PROTOCOL
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
