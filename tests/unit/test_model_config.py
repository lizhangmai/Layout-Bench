"""Run configuration keeps credential-like values out of public Agent env."""

import pytest

from benchmarking.model_config import load_run_config

pytestmark = pytest.mark.unit


def _config(tmp_path, environment):
    path = tmp_path / "agent.toml"
    lines = [
        "schema_version = 1",
        'id = "test-agent"',
        'image = "synthetic:tag"',
        'command = ["python", "-c", "pass"]',
        "wall_seconds = 10",
        "memory_mb = 128",
        "cpus = 1",
        "pids = 16",
        "workspace_mb = 4",
        "",
        "[environment]",
    ]
    lines.extend(f'{name} = "{value}"' for name, value in environment.items())
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.mark.parametrize(
    "name",
    ["OPENAI_API_KEY", "GITHUB_TOKEN", "DATABASE_SECRET", "DB_PASSWORD"],
)
def test_credential_like_environment_names_are_rejected(tmp_path, name):
    with pytest.raises(ValueError, match="(?i)credential"):
        load_run_config(_config(tmp_path, {name: "not-a-real-secret"}))


def test_credential_like_environment_names_are_rejected_case_insensitively(tmp_path):
    with pytest.raises(ValueError, match="(?i)credential"):
        load_run_config(_config(tmp_path, {"service_token": "not-a-real-secret"}))


def test_tool_environment_names_remain_supported(tmp_path):
    config = load_run_config(
        _config(
            tmp_path,
            {"KLAYOUT": "1", "PYTHONPATH": "/workspace/lib", "PDK_ROOT": "/workspace/pdk"},
        )
    )

    assert config.environment == {
        "KLAYOUT": "1",
        "PYTHONPATH": "/workspace/lib",
        "PDK_ROOT": "/workspace/pdk",
    }
