"""Pinned DC–130 GHz source diagnostics; these tests do not qualify a task.

Requires the TO/PDK checkouts and the unified tools image. Native extraction
must not replace the separately maintained schematic-derived LVS circuit.
"""

import json
import os
import re
import tomllib
from pathlib import Path

import pytest

from benchmarking.bundles import load_bundle
from benchmarking.docker import DockerTool
from benchmarking.files import Asset
from benchmarking.prepare_support import prepare_support
from benchmarking.upstream import evaluate

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "tasks/TO_Apr2025/cases/DC_to_130_GHz_TIA.design_1/case.toml"


@pytest.fixture(scope="module")
def source_context(tmp_path_factory):
    directory = tmp_path_factory.mktemp("to-source")
    support = directory / "support"
    prepare_support(ROOT / "third_party/IHP-Open-PDK", ROOT / "technology/sg13g2/klayout.json", support)
    case = tomllib.loads(CASE.read_text())
    checkout = ROOT / case["origin"]["checkout"]
    assets = {}
    for entry in case["sources"] + case["upstream_assets"]:
        asset = Asset((checkout / entry["path"]).read_bytes(), entry["format"])
        assert asset.sha256 == entry["sha256"], entry["path"]
        assets[entry["id"]] = asset
    return case, assets, support, os.environ.get("LAYOUT_BENCH_TEST_IMAGE", "layout-bench-tools:local")


def test_original_physical_rejection_preserves_reader_error(source_context, tmp_path):
    _, _, support, image = source_context
    report = evaluate(CASE, support, tmp_path / "run", image, root=ROOT)
    assert report["jobs"]["artifact"]["status"] == "passed"
    assert report["jobs"]["drc"]["status"] == "failed"
    # An incompatible poly card must be reported as an execution error,
    # never converted to NoMatch, silently bulk-tied, or accepted as a pass.
    lvs = report["jobs"]["lvs"]
    assert lvs["status"] == "error"
    assert any(b"Poly resistor should have 3 nodes" in (tmp_path / "run" / item["path"]).read_bytes()
               for item in lvs["evidence"].values())
    assert report["physical_valid"] is False
    assert report["task_success"] is None


def test_native_extraction_identifies_core_and_exposes_capacitor_disagreement(source_context):
    case, assets, support, image = source_context
    mapping = case["upstream_evaluation"]
    bundle = load_bundle(support)
    profile = json.loads(dict(bundle.files)[mapping["lvs_profile"]].content)
    variables = {**profile["variables"], "net_only": "true", "input": "/workspace/candidate.gds",
                 "topcell": mapping["top_cell"], "report": "/workspace/diagnostic.lvsdb",
                 "target_netlist": "/workspace/extracted.cir", "log": "/workspace/extraction.log"}
    command = ["klayout", "-b", "-r", "/workspace/support/" + profile["deck"]]
    for name, value in variables.items():
        command.extend(["-rd", f"{name}={value}"])
    result = DockerTool(image, ["klayout", "-v"], 180).run(
        command, {"candidate.gds": assets[mapping["layout"]],
                  **bundle.mounted_files()},
        {"extracted.cir": "spice", "extraction.log": "text"},
    )
    assert result.returncode == 0 and not result.reason, result.evidence
    raw = result.files["extracted.cir"].content.decode()
    cards = [line.split() for line in re.sub(r"\n\+", " ", raw).splitlines()
             if line and not line.startswith("*")]
    subcircuit = next(c for c in cards if c[0].upper() == ".SUBCKT")
    assert subcircuit[1] == mapping["top_cell"]
    ports = subcircuit[2:]
    assert set(ports) == {"INPUT", "OUTPUT", "VCC2V", "VCC2V$1", "VEE"}
    hbt = [c for c in cards if c[0].startswith("Q")]
    # The public schematic and design description specify two common-emitter
    # stages, Nx=5/4, with stage one's collector driving stage two's base.
    assert len(hbt) == 2
    first = next(c for c in hbt if c[2] == "INPUT")
    second = next(c for c in hbt if c[1] == "OUTPUT")
    assert first[1] == second[2]
    for card, nx in [(first, "5"), (second, "4")]:
        assert card[3:6] == ["VEE", "VEE", "npn13G2"]
        assert dict(t.split("=") for t in card[6:]) == {"we": "70n", "le": "900n", "Nx": nx, "m": "1"}
    resistors = [c for c in cards if "rppd" in c]
    assert len(resistors) == 3
    expected = {(frozenset(["VCC2V", first[1]]), "15u", "4u"),
                (frozenset(["INPUT", first[1]]), "29u", "6.3u"),
                (frozenset(["OUTPUT", "VCC2V$1"]), "11.5u", "2u")}
    actual = set()
    for card in resistors:
        assert card[3:5] == ["VEE", "rppd"]
        params = dict(t.split("=") for t in card[5:])
        assert params["m"] == "1"
        actual.add((frozenset(card[1:3]), params["w"], params["l"]))
    assert actual == expected
    taps = [c for c in cards if "ptap1" in c]
    assert len(taps) == 1 and taps[0][1:4] == ["VEE", "VEE", "ptap1"]
    assert dict(t.split("=") for t in taps[0][4:]) == {"A": "3.6504p", "P": "18.72u"}
    capacitors = [c for c in cards if "cap_cmim" in c]
    assert len(capacitors) == 2
    # The author's LVS reference puts both 30x30 um caps on the supplies.
    # Today's unmodified extraction does not. Keep this explicit discrepancy
    # visible until a reviewed investigation changes the source/tool contract.
    source = assets[mapping["netlist"]].content.decode()
    archived_caps = [line.split() for line in source.splitlines() if line.startswith("C")]
    assert {c[1] for c in archived_caps} == {"VCC2V", "VCC2V1"}
    for card in capacitors:
        assert card[2] == "VEE" and card[1] not in ports
        params = dict(t.split("=") for t in card[4:])
        assert (params["w"], params["l"]) == ("30u", "30u")
        assert all(card[1] not in other[1:4] for other in hbt + resistors)


