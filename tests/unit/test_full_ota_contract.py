"""OTA acceptance machinery exercised at the declared limits, without EDA claims.

Limit values live only in the case configuration; these tests derive probe
points from it and verify enforcement behavior at and just outside each bound.
"""

from pathlib import Path

import pytest

from benchmarking.evaluate import JobResult, Measurement, run_evaluation
from benchmarking.files import Asset
from benchmarking.tasks import load_task

pytestmark = pytest.mark.unit
TASK = load_task(Path(__file__).resolve().parents[2]
                 / "tasks/ihp-sg13g2/IHP-AnalogAcademy/cases/full_OTA/case.toml")


def _performance_metrics():
    return [metric for metric in TASK.evaluation.metrics if metric.category == "performance"]


def _interior(metric):
    if metric.lower is not None and metric.upper is not None:
        return (metric.lower + metric.upper) / 2
    if metric.lower is not None:
        return metric.lower * 1.05 or 1e-30
    return metric.upper * 0.95


NOMINAL = {observation.split(":", 1)[1]: Measurement(_interior(metric), metric.unit)
           for metric in _performance_metrics() for observation in metric.observations}


def _probes(metric):
    for bound, sign in ((metric.lower, -1), (metric.upper, 1)):
        if bound is not None:
            yield bound, bound + sign * max(abs(bound) * 1e-6, 1e-30)


BOUNDARIES = [(metric.id, bound, outside, metric.unit)
              for metric in _performance_metrics()
              for bound, outside in _probes(metric)]


class MeasurementFixture:
    """Substitute tool results only, exercising the real case plan and decisions."""

    @property
    def identity(self):
        return {"adapter": "synthetic-measurements"}

    def __init__(self, name, value, unit):
        self.nominal = {**NOMINAL, name: Measurement(value, unit)}

    def run(self, job, inputs):
        measurements = (self.nominal if job.stage == "simulate" else
                        {"area": Measurement(2700, "um2")} if job.gate == "constraint" else {})
        return JobResult("passed", measurements=measurements,
                         outputs={name: Asset(b"synthetic tool output", format) for name, format in job.outputs},
                         evidence={"fixture": Asset(b"not a physical qualification run", "text")})


@pytest.mark.parametrize("name,boundary,outside,unit", BOUNDARIES, ids=[f"{name}@{bound}" for name, bound, _, _ in BOUNDARIES])
def test_each_ota_performance_boundary_is_inclusive_and_enforced(name, boundary, outside, unit, tmp_path):
    inputs = {**TASK.evaluation_inputs(), "candidate": Asset(b"synthetic candidate", "gds")}
    for label, value, passed in [("boundary", boundary, True), ("outside", outside, False)]:
        backend = MeasurementFixture(name, value, unit)
        report = run_evaluation(TASK.evaluation, inputs,
                                {job.operation: backend for job in TASK.evaluation.jobs}, tmp_path / label)
        assert report["physical_valid"] is True
        assert report["specs_pass"] is report["task_success"] is passed
        assert report["metrics"][name]["status"] == ("passed" if passed else "failed")
        assert all(job["status"] == "passed" for job in report["jobs"].values())


def test_ota_extracts_candidate_rc_after_geometry():
    jobs = {job.id: job for job in TASK.evaluation.jobs}
    assert TASK.evaluation.mode == "post_layout"
    assert dict(jobs["parasitics"].inputs) == {"layout": "candidate"}
    assert "geometry" in jobs["parasitics"].requires
    assert dict(jobs["nominal"].inputs)["dut"] == "job:parasitics:netlist"
