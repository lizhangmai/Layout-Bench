"""Export the pinned schematic with real Xschem; require course/PDK checkouts."""

import json
import os
import re
import tomllib
from pathlib import Path

import pytest

from benchmarking.bundles import load_bundle
from benchmarking.docker import DockerTool
from benchmarking.evaluate import run_evaluation
from benchmarking.evaluation import parse_evaluation
from benchmarking.files import Asset
from benchmarking.klayout import KLayoutDocker
from benchmarking.prepare import export_xschem, resolve_source_files
from benchmarking.prepare_support import prepare_support

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "tasks/ihp-sg13g2/IHP-AnalogAcademy/cases/input_pair"


def test_schematic_export_preserves_mos_and_computes_tap_from_dimensions(tmp_path):
    output = tmp_path / "export"
    export_xschem(CASE / "case.toml", {
        "analogacademy": ROOT / "third_party/IHP-AnalogAcademy",
        "pdk": ROOT / "third_party/IHP-Open-PDK",
    }, output, os.environ.get("LAYOUT_BENCH_TEST_IMAGE", "layout-bench-tools:local"))
    raw = (output / "input_common_centroid.cdl").read_text()
    assert raw.encode() == (CASE / "materials/circuit.cdl").read_bytes()
    assert "?" not in raw
    lines = [line.split() for line in raw.splitlines() if line and not line.startswith("*")]
    assert next(line for line in lines if line[0] == ".subckt") == [
        ".subckt", "input_common_centroid", "v-", "v+", "vdd", "dn3", "dn4",
    ]
    # Read directly from the schematic's six device instances. Ignore the
    # redundant device-name prefix added by the symbol's LVS format string.
    connections = {
        "1": ["dn3", "v-", "dn2", "bulk"],
        "2": ["dn4", "v+", "dn2", "bulk"],
        "8": ["dn4", "vdd", "vdd", "bulk"],
        "10": ["dn3", "vdd", "vdd", "bulk"],
        "15": ["dn2", "vdd", "vdd", "bulk"],
        "16": ["dn2", "vdd", "vdd", "bulk"],
    }
    mos = {line[0].lstrip("M"): line for line in lines if line[0].startswith("M")}
    assert mos.keys() == connections.keys()
    for name, nets in connections.items():
        assert mos[name][1:6] == [*nets, "sg13_lv_pmos"]
        assert dict(token.split("=") for token in mos[name][6:]) == {
            "w": "3.64u", "l": "3.7u", "ng": "1", "m": "2",
        }
    tap_lines = [line for line in raw.splitlines() if line.startswith("R")]
    assert len(tap_lines) == 1
    assert tap_lines[0].split()[1:4] == ["vdd", "bulk", "ntap1"]
    params = dict(re.findall(r"([AP])\s*=\s*(\S+)", tap_lines[0]))
    # The schematic declares 13 by 34 um. The unmodified PDK symbol uses
    # rectangle area and perimeter, independently of any layout extraction.
    assert float(params["A"]) == pytest.approx(442e-12, rel=1e-7)
    assert float(params["P"]) == pytest.approx(94e-6, rel=1e-7)
    provenance = json.loads((output / "provenance.json").read_text())
    assert provenance["postprocessing"] == "none"

    # Export the simulator dialect independently from the same pinned source.
    # No extracted layout or rewritten CDL supplies simulator device parameters.
    _, entries, _ = resolve_source_files(CASE / "case.toml")
    source_inputs = {}
    for entry in entries:
        checkout = "IHP-AnalogAcademy" if entry["checkout"] == "analogacademy" else "IHP-Open-PDK"
        asset = Asset((ROOT / "third_party" / checkout / entry["path"]).read_bytes(), "text")
        assert asset.sha256 == entry["sha256"]
        source_inputs["source/" + entry["target"]] = asset
    exported = DockerTool(os.environ.get("LAYOUT_BENCH_TEST_IMAGE", "layout-bench-tools:local"),
                          ["xschem", "--version"], 60).run(
        ["xschem", "-i", "-x", "-q", "-r", "-s", "--tcl",
         ("file mkdir /workspace/export; set XSCHEM_LIBRARY_PATH "
         "/workspace/source:$XSCHEM_SHAREDIR/xschem_library/devices; "
         "set top_is_subckt 1; set lvs_netlist 0; set spiceprefix 1"),
         "--command", "xschem set format format; xschem netlist",
         "-o", "/workspace/export", "-N", "circuit.spice",
         "/workspace/source/input_common_centroid.sch"],
        source_inputs, {"export/circuit.spice": "spice"},
    )
    assert exported.returncode == 0 and not exported.reason
    simulation = exported.files["export/circuit.spice"]
    assert simulation.content == (CASE / "materials/circuit.spice").read_bytes()
    tap = next(line.split() for line in simulation.content.decode().splitlines() if line.startswith("XR1 "))
    tap_params = dict(token.split("=") for token in tap[4:])
    # Independently evaluate the PDK symbol's area/perimeter conductance model.
    assert float(tap_params["R"]) == pytest.approx(1 / (442e-12 / 9.8e-10 + 94e-6 / 9.8e-4), rel=1e-6)

    # Interpret both CDL files and the simulator export with the pinned PDK's
    # reader. SPICE model names are case-insensitive; normalize that spelling
    # and instance-name prefixes without altering connectivity or parameters.
    script = """require 'json'
require 'logger'
def logger; Logger.new($stdout); end
def dbu; 0.001; end
base = '/workspace/support/ihp-sg13g2/libs.tech/klayout/tech/lvs/rule_decks/'
%w[globals.lvs custom_combiner.lvs custom_devices.lvs custom_mim_extractor.lvs custom_reader.lvs].each { |f| load(base + f) }
load('/workspace/support/sg13g2-model-calls.lvs')
result = {}
%w[fresh archived simulation].each do |kind|
  netlist = RBA::Netlist.new
  netlist.read((kind == 'simulation' ? 'circuit.spice' : kind + '.cdl'), RBA::NetlistSpiceReader.new(CustomReader.new))
  circuit = netlist.circuit_by_name('INPUT_COMMON_CENTROID')
  result[kind] = circuit.each_device.to_h do |d|
    cls = d.device_class
    [cls.name.downcase + ':' + d.name.sub(/^[MR]/, ''), {
      model: cls.name.downcase,
      params: cls.parameter_definitions.to_h { |p| [p.name, d.parameter(p.id)] },
      nets: cls.terminal_definitions.to_h { |t| [t.name, d.net_for_terminal(t.id).name] }
    }]
  end
end
File.write('comparison.json', JSON.pretty_generate(result))
"""
    prepare_support(ROOT / "third_party/IHP-Open-PDK", f"{ROOT}/tasks/ihp-sg13g2/pdk.toml#klayout",
                    tmp_path / "support")
    bundle = load_bundle(tmp_path / "support")
    config = tomllib.loads((CASE / "case.toml").read_text())
    archived = next(a for a in config["upstream_assets"] if a["role"] == "source-netlist")
    result = DockerTool(os.environ.get("LAYOUT_BENCH_TEST_IMAGE", "layout-bench-tools:local"),
                        ["klayout", "-v"], 120).run(
        ["klayout", "-b", "-r", "compare.rb"],
        {"compare.rb": Asset(script.encode(), "ruby"),
         "fresh.cdl": Asset(raw.encode(), "cdl"),
         "circuit.spice": simulation,
         "archived.cdl": Asset((ROOT / config["origin"]["checkout"] / archived["path"]).read_bytes(), "cdl"),
         **bundle.mounted_files()},
        {"comparison.json": "json"},
    )
    assert result.returncode == 0 and not result.reason, result.evidence["console"].content.decode()
    comparison = json.loads(result.files["comparison.json"].content)
    fresh, archived = comparison["fresh"], comparison["archived"]
    assert fresh == comparison["simulation"]
    assert fresh.keys() == archived.keys()
    for name in fresh:
        if fresh[name]["model"].lower() == "ntap1":
            assert fresh[name]["nets"] == archived[name]["nets"]
            assert fresh[name]["params"]["A"] == pytest.approx(442)
            assert fresh[name]["params"]["P"] == pytest.approx(94)
            assert archived[name]["params"]["A"] == pytest.approx(197.9248)
            assert archived[name]["params"]["P"] == pytest.approx(243.6)
        else:
            assert fresh[name] == archived[name]


