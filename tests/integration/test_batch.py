"""The public batch CLI creates fresh real containers; no model or layout score."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from benchmarking.files import Asset
from benchmarking.tasks import load_task

IMAGE = os.environ.get("LAYOUT_BENCH_TEST_IMAGE", "layout-bench-tools:local")

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def test_cli_batch_fresh_sessions_and_recomputed_summary(tmp_path):
    task_path = ROOT / "tasks/IHP-AnalogAcademy/module_3_8_bit_SAR_ADC/part_2_digital_comps/T_gate/task.toml"
    task = load_task(task_path)
    # Nothing is submitted, so these fixture bindings are never invoked as a judge.
    tools = 'schema_version = 1\n[backends.fixture]\ntype = "klayout-docker"\nsettings = {image = "layout-bench-tools:local", check = "artifact"}\n[bindings]\n'
    tools += ''.join(f'"{job.operation}" = "fixture"\n' for job in {job.operation: job for job in task.evaluation.jobs}.values())
    (tmp_path / "tools.toml").write_text(tools.replace('"layout-bench-tools:local"', json.dumps(IMAGE)))
    script = b'''from pathlib import Path
assert not Path('/workspace/memory').exists()
Path('/workspace/memory').write_text('must not reach the next repeat')
assert not Path('/task/reference').exists()
assert not Path('/protocol/execution.json').exists()
print('fresh workspace', flush=True)
'''
    (tmp_path / "cli.py").write_bytes(script)
    (tmp_path / "agent.toml").write_text(f'''schema_version = 1
id = "fresh-session-probe"
image = {json.dumps(IMAGE)}
command = ["python", "/agent/cli.py"]
wall_seconds = 10
memory_mb = 128
cpus = 1
pids = 16
workspace_mb = 4
[[files]]
path = "cli.py"
target = "cli.py"
sha256 = "{Asset(script, 'python').sha256}"
''')
    (tmp_path / "plan.toml").write_text(f'''schema_version = 1
id = "cli-batch-probe"
scope = "synthetic"
repetitions = 2
order = "interleaved"
seed = 0
max_infrastructure_retries = 0
[[tasks]]
config = "{task_path}"
toolchain = "tools.toml"
[[agents]]
id = "probe"
config = "agent.toml"
''')
    command = subprocess.run([sys.executable, str(ROOT / "main.py"), "batch", str(tmp_path / "plan.toml"),
                              "--output", str(tmp_path / "run")], cwd=tmp_path,
                             capture_output=True, text=True, timeout=30, check=False)
    assert command.returncode == 0, command.stderr
    batch = json.loads((tmp_path / "run/batch.json").read_text())
    group = batch["summary"]["groups"][0]
    assert batch["outcome"] == "complete" and group["success_rate"] == 0
    assert group["run_kind"] == "offline_cli_development"
    containers = set()
    for entry in batch["attempts"]:
        directory = tmp_path / "run" / entry["path"]
        report = json.loads((directory / "run.json").read_text())
        assert report["termination"] == "completed" and report["outcome"] == "no_submission"
        for line in (directory / "events.jsonl").read_text().splitlines():
            event = json.loads(line)
            if event["kind"] == "session.created":
                containers.add(event["data"]["container_id"])
    assert len(containers) == 2
    summary = subprocess.run([sys.executable, str(ROOT / "main.py"), "summarize", str(tmp_path / "run")],
                             cwd=tmp_path, capture_output=True, text=True, timeout=10, check=False)
    assert summary.returncode == 0, summary.stderr
    assert json.loads(summary.stdout) == batch["summary"]
    execution = json.loads((tmp_path / "run/execution.json").read_text())
    assert execution["framework"]["git"]["commit"]
    assert execution["host"]["concurrency"] == 1
