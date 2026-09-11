"""The approved comparator witness and original DRC failure through one judge."""

import itertools
import json
import shutil
import struct
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarking.bundles import publish_bundle
from benchmarking.evaluate import run_evaluation
from benchmarking.evaluation import parse_evaluation
from benchmarking.files import Asset
from benchmarking.klayout import KLayoutDocker
from benchmarking.prepare_support import prepare_support
from benchmarking.tasks import load_task
from benchmarking.toolchains import load_toolchain

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "tasks/ihp-sg13g2/IHP-AnalogAcademy/cases/comparator"


@pytest.fixture(scope="module")
def case_config(tmp_path_factory):
    root = tmp_path_factory.mktemp("comparator-support")
    directory = root / "case"
    shutil.copytree(CASE, directory)
    path = directory / "case.toml"
    config = path.read_text()
    for profile, name in [("klayout", "klayout"), ("magic", "magic"), ("analog-models", "analog-models")]:
        prepare_support(ROOT / "third_party/IHP-Open-PDK", f"{ROOT}/tasks/ihp-sg13g2/pdk.toml#{profile}", root / name)
        config = config.replace(f"build/support/comparator-{name}", str(root / name))
    path.write_text(config)
    return path


def evaluate(candidate, case_config, destination):
    completed = subprocess.run(
        ["uv", "run", "--locked", "python", "main.py", "evaluate", str(case_config),
         str(candidate), "--output", str(destination)],
        cwd=ROOT, capture_output=True, text=True, timeout=1200, check=False,
    )
    assert (destination / "report.json").is_file(), completed.stdout + completed.stderr
    return completed, json.loads((destination / "report.json").read_text())


def check_transient_measurements(job, directory, polarity):
    """Recompute delay/margin/power from raw voltages/current, without .meas vectors."""
    path = directory / job["outputs"]["waveform"]["path"]
    header, binary = path.read_bytes().split(b"Binary:\n", 1)
    fields, variables = header.decode().split("Variables:\n", 1)
    metadata = dict(line.split(":", 1) for line in fields.splitlines())
    assert "real" in metadata["Flags"]
    names = [line.split()[1] for line in variables.splitlines() if line.strip()]
    values = [v[0] for v in struct.iter_unpack("<d", binary)]
    assert len(values) == len(names) * int(metadata["No. Points"])
    rows = [dict(zip(names, values[i:i + len(names)], strict=True))
            for i in range(0, len(values), len(names))]
    time = [row["time"] for row in rows]
    output = [polarity * (row["v(outp)"] - row["v(outm)"]) for row in rows]
    clock = [row["v(clk)"] for row in rows]

    def interpolate(x0, y0, x1, y1, x):
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)

    def window(vector, start, stop):
        samples = [(t, value) for t, value in zip(time, vector, strict=True) if start <= t <= stop]
        for edge in (start, stop):
            if not any(t == edge for t, _ in samples):
                i = next(i for i in range(1, len(time)) if time[i - 1] < edge < time[i])
                samples.append((edge, interpolate(time[i - 1], vector[i - 1], time[i], vector[i], edge)))
        return sorted(samples)

    def crossing(vector, threshold, start, stop, rising):
        points = window(vector, start, stop)
        for (t0, v0), (t1, v1) in itertools.pairwise(points):
            if (v0 < threshold <= v1) if rising else (v0 > threshold >= v1):
                return interpolate(v0, t0, v1, t1, threshold)
        pytest.fail("Missing waveform crossing")

    measurements = job["measurements"]
    for cycle in range(2, 10):
        trigger = crossing(clock, 0.6, cycle * 10e-9, (cycle + 1) * 10e-9, False)
        target = crossing(output, 1.0, cycle * 10e-9 + 5.75e-9, (cycle + 1) * 10e-9, True)
        # ngspice MIN selects samples inside the window; it does not add
        # interpolated boundary samples as the crossing/average operations do.
        margin = min(value for t, value in zip(time, output, strict=True)
                     if cycle * 10e-9 + 8.75e-9 <= t <= cycle * 10e-9 + 9.75e-9)
        # ngspice prints seven significant digits; allow interpolation roundoff.
        assert measurements[f"delay_c{cycle:02}"]["value"] == pytest.approx(target - trigger, abs=2e-14)
        assert measurements[f"margin_c{cycle:02}"]["value"] == pytest.approx(margin, abs=2e-6)
    points = window([-1.2 * row["i(vdd)"] for row in rows], 20e-9, 100e-9)
    energy = sum((t1 - t0) * (p0 + p1) / 2 for (t0, p0), (t1, p1) in itertools.pairwise(points))
    assert measurements["supply_power"]["value"] == pytest.approx(energy / 80e-9, rel=1e-4, abs=1e-10)


