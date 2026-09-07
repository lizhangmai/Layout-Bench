"""Real upstream DRC/LVS gates and post-layout success, using newly built GDS."""

import json
import runpy
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarking.bundles import publish_bundle
from benchmarking.environment import prepare_pdk
from benchmarking.evaluate import run_evaluation
from benchmarking.files import Asset
from benchmarking.klayout import KLayoutDocker
from benchmarking.prepare_support import prepare_support
from benchmarking.tasks import load_task
from benchmarking.toolchains import load_toolchain

pytestmark = [pytest.mark.integration, pytest.mark.acceptance, pytest.mark.acceptance_eda]
ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples/sg13g2"


@pytest.fixture(scope="module")
def context(tmp_path_factory):
    root = tmp_path_factory.mktemp("physical-checks")
    pdk = ROOT / "third_party/IHP-Open-PDK"
    for profile, dest in [("klayout", "klayout"), ("magic", "magic"), ("mos-models", "models")]:
        prepare_support(pdk, ROOT / f"technology/sg13g2/{profile}.json", root / dest)
    prepare_pdk(pdk, root / "view")
    generate = runpy.run_path(str(EXAMPLES / "generate.py"))["generate_fixtures"]
    fixtures = generate(root / "view", root / "fixtures", suite="checks")
    config = (EXAMPLES / "checked-switch/toolchain.toml").read_text()
    for old, new in [("klayout", "klayout"), ("magic", "magic"), ("mos-models", "models")]:
        config = config.replace(f"build/support/sg13g2-{old}", str(root / new))
    (root / "toolchain.toml").write_text(config)
    return fixtures, load_toolchain(root / "toolchain.toml"), load_task(EXAMPLES / "checked-switch/task.toml")


def run_fixture(context, name, destination):
    fixtures, backends, task = context
    return run_evaluation(task.evaluation, {"candidate": fixtures[name], **task.evaluation_inputs()},
                          backends, destination, task_sha256=task.digest)


def test_physical_success_is_not_sufficient_for_task_success(context, tmp_path):
    valid = run_fixture(context, "valid", tmp_path / "valid")
    slow = run_fixture(context, "slow", tmp_path / "slow")
    for report in (valid, slow):
        assert report["physical_valid"] is True, report["jobs"]
        assert all(j["status"] == "passed" for j in report["jobs"].values()), report["jobs"]
        assert report["metrics"]["low_voltage"]["status"] == "passed"
        assert report["jobs"]["drc"]["evidence"]["report.db"]["bytes"] > 1000
        assert report["jobs"]["lvs"]["evidence"]["extracted.spice"]["bytes"] > 100
        assert report["jobs"]["parasitics"]["inputs"]["layout"]["sha256"] == report["inputs"]["candidate"]["sha256"]
        assert report["jobs"]["transient"]["inputs"]["dut"]["sha256"] == report["jobs"]["parasitics"]["outputs"]["netlist"]["sha256"]
    assert valid["task_success"] is True and valid["outcome"] == "passed"
    assert slow["task_success"] is False and slow["outcome"] == "failed"
    assert slow["metrics"]["fall_delay"]["value"] > 20 * valid["metrics"]["fall_delay"]["value"]
    assert slow["quality_eligible"] is False


@pytest.mark.parametrize("fault,gate", [("short", "lvs"), ("open", "lvs"), ("parameter", "lvs"),
                                        ("pin", "lvs"), ("drc", "drc"), ("empty", "artifact")])
def test_invalid_geometry_is_rejected_and_blocks_post_layout(context, tmp_path, fault, gate):
    report = run_fixture(context, fault, tmp_path / fault)
    assert report["jobs"][gate]["status"] == "failed", report["jobs"]
    assert report["outcome"] == "failed", report["jobs"]
    assert report["physical_valid"] is False and report["task_success"] is False
    assert report["jobs"]["parasitics"]["status"] == "blocked"
    assert report["jobs"]["transient"]["status"] == "blocked"
    assert report["metrics"]["fall_delay"]["value"] is None
    assert report["jobs"][gate]["evidence"]["result.json"]["bytes"] > 0


def test_artifact_rejection_limits_and_configuration_errors(context):
    fixtures, backends, task = context
    backend = backends["layout.artifact"]
    job = next(j for j in task.evaluation.jobs if j.id == "artifact")
    with pytest.raises(ValueError, match="declared gate"):
        backend.run(replace(job, gate="drc"),
                    {"layout": fixtures["valid"], "task": task.evaluation_inputs()["task"]})
    metadata = task.description()
    for layout, change in [(Asset(b"not GDS", "gds"), {}),
                           (Asset(b"\x00\x06\x00\x02\x02\x58", "gds"), {}),
                           (fixtures["valid"], {"top_cell": "ABSENT"}),
                           (fixtures["valid"], {"max_bytes": 6})]:
        changed = {**metadata, "output": {**metadata["output"], **change}}
        result = backend.run(job, {"layout": layout, "task": Asset(json.dumps(changed).encode(), "json")})
        assert result.status == "failed", result.reason
    with pytest.raises(ValueError, match="differs from task"):
        backend.run(replace(job, parameters_json='{"top_cell":"WRONG"}'),
                    {"layout": fixtures["valid"], "task": task.evaluation_inputs()["task"]})


