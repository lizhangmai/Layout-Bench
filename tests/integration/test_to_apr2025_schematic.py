"""The approved design_1 core source: export fidelity, actual LVS and DC models.

Requires the TO/PDK checkouts and tools image. No RF or PEX qualification.
"""

import json
import os
import struct
import tomllib
from pathlib import Path

import pytest

from benchmarking.bundles import load_bundle
from benchmarking.docker import DockerTool
from benchmarking.evaluate import run_evaluation
from benchmarking.evaluation import parse_evaluation
from benchmarking.files import Asset
from benchmarking.klayout import KLayoutDocker
from benchmarking.ngspice import NgspiceDocker
from benchmarking.prepare import export_xschem
from benchmarking.prepare_support import prepare_support

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "tasks/TO_Apr2025/cases/DC_to_130_GHz_TIA.design_1"
TOP = "FMD_QNC_03a_TIA_1"
PORTS = ["INPUT", "OUTPUT", "VCC2V", "VCC2V1", "VEE"]


@pytest.fixture(scope="module")
def context(tmp_path_factory):
    directory = tmp_path_factory.mktemp("to-derived")
    config = tomllib.loads((CASE / "case.toml").read_text())
    image = os.environ.get("LAYOUT_BENCH_TEST_IMAGE", "layout-bench-tools:local")
    for name in ("klayout", "hbt-models"):
        prepare_support(ROOT / "third_party/IHP-Open-PDK", ROOT / f"technology/sg13g2/{name}.json",
                        directory / name, compiler_image=image)
    for entry in config["assets"]:
        assert Asset((CASE / entry["path"]).read_bytes(), entry["format"]).sha256 == entry["sha256"]
    return config, image, directory


