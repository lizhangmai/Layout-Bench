"""Comparator evaluation structure and reference identity, independent of file organization.

Operating points and metric limits are declared only in the case configuration;
these tests verify the evaluation structure and documentation cross-references,
not copies of the declared values.
"""

import hashlib
import tomllib
from pathlib import Path

import pytest

from benchmarking.tasks import load_task

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
COMPARATOR = ROOT / "tasks/ihp-sg13g2/IHP-AnalogAcademy/cases/comparator/case.toml"


def test_comparator_routes_candidate_rc_into_every_simulation():
    task = load_task(COMPARATOR)
    assert task.status == "qualified"
    assert task.evaluation is not None
    assert task.evaluation.mode == "post_layout"
    drc = next(job for job in task.evaluation.jobs if job.id == "drc")
    assert not drc.parameters.get("waivers")
    jobs = {job.id: job for job in task.evaluation.jobs}
    assert set(jobs["parasitics"].requires) == {"artifact", "drc", "lvs", "geometry"}
    assert dict(jobs["parasitics"].inputs) == {"layout": "candidate"}
    simulations = [job for job in jobs.values() if job.stage == "simulate"]
    assert simulations
    for job in simulations:
        assert dict(job.inputs) == {"deck": "input:performance", "dut": "job:parasitics:netlist"}
        values = job.parameters["values"]
        assert values["polarity"] == (1 if values["input_difference"] > 0 else -1)


def test_comparator_reference_matches_the_documented_repair():
    config = tomllib.loads(COMPARATOR.read_text())
    qualification = config["qualification"]
    documentation = COMPARATOR.parent / qualification["evidence"]
    reference = COMPARATOR.parent / qualification["reference"]
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    # The case README records the reviewed repair identity; the reference stays maintainer-only.
    assert digest in documentation.read_text()
    assert digest not in {item.sha256 for item in load_task(COMPARATOR).inputs}