@pytest.mark.acceptance_eda
def test_reference_passes_complete_post_layout_evaluation(case_config, tmp_path):
    completed, report = evaluate(CASE / "reference/DIFF_COMPARATOR.gds", case_config, tmp_path / "reference")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert report["physical_valid"] is report["specs_pass"] is report["task_success"] is True
    assert report["outcome"] == "passed"
    task = load_task(case_config)
    assert report["jobs"]["geometry"]["inputs"]["constraints"]["sha256"] == task.evaluation_inputs()["input:constraints"].sha256
    assert set(report["jobs"]) == {job.id for job in task.evaluation.jobs}
    assert all(job["status"] == "passed" for job in report["jobs"].values())
    netlist = report["jobs"]["parasitics"]["outputs"]["netlist"]
    simulations = [job for job in report["jobs"].values() if job["stage"] == "simulate"]
    assert all(job["inputs"]["dut"]["sha256"] == netlist["sha256"] for job in simulations)
    # The approved limits/conditions are checked independently in the case contract
    # test. Here verify that the real run completed every declared observation.
    assert set(report["metrics"]) == {metric.id for metric in task.evaluation.metrics}
    for metric in task.evaluation.metrics:
        observations = report["metrics"][metric.id]["observations"]
        assert set(observations) == set(metric.observations)
        assert all(observation["status"] == "passed" for observation in observations.values())

    # Both analyses use the same stimuli, models and measurement definitions.
    # Pre-layout gets the schematic export; post-layout gets candidate RC.
    data = task.evaluation.description()
    jobs = [job for job in data["jobs"] if job["stage"] == "simulate"]
    for job in jobs:
        job["inputs"]["dut"] = "input:simulation"
    data.update(mode="characterization", jobs=jobs,
                metrics=[metric for metric in data["metrics"] if metric["category"] == "performance"])
    pre = run_evaluation(parse_evaluation(json.dumps(data).encode(), file_format="json"),
                         task.evaluation_inputs(), load_toolchain(case_config), tmp_path / "pre")
    assert pre["outcome"] == "passed", pre["jobs"]
    assert pre["task_success"] is None
    assert pre["backends"]["circuit.simulate"] == report["backends"]["circuit.simulate"]
    for specification in jobs:
        name = specification["id"]
        before, after = pre["jobs"][name], report["jobs"][name]
        assert before["inputs"]["dut"]["sha256"] == task.evaluation_inputs()["input:simulation"].sha256
        assert before["inputs"]["deck"] == after["inputs"]["deck"]
        polarity = specification["parameters"]["values"]["polarity"]
        check_transient_measurements(before, tmp_path / "pre", polarity)
        check_transient_measurements(after, tmp_path / "reference", polarity)


def test_original_drc_findings_block_extraction_and_performance(case_config, tmp_path):
    # Reuse the unmodified source already investigated during intake.
    original = ROOT / (
        "third_party/IHP-AnalogAcademy/modules/module_3_8_bit_SAR_ADC/"
        "part_5_analog_layout/comparator/layout/DIFF_COMPARATOR.gds"
    )
    completed, report = evaluate(original, case_config, tmp_path / "original")
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert report["outcome"] == "failed"
    assert report["physical_valid"] is report["task_success"] is False
    assert report["jobs"]["drc"]["status"] == "failed"
    assert report["jobs"]["lvs"]["status"] == "passed"
    task = load_task(case_config)
    for job in task.evaluation.jobs:
        if job.stage in {"extract", "simulate"} or job.id == "geometry":
            assert report["jobs"][job.id]["status"] == "blocked"
    assert all(metric["value"] is None for metric in report["metrics"].values())


@pytest.fixture(scope="module")
def context(case_config):
    return ({"valid": Asset((CASE / "reference/DIFF_COMPARATOR.gds").read_bytes(), "gds")},
            load_toolchain(case_config), load_task(case_config))