def test_both_exports_preserve_the_approved_core(context, tmp_path):
    config, image, directory = context
    checkouts = {"case": CASE, "pdk": ROOT / "third_party/IHP-Open-PDK"}
    export_xschem(CASE / "case.toml", checkouts, tmp_path / "cdl", image)
    cdl = Asset((tmp_path / "cdl/circuit.cdl").read_bytes(), "spice")
    assert cdl.content == (CASE / "materials/circuit.cdl").read_bytes()
    inputs = {}
    for entry in config["source_export"]["files"]:
        asset = Asset((checkouts[entry["checkout"]] / entry["path"]).read_bytes(), "text")
        assert asset.sha256 == entry["sha256"]
        inputs["source/" + entry["target"]] = asset
    tool = DockerTool(image, ["xschem", "--version"], 60)
    command = ["xschem", "-i", "-x", "-q", "-r", "-s", "--tcl",
               ("file mkdir /workspace/export; set XSCHEM_LIBRARY_PATH "
               "/workspace/source:$XSCHEM_SHAREDIR/xschem_library/devices; "
               "set top_is_subckt 1; set lvs_netlist 0; set spiceprefix 1"),
               "--command", "xschem set format format; xschem netlist", "-o", "/workspace/export",
               "-N", "circuit.spice", "/workspace/source/" + config["source_export"]["schematic"]]
    result = tool.run(command, inputs, {"export/circuit.spice": "spice"})
    assert result.returncode == 0 and not result.reason
    spice = result.files["export/circuit.spice"]
    assert spice.content == (CASE / "materials/circuit.spice").read_bytes()
    (tmp_path / "circuit.spice").write_bytes(spice.content)
    (tmp_path / "simulation-export.json").write_text(json.dumps({
        "identity": tool.identity, "command": command, "postprocessing": "none",
        "inputs": {name: asset.sha256 for name, asset in inputs.items()}, "output": spice.sha256,
    }, indent=2) + "\n")
    for netlist in (cdl, spice):
        lines = netlist.content.decode().splitlines()
        assert next(line.split()[1:] for line in lines if line.startswith(".subckt")) == [TOP, *PORTS]
        assert "expr_eng" not in netlist.content.decode() and b"?" not in netlist.content

    # Native PDK parsing validates the actual CDL dialect, terminals and units.
    script = """require 'json'
require 'logger'
def logger; Logger.new($stdout); end
def dbu; 0.001; end
SERIES_RES = true
PARALLEL_RES = true
base = '/workspace/support/ihp-sg13g2/libs.tech/klayout/tech/lvs/rule_decks/'
%w[globals.lvs custom_combiner.lvs custom_devices.lvs custom_mim_extractor.lvs custom_bjt_extractor.lvs custom_reader.lvs].each { |f| load(base + f) }
n = RBA::Netlist.new
n.read('circuit.cdl', RBA::NetlistSpiceReader.new(CustomReader.new))
c = n.circuit_by_name('FMD_QNC_03A_TIA_1')
data = c.each_device.to_h do |d|
  cls = d.device_class
  [d.name, {model: cls.name.downcase,
    params: cls.parameter_definitions.to_h { |p| [p.name, d.parameter(p.id)] },
    nets: cls.terminal_definitions.map { |t| d.net_for_terminal(t.id).name }}]
end
File.write('devices.json', JSON.pretty_generate(data))
"""
    result = DockerTool(image, ["klayout", "-v"], 60).run(
        ["klayout", "-b", "-r", "read.rb"],
        {"read.rb": Asset(script.encode(), "ruby"), "circuit.cdl": cdl,
         **load_bundle(directory / "klayout").mounted_files()}, {"devices.json": "json"})
    assert result.returncode == 0 and not result.reason, result.evidence["console"].content.decode()
    devices = json.loads(result.files["devices.json"].content)
    # Expected graph comes from the approved source boundary, not extraction.
    expected = {
        "Q1": ("npn13g2", ["DN1", "INPUT", "VEE", "VEE"], {"Nx": 5, "we": 0.07, "le": 0.9}),
        "Q2": ("npn13g2", ["OUTPUT", "DN1", "VEE", "VEE"], {"Nx": 4, "we": 0.07, "le": 0.9}),
        "RC1": ("rppd", ["VCC2V", "DN1", "VEE"], {"w": 15, "l": 4, "m": 1, "b": 0}),
        "RC2": ("rppd", ["VCC2V1", "OUTPUT", "VEE"], {"w": 11.5, "l": 2, "m": 1, "b": 0}),
        "RF": ("rppd", ["DN1", "INPUT", "VEE"], {"w": 29, "l": 6.3, "m": 1, "b": 0}),
        "C1": ("cap_cmim", ["VCC2V", "VEE"], {"w": 30, "l": 30, "m": 1}),
        "C2": ("cap_cmim", ["VCC2V1", "VEE"], {"w": 30, "l": 30, "m": 1}),
        "RTAP": ("ptap1", ["VEE", "VEE"], {"A": 3.6504, "P": 18.72}),
    }
    assert devices.keys() == expected.keys()
    simulator = {line.split()[0][1:]: line.split()[1:] for line in spice.content.decode().splitlines()
                 if line.startswith("X")}
    assert simulator.keys() == expected.keys()
    for name, (model, nets, params) in expected.items():
        d = devices[name]
        assert d["model"] == model and d["nets"] == nets
        assert {key: d["params"][key] for key in params} == pytest.approx(params)
        card = simulator[name]
        assert card[:len(nets)] == nets and card[len(nets)].lower() == model
        values = dict(token.split("=") for token in card[len(nets) + 1:])
        # Native model calls express geometry in metres; the reader uses um.
        for key, value in params.items():
            if key in {"we", "le"}:
                continue  # npn13G2's fixed emitter geometry is encoded in its model.
            scale = 1e-12 if key == "A" else 1e-6 if key in {"w", "l", "P"} else 1
            token = values[key.lower() if key in {"A", "P"} else key]
            number = float(token[:-1]) * 1e-6 if token.endswith("u") else float(token)
            assert number == pytest.approx(value * scale)
    resistance = float(simulator["RTAP"][-1].split("=")[1])
    assert resistance == pytest.approx(1 / (3.6504e-12 / 9.8e-10 + 18.72e-6 / 9.8e-4), rel=1e-6)


