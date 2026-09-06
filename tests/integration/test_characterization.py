"""Real simulator qualification with analytical expectations, not layout scores."""

import math
from pathlib import Path

import pytest

from benchmarking.evaluate import run_evaluation
from benchmarking.evaluation import parse_evaluation
from benchmarking.files import Asset
from benchmarking.toolchains import load_toolchain

pytestmark = pytest.mark.integration
EXAMPLES = Path(__file__).resolve().parents[2] / "examples/characterization"


@pytest.fixture(scope="module")
def backends():
    return load_toolchain(EXAMPLES / "toolchain.toml")


def asset(name):
    return Asset((EXAMPLES / name).read_bytes(), "spice")


def rc_inputs():
    return {"input:dut": asset("rc.spice"), "input:transient": asset("rc_transient.spice"),
            "input:ac": asset("rc_ac.spice")}


def test_rc_transient_and_ac_match_analytic_values_and_retain_waveforms(tmp_path, backends):
    plan = parse_evaluation((EXAMPLES / "rc.toml").read_bytes())
    report = run_evaluation(plan, rc_inputs(), backends, tmp_path / "rc")
    assert report["outcome"] == "passed", report["jobs"]
    assert report["task_success"] is None
    for name, resistance in (("nominal", 1000), ("large_r", 2000)):
        t50 = report["jobs"][f"step_{name}"]["measurements"]["t50"]["value"]
        bandwidth = report["jobs"][f"ac_{name}"]["measurements"]["bandwidth"]["value"]
        assert t50 == pytest.approx(math.log(2) * resistance * 1e-9 + 0.5e-9, rel=0.002)
        assert bandwidth == pytest.approx(1 / (2 * math.pi * resistance * 1e-9), rel=0.002)
    waveform = report["jobs"]["step_nominal"]["outputs"]["waveform"]
    assert (tmp_path / "rc" / waveform["path"]).stat().st_size > 100
    assert report["backends"]["circuit.simulate"]["image_id"].startswith("sha256:")


def test_another_circuit_and_metric_set_uses_same_backend_and_core(tmp_path, backends):
    plan = parse_evaluation((EXAMPLES / "divider.toml").read_bytes())
    report = run_evaluation(plan, {"input:dut": asset("divider.spice"), "input:dc": asset("divider_dc.spice")},
                            backends, tmp_path / "divider")
    assert report["outcome"] == "passed", report["jobs"]
    assert report["metrics"]["voltage_ratio"]["value"] == pytest.approx(0.5)
    assert report["metrics"]["dc_power"]["value"] == pytest.approx(0.0005)


def test_slower_rc_fails_specs_without_becoming_a_tool_error(tmp_path, backends):
    raw = (EXAMPLES / "rc.toml").read_bytes().replace(b"2000.0", b"4000.0")
    report = run_evaluation(parse_evaluation(raw), rc_inputs(), backends, tmp_path / "slow")
    assert all(job["status"] == "passed" for job in report["jobs"].values())
    assert report["outcome"] == "failed"
    assert report["specs_pass"] is False
    assert report["metrics"]["step_time"]["status"] == "failed"
    assert report["metrics"]["bandwidth"]["status"] == "failed"


def test_simulator_exit_success_without_measurement_is_an_error(tmp_path, backends):
    raw = (EXAMPLES / "divider.toml").read_bytes().replace(b"ratio =", b"absent_measurement =")
    report = run_evaluation(parse_evaluation(raw),
                            {"input:dut": asset("divider.spice"), "input:dc": asset("divider_dc.spice")},
                            backends, tmp_path / "missing")
    assert report["outcome"] == "error"
    assert report["specs_pass"] is None
    job = report["jobs"]["operating_point"]
    assert job["measurements"] == {}
    assert job["evidence"]["log"]["bytes"] > 0
