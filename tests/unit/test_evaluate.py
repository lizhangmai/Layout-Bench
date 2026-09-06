import hashlib
import json
from typing import ClassVar

import pytest

from benchmarking.evaluate import JobResult, Measurement, run_evaluation
from benchmarking.evaluation import parse_evaluation
from benchmarking.files import Asset

pytestmark = pytest.mark.unit

PLAN = b'''schema_version = 1
mode = "post_layout"

[[jobs]]
id = "slow"
stage = "simulate"
operation = "response"
inputs = { dut = "job:parasitics:netlist" }
[jobs.parameters]
load = 2.0

[[jobs]]
id = "artifact"
stage = "check"
operation = "check"
gate = "artifact"
inputs = { layout = "candidate" }

[[jobs]]
id = "drc"
stage = "check"
operation = "check"
gate = "drc"
inputs = { layout = "candidate" }
requires = ["artifact"]

[[jobs]]
id = "lvs"
stage = "check"
operation = "check"
gate = "lvs"
inputs = { layout = "candidate", schematic = "input:netlist" }
requires = ["artifact"]

[[jobs]]
id = "parasitics"
stage = "extract"
operation = "extract"
inputs = { layout = "candidate" }
requires = ["drc", "lvs"]
outputs = { netlist = "spice" }

[[jobs]]
id = "nominal"
stage = "simulate"
operation = "response"
inputs = { dut = "job:parasitics:netlist" }
[jobs.parameters]
load = 1.0

[[metrics]]
id = "delay"
category = "performance"
observations = ["nominal:delay", "slow:delay"]
unit = "s"
direction = "minimize"
aggregation = "max"
upper = 4.0
'''


class Checks:
    identity: ClassVar[dict] = {"adapter": "synthetic-checks", "version": "1"}

    def __init__(self, reject=None, crash=None):
        self.reject = reject
        self.crash = crash
        self.calls = []

    def run(self, job, inputs):
        self.calls.append(job.id)
        if job.id == self.crash:
            raise RuntimeError("Tool failed unexpectedly")
        return JobResult("failed" if job.id == self.reject else "passed",
                         "Synthetic rejection" if job.id == self.reject else "",
                         evidence={"log": Asset(job.id.encode(), "text")})


class Extractor:
    identity: ClassVar[dict] = {"adapter": "synthetic-extractor", "version": "1"}

    def run(self, job, inputs):
        assert inputs["layout"].content == b"synthetic-layout"
        return JobResult("passed", outputs={"netlist": Asset(b"derived-from-layout", "spice")},
                         evidence={"log": Asset(b"extraction evidence", "text")})


class Simulator:
    identity: ClassVar[dict] = {"adapter": "synthetic-simulator", "version": "1"}

    def __init__(self, factor=1.0, unit="s", missing=False):
        self.factor, self.unit, self.missing = factor, unit, missing

    def run(self, job, inputs):
        assert inputs["dut"].content == b"derived-from-layout"
        value = self.factor * (1.0 if job.parameters["load"] == 1.0 else 3.0)
        return JobResult("passed", measurements={} if self.missing else {"delay": Measurement(value, self.unit)},
                         evidence={"waveform": Asset(b"synthetic response", "text")})


@pytest.fixture
def bindings():
    return {"check": Checks(), "extract": Extractor(), "response": Simulator()}


@pytest.fixture
def inputs():
    return {"candidate": Asset(b"synthetic-layout", "gds"), "input:netlist": Asset(b"schematic", "spice"),
            "input:unlisted_reference": Asset(b"reference must not be consumed", "gds")}


def evaluate(tmp_path, inputs, bindings, raw=PLAN):
    return run_evaluation(parse_evaluation(raw), inputs, bindings, tmp_path / "report")


def test_dependencies_follow_extracted_candidate_and_archive_evidence(tmp_path, inputs, bindings):
    report = evaluate(tmp_path, inputs, bindings)
    assert report["physical_valid"] is True
    assert report["task_success"] is True
    assert report["quality_eligible"] is True
    assert report["metrics"]["delay"]["value"] == 3.0
    assert list(report["jobs"]).index("parasitics") < list(report["jobs"]).index("slow")
    assert "input:unlisted_reference" not in report["inputs"]
    output = report["jobs"]["parasitics"]["outputs"]["netlist"]
    content = (tmp_path / "report" / output["path"]).read_bytes()
    assert hashlib.sha256(content).hexdigest() == output["sha256"]
    assert report["jobs"]["slow"]["inputs"]["dut"]["sha256"] == output["sha256"]
    assert json.loads((tmp_path / "report/report.json").read_text()) == report


def test_drc_lvs_success_is_not_performance_success(tmp_path, inputs, bindings):
    report = evaluate(tmp_path, inputs, bindings, PLAN.replace(b"upper = 4.0", b"upper = 2.0"))
    assert report["physical_valid"] is True
    assert report["specs_pass"] is False
    assert report["task_success"] is False
    assert report["metrics"]["delay"]["observations"]["nominal:delay"]["status"] == "passed"
    assert report["metrics"]["delay"]["observations"]["slow:delay"]["status"] == "failed"


