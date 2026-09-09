"""Approved comparator requirements and reference identity, independent of file organization."""

import hashlib
import tomllib
from pathlib import Path

import pytest

from benchmarking.tasks import load_task

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
COMPARATOR = ROOT / "tasks/IHP-AnalogAcademy/cases/comparator/case.toml"


def test_comparator_uses_candidate_rc_and_all_approved_operating_points():
    task = load_task(COMPARATOR)
    assert task.status == "qualified"
    assert task.evaluation is not None
    assert task.evaluation.mode == "post_layout"
    drc = next(job for job in task.evaluation.jobs if job.id == "drc")
    assert not drc.parameters.get("waivers")
    config = tomllib.loads(COMPARATOR.read_text())
    source = next(item for item in config["upstream_assets"] if item["role"] == "source-netlist")
    assert task.evaluation_inputs()["input:netlist"].sha256 == source["sha256"]
    jobs = {job.id: job for job in task.evaluation.jobs}
    assert set(jobs["parasitics"].requires) == {"artifact", "drc", "lvs", "geometry"}
    assert dict(jobs["parasitics"].inputs) == {"layout": "candidate"}
    simulations = [job for job in jobs.values() if job.stage == "simulate"]
    assert sorted(job.parameters["values"]["input_difference"] for job in simulations) == [-.005, -.003, .003, .005]
    for job in simulations:
        assert dict(job.inputs) == {"deck": "input:performance", "dut": "job:parasitics:netlist"}
        values = job.parameters["values"]
        assert values["polarity"] == (1 if values["input_difference"] > 0 else -1)
    metrics = {metric.id: metric for metric in task.evaluation.metrics}
    for name, measure, limits in [("worst_delay", "delay", (0, 3e-9)),
                                   ("decision_margin", "margin", (1, None))]:
        metric = metrics[name]
        assert (metric.lower, metric.upper) == limits
        assert set(metric.observations) == {
            f"{job.id}:{measure}_c{cycle:02}" for job in simulations for cycle in range(2, 10)
        }
    assert (metrics["supply_power"].lower, metrics["supply_power"].upper) == (0, 80e-6)
    assert set(metrics["supply_power"].observations) == {f"{job.id}:supply_power" for job in simulations}


def test_comparator_reference_matches_the_documented_repair():
    config = tomllib.loads(COMPARATOR.read_text())
    qualification = config["qualification"]
    documentation = COMPARATOR.parent / qualification["evidence"]
    reference = COMPARATOR.parent / qualification["reference"]
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    # Reviewed repair identity, independent of current layout bytes; see case README.
    assert digest == "9f2548f157ccfc4448820dbd71f26c60d9a0525043e86d8928ea448cf56d7279"
    assert digest in documentation.read_text()
    assert digest not in {item.sha256 for item in load_task(COMPARATOR).inputs}