def test_original_gds_matches_core_but_rejects_capacitor_connections(context, tmp_path):
    config, image, directory = context
    mapping = config["upstream_evaluation"]
    entry = next(a for a in config["upstream_assets"] if a["id"] == mapping["layout"])
    candidate = Asset((ROOT / config["origin"]["checkout"] / entry["path"]).read_bytes(), "gds")
    assert candidate.sha256 == entry["sha256"]
    plan = parse_evaluation(json.dumps({"schema_version": 1, "mode": "characterization", "metrics": [],
        "jobs": [{"id": "lvs", "stage": "check", "operation": "layout.lvs",
                  "inputs": {"layout": "input:layout", "netlist": "input:netlist"},
                  "parameters": {"top_cell": TOP, "subcircuit": TOP, "max_bytes": 67108864}}],
    }).encode(), file_format="json")
    settings = {**config["toolchain"]["backends"]["lvs"]["settings"],
                "image": image, "support": str(directory / "klayout")}
    report = run_evaluation(plan, {"input:layout": candidate,
        "input:netlist": Asset((CASE / "materials/circuit.cdl").read_bytes(), "spice")},
        {"layout.lvs": KLayoutDocker(**settings)}, tmp_path / "lvs")
    job = report["jobs"]["lvs"]
    assert job["status"] == "failed" and report["task_success"] is None
    native = Asset((tmp_path / "lvs" / job["evidence"]["report.db"]["path"]).read_bytes(), "lvsdb")
    script = """import json, klayout.db as k
n=k.LayoutVsSchematic(); n.read('report.lvsdb'); x=n.xref()
c=next(x.each_circuit_pair())
assert str(c.status()) == 'NoMatch'
result={p.second().name:str(p.status()) for p in x.each_device_pair(c) if p.second()}
open('pairs.json','w').write(json.dumps(result))
"""
    result = DockerTool(image, ["klayout", "-v"], 60).run(
        ["python", "pairs.py"], {"pairs.py": Asset(script.encode(), "python"), "report.lvsdb": native},
        {"pairs.json": "json"})
    assert result.returncode == 0 and not result.reason
    assert json.loads(result.files["pairs.json"].content) == {
        "Q1": "Match", "Q2": "Match", "RC1": "Match", "RC2": "Match", "RF": "Match",
        "RTAP": "Match", "C1": "Mismatch", "C2": "Mismatch"}