def test_translation_and_hierarchy_preserve_validity(context, tmp_path):
    fixtures, backends, task = context
    script = b'''from klayout import db
l=db.Layout(); l.read("source.gds")
c=l.top_cell(); c.name="CHILD"
t=l.create_cell("MOS_SWITCH")
tr=db.Trans(100000,-200000)
t.insert(db.CellInstArray(c.cell_index(),tr))
# Retain the declared interface labels at the top; only geometry becomes hierarchical.
for shape in c.shapes(l.layer(8,25)).each():
    t.shapes(l.layer(8,25)).insert(shape.text.transformed(tr))
l.write("hierarchy.gds")
'''
    result = backends["layout.artifact"].tool.run(["python", "transform.py"],
        {"transform.py": Asset(script, "python"), "source.gds": fixtures["valid"]}, {"hierarchy.gds": "gds"})
    assert not result.reason
    report = run_evaluation(task.evaluation, {"candidate": result.files["hierarchy.gds"], **task.evaluation_inputs()},
                            backends, tmp_path / "hierarchy")
    assert report["physical_valid"] is True, report["jobs"]
    assert report["task_success"] is True, report["jobs"]
    assert report["metrics"]["fall_delay"]["value"] == pytest.approx(1.10026e-11, rel=0.01)


@pytest.mark.parametrize("fault", ["missing_report", "partial_report", "extract_only", "broken_deck"])
def test_zero_exit_or_incomplete_deck_never_passes(context, tmp_path, fault):
    fixtures, backends, task = context
    mode = "lvs" if fault == "extract_only" else "drc"
    original = backends[f"layout.{mode}"]
    settings = dict(original.settings)
    files = dict(original.support.files)
    if fault == "extract_only":
        settings["variables"] = {**settings["variables"], "net_only": "true"}
    else:
        settings["deck"] = "fixture.drc"
        script = {"missing_report": '# Intentionally produces no report.\n',
                  "partial_report": 'source($input, $topcell)\nreport("incomplete", $report)\ninput(8,0).width(0.1).output("M1.a")\n',
                  "broken_deck": 'raise "intentional tool failure"\n'}[fault]
        files["fixture.drc"] = Asset(script.encode(), "ruby")
    files[f"{mode}.json"] = Asset(json.dumps(settings).encode(), "json")
    publish_bundle(files, {"purpose": "deliberately broken tool configuration"}, tmp_path / "support")
    backend = KLayoutDocker(image="layout-bench-tools:local", check=mode,
                            support=str(tmp_path / "support"), profile=f"{mode}.json")
    report = run_evaluation(task.evaluation, {"candidate": fixtures["valid"], **task.evaluation_inputs()},
                            {**backends, f"layout.{mode}": backend}, tmp_path / "run")
    assert report["jobs"][mode]["status"] == "error", report["jobs"]
    assert report["outcome"] == "error"
    assert report["physical_valid"] is None and report["task_success"] is None
    assert report["jobs"]["parasitics"]["status"] == "blocked"
    assert report["jobs"][mode]["evidence"]["result.json"]["bytes"] > 0
    if fault == "partial_report":
        assert report["jobs"][mode]["evidence"]["report.db"]["bytes"] > 0
        assert "required categories" in report["jobs"][mode]["reason"]


def test_unresolved_hierarchy_text_only_and_disguised_oasis_are_rejected(context):
    fixtures, backends, task = context
    backend = backends["layout.artifact"]
    script = b'''from klayout import db
l=db.Layout(); t=l.create_cell("MOS_SWITCH"); g=l.create_cell("MISSING")
g.ghost_cell=True
t.insert(db.CellInstArray(g.cell_index(),db.Trans()))
t.shapes(l.layer(8,0)).insert(db.Box(0,0,1000,1000))
l.write("ghost.gds")
l=db.Layout(); t=l.create_cell("MOS_SWITCH")
t.shapes(l.layer(8,25)).insert(db.Text("D",db.Trans()))
l.write("text.gds")
l=db.Layout(); l.read("valid.gds"); l.write("disguised.oas")
'''
    outputs = {"ghost.gds": "gds", "text.gds": "gds", "disguised.oas": "gds"}
    result = backend.tool.run(["python", "generate.py"],
        {"generate.py": Asset(script, "python"), "valid.gds": fixtures["valid"]}, outputs)
    assert not result.reason
    job = next(j for j in task.evaluation.jobs if j.id == "artifact")
    for name, fragment in [("ghost.gds", "Unresolved"), ("text.gds", "no polygon"), ("disguised.oas", "not a GDSII")]:
        checked = backend.run(job, {"layout": result.files[name], "task": task.evaluation_inputs()["task"]})
        assert checked.status == "failed" and fragment in checked.reason, (name, checked.status, checked.reason)
