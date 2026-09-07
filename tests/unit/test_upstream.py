import copy
import hashlib
import tomllib
from pathlib import Path

import pytest

from benchmarking import upstream
from benchmarking.tasks import _validate_case

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
CASES = sorted((ROOT / "tasks").glob("*/cases/*.toml"))


@pytest.mark.parametrize("case", CASES, ids=lambda path: path.stem)
def test_all_original_asset_mappings_are_valid(case):
    data = tomllib.loads(case.read_text())
    _validate_case(data)
    assert data["upstream_evaluation"]["basis"]
    manifest = tomllib.loads((case.parents[1] / "catalog.toml").read_text())
    assert data["origin"]["commit"] == manifest["source_commit"]


def test_extracted_netlist_cannot_be_used_as_authoritative_source():
    data = tomllib.loads(CASES[0].read_text())
    data["upstream_evaluation"]["netlist"] = next(
        asset["id"] for asset in data["upstream_assets"] if asset["role"] == "extracted-netlist")
    with pytest.raises(ValueError, match="correct role and format"):
        _validate_case(data)


def test_missing_asset_and_unknown_mapping_fields_are_rejected():
    data = tomllib.loads(CASES[0].read_text())
    missing = copy.deepcopy(data)
    missing["upstream_evaluation"]["layout"] = "missing"
    with pytest.raises(ValueError, match="declared original asset"):
        _validate_case(missing)
    data["upstream_evaluation"]["normalize"] = "true"
    with pytest.raises(ValueError):
        _validate_case(data)


def test_original_bytes_and_distinct_circuit_names_reach_api(tmp_path, monkeypatch):
    case = ROOT / "tasks/TO_Apr2025/cases/DC_to_130_GHz_TIA.design_1.toml"
    data = tomllib.loads(case.read_text())
    if not (ROOT / data["origin"]["checkout"] / ".git").exists():
        pytest.skip("TO_Apr2025 checkout is not initialized")
    mapping = data["upstream_evaluation"]
    settings = {}

    def backend(**kwargs):
        settings[kwargs["check"]] = kwargs
        return object()

    def evaluate(plan, inputs, backends, output, *, task_sha256):
        assert task_sha256 == hashlib.sha256(case.read_bytes()).hexdigest()
        for field, key in (("layout", "candidate"), ("netlist", "input:netlist")):
            asset = next(a for a in data["upstream_assets"] if a["id"] == mapping[field])
            assert inputs[key].content == (ROOT / data["origin"]["checkout"] / asset["path"]).read_bytes()
        job = next(job for job in plan.jobs if job.id == "lvs")
        assert job.parameters["top_cell"] == "FMD_QNC_03a_TIA_1"
        assert job.parameters["subcircuit"] == "TOP"
        assert all("waivers" not in job.parameters for job in plan.jobs)
        output.mkdir()
        return {"outcome": "failed"}

    monkeypatch.setattr(upstream, "KLayoutDocker", backend)
    monkeypatch.setattr(upstream, "run_evaluation", evaluate)
    output = tmp_path / "result"
    upstream.evaluate(case, tmp_path, output, "declared-image", root=ROOT)
    assert settings["lvs"]["profile"] == "lvs-to-apr2025.json"
    assert (output / "case.toml").read_bytes() == case.read_bytes()


def test_checksum_mismatch_stops_before_eda(tmp_path, monkeypatch):
    data = tomllib.loads(CASES[0].read_text())
    monkeypatch.setattr(upstream.subprocess, "check_output", lambda *args, **kwargs: data["origin"]["commit"])
    monkeypatch.setattr(upstream, "read_file", lambda *args: b"corrupt")
    monkeypatch.setattr(upstream, "KLayoutDocker", lambda **kwargs: pytest.fail("EDA must not start"))
    with pytest.raises(ValueError, match="checksum mismatch"):
        upstream.evaluate(CASES[0], tmp_path, tmp_path / "result", "unused", root=ROOT)
