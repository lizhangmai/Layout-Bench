import hashlib
import json
from pathlib import Path

import pytest

from benchmarking.tasks import load_task

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def package(tmp_path):
    files = {
        "input/spec.spice": b".subckt SYNTHETIC A B\n.ends\n",
        "input/constraints.json": b'{"hard": []}\n',
    }
    for path, content in files.items():
        file = tmp_path / path
        file.parent.mkdir(exist_ok=True)
        file.write_bytes(content)
    provenance = tmp_path / "provenance.json"
    provenance.write_text('{"note": "maintainer only"}\n')
    (tmp_path / "unlisted.txt").write_text("must not reach the solver")
    config = '''schema_version = 1
id = "synthetic"
title = "Synthetic input preparation test"
kind = "netlist_to_gds"
family = "synthetic"
status = "candidate"
environment = "synthetic-tools"

[inputs.netlist]
path = "input/spec.spice"
sha256 = "NETLIST_HASH"
subcircuit = "SYNTHETIC"

[inputs.constraints]
path = "input/constraints.json"
sha256 = "CONSTRAINTS_HASH"

[provenance]
path = "provenance.json"
sha256 = "PROVENANCE_HASH"

[output]
path = "deliverables/chip.gds"
format = "gds"
top_cell = "SYNTHETIC"
max_bytes = 1048576
'''
    for placeholder, path in (
        ("NETLIST_HASH", "input/spec.spice"),
        ("CONSTRAINTS_HASH", "input/constraints.json"),
        ("PROVENANCE_HASH", "provenance.json"),
    ):
        config = config.replace(placeholder, hashlib.sha256((tmp_path / path).read_bytes()).hexdigest())
    path = tmp_path / "task.toml"
    path.write_text(config)
    return path


def replace(config: Path, before: str, after: str):
    config.write_text(config.read_text().replace(before, after))


def test_materialization_uses_validated_snapshot_and_configured_io(package, tmp_path):
    task = load_task(package)
    original = (tmp_path / "input/spec.spice").read_bytes()
    (tmp_path / "input/spec.spice").write_text("changed after loading")
    destination = tmp_path / "run-inputs"
    task.materialize(destination)
    assert (destination / "input/spec.spice").read_bytes() == original
    assert sorted(p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()) == [
        "input/constraints.json", "input/spec.spice",
    ]
    description = task.description()
    assert description["inputs"]["netlist"] == "/task/input/spec.spice"
    assert description["output"]["path"] == "/workspace/deliverables/chip.gds"
    assert description["output"]["top_cell"] == "SYNTHETIC"
    assert description["netlist_subcircuit"] == "SYNTHETIC"
    assert "maintainer only" not in json.dumps(description)
    assert (destination / "input/spec.spice").stat().st_mode & 0o222 == 0


def test_candidate_circuit_case_without_task_is_not_an_executable_task():
    config = ROOT / (
        "tasks/IHP-AnalogAcademy/cases/"
        "module_1_bandgap_reference.part_3_layout.OTA_layout.full_OTA.toml"
    )
    with pytest.raises(ValueError, match="does not declare an executable task"):
        load_task(config)


def test_changed_input_is_rejected(package, tmp_path):
    (tmp_path / "input/spec.spice").write_text("unreviewed content")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_task(package)


@pytest.mark.parametrize("path", ["../escape.gds", "/absolute.gds", "a/../final.gds", "a//b.gds", "a\\b.gds"])
def test_unsafe_output_path_is_rejected(package, path):
    replace(package, '"deliverables/chip.gds"', json.dumps(path))
    with pytest.raises(ValueError, match="relative POSIX"):
        load_task(package)


def test_input_cannot_escape_package(package):
    replace(package, 'path = "input/spec.spice"', 'path = "../outside.spice"')
    with pytest.raises(ValueError, match="relative POSIX"):
        load_task(package)


