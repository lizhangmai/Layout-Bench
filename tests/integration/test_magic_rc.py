"""Real RC extraction: analytical wire resistance and candidate-dependent delay."""

import json
from pathlib import Path

import pytest

from benchmarking.docker import DockerTool
from benchmarking.environment import prepare_pdk
from benchmarking.evaluate import run_evaluation
from benchmarking.evaluation import parse_evaluation
from benchmarking.files import Asset
from benchmarking.magic import MagicRCDocker
from benchmarking.ngspice import NgspiceDocker
from benchmarking.prepare_support import prepare_support

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]

PLAN = b'''schema_version = 1
mode = "characterization"
[[jobs]]
id = "rc"
stage = "extract"
operation = "layout.extract_rc"
inputs = {layout = "input:layout"}
outputs = {netlist = "spice"}
parameters = {top_cell = "MOS_SWITCH", ports = ["D", "G", "S", "B"]}
[[jobs]]
id = "dc"
stage = "simulate"
operation = "circuit.simulate"
inputs = {deck = "input:dc", dut = "job:rc:netlist"}
parameters = {measurements = {current = "A"}}
[[jobs]]
id = "tran"
stage = "simulate"
operation = "circuit.simulate"
inputs = {deck = "input:tran", dut = "job:rc:netlist"}
parameters = {measurements = {delay = "s"}}
[[metrics]]
id = "current"
category = "performance"
observations = ["dc:current"]
unit = "A"
direction = "maximize"
aggregation = "min"
[[metrics]]
id = "delay"
category = "performance"
observations = ["tran:delay"]
unit = "s"
direction = "minimize"
aggregation = "max"
upper = 2.2e-9
'''

DC = Asset(b'''* Low-voltage on resistance includes the drain wire.
.lib cornerMOSlv.lib mos_tt
.include dut.spice
XDUT IN GATE 0 0 MOS_SWITCH
VGATE GATE 0 1.2
VDRIVE IN 0 1m
.dc VDRIVE 0 1m 1m
.measure dc current FIND i(VDRIVE) AT=1m
.end
''', "spice")
TRAN = Asset(b'''* The same extracted MOS and wire discharge a known load.
.lib cornerMOSlv.lib mos_tt
.include dut.spice
XDUT OUT GATE 0 0 MOS_SWITCH
VDD SUPPLY 0 1.2
RLOAD SUPPLY OUT 10k
VGATE GATE 0 PULSE(0 1.2 1n 10p 10p 100n 200n)
CLOAD OUT 0 1p
.tran 2p 15n
.measure tran delay TRIG v(GATE) VAL=0.6 RISE=1 TARG v(OUT) VAL=0.6 FALL=1
.end
''', "spice")


@pytest.fixture(scope="module")
def context(tmp_path_factory):
    root = tmp_path_factory.mktemp("magic-rc")
    prepare_support(ROOT / "third_party/IHP-Open-PDK", ROOT / "technology/sg13g2/magic.json", root / "magic")
    prepare_support(ROOT / "third_party/IHP-Open-PDK", ROOT / "technology/sg13g2/mos-models.json", root / "models")
    prepare_pdk(ROOT / "third_party/IHP-Open-PDK", root / "view")
    backends = {
        "layout.extract_rc": MagicRCDocker(
            image="layout-bench-tools:local", support=str(root / "magic"),
            technology="magic/ihp-sg13g2.tech", tech_name="ihp-sg13g2", style="ngspice()"),
        "circuit.simulate": NgspiceDocker(image="layout-bench-tools:local", support=str(root / "models")),
    }
    source = Asset((ROOT / "tests/fixtures/sg13g2/make_switch.py").read_bytes(), "python")
    primitive_files = {"pdk/" + p.relative_to(root / "view").as_posix(): Asset(p.read_bytes(), "binary")
                       for p in (root / "view").rglob("*") if p.is_file()}
    environment = {"KLAYOUT": "1", "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": "/workspace/pdk/ihp-sg13g2/libs.tech/klayout/python:"
                                 "/workspace/pdk/ihp-sg13g2/libs.tech/klayout/python/pycell4klayout-api/source/python"}
    tool = DockerTool("layout-bench-tools:local", ["klayout", "-v"], 60)
    layouts = {}
    for length in (200, 2000):
        result = tool.run(["python", "wire.py", "wire.gds", "--wire-length", str(length)],
                          {"wire.py": source, **primitive_files},
                          {"wire.gds": "gds"}, environment=environment)
        assert result.returncode == 0 and not result.reason, result.evidence
        layouts[length] = result.files["wire.gds"]
    return backends, layouts, primitive_files, environment, tool


