"""Real OTA reference, source calibration and minimal rejection checks."""

import cmath
import json
import math
import struct
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from benchmarking.evaluate import run_evaluation
from benchmarking.evaluation import parse_evaluation
from benchmarking.files import Asset, read_file
from benchmarking.prepare_support import prepare_support
from benchmarking.tasks import load_task
from benchmarking.toolchains import load_toolchain

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "tasks/IHP-AnalogAcademy/cases/full_OTA"


def declared_asset(config, role):
    entry = next(asset for asset in config["assets"] if asset["role"] == role)
    asset = Asset(read_file(CASE, entry["path"]), entry["format"])
    assert asset.sha256 == entry["sha256"], entry["path"]
    return asset


@pytest.fixture(scope="module")
def environment(tmp_path_factory):
    root = tmp_path_factory.mktemp("full-ota-support")
    config = (CASE / "case.toml").read_text()
    # Freeze just the declared inputs and host configuration for this check.
    load_task(CASE / "case.toml").materialize(root / "case")
    for profile, name in [("klayout", "klayout-spice"), ("magic", "magic"), ("analog-models", "models")]:
        prepare_support(ROOT / "third_party/IHP-Open-PDK", ROOT / f"technology/sg13g2/{profile}.json", root / name)
        config = config.replace(f"build/support/full-ota-{name}", str(root / name))
    path = root / "case/case.toml"
    path.write_text(config)
    return path, load_task(path), load_toolchain(path), tomllib.loads(config)


def evaluate(layout, environment, destination):
    config, _, _, _ = environment
    candidate = destination.with_suffix(".gds")
    candidate.write_bytes(layout.content)
    completed = subprocess.run(
        [sys.executable, "main.py", "evaluate", str(config), str(candidate), "--output", str(destination)],
        cwd=ROOT, capture_output=True, text=True, timeout=1200, check=False,
    )
    assert completed.returncode in (0, 1), completed.stdout + completed.stderr
    return completed.returncode, json.loads((destination / "report.json").read_text())


def raw_rows(path):
    """Read the real/complex binary vectors exported by ngspice on Linux x86-64."""
    header, binary = path.read_bytes().split(b"Binary:\n", 1)
    fields, variables = header.decode().split("Variables:\n", 1)
    metadata = dict(line.split(":", 1) for line in fields.splitlines())
    names = [line.split()[1] for line in variables.splitlines() if line.strip()]
    count = int(metadata["No. Points"])
    complex_values = "complex" in metadata["Flags"]
    values = [item[0] for item in struct.iter_unpack("<d", binary)]
    if complex_values:
        values = [complex(real, imaginary) for real, imaginary in zip(values[::2], values[1::2], strict=True)]
    assert len(names) == int(metadata["No. Variables"])
    assert len(values) == count * len(names)
    return [dict(zip(names, values[i:i + len(names)], strict=True)) for i in range(0, len(values), len(names))]


def check_waveform_measurements(report, destination):
    job = report["jobs"]["nominal"]
    ac = raw_rows(destination / job["outputs"]["ac"]["path"])
    op = raw_rows(destination / job["outputs"]["op"]["path"])[0]
    # Derive transfer from node voltages, without using the deck's computed
    # gain/phase vectors or copying the simulator's measurement output.
    transfer = [row["v(vout)"] / (row["v(vp)"] - row["v(vm)"]) for row in ac]
    gain = [20 * math.log10(abs(value)) for value in transfer]
    frequency = [row["frequency"].real for row in ac]
    phase = []
    for value in transfer:
        angle = math.degrees(cmath.phase(value))
        phase.append(angle if not phase else phase[-1] + (angle - phase[-1] + 180) % 360 - 180)
    assert frequency[0] == 1 and abs(phase[0]) < 1
    index = next(i for i in range(1, len(gain)) if gain[i - 1] > 0 >= gain[i])
    fraction = gain[index - 1] / (gain[index - 1] - gain[index])
    expected = {
        "low_frequency_gain": gain[0],
        "unity_gain_bandwidth": frequency[index - 1] + fraction * (frequency[index] - frequency[index - 1]),
        "phase_margin": 180 + phase[index - 1] + fraction * (phase[index] - phase[index - 1]),
        "supply_power": -op["v(vdd)"] * op["i(vdd)"],
        "output_bias": op["v(vout)"],
    }
    # Account for ngspice's printed measurement precision and interpolation.
    tolerances = {"low_frequency_gain": 1e-4, "unity_gain_bandwidth": 2,
                  "phase_margin": 1e-3, "supply_power": 1e-12, "output_bias": 1e-10}
    for name, value in expected.items():
        assert job["measurements"][name]["value"] == pytest.approx(value, abs=tolerances[name], rel=0)