def test_symlinked_input_is_rejected(package, tmp_path):
    original = tmp_path / "input/spec.spice"
    original.rename(tmp_path / "source.spice")
    original.symlink_to(tmp_path / "source.spice")
    with pytest.raises(ValueError, match="non-symlink"):
        load_task(package)


def test_unknown_output_field_is_not_silently_ignored(package):
    replace(package, "top_cell =", "topcell =")
    with pytest.raises(ValueError, match="top_cell"):
        load_task(package)


def test_missing_required_input_is_rejected(package):
    replace(package, "[inputs.constraints]", "[inputs.other]")
    with pytest.raises(ValueError, match="constraints"):
        load_task(package)


def test_existing_destination_is_preserved(package, tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "work.txt"
    sentinel.write_text("existing work")
    with pytest.raises(FileExistsError):
        load_task(package).materialize(destination)
    assert sentinel.read_text() == "existing work"


def test_output_change_changes_task_identity(package):
    original = load_task(package)
    replace(package, "deliverables/chip.gds", "output/final.gds")
    updated = load_task(package)
    assert original.digest != updated.digest
    assert updated.description()["output"]["path"] == "/workspace/output/final.gds"


def test_preparation_provenance_cannot_become_input(package):
    replace(package, 'path = "provenance.json"', 'path = "input/spec.spice"')
    with pytest.raises(ValueError, match="must not be an Agent input"):
        load_task(package)


def add_evaluation(package, *, reference="input:netlist"):
    root = package.parent
    plan = f'''schema_version = 1
mode = "characterization"
[[jobs]]
id = "dc"
stage = "simulate"
operation = "circuit.measure"
inputs = {{ dut = "{reference}", deck = "input:testbench" }}
[[metrics]]
id = "gain"
category = "performance"
observations = ["dc:gain"]
unit = "1"
direction = "maximize"
aggregation = "min"
lower = 1.0
'''
    files = {"evaluation": ("evaluation/plan.toml", plan, "toml"),
             "testbench": ("evaluation/testbench.spice", "* generic testbench", "spice")}
    additions = ""
    for role, (relative, contents, file_format) in files.items():
        path = root / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text(contents)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        additions += f'\n[inputs.{role}]\npath = "{relative}"\nsha256 = "{digest}"\nformat = "{file_format}"\n'
    package.write_text(package.read_text() + additions)


def test_evaluation_and_arbitrary_named_testbenches_are_frozen_inputs(package, tmp_path):
    add_evaluation(package)
    task = load_task(package)
    assert task.evaluation.jobs[0].operation == "circuit.measure"
    assert task.evaluation_inputs()["input:testbench"].format == "spice"
    before = task.evaluation.sha256
    (tmp_path / "evaluation/plan.toml").write_text("changed after loading")
    destination = tmp_path / "prepared"
    task.materialize(destination)
    assert hashlib.sha256((destination / "evaluation/plan.toml").read_bytes()).hexdigest() == before
    assert task.description()["evaluation"]["metrics"][0]["id"] == "gain"
    assert not (destination / "provenance.json").exists()


def test_evaluation_cannot_reference_an_undeclared_input(package):
    add_evaluation(package, reference="input:private_reference")
    with pytest.raises(ValueError, match="undeclared task input"):
        load_task(package)


def test_evaluator_gets_configured_top_and_subcircuit_from_frozen_task_metadata(package):
    add_evaluation(package, reference="task")
    task = load_task(package)
    replace(package, 'top_cell = "SYNTHETIC"', 'top_cell = "changed"')
    metadata = task.evaluation_inputs()["task"]
    assert metadata.format == "json"
    contents = json.loads(metadata.content)
    assert contents["output"]["top_cell"] == "SYNTHETIC"
    assert contents["netlist_subcircuit"] == "SYNTHETIC"
    assert "provenance" not in contents


def test_evaluation_definition_is_hash_checked(package, tmp_path):
    add_evaluation(package)
    plan = tmp_path / "evaluation/plan.toml"
    plan.write_text(plan.read_text().replace("lower = 1.0", "lower = 0.0"))
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_task(package)
