import os

import pytest

from benchmarking.model_config import load_run_config
from benchmarking.snapshot import snapshot

pytestmark = pytest.mark.unit


def test_snapshot_is_immutable_and_rejects_links_and_non_files(tmp_path):
    (tmp_path / "out").mkdir()
    file = tmp_path / "out/final.gds"
    file.write_bytes(b"first")
    frozen = snapshot(tmp_path, "out/final.gds", 16)
    file.write_bytes(b"second")
    assert frozen == b"first"
    with pytest.raises(ValueError, match="size limit"):
        snapshot(tmp_path, "out/final.gds", 3)
    (tmp_path / "link").symlink_to("out", target_is_directory=True)
    with pytest.raises(OSError):
        snapshot(tmp_path, "link/final.gds", 16)
    (tmp_path / "filelink").symlink_to(file)
    with pytest.raises(OSError):
        snapshot(tmp_path, "filelink", 16)
    os.link(file, tmp_path / "hardlink")
    with pytest.raises(ValueError, match="without links"):
        snapshot(tmp_path, "hardlink", 16)
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(ValueError, match="regular file"):
        snapshot(tmp_path, "pipe", 16)
    with pytest.raises((OSError, ValueError)):
        snapshot(tmp_path, "out", 16)


@pytest.mark.parametrize("path", ["../escape", "/etc/passwd", "out//final.gds", "./final.gds"])
def test_snapshot_rejects_path_escape(tmp_path, path):
    with pytest.raises(ValueError):
        snapshot(tmp_path, path, 16)


def test_run_config_freezes_declared_code_and_rejects_changes(tmp_path):
    from benchmarking.files import Asset

    script = Asset(b"print('hello')", "python")
    (tmp_path / "cli.py").write_bytes(script.content)
    config = tmp_path / "agent.toml"
    config.write_text(f'''schema_version = 1
id = "offline-test"
image = "layout-bench-tools:local"
command = ["python", "/agent/cli.py"]
wall_seconds = 10
memory_mb = 128
cpus = 1
pids = 32
workspace_mb = 16
[[files]]
path = "cli.py"
target = "cli.py"
sha256 = "{script.sha256}"
''')
    loaded = load_run_config(config)
    (tmp_path / "cli.py").write_bytes(b"changed")
    assert loaded.files["cli.py"].content == script.content
    with pytest.raises(ValueError, match="checksum"):
        load_run_config(config)