@pytest.mark.acceptance_eda
def test_reference_passes_and_pre_post_calibration_uses_the_same_conditions(environment, tmp_path):
    _, task, backends, config = environment
    reference = declared_asset(config, "physical-witness")
    code, post = evaluate(reference, environment, tmp_path / "post")
    assert code == 0
    assert post["physical_valid"] is post["specs_pass"] is post["task_success"] is True
    assert all(job["status"] == "passed" for job in post["jobs"].values())
    pex = post["jobs"]["parasitics"]
    nominal = post["jobs"]["nominal"]
    assert pex["inputs"]["layout"]["sha256"] == reference.sha256
    assert nominal["inputs"]["dut"]["sha256"] == pex["outputs"]["netlist"]["sha256"]
    assert post["jobs"]["geometry"]["inputs"]["constraints"]["sha256"] == task.inline_constraints.sha256

    # Derive source characterization from the single authoritative case plan.
    # Simulate the matched schematic's separate SPICE export. Model calls
    # retain source ng/m; source-export regression checks its CDL equivalence.
    data = task.evaluation.description()
    simulation = next(job for job in data["jobs"] if job["id"] == "nominal")
    simulation["inputs"]["dut"] = "input:simulation"
    data.update(mode="characterization", jobs=[simulation],
                metrics=[metric for metric in data["metrics"] if metric["category"] == "performance"])
    pre = run_evaluation(parse_evaluation(json.dumps(data).encode(), file_format="json"),
                         task.evaluation_inputs(),
                         backends, tmp_path / "pre", task_sha256=task.digest)
    assert pre["outcome"] == "passed", pre["jobs"]
    assert pre["task_success"] is None
    assert pre["jobs"]["nominal"]["inputs"]["dut"]["sha256"] == task.evaluation_inputs()["input:simulation"].sha256
    assert pre["jobs"]["nominal"]["inputs"]["deck"] == nominal["inputs"]["deck"]
    assert pre["backends"]["circuit.simulate"] == post["backends"]["circuit.simulate"]
    check_waveform_measurements(pre, tmp_path / "pre")
    check_waveform_measurements(post, tmp_path / "post")


@pytest.mark.acceptance_eda
def test_rotated_reference_exceeds_height_and_blocks_pex(environment, tmp_path):
    _, _, backends, config = environment
    # 90-degree rotation preserves devices and connectivity but places the
    # reference's long axis along Y, exceeding the approved 50 um height.
    script = Asset(b'''from klayout import db
layout = db.Layout()
layout.read("original.gds")
layout.top_cell().transform(db.Trans(db.Trans.R90))
layout.write("rotated.gds")
''', "python")
    result = backends["layout.artifact"].tool.run(
        ["python", "rotate.py"], {"rotate.py": script, "original.gds": declared_asset(config, "physical-witness")},
        {"rotated.gds": "gds"})
    assert result.returncode == 0 and not result.reason, result.evidence
    code, report = evaluate(result.files["rotated.gds"], environment, tmp_path / "rotated")
    assert code == 1
    assert report["physical_valid"] is True, report["jobs"]
    assert report["jobs"]["geometry"]["status"] == "failed"
    assert report["task_success"] is False
    assert report["jobs"]["parasitics"]["status"] == report["jobs"]["nominal"]["status"] == "blocked"


def test_original_physical_failures_block_geometry_pex_and_simulation(environment, tmp_path):
    _, _, _, config = environment
    entry = next(asset for asset in config["upstream_assets"] if asset["id"] == config["upstream_evaluation"]["layout"])
    layout = Asset(read_file(ROOT / config["origin"]["checkout"], entry["path"]), "gds")
    assert layout.sha256 == entry["sha256"]
    code, report = evaluate(layout, environment, tmp_path / "original")
    assert code == 1
    assert report["physical_valid"] is report["task_success"] is False
    assert report["jobs"]["drc"]["status"] == report["jobs"]["lvs"]["status"] == "failed"
    for job in ("geometry", "parasitics", "nominal"):
        assert report["jobs"][job]["status"] == "blocked"