def test_core_operating_point_uses_real_hbt_resistor_and_capacitor_models(context, tmp_path):
    config, image, directory = context
    plan = parse_evaluation(json.dumps({"schema_version": 1, "mode": "characterization", "metrics": [],
        "jobs": [{"id": "op", "stage": "simulate", "operation": "circuit.simulate",
                  "inputs": {"deck": "input:deck", "circuit": "input:circuit"},
                  "outputs": {"waveform": "ngspice-raw"},
                  "parameters": {"measurements": {"input_bias": "V", "output_bias": "V",
                                 "supply1_current": "A", "supply2_current": "A"},
                                 "exports": {"waveform": "operating_point.raw"}}}],
    }).encode(), file_format="json")
    settings = {**config["toolchain"]["backends"]["simulation"]["settings"],
                "image": image, "support": str(directory / "hbt-models")}
    report = run_evaluation(plan, {
        "input:deck": Asset((CASE / "materials/testbench.spice").read_bytes(), "spice"),
        "input:circuit": Asset((CASE / "materials/circuit.spice").read_bytes(), "spice")},
        {"circuit.simulate": NgspiceDocker(**settings)}, tmp_path / "op")
    assert report["outcome"] == "passed", report["jobs"]["op"]["reason"]
    assert report["task_success"] is None
    job = report["jobs"]["op"]
    raw = (tmp_path / "op" / job["outputs"]["waveform"]["path"]).read_bytes()
    header, binary = raw.split(b"Binary:\n", 1)
    fields, variables = header.decode().split("Variables:\n", 1)
    assert "No. Points: 1" in fields and "Flags: real" in fields
    names = [line.split()[1] for line in variables.splitlines() if line.strip()]
    values = [v[0] for v in struct.iter_unpack("<d", binary)]
    waveform = dict(zip(names, values, strict=True))
    for name, expression in [("input_bias", "v(input)"), ("output_bias", "v(output)"),
                             ("supply1_current", "i(vcc1)"), ("supply2_current", "i(vcc2)")]:
        expected = waveform[expression] * (-1 if name.endswith("current") else 1)
        assert job["measurements"][name]["value"] == pytest.approx(expected, rel=1e-6)
    assert waveform["v(vcc1)"] == 2 and waveform["v(vcc2)"] == 2
    # A connected, self-biased core draws current from both independent sources.
    # These are source smoke checks, not benchmark performance limits.
    assert waveform["i(vcc1)"] < 0 and waveform["i(vcc2)"] < 0


def test_original_capacitor_routes_lack_supply_pad_vias(context, tmp_path):
    config, image, _ = context
    entry = next(a for a in config["upstream_assets"] if a["id"] == config["upstream_evaluation"]["layout"])
    candidate = Asset((ROOT / config["origin"]["checkout"] / entry["path"]).read_bytes(), "gds")
    assert candidate.sha256 == entry["sha256"]
    # Independent conductor tracing excludes device extraction/simplification.
    # Layer numbers come from the pinned SG13G2 layer map and via stack.
    script = """import json, klayout.db as k
l=k.Layout();l.read('candidate.gds');top=l.top_cell();top.flatten(True)
n=k.LayoutToNetlist(k.RecursiveShapeIterator(l,top,[]))
stack=[('m1',8),('v1',19),('m2',10),('v2',29),('m3',30),('v3',49),
       ('m4',50),('v4',66),('m5',67),('tv1',125),('tm1',126),('tv2',133),('tm2',134)]
layers={name:n.make_layer(l.layer(layer,0),name) for name,layer in stack}
for layer in layers.values():n.connect(layer)
for (a,_),(b,_) in zip(stack,stack[1:]):n.connect(layers[a],layers[b])
for name,layer in [('vmim',129),('mim',36)]:
    layers[name]=n.make_layer(l.layer(layer,0),name);n.connect(layers[name])
n.connect(layers['tm1'],layers['vmim']);n.connect(layers['vmim'],layers['mim'])
n.extract_netlist()
def region(layer):return k.Region(top.begin_shapes_rec(l.layer(layer,0)))
mim=region(36);tm2=region(134);tv2=region(133)
labels=[s.text for s in top.shapes(l.layer(134,25)).each() if s.is_text()]
result=[]
for cap in mim.each():
    net=n.probe_net(layers['mim'],k.DPoint(cap.bbox().center())*l.dbu)
    metal=n.shapes_of_net(net,layers['tm1'])
    overlap=metal&tm2
    result.append({'cap':str(cap.bbox()*l.dbu),
       'overlap_boxes':[str(p.bbox()*l.dbu) for p in overlap.each()],
       'overlap_area':overlap.area()*l.dbu*l.dbu,
       'via_area':(metal&tv2).area()*l.dbu*l.dbu,
       'connected_tm2_area':n.shapes_of_net(net,layers['tm2']).area()*l.dbu*l.dbu,
       'labels':[t.string for t in labels if not (overlap&k.Region(k.Box(t.x,t.y,t.x+1,t.y+1))).is_empty()]})
open('connectivity.json','w').write(json.dumps(result,indent=2))
"""
    result = DockerTool(image, ["klayout", "-v"], 60).run(
        ["python", "trace.py"], {"trace.py": Asset(script.encode(), "python"), "candidate.gds": candidate},
        {"connectivity.json": "json"})
    assert result.returncode == 0 and not result.reason, result.evidence["console"].content.decode()
    (tmp_path / "connectivity.json").write_bytes(result.files["connectivity.json"].content)
    data = json.loads(result.files["connectivity.json"].content)
    assert len(data) == 2
    for cap in data:
        # A 50x50 um supply pad physically overlaps the capacitor's TM1 route,
        # but the original GDS supplies no connecting TopVia2 at either pad.
        assert cap["overlap_area"] == 2500 and cap["labels"] == ["VCC2V"]
        assert cap["via_area"] == 0 and cap["connected_tm2_area"] == 0


