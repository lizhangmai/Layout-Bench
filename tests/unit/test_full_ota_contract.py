"""OTA acceptance boundaries from the approved requirements, without EDA claims."""

import json
from pathlib import Path

import pytest

from benchmarking.evaluate import JobResult, Measurement, run_evaluation
from benchmarking.files import Asset
from benchmarking.tasks import load_task

pytestmark = pytest.mark.unit
CASE = Path(__file__).resolve().parents[2] / "tasks/IHP-AnalogAcademy/cases/full_OTA/case.toml"

# Published inclusive limits, independent of the configuration being tested.
BOUNDARIES = [
    ("low_frequency_gain", 60, 59.999, "dB"),
    ("unity_gain_bandwidth", 3e6, 3e6 - 1, "Hz"),
    ("phase_margin", 55, 54.999, "deg"),
    ("supply_power", 0, -1e-9, "W"),
    ("supply_power", 220e-6, 220.001e-6, "W"),
    ("output_bias", .55, .549999, "V"),
    ("output_bias", .65, .650001, "V"),
]


class MeasurementFixture:
    """Substitute tool results only, exercising the real case plan and decisions."""

    @property
    def identity(self):
        return {"adapter": "synthetic-measurements"}

    def __init__(self, name, value, unit):
        self.nominal = {
            "low_frequency_gain": Measurement(70, "dB"),
            "unity_gain_bandwidth": Measurement(4e6, "Hz"),
            "phase_margin": Measurement(60, "deg"),
            "supply_power": Measurement(200e-6, "W"),
            "output_bias": Measurement(.6, "V"),
        }
        self.nominal[name] = Measurement(value, unit)

    def run(self, job, inputs):
        measurements = (self.nominal if job.stage == "simulate" else
                        {"area": Measurement(2700, "um2")} if job.gate == "constraint" else {})
        return JobResult("passed", measurements=measurements,
                         outputs={name: Asset(b"synthetic tool output", format) for name, format in job.outputs},
                         evidence={"fixture": Asset(b"not a physical qualification run", "text")})


@pytest.mark.parametrize("name,boundary,outside,unit", BOUNDARIES)
def test_each_ota_performance_boundary_is_inclusive_and_enforced(name, boundary, outside, unit, tmp_path):
    task = load_task(CASE)
    inputs = {**task.evaluation_inputs(), "candidate": Asset(b"synthetic candidate", "gds")}
    for label, value, passed in [("boundary", boundary, True), ("outside", outside, False)]:
        backend = MeasurementFixture(name, value, unit)
        report = run_evaluation(task.evaluation, inputs,
                                {job.operation: backend for job in task.evaluation.jobs}, tmp_path / label)
        assert report["physical_valid"] is True
        assert report["specs_pass"] is report["task_success"] is passed
        assert report["metrics"][name]["status"] == ("passed" if passed else "failed")
        assert all(job["status"] == "passed" for job in report["jobs"].values())


def test_ota_uses_candidate_rc_after_geometry_and_reports_raw_area():
    task = load_task(CASE)
    jobs = {job.id: job for job in task.evaluation.jobs}
    assert task.evaluation.mode == "post_layout"
    assert dict(jobs["parasitics"].inputs) == {"layout": "candidate"}
    assert "geometry" in jobs["parasitics"].requires
    assert dict(jobs["nominal"].inputs)["dut"] == "job:parasitics:netlist"
    constraints = json.loads(task.inline_constraints.content)
    outline = next(spec for spec in constraints["hard"] if spec["type"] == "bbox_max")
    assert (outline["max_width_um"], outline["max_height_um"]) == (80, 50)
    area = next(metric for metric in task.evaluation.metrics if metric.id == "functional_area")
    assert (area.lower, area.upper, area.unit) == (None, None, "um2")