def test_repaired_reference_passes_and_original_layout_is_rejected(tmp_path):
    support = tmp_path / "support"
    prepare_support(ROOT / "third_party/IHP-Open-PDK", f"{ROOT}/tasks/ihp-sg13g2/pdk.toml#klayout", support)
    config = tomllib.loads((CASE / "case.toml").read_text())
    original = next(a for a in config["upstream_assets"] if a["role"] == "reference")
    assets = {}
    for entry in config["assets"]:
        fmt = "spice" if entry["role"] == "source-netlist" else entry["format"]
        asset = Asset((CASE / entry["path"]).read_bytes(), fmt)
        assert asset.sha256 == entry["sha256"]
        assets[entry["role"]] = asset
    mapping = config["upstream_evaluation"]
    jobs, backends = [], {}
    for check in ("artifact", "drc", "lvs"):
        parameters = {"top_cell": mapping["top_cell"], "max_bytes": 67108864}
        inputs = {"layout": "candidate"}
        if check == "lvs":
            parameters["subcircuit"] = mapping["subcircuit"]
            inputs["netlist"] = "input:netlist"
        jobs.append({"id": check, "stage": "check", "operation": f"layout.{check}",
                     "gate": check, "inputs": inputs, "parameters": parameters})
        settings = {} if check == "artifact" else {
            "support": str(support), "profile": mapping[f"{check}_profile"],
        }
        backends[f"layout.{check}"] = KLayoutDocker(
            image=os.environ.get("LAYOUT_BENCH_TEST_IMAGE", "layout-bench-tools:local"),
            check=check, timeout_seconds=600, **settings)
    plan = parse_evaluation(json.dumps({"schema_version": 1, "mode": "physical",
                                       "jobs": jobs, "metrics": []}).encode(), file_format="json")
    for name, layout in [("reference", None), ("original", ROOT / config["origin"]["checkout"] / original["path"])]:
        output = tmp_path / name
        candidate = assets["physical-witness"] if layout is None else Asset(layout.read_bytes(), "gds")
        report = run_evaluation(plan, {"candidate": candidate, "input:netlist": assets["source-netlist"]},
                                backends, output)
        assert report["outcome"] == ("passed" if name == "reference" else "failed")
        assert report["jobs"]["artifact"]["status"] == "passed"
        for check in ("drc", "lvs"):
            assert report["jobs"][check]["status"] == ("passed" if name == "reference" else "failed")
        assert report["physical_valid"] is (name == "reference")