def test_physical_proposal_preserves_circuit_layers_and_labels(context, tmp_path):
    config, image, _ = context
    entry = next(a for a in config["upstream_assets"] if a["id"] == config["upstream_evaluation"]["layout"])
    original = Asset((ROOT / config["origin"]["checkout"] / entry["path"]).read_bytes(), "gds")
    entry = next(a for a in config["assets"] if a["role"] == "unqualified-reference-layout")
    candidate = Asset((CASE / entry["path"]).read_bytes(), "gds")
    assert candidate.sha256 == entry["sha256"]
    # Protect the independently stated repair scope: auxiliary top-level marks
    # may be removed, while functional device layers and all labels stay intact.
    script = """import json, klayout.db as k
layouts=[]
for path in ['original.gds','candidate.gds']:
    l=k.Layout();l.read(path);layouts.append(l)
a,b=layouts
assert a.dbu == b.dbu == 0.001
assert [c.name for c in a.top_cells()] == [c.name for c in b.top_cells()]
assert a.top_cell().bbox() == b.top_cell().bbox()
def region(l,info):return k.Region(l.top_cell().begin_shapes_rec(l.layer(info)))
def texts(l,info):
    it=l.top_cell().begin_shapes_rec(l.layer(info));result=[]
    while not it.at_end():
        if it.shape().is_text():result.append(str(it.shape().text.transformed(it.trans())))
        it.next()
    return sorted(result)
allowed={(1,0),(6,0),(8,0),(19,0),(8,22),(5,23),(126,0),(133,0),(134,0),(41,0)}
infos={(i.layer,i.datatype) for l in layouts for i in l.layer_infos()}
areas={}
for layer,datatype in infos:
    info=k.LayerInfo(layer,datatype);old=region(a,info);new=region(b,info)
    if (layer,datatype) not in allowed:assert (old^new).is_empty(),str(info)
    assert texts(a,info)==texts(b,info), str(info)
    if not (old^new).is_empty():
        areas[str(info)]={'added_um2':(new-old).area()*1e-6,'removed_um2':(old-new).area()*1e-6}
# All functional Activ/Cont geometry is below the original top cell.
# Only its six auxiliary mark groups are removed by this proposal.
for layer in [1,6]:
    info=k.LayerInfo(layer,0)
    auxiliary=k.Region(a.top_cell().shapes(a.layer(info)))
    assert (region(b,info)^(region(a,info)-auxiliary)).is_empty()
# The 16 supply vias are actual cuts, outside the unchanged passivation openings.
info=k.LayerInfo(133,0);added=region(b,info)-region(a,info)
assert added.count()==16
assert all(p.bbox().width()==900 and p.bbox().height()==900 for p in added.each())
assert (added&region(b,k.LayerInfo(9,0))).is_empty()
# No nofill/rule-exclusion layer was added. The poly keepouts are smaller;
# existing filler geometry stays unchanged and the local keepouts fit 400 um.
info=k.LayerInfo(5,23)
assert (region(b,info)-region(a,info)).is_empty()
assert all(max(p.bbox().width(),p.bbox().height())<=400000 for p in region(b,info).merged().each())
# Pad outlines must identify real metal and real passivation, not blank waivers.
pads=region(b,k.LayerInfo(41,0))-region(a,k.LayerInfo(41,0))
assert pads.count()==2
assert (pads-region(b,k.LayerInfo(134,0))).is_empty()
assert all(not (k.Region(p)&region(b,k.LayerInfo(9,0))).is_empty() for p in pads.each())
open('geometry.json','w').write(json.dumps(areas,indent=2))
"""
    result = DockerTool(image, ["klayout", "-v"], 60).run(
        ["python", "geometry.py"], {"geometry.py": Asset(script.encode(), "python"),
         "original.gds": original, "candidate.gds": candidate}, {"geometry.json": "json"})
    assert result.returncode == 0 and not result.reason, result.evidence["console"].content.decode()
    (tmp_path / "geometry.json").write_bytes(result.files["geometry.json"].content)


