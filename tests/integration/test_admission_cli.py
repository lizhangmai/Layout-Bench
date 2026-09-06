"""Real containers and CLI release of synthetic hidden fixtures, with no model calls."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from admission_helpers import SECRET, approve, save_policy

from benchmarking.files import Asset

IMAGE = os.environ.get("LAYOUT_BENCH_TEST_IMAGE", "layout-bench-evaluator:local")

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def test_prepared_pinned_cli_and_hidden_material_export_boundary(tmp_path):
    evaluation = '''schema_version = 1
mode = "post_layout"
'''
    for gate in ("artifact", "drc", "lvs"):
        evaluation += f'''[[jobs]]
id = "{gate}"
stage = "check"
operation = "check"
gate = "{gate}"
inputs = {{layout = "candidate"}}
'''
    evaluation += '''[[jobs]]
id = "pex"
stage = "extract"
operation = "extract"
inputs = {layout = "candidate"}
requires = ["artifact", "drc", "lvs"]
outputs = {netlist = "spice"}
[[jobs]]
id = "sim"
stage = "simulate"
operation = "response"
inputs = {netlist = "job:pex:netlist"}
[[metrics]]
id = "synthetic"
category = "performance"
observations = ["sim:value"]
unit = "s"
direction = "minimize"
aggregation = "max"
upper = 1.0
'''
    # No submission: the fixture bindings are inspected but never used to judge layout.
    (tmp_path / "tools.toml").write_text('''schema_version = 1
[backends.fixture]
type = "klayout-docker"
settings = {image = "layout-bench-evaluator:local", check = "artifact"}
[bindings]
check = "fixture"
extract = "fixture"
response = "fixture"
'''.replace('"layout-bench-evaluator:local"', json.dumps(IMAGE)))
    plan = '''schema_version = 1
id = "synthetic-admission-probe"
scope = "synthetic"
repetitions = 2
order = "interleaved"
seed = 0
max_infrastructure_retries = 0
'''
    for i in range(3):
        directory = tmp_path / f"task-{i}"
        directory.mkdir()
        files = {"netlist": (f"* SYNTHETIC_CURRENT_INPUT_{i}\n.subckt FIXTURE A B\n.ends\n".encode(), "spice"),
                 "constraints": (b"{}", "json"), "evaluation": (evaluation.encode(), "toml")}
        task = f'''schema_version = 1
id = "synthetic-task-{i}"
title = "Synthetic access boundary fixture"
kind = "netlist_to_gds"
family = "family-{i % 2}"
status = "candidate"
environment = "synthetic"
[output]
path = "output/final.gds"
format = "gds"
top_cell = "FIXTURE"
max_bytes = 1024
'''
        for role, (raw, file_format) in files.items():
            (directory / role).write_bytes(raw)
            task += f'\n[inputs.{role}]\npath = "{role}"\nformat = "{file_format}"\nsha256 = "{Asset(raw, file_format).sha256}"\n'
            if role == "netlist":
                task += 'subcircuit = "FIXTURE"\n'
        (directory / "task.toml").write_text(task)
        (directory / "reference.gds").write_text(SECRET)
        plan += f'\n[[tasks]]\nconfig = "task-{i}/task.toml"\ntoolchain = "tools.toml"\n'
    plan += '\n[[agents]]\nid = "probe"\nconfig = "agent.toml"\n'
    (tmp_path / "plan.toml").write_text(plan)
    script = b'''from pathlib import Path
assert not Path('/workspace/memory').exists()
Path('/workspace/memory').write_text('private repeat memory')
assert {p.name for p in Path('/task').iterdir()} == {'netlist', 'constraints', 'evaluation'}
assert not Path('/task/reference.gds').exists()
assert not Path('/protocol/execution.json').exists()
assert not Path('/protocol/policy.json').exists()
assert not Path('/resources/authorization.txt').exists()
current = Path('/task/netlist').read_text()
assert current.count('SYNTHETIC_CURRENT_INPUT_') == 1
print(current, flush=True)
print('SYNTHETIC_PRIVATE_GENERATED_GDS_AND_LOG', flush=True)
'''
    (tmp_path / "cli.py").write_bytes(script)
    (tmp_path / "agent.toml").write_text(f'''schema_version = 1
id = "probe"
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

    def cli(*arguments):
        return subprocess.run([sys.executable, str(ROOT / "main.py"), *map(str, arguments)], cwd=tmp_path,
                              capture_output=True, text=True, timeout=90, check=False)

    prepared = cli("batch", tmp_path / "plan.toml", "--prepare-only", "--output", tmp_path / "prepared")
    assert prepared.returncode == 0, prepared.stderr
    assert json.loads(prepared.stdout)["outcome"] == "prepared"
    assert not (tmp_path / "prepared/runs").exists()
    manifest = json.loads((tmp_path / "prepared/execution.json").read_text())
    operator = tmp_path / "operator"
    policy = save_policy(operator, approve(operator, manifest))
    denied = cli("batch", tmp_path / "plan.toml", "--policy", operator / "policy.json",
                 "--policy-sha256", "0"*64, "--output", tmp_path / "denied")
    assert denied.returncode == 2 and not (tmp_path / "denied").exists()
    result = cli("batch", tmp_path / "plan.toml", "--policy", operator / "policy.json",
                 "--policy-sha256", policy.source.sha256, "--output", tmp_path / "run")
    assert result.returncode == 0, result.stderr
    assert "summary" not in json.loads(result.stdout)
    batch = json.loads((tmp_path / "run/batch.json").read_text())
    assert len(batch["attempts"]) == 6
    for attempt in batch["attempts"]:
        run = json.loads((tmp_path / "run" / attempt["report"]["path"]).read_text())
        assert run["termination"] == "completed", run
        assert run["outcome"] == "no_submission"
    released = cli("export", tmp_path / "run", "--policy-sha256", policy.source.sha256)
    assert released.returncode == 0, released.stderr
    group = json.loads(released.stdout)["groups"][0]
    assert group["trials"] == 6 and group["success_rate"] == 0
    assert group["run_kind"] == "offline_cli_development"
    for excluded in (SECRET, "SYNTHETIC_CURRENT_INPUT_", "SYNTHETIC_PRIVATE_GENERATED", "synthetic-task-", "artifacts/", str(tmp_path)):
        assert excluded not in released.stdout
    refused = cli("export", tmp_path / "run", "--policy-sha256", "0"*64)
    assert refused.returncode == 2 and refused.stdout == ""
    assert str(tmp_path) not in refused.stderr and SECRET not in refused.stderr
