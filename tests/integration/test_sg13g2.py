"""Actual model, GDS capacitance and transistor simulation checks; no task score."""

import json
import runpy
from pathlib import Path

import pytest

from benchmarking.docker import DockerTool
from benchmarking.environment import prepare_pdk
from benchmarking.evaluate import run_evaluation
from benchmarking.evaluation import parse_evaluation
from benchmarking.files import Asset
from benchmarking.magic import MagicCapacitanceDocker
from benchmarking.ngspice import NgspiceDocker
from benchmarking.prepare_support import prepare_support

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples/sg13g2"


@pytest.fixture(scope="module")
def context(tmp_path_factory):
    root = tmp_path_factory.mktemp("sg13g2")
    pdk = ROOT / "third_party/IHP-Open-PDK"
    prepare_support(pdk, ROOT / "technology/sg13g2/magic.json", root / "magic")
    prepare_support(pdk, ROOT / "technology/sg13g2/mos-models.json", root / "models")
    prepare_pdk(pdk, root / "view")
    generate = runpy.run_path(str(EXAMPLES / "generate.py"))["generate_fixtures"]
    fixtures = generate(root / "view", root / "fixtures")
    backends = {
        "layout.extract_capacitance": MagicCapacitanceDocker(
            image="layout-bench-tools:local", support=str(root / "magic"),
            technology="magic/ihp-sg13g2.tech", tech_name="ihp-sg13g2", style="ngspice()"),
        "circuit.simulate": NgspiceDocker(image="layout-bench-tools:local", support=str(root / "models")),
    }
    return fixtures, backends


def inputs(fixture, deck, role):
    return {"input:layout": fixture, f"input:{role}": Asset((EXAMPLES / deck).read_bytes(), "spice")}


def test_reviewed_psp_models_load_and_distinguish_on_and_off(tmp_path, context):
    _, backends = context
    plan = parse_evaluation((EXAMPLES / "mos.toml").read_bytes())
    report = run_evaluation(plan, {"input:dc": Asset((EXAMPLES / "mos_dc.spice").read_bytes(), "spice")},
                            backends, tmp_path / "mos")
    assert report["outcome"] == "passed", report["jobs"]
    assert report["metrics"]["on_current"]["value"] > 1e5 * report["metrics"]["off_current"]["value"]
    assert report["backends"]["circuit.simulate"]["support_sha256"]
    assert report["jobs"]["on"]["evidence"]["support:osdi/psp103.osdi"]["bytes"] > 1000


def test_gds_capacitance_matches_technology_area_and_perimeter_formula(tmp_path, context):
    fixtures, backends = context
    plan = parse_evaluation((EXAMPLES / "plate.toml").read_bytes())
    for width in (20, 40):
        report = run_evaluation(plan, inputs(fixtures[f"plate{width}"], "plate_ac.spice", "ac"),
                                backends, tmp_path / f"plate{width}")
        assert report["outcome"] == "passed", report["jobs"]
        # From the reviewed Magic nominal M1 rule, in aF/um² and aF/um.
        expected = (35.015 * width * 10 + 39.585 * 2 * (width + 10)) * 1e-18
        assert report["metrics"]["plate_capacitance"]["value"] == pytest.approx(expected, rel=1e-5)
        assert report["task_success"] is None


def test_mos_layout_capacitance_changes_the_actual_post_extraction_delay(tmp_path, context):
    fixtures, backends = context
    raw = (EXAMPLES / "switch.toml").read_bytes()
    # This limit is solely a test fixture: it is not a calibrated task spec.
    plan = parse_evaluation(raw + b"\nupper = 1e-10\n")
    reports = []
    for size in (10, 100):
        report = run_evaluation(plan, inputs(fixtures[f"switch{size}"], "switch_transient.spice", "transient"),
                                backends, tmp_path / f"switch{size}")
        assert all(j["status"] == "passed" for j in report["jobs"].values()), report["jobs"]
        extraction = report["jobs"]["parasitics"]["outputs"]["netlist"]
        # Check all four terminals using an existing EDA reader. The stub only
        # declares a connectivity interface, and is never sent to ngspice.
        extracted = (tmp_path / f"switch{size}" / extraction["path"]).read_bytes()
        stub = (b"* Connectivity-only interface, not a simulation model.\n"
                b".subckt sg13_lv_nmos D G S B w=1u l=1u ad=0 as=0 pd=0 ps=0\n.ends\n")
        inspect = b'''from klayout import db
n = db.Netlist()
n.read("circuit.spice", db.NetlistSpiceReader())
c = n.circuit_by_name("MOS_SWITCH")
assert [p.name() for p in c.each_pin()] == ["D", "G", "S", "B"]
devices = list(c.each_subcircuit())
assert len(devices) == 1
x = devices[0]
assert {p.name(): x.net_for_pin(p.id()).name for p in x.circuit_ref().each_pin()} == {p: p for p in ("D", "G", "S", "B")}
'''
        check = DockerTool("layout-bench-tools:local", ["magic", "--version"], 30).run(
            ["python", "inspect.py"], {"inspect.py": Asset(inspect, "python"),
                                       "circuit.spice": Asset(stub + extracted, "spice")}, {})
        assert check.returncode == 0 and not check.reason, check.evidence
        assert report["jobs"]["transient"]["inputs"]["dut"]["sha256"] == extraction["sha256"]
        assert report["jobs"]["transient"]["outputs"]["waveform"]["bytes"] > 1000
        assert report["task_success"] is None
        reports.append(report)
    assert reports[1]["metrics"]["fall_delay"]["value"] > 10 * reports[0]["metrics"]["fall_delay"]["value"]
    assert [r["outcome"] for r in reports] == ["passed", "failed"]


@pytest.mark.parametrize("change", ["missing_top", "missing_pin", "corrupt_gds"])
def test_extraction_errors_block_simulation_and_preserve_diagnostics(tmp_path, context, change):
    fixtures, backends = context
    raw = (EXAMPLES / "plate.toml").read_bytes()
    if change == "missing_top":
        raw = raw.replace(b'top_cell = "PLATE"', b'top_cell = "ABSENT"')
    elif change == "missing_pin":
        raw = raw.replace(b'"GND"', b'"ABSENT"')
    fixture = Asset(b"not a GDS", "gds") if change == "corrupt_gds" else fixtures["plate20"]
    report = run_evaluation(parse_evaluation(raw), inputs(fixture, "plate_ac.spice", "ac"), backends, tmp_path / change)
    assert report["outcome"] == "error"
    assert report["jobs"]["parasitics"]["status"] == "error"
    assert report["jobs"]["parasitics"]["evidence"]["console"]["bytes"] > 0
    assert report["jobs"]["ac"]["status"] == "blocked"
    assert report["metrics"]["plate_capacitance"]["value"] is None
    assert json.loads((tmp_path / change / "report.json").read_text())["task_success"] is None