def test_complete_physical_proposal_passes_both_drc_decks_and_lvs(context, tmp_path):
    config, image, directory = context
    entry = next(a for a in config["assets"] if a["role"] == "unqualified-reference-layout")
    candidate = Asset((CASE / entry["path"]).read_bytes(), "gds")
    jobs, backends = [], {}
    for check in ("artifact", "drc", "lvs"):
        operation = "layout." + check
        inputs = {"layout": "candidate"}
        parameters = {"top_cell": TOP, "max_bytes": 67108864}
        if check == "lvs":
            inputs["netlist"] = "input:netlist"
            parameters["subcircuit"] = TOP
        jobs.append({"id": check, "stage": "check", "gate": check, "operation": operation,
                     "inputs": inputs, "parameters": parameters})
        binding = config["toolchain"]["bindings"][operation]
        settings = {**config["toolchain"]["backends"][binding]["settings"], "image": image}
        if check != "artifact":
            settings["support"] = str(directory / "klayout")
        backends[operation] = KLayoutDocker(**settings)
    plan = parse_evaluation(json.dumps({"schema_version": 1, "mode": "physical",
                                       "metrics": [], "jobs": jobs}).encode(), file_format="json")
    report = run_evaluation(plan, {"candidate": candidate,
        "input:netlist": Asset((CASE / "materials/circuit.cdl").read_bytes(), "spice")},
        backends, tmp_path / "physical")
    assert {name: job["status"] for name, job in report["jobs"].items()} == {
        "artifact": "passed", "drc": "passed", "lvs": "passed"}
    assert report["physical_valid"] is True and report["task_success"] is None
    # Both maintained decks must complete with empty native report databases.
    import xml.etree.ElementTree as ET
    evidence = report["jobs"]["drc"]["evidence"]
    for name in ("report.db", "report-1.db"):
        native_report = ET.fromstring((tmp_path / "physical" / evidence[name]["path"]).read_bytes())
        assert not native_report.findall("./items/item")
    native = report["jobs"]["lvs"]["evidence"]["report.db"]
    script = """import json, klayout.db as k
n=k.LayoutVsSchematic();n.read('report.lvsdb');x=n.xref()
c=next(x.each_circuit_pair());assert str(c.status())=='Match'
result={p.second().name:str(p.status()) for p in x.each_device_pair(c) if p.second()}
open('pairs.json','w').write(json.dumps(result))
"""
    result = DockerTool(image, ["klayout", "-v"], 60).run(
        ["python", "pairs.py"], {"pairs.py": Asset(script.encode(), "python"),
         "report.lvsdb": Asset((tmp_path / "physical" / native["path"]).read_bytes(), "lvsdb")},
        {"pairs.json": "json"})
    assert result.returncode == 0 and not result.reason
    assert json.loads(result.files["pairs.json"].content) == dict.fromkeys(
        ["Q1", "Q2", "RC1", "RC2", "RF", "RTAP", "C1", "C2"], "Match")