def test_qucs_path_relocation_is_not_a_circuit_preserving_migration(source_context, tmp_path):
    case, assets, _, image = source_context
    original = assets[case["sources"][0]["id"]]
    source = original.content.decode()
    files = {}
    pdk = ROOT / "third_party/IHP-Open-PDK"
    for name in ("IHP_PDK_basic_components", "IHP_PDK_nonlinear_components"):
        path = pdk / f"ihp-sg13g2/libs.tech/qucs-s/user_lib/{name}.lib"
        files[f"lib/{name}.lib"] = Asset(path.read_bytes(), "text")
        source = re.sub(r'"[^"\n]*/' + name + r'"', '"/workspace/lib/' + name + '"', source)
    for entry in case["upstream_assets"]:
        if entry["format"] == "s2p":
            name = Path(entry["path"]).name
            files[f"em/{name}"] = assets[entry["id"]]
            source = re.sub(r'"[^"\n]*/' + re.escape(name) + r'"', '"/workspace/em/' + name + '"', source)
    files["source.sch"] = Asset(source.encode(), "text")
    tool = DockerTool(image, ["qucs-s", "--version"], 90)
    provenance = {"identity": tool.identity, "original_sha256": original.sha256,
                  "input_sha256": {name: asset.sha256 for name, asset in files.items()},
                  "scope": "Diagnostic library/S2P path relocation only; not an authoritative circuit export."}
    (tmp_path / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    devices = {}
    for flag, name in [("--cdl", "circuit.cdl"), ("--ngspice", "circuit.spice")]:
        result = tool.run(["qucs-s", "-n", flag, "-i", "/workspace/source.sch", "-o", "/workspace/" + name],
                          files, {name: "text"}, environment={"QT_QPA_PLATFORM": "offscreen"})
        (tmp_path / (name + ".log")).write_bytes(result.evidence["console"].content)
        assert result.returncode == 0 and not result.reason
        raw = result.files[name].content
        (tmp_path / name).write_bytes(raw)
        text = raw.decode()
        lines = [line.split() for line in text.splitlines()]
        devices[name] = [line for line in lines if line and line[0].startswith(("Xnpn", "Xrppd", "Xcap"))]
        resistors = [line for line in devices[name] if line[0].startswith("Xrppd")]
        assert len(resistors) == 3
        # New library symbols require bulk terminals absent from the old
        # schematic. The native exporter succeeds but invents unconnected net
        # names; these are not equivalent to the GDS's VEE-connected bulks.
        for resistor in resistors:
            bulk = resistor[4]
            assert bulk != "0"
            assert len(re.findall(r"(?<!\w)" + re.escape(bulk) + r"(?!\w)", text)) == 1
        # CDL mode also retains RF XSPICE transfer-function syntax, so this
        # full test circuit cannot be passed to the KLayout device reader.
        assert ".model xfer1 xfer" in text
    assert devices["circuit.cdl"] == devices["circuit.spice"]
