"""Fixed-interface input admittance from real, physically checked candidate RC."""

import json
import math
import os
import re
import struct
import tomllib
from pathlib import Path

import pytest

from benchmarking.evaluate import run_evaluation
from benchmarking.evaluation import parse_evaluation
from benchmarking.files import Asset
from benchmarking.prepare_support import prepare_support
from benchmarking.toolchains import load_toolchain

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "tasks/ihp-sg13g2/IHP-AnalogAcademy/cases/input_pair"


def _ac_rows(path):
    """Read ngspice Linux binary complex vectors, independently of .meas."""
    header, binary = path.read_bytes().split(b"Binary:\n", 1)
    fields, variables = header.decode().split("Variables:\n", 1)
    metadata = dict(line.split(":", 1) for line in fields.splitlines())
    assert "complex" in metadata["Flags"]
    names = [line.split()[1] for line in variables.splitlines() if line.strip()]
    values = [value[0] for value in struct.iter_unpack("<d", binary)]
    values = [complex(r, i) for r, i in zip(values[::2], values[1::2], strict=True)]
    assert len(values) == int(metadata["No. Points"]) * len(names)
    return [dict(zip(names, values[i:i + len(names)], strict=True))
            for i in range(0, len(values), len(names))]


def _characterization_plan(config):
    # Candidate cases have no task contract or performance limits. Build the
    # calibration plan here, using the case's declared physical scope.
    mapping = config["upstream_evaluation"]
    jobs = []
    for check in ("artifact", "drc", "lvs"):
        parameters = {"top_cell": mapping["top_cell"], "max_bytes": 67108864}
        inputs = {"layout": "candidate"}
        if check == "lvs":
            parameters["subcircuit"] = mapping["subcircuit"]
            inputs["netlist"] = "input:source-netlist"
        jobs.append({"id": check, "stage": "check", "operation": f"layout.{check}",
                     "gate": check, "inputs": inputs, "parameters": parameters})
    jobs.append({"id": "rc", "stage": "extract", "operation": "layout.extract_rc",
                 "requires": ["artifact", "drc", "lvs"], "inputs": {"layout": "candidate"},
                 "outputs": {"netlist": "spice"}, "parameters": {
                     "top_cell": mapping["top_cell"], "ports": ["v-", "v+", "vdd", "dn3", "dn4"]}})
    for phase in ("pre", "post"):
        for excitation in ("plus", "minus"):
            dut = "input:simulation-netlist" if phase == "pre" else "job:rc:netlist"
            jobs.append({"id": f"{phase}_{excitation}", "stage": "simulate", "operation": "circuit.simulate",
                         "inputs": {"deck": "input:testbench", "dut": dut},
                         "outputs": {"op": "ngspice-raw", "ac": "ngspice-raw"}, "parameters": {
                             "values": {"plus_ac": int(excitation == "plus"), "minus_ac": int(excitation == "minus")},
                             "exports": {"op": "op.raw", "ac": "ac.raw"}, "measurements": {
                                 "input_p_cap": "F", "input_m_cap": "F",
                                 "input_p_conductance": "S", "input_m_conductance": "S"}}})
    return parse_evaluation(json.dumps({"schema_version": 1, "mode": "characterization",
                                       "metrics": [], "jobs": jobs}).encode(), file_format="json")


def test_reference_rc_and_input_admittance_use_the_fixed_schematic_interface(tmp_path):
    text = (CASE / "case.toml").read_text()
    for profile, name in [("klayout", "klayout"), ("magic", "magic"), ("analog-models", "models")]:
        support = tmp_path / name
        prepare_support(ROOT / "third_party/IHP-Open-PDK", f"{ROOT}/tasks/ihp-sg13g2/pdk.toml#{profile}", support)
        text = text.replace(f"build/support/input-pair-{name}", str(support))
    text = text.replace("layout-bench-tools:local",
                        os.environ.get("LAYOUT_BENCH_TEST_IMAGE", "layout-bench-tools:local"))
    config_path = tmp_path / "case.toml"
    config_path.write_text(text)
    config = tomllib.loads(text)
    inputs = {}
    for entry in config["assets"]:
        asset = Asset((CASE / entry["path"]).read_bytes(),
                      "spice" if entry["format"] == "cdl" else entry["format"])
        assert asset.sha256 == entry["sha256"]
        key = "candidate" if entry["role"] == "physical-witness" else "input:" + entry["role"]
        inputs[key] = asset
    destination = tmp_path / "characterization"
    report = run_evaluation(
        _characterization_plan(config),
        inputs, load_toolchain(config_path), destination,
    )
    assert all(job["status"] == "passed" for job in report["jobs"].values()), report
    # Characterization reports intentionally leave aggregate task verdicts unset.
    assert report["physical_valid"] is None
    # This catches the former v- pin marker's off-wire extraction failure.
    extracted = report["jobs"]["rc"]["outputs"]["netlist"]
    netlist = (destination / extracted["path"]).read_text()
    # Magic escapes punctuation in local node names; positional port identity
    # is preserved through its recorded alias map, including continuation lines.
    alias_file = report["jobs"]["rc"]["evidence"]["port_aliases"]
    aliases = json.loads((destination / alias_file["path"]).read_text())["aliases"]
    original_names = {alias: name for name, alias in aliases.items()}
    logical_lines = re.sub(r"\n\+\s*", " ", netlist).splitlines()
    interface = next(line.split() for line in logical_lines if line.lower().startswith(".subckt"))
    assert [original_names.get(name, name) for name in interface] == [
        ".subckt", "input_common_centroid", "v-", "v+", "vdd", "dn3", "dn4",
    ]
    diagonal = {}
    for phase in ("pre", "post"):
        for excitation in ("plus", "minus"):
            job = report["jobs"][f"{phase}_{excitation}"]
            rows = _ac_rows(destination / job["outputs"]["ac"]["path"])
            assert rows[0]["frequency"].real == pytest.approx(1e3)
            assert rows[-1]["frequency"].real == pytest.approx(1e9)
            assert all(math.isfinite(v.real) and math.isfinite(v.imag) for row in rows for v in row.values())
            row = min(rows, key=lambda r: abs(r["frequency"].real - 1e6))
            assert row["frequency"].real == pytest.approx(1e6)
            for pin, node in (("p", "vp"), ("m", "vm")):
                driven = pin == ("p" if excitation == "plus" else "m")
                assert row[f"v({node})"] == pytest.approx(1 if driven else 0, abs=1e-12)
                # The source current points out of the DUT. The excitation is 1 V.
                admittance = -row[f"i({node})"]
                cap = admittance.imag / (2 * math.pi * row["frequency"].real)
                assert job["measurements"][f"input_{pin}_cap"]["value"] == pytest.approx(cap, rel=1e-6, abs=1e-21)
                assert job["measurements"][f"input_{pin}_conductance"]["value"] == pytest.approx(
                    admittance.real, rel=1e-6, abs=1e-20)
                if driven:
                    assert cap > 0
                    diagonal[phase, pin] = cap
    # The symmetric schematic has identical input loading; extracted metal
    # adds shunt/coupling capacitance. These are regression observations,
    # not performance limits for prospective benchmark submissions.
    assert diagonal["pre", "p"] == pytest.approx(diagonal["pre", "m"], rel=1e-5)
    for pin in ("p", "m"):
        assert diagonal["post", pin] > diagonal["pre", pin]