def test_wire_resistance_and_delay_use_the_extracted_network(tmp_path, context):
    backends, layouts, *_ = context
    reports = []
    for length, layout in layouts.items():
        destination = tmp_path / str(length)
        report = run_evaluation(parse_evaluation(PLAN), {
            "input:layout": layout, "input:dc": DC, "input:tran": TRAN,
        }, backends, destination)
        assert all(j["status"] == "passed" for j in report["jobs"].values()), report["jobs"]
        extraction = report["jobs"]["rc"]
        preparation = json.loads((destination / extraction["evidence"]["preparation-check.json"]["path"]).read_text())
        assert preparation["flattened"] and preparation["geometry_unchanged"]
        assert extraction["evidence"]["resistance.ext"]["bytes"] > 0
        assert report["jobs"]["tran"]["inputs"]["dut"]["sha256"] == extraction["outputs"]["netlist"]["sha256"]
        reports.append(report)
    resistances = [-1e-3 / r["metrics"]["current"]["value"] for r in reports]
    # Pinned nominal Magic M1 sheet resistance: 110 milliohms/square.
    assert resistances[1] - resistances[0] == pytest.approx(0.110 * (2000 - 200) / 0.2, rel=2e-3)
    assert reports[1]["metrics"]["delay"]["value"] > 1.2 * reports[0]["metrics"]["delay"]["value"]
    # A fixture-only threshold checks the rejection path, not comparator limits.
    assert [r["outcome"] for r in reports] == ["passed", "failed"]
    assert all(r["task_success"] is None for r in reports)


def test_invalid_gds_blocks_rc_simulation(tmp_path, context):
    backends, *_ = context
    report = run_evaluation(parse_evaluation(PLAN), {
        "input:layout": Asset(b"invalid GDS", "gds"), "input:dc": DC, "input:tran": TRAN,
    }, backends, tmp_path / "invalid")
    assert report["jobs"]["rc"]["status"] == "error"
    assert report["jobs"]["dc"]["status"] == report["jobs"]["tran"]["status"] == "blocked"
    assert report["metrics"]["delay"]["value"] is None


def test_same_conductor_port_aliases_are_rejected(tmp_path, context):
    backends, *_ = context
    # Magic's short-resistor export would bypass the distributed resistance
    # between P and B. Native topology validation must reject this unsupported
    # interface instead of accepting a short or duplicate resistance network.
    source = Asset((ROOT / "tests/fixtures/sg13g2/make_plate.py").read_bytes(), "python")
    tool = DockerTool("layout-bench-tools:local", ["klayout", "-v"], 60)
    result = tool.run(["python", "plate.py", "wire.gds", "--alias-port", "B"],
                      {"plate.py": source}, {"wire.gds": "gds"})
    assert not result.returncode and not result.reason
    plan = PLAN.replace(b'top_cell = "MOS_SWITCH", ports = ["D", "G", "S", "B"]',
                        b'top_cell = "PLATE", ports = ["P", "B", "GND"]')
    report = run_evaluation(parse_evaluation(plan), {
        "input:layout": result.files["wire.gds"], "input:dc": DC, "input:tran": TRAN,
    }, backends, tmp_path / "aliases")
    assert report["jobs"]["rc"]["status"] == "error"
    assert report["jobs"]["tran"]["status"] == "blocked"
    evidence = report["jobs"]["rc"]["evidence"]["console"]["path"]
    assert "multiple ports on the same conductor" in (tmp_path / "aliases" / evidence).read_text()


def test_internal_wire_with_low_w_over_l_drivers_retains_resistance(tmp_path, context):
    backends, _, primitive_files, environment, tool = context
    source = Asset((ROOT / "tests/fixtures/sg13g2/make_series_switch.py").read_bytes(), "python")
    plan = parse_evaluation(b'''schema_version = 1
mode = "characterization"
[[jobs]]
id = "rc"
stage = "extract"
operation = "layout.extract_rc"
inputs = {layout = "input:layout"}
outputs = {netlist = "spice"}
parameters = {top_cell = "SERIES_SWITCH", ports = ["D", "G1", "G2", "S", "B"]}
[[jobs]]
id = "dc"
stage = "simulate"
operation = "circuit.simulate"
inputs = {deck = "input:dc", dut = "job:rc:netlist"}
parameters = {measurements = {current = "A"}}
[[metrics]]
id = "current"
category = "performance"
observations = ["dc:current"]
unit = "A"
direction = "maximize"
aggregation = "min"
''')
    dc = Asset(b'''* Measure the extracted wire with idealized device channels.
* Extraction still sees the real low-W/L MOS geometry. Replacing its channel
* model here separates wire resistance from MOS/body-bias changes.
.subckt sg13_lv_nmos D G S B w=1u l=1u ad=0 as=0 pd=0 ps=0
RCHANNEL D S 1m
.ends sg13_lv_nmos
.include dut.spice
.option rshunt=1e12
XDUT IN GATE GATE 0 0 SERIES_SWITCH
VGATE GATE 0 1.2
VDRIVE IN 0 1m
.dc VDRIVE 0 1m 1m
.measure dc current FIND i(VDRIVE) AT=1m
.end
''', "spice")
    resistances = []
    for length in (200, 2000):
        layout = tool.run(["python", "series.py", "series.gds", "--wire-length", str(length)],
                          {"series.py": source, **primitive_files}, {"series.gds": "gds"},
                          environment=environment)
        assert not layout.returncode and not layout.reason, layout.evidence
        report = run_evaluation(plan, {"input:layout": layout.files["series.gds"], "input:dc": dc},
                                backends, tmp_path / str(length))
        assert report["outcome"] == "passed", report["jobs"]
        resistances.append(-1e-3 / report["metrics"]["current"]["value"])
    # Metal1 sheet resistance is 0.110 ohm/square. Both drivers have W/L < 1;
    # integer truncation in Magic 8.3.678 used to silently omit this unlabelled
    # internal net. The ideal channel model isolates this geometric resistance.
    assert resistances[1] - resistances[0] == pytest.approx(0.110 * 1800 / 0.2, rel=2e-3)