@pytest.mark.acceptance_eda
def test_artifact_rejection_limits_and_configuration_errors(context):
    fixtures, backends, task = context
    backend = backends["layout.artifact"]
    job = next(j for j in task.evaluation.jobs if j.id == "artifact")
    with pytest.raises(ValueError, match="declared gate"):
        backend.run(replace(job, gate="drc"),
                    {"layout": fixtures["valid"], "task": task.evaluation_inputs()["task"]})
    metadata = task.description()
    for layout, change in [(Asset(b"not GDS", "gds"), {}),
                           (Asset(b"\x00\x06\x00\x02\x02\x58", "gds"), {}),
                           (fixtures["valid"], {"top_cell": "ABSENT"}),
                           (fixtures["valid"], {"max_bytes": 6})]:
        changed = {**metadata, "output": {**metadata["output"], **change}}
        result = backend.run(job, {"layout": layout, "task": Asset(json.dumps(changed).encode(), "json")})
        assert result.status == "failed", result.reason
    with pytest.raises(ValueError, match="differs from task"):
        backend.run(replace(job, parameters_json='{"top_cell":"WRONG"}'),
                    {"layout": fixtures["valid"], "task": task.evaluation_inputs()["task"]})


@pytest.mark.acceptance_eda
@pytest.mark.parametrize("fault", ["missing_report", "partial_report", "extract_only", "broken_deck"])
def test_zero_exit_or_incomplete_deck_never_passes(context, tmp_path, fault):
    fixtures, backends, task = context
    mode = "lvs" if fault == "extract_only" else "drc"
    original = backends[f"layout.{mode}"]
    settings = dict(original.settings)
    files = dict(original.support.files)
    if fault == "extract_only":
        settings["variables"] = {**settings["variables"], "net_only": "true"}
    else:
        settings["deck"] = "fixture.drc"
        script = {"missing_report": '# Intentionally produces no report.\n',
                  "partial_report": 'source($input, $topcell)\nreport("incomplete", $report)\ninput(8,0).width(0.1).output("M1.a")\n',
                  "broken_deck": 'raise "intentional tool failure"\n'}[fault]
        files["fixture.drc"] = Asset(script.encode(), "ruby")
    files[f"{mode}.json"] = Asset(json.dumps(settings).encode(), "json")
    publish_bundle(files, {"purpose": "deliberately broken tool configuration"}, tmp_path / "support")
    backend = KLayoutDocker(image="layout-bench-tools:local", check=mode,
                            support=str(tmp_path / "support"), profile=f"{mode}.json")
    report = run_evaluation(task.evaluation, {"candidate": fixtures["valid"], **task.evaluation_inputs()},
                            {**backends, f"layout.{mode}": backend}, tmp_path / "run")
    assert report["jobs"][mode]["status"] == "error", report["jobs"]
    assert report["outcome"] == "error"
    assert report["physical_valid"] is None and report["task_success"] is None
    assert report["jobs"]["parasitics"]["status"] == "blocked"
    assert all(report["jobs"][job.id]["status"] == "blocked"
               for job in task.evaluation.jobs if job.stage == "simulate")
    assert report["jobs"][mode]["evidence"]["result.json"]["bytes"] > 0
    if fault == "partial_report":
        assert report["jobs"][mode]["evidence"]["report.db"]["bytes"] > 0
        assert "required categories" in report["jobs"][mode]["reason"]


@pytest.mark.acceptance_eda
def test_unresolved_hierarchy_text_only_and_disguised_oasis_are_rejected(context):
    fixtures, backends, task = context
    backend = backends["layout.artifact"]
    script = b'''from klayout import db
l=db.Layout(); t=l.create_cell("DIFF_COMPARATOR"); g=l.create_cell("MISSING")
g.ghost_cell=True
t.insert(db.CellInstArray(g.cell_index(),db.Trans()))
t.shapes(l.layer(8,0)).insert(db.Box(0,0,1000,1000))
l.write("ghost.gds")
l=db.Layout(); t=l.create_cell("DIFF_COMPARATOR")
t.shapes(l.layer(8,25)).insert(db.Text("D",db.Trans()))
l.write("text.gds")
l=db.Layout(); l.read("valid.gds"); l.write("disguised.oas")
'''
    outputs = {"ghost.gds": "gds", "text.gds": "gds", "disguised.oas": "gds"}
    result = backend.tool.run(["python", "generate.py"],
        {"generate.py": Asset(script, "python"), "valid.gds": fixtures["valid"]}, outputs)
    assert not result.reason
    job = next(j for j in task.evaluation.jobs if j.id == "artifact")
    for name, fragment in [("ghost.gds", "Unresolved"), ("text.gds", "no polygon"), ("disguised.oas", "not a GDSII")]:
        checked = backend.run(job, {"layout": result.files[name], "task": task.evaluation_inputs()["task"]})
        assert checked.status == "failed" and fragment in checked.reason, (name, checked.status, checked.reason)
