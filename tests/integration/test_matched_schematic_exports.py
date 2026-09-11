"""Matched case schematics export equivalent, reproducible CDL and SPICE."""

import json
import os
import tomllib
from pathlib import Path

import pytest

from benchmarking.bundles import load_bundle
from benchmarking.docker import DockerTool
from benchmarking.files import Asset
from benchmarking.prepare import export_xschem, resolve_source_files
from benchmarking.prepare_support import prepare_support

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("case_name,top,ports,mos,taps", [
    ("full_OTA", "two_stage_OTA_layout", ["v-", "v+", "vss", "vdd", "iout", "vout"],
     [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 16],
     {"R1": (28.1356, 181.52), "R2": (8.559, 57.06), "R3": (6.9626, 44.92),
      "R4": (30.288, 201.92), "R5": (26.815, 173.0)}),
    ("comparator", "DIFF_COMPARATOR", ["vdd", "gnd", "v+", "v-", "clk", "out-", "out+", "vbias"],
     list(range(1, 14)), {"R1": (15.376, 99.2), "R2": (11.376, 75.84)}),
], ids=["full_OTA", "comparator"])
def test_matched_schematic_exports_preserve_reference_devices_and_tap_geometry(
        tmp_path, case_name, top, ports, mos, taps):
    case = ROOT / "tasks/ihp-sg13g2/IHP-AnalogAcademy/cases" / case_name
    image = os.environ.get("LAYOUT_BENCH_TEST_IMAGE", "layout-bench-tools:local")
    checkouts = {"case": case, "pdk": ROOT / "third_party/IHP-Open-PDK"}
    export_xschem(case / "case.toml", checkouts, tmp_path / "export", image)
    cdl = Asset((tmp_path / "export/circuit.cdl").read_bytes(), "spice")
    assert cdl.content == (case / "materials/circuit.cdl").read_bytes()
    assert b"?" not in cdl.content
    config = tomllib.loads((case / "case.toml").read_text())
    _, entries, _ = resolve_source_files(case / "case.toml")
    inputs = {}
    for entry in entries:
        asset = Asset((checkouts[entry["checkout"]] / entry["path"]).read_bytes(), "text")
        assert asset.sha256 == entry["sha256"]
        inputs["source/" + entry["target"]] = asset
    result = DockerTool(image, ["xschem", "--version"], 60).run(
        ["xschem", "-i", "-x", "-q", "-r", "-s", "--tcl",
         ("file mkdir /workspace/export; set XSCHEM_LIBRARY_PATH "
          "/workspace/source:$XSCHEM_SHAREDIR/xschem_library/devices; "
          "set top_is_subckt 1; set lvs_netlist 0; set spiceprefix 1"),
         "--command", "xschem set format format; xschem netlist",
         "-o", "/workspace/export", "-N", "circuit.spice",
         "/workspace/source/" + config["source_export"]["schematic"]],
        inputs, {"export/circuit.spice": "spice"},
    )
    assert result.returncode == 0 and not result.reason
    spice = result.files["export/circuit.spice"]
    assert spice.content == (case / "materials/circuit.spice").read_bytes()
    expected_ports = [top, *ports]
    for netlist in (cdl, spice):
        line = next(line for line in netlist.content.decode().splitlines() if line.startswith(".subckt"))
        assert line.split()[1:] == expected_ports

    prepare_support(checkouts["pdk"], f"{ROOT}/tasks/ihp-sg13g2/pdk.toml#klayout", tmp_path / "support")
    bundle = load_bundle(tmp_path / "support")
    # Cross-check model interfaces with the PDK reader without simplification:
    # this catches missing devices, altered terminals and geometry parameters.
    script = """require 'json'
require 'logger'
def logger; Logger.new($stdout); end
def dbu; 0.001; end
base = '/workspace/support/ihp-sg13g2/libs.tech/klayout/tech/lvs/rule_decks/'
%w[globals.lvs custom_combiner.lvs custom_devices.lvs custom_mim_extractor.lvs custom_reader.lvs].each { |f| load(base + f) }
load('/workspace/support/sg13g2-model-calls.lvs')
result = {}
%w[cdl spice].each do |kind|
  n = RBA::Netlist.new
  n.read('circuit.' + kind, RBA::NetlistSpiceReader.new(CustomReader.new))
  c = n.circuit_by_name('TWO_STAGE_OTA_LAYOUT')
  result[kind] = c.each_device.to_h do |d|
    cls = d.device_class
    [d.name, {model: cls.name.downcase,
      params: cls.parameter_definitions.to_h { |p| [p.name, d.parameter(p.id)] },
      nets: cls.terminal_definitions.to_h { |t| [t.name, d.net_for_terminal(t.id).name] }}]
  end
end
File.write('comparison.json', JSON.pretty_generate(result))
"""
    result = DockerTool(image, ["klayout", "-v"], 120).run(
        ["klayout", "-b", "-r", "compare.rb"],
        {"compare.rb": Asset(script.replace("TWO_STAGE_OTA_LAYOUT", top.upper()).encode(), "ruby"), "circuit.cdl": cdl,
         "circuit.spice": spice, **bundle.mounted_files()}, {"comparison.json": "json"},
    )
    assert result.returncode == 0 and not result.reason, result.evidence["console"].content.decode()
    comparison = json.loads(result.files["comparison.json"].content)
    (tmp_path / "comparison.json").write_bytes(result.files["comparison.json"].content)
    assert comparison["cdl"] == comparison["spice"]
    devices = comparison["cdl"]
    assert set(devices) == {*(f"M{i}" for i in mos), *taps, *(["C2"] if case_name == "full_OTA" else [])}
    # Independent active-ring geometry established for each reference; the
    # physical regressions additionally extract and compare the actual GDS.
    cards = [line.split() for line in spice.content.decode().splitlines() if line.startswith("XR")]
    for name, (area, perimeter) in taps.items():
        assert devices[name]["params"] == pytest.approx({"A": area, "P": perimeter})
        card = next(card for card in cards if card[0] == "X" + name)
        parameters = dict(token.split("=") for token in card[4:])
        expected_r = 1 / (area * 1e-12 / 9.8e-10 + perimeter * 1e-6 / 9.8e-4)
        # Native ev7 emits seven significant digits.
        assert float(parameters["r"]) == pytest.approx(expected_r, rel=1e-6)