def test_summary_cannot_hide_a_failing_case(tmp_path, inputs, bindings):
    report = evaluate(tmp_path, inputs, bindings, PLAN + b"lower = 2.0\n")
    assert report["metrics"]["delay"]["value"] == 3.0
    assert report["metrics"]["delay"]["status"] == "failed"


def test_replacing_backend_changes_tool_identity_and_results_without_changing_task(tmp_path, inputs, bindings):
    first = run_evaluation(parse_evaluation(PLAN), inputs, bindings, tmp_path / "first")
    alternative = Simulator(factor=2.0)
    alternative.identity = {"adapter": "alternative-simulator", "version": "2"}
    bindings["response"] = alternative
    second = run_evaluation(parse_evaluation(PLAN), inputs, bindings, tmp_path / "second")
    assert first["plan"] == second["plan"]
    assert first["task_success"] is True and second["task_success"] is False
    assert first["backends"]["response"] != second["backends"]["response"]


def test_failed_gate_blocks_dependent_work_but_preserves_independent_checks(tmp_path, inputs, bindings):
    bindings["check"] = Checks(reject="drc")
    report = evaluate(tmp_path, inputs, bindings)
    assert report["physical_valid"] is False
    assert report["task_success"] is False
    assert report["jobs"]["lvs"]["status"] == "passed"
    assert report["jobs"]["parasitics"]["status"] == "blocked"
    assert report["metrics"]["delay"]["value"] is None


def test_tool_error_is_not_a_circuit_failure(tmp_path, inputs, bindings):
    bindings["check"] = Checks(crash="drc")
    report = evaluate(tmp_path, inputs, bindings)
    assert report["outcome"] == "error"
    assert report["physical_valid"] is None
    assert report["task_success"] is None
    assert report["jobs"]["lvs"]["status"] == "passed"


@pytest.mark.parametrize("simulator", [Simulator(unit="ms"), Simulator(missing=True), Simulator(factor=float("nan")), Simulator(factor=float("inf"))])
def test_missing_nonfinite_or_wrong_unit_never_passes(tmp_path, inputs, bindings, simulator):
    bindings["response"] = simulator
    report = evaluate(tmp_path, inputs, bindings)
    assert report["outcome"] == "error"
    assert report["task_success"] is None
    assert report["quality_eligible"] is False


@pytest.mark.parametrize("mode", ["physical", "characterization"])
def test_partial_scope_does_not_claim_full_task_success(tmp_path, inputs, bindings, mode):
    report = evaluate(tmp_path, inputs, bindings, PLAN.replace(b'"post_layout"', f'"{mode}"'.encode()))
    assert report["outcome"] == "passed"
    assert report["task_success"] is None
    assert report["quality_eligible"] is False


@pytest.mark.parametrize(("before", "after", "message"), [
    (b"job:parasitics:netlist", b"input:netlist", "consume candidate extraction"),
    (b'inputs = { layout = "candidate" }\nrequires = ["drc", "lvs"]',
     b'inputs = { layout = "input:netlist" }\nrequires = ["drc", "lvs"]', "consume candidate extraction"),
    (b'requires = ["drc", "lvs"]', b'requires = ["artifact"]', "physical validity gates"),
    (b'gate = "drc"', b'gate = "constraint"', "one drc gate"),
    (b'job:parasitics:netlist', b'job:parasitics:absent', "Unknown job output"),
    (b'requires = ["drc", "lvs"]', b'requires = ["slow"]', "cycle"),
    (b'upper = 4.0', b'upper = nan', "finite numeric"),
    (b'upper = 4.0', b'lower = 5.0\nupper = 4.0', "Inverted bounds"),
    (b'aggregation = "max"', b'aggregation = "mean"', "aggregation"),
])
def test_invalid_plans_are_rejected(before, after, message):
    with pytest.raises(ValueError, match=message):
        parse_evaluation(PLAN.replace(before, after))


def test_missing_binding_is_preflight_error(tmp_path, inputs, bindings):
    del bindings["extract"]
    with pytest.raises(ValueError, match="Missing backend"):
        evaluate(tmp_path, inputs, bindings)
    assert not (tmp_path / "report").exists()


def test_untrusted_backend_cannot_claim_success_without_declared_output(tmp_path, inputs, bindings):
    bindings["extract"] = Checks()
    report = evaluate(tmp_path, inputs, bindings)
    assert report["jobs"]["parasitics"]["status"] == "error"
    assert report["task_success"] is None


def test_plan_parameters_are_immutable():
    plan = parse_evaluation(PLAN)
    job = next(j for j in plan.jobs if j.id == "slow")
    job.parameters["load"] = 100
    assert job.parameters["load"] == 2.0


def test_physical_measurements_can_come_from_completed_checks():
    raw = PLAN + b'''
[[metrics]]
id = "area"
category = "physical"
observations = ["artifact:area"]
unit = "um2"
direction = "minimize"
aggregation = "max"
'''
    assert parse_evaluation(raw).metrics[-1].id == "area"
    with pytest.raises(ValueError, match="measurement stage"):
        parse_evaluation(raw.replace(b'category = "physical"', b'category = "performance"'))
