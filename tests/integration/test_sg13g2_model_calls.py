"""The SG13G2 input adapter preserves native device and hierarchy semantics."""

import json
from pathlib import Path

import pytest

from benchmarking.bundles import load_bundle
from benchmarking.docker import DockerTool
from benchmarking.files import Asset
from benchmarking.prepare_support import prepare_support

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def test_model_calls_preserve_geometry_multiplicity_terminals_and_hierarchy(tmp_path):
    # Independent device dimensions exercise SI-to-micron scaling, width*m,
    # area/perimeter formulas, and a hierarchical call that must stay a circuit.
    source = """* Model interface probe
.subckt child d g s b
XN d g s b sg13_lv_nmos w=2u l=0.5u ng=2 m=3
.ends child
.subckt sample d g s b
.param tap_a=2p tap_p=6u
XH d g s b child
XP d g s b sg13_lv_pmos w=4u l=1u ng=2 m=2
XC d s cap_cmim w=3u l=5u m=2
XTN d b ntap1 a={tap_a} p={tap_p}
+ r={1/(tap_a/9.8e-10+tap_p/9.8e-4)}
XTP s b ptap1 a=4p p=10u r=70
.ends sample
"""
    script = """require 'json'
require 'logger'
def logger; Logger.new($stdout); end
def dbu; 0.001; end
base = '/workspace/support/ihp-sg13g2/libs.tech/klayout/tech/lvs/rule_decks/'
%w[globals.lvs custom_combiner.lvs custom_devices.lvs custom_mim_extractor.lvs custom_reader.lvs].each { |f| load(base + f) }
# Ruby load installs just the input adapter; %include is a runset directive.
load('/workspace/support/sg13g2-model-calls.lvs')
netlist = RBA::Netlist.new
netlist.read('source.spice', RBA::NetlistSpiceReader.new(CustomReader.new))
circuits = {}
netlist.each_circuit do |c|
  devices = {}
  c.each_device do |d|
    cls = d.device_class
    devices[d.name] = {
      model: cls.name.downcase,
      params: cls.parameter_definitions.to_h { |p| [p.name, d.parameter(p.id)] },
      nets: cls.terminal_definitions.to_h { |t| [t.name, d.net_for_terminal(t.id).name] }
    }
  end
  circuits[c.name] = {
    devices: devices,
    hierarchy: c.each_subcircuit.map { |s| [s.name, s.circuit_ref.name] }
  }
end
File.write('devices.json', JSON.generate(circuits))
"""
    prepare_support(ROOT / "third_party/IHP-Open-PDK", ROOT / "technology/sg13g2/klayout.json", tmp_path / "support")
    support = load_bundle(tmp_path / "support")
    result = DockerTool("layout-bench-tools:local", ["klayout", "-v"], 120).run(
        ["klayout", "-b", "-r", "probe.rb"],
        {"probe.rb": Asset(script.encode(), "ruby"), "source.spice": Asset(source.encode(), "spice"),
         **support.mounted_files()}, {"devices.json": "json"})
    assert result.returncode == 0 and not result.reason, result.evidence["console"].content.decode()
    circuits = json.loads(result.files["devices.json"].content)
    child, sample = circuits["CHILD"], circuits["SAMPLE"]
    assert sample["hierarchy"] == [["H", "CHILD"]]
    nmos = child["devices"]["N"]
    pmos = sample["devices"]["P"]
    assert nmos["model"] == "sg13_lv_nmos"
    assert pmos["model"] == "sg13_lv_pmos"
    for mos, width, length in [(nmos, 6, 0.5), (pmos, 8, 1)]:
        assert mos["params"]["W"] == pytest.approx(width)
        assert mos["params"]["L"] == pytest.approx(length)
        assert mos["nets"] == {"D": "D", "G": "G", "S": "S", "B": "B"}
    capacitor = sample["devices"]["C"]
    assert capacitor["model"] == "cap_cmim"
    assert capacitor["params"] == pytest.approx({"w": 3, "l": 5, "A": 15, "P": 16, "m": 2})
    assert capacitor["nets"] == {"mim_top": "D", "mim_btm": "S"}
    for name, model, area, perimeter, tie in [("TN", "ntap1", 2, 6, "D"), ("TP", "ptap1", 4, 10, "S")]:
        tap = sample["devices"][name]
        assert tap["model"] == model
        assert tap["params"] == pytest.approx({"A": area, "P": perimeter})
        assert tap["nets"] == {"TIE": tie, "WELL": "B"}
