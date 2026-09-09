import copy
import hashlib
import tomllib

import pytest

from benchmarking import upstream
from benchmarking.tasks import _validate_case

pytestmark = pytest.mark.unit


def test_extracted_netlist_cannot_be_used_as_authoritative_source(circuit_case):
    data = tomllib.loads(circuit_case.read_text())
    data["upstream_evaluation"]["netlist"] = "extracted"
    with pytest.raises(ValueError, match="correct role and format"):
        _validate_case(data)


def test_missing_asset_and_unknown_mapping_fields_are_rejected(circuit_case):
    data = tomllib.loads(circuit_case.read_text())
    missing = copy.deepcopy(data)
    missing["upstream_evaluation"]["layout"] = "missing"
    with pytest.raises(ValueError, match="declared original asset"):
        _validate_case(missing)
    data["upstream_evaluation"]["normalize"] = "true"
    with pytest.raises(ValueError):
        _validate_case(data)


def test_original_bytes_and_distinct_circuit_names_reach_api(circuit_case, tmp_path, monkeypatch):
    case = circuit_case
    data = tomllib.loads(case.read_text())
    settings = {}
    evaluated = []

    def backend(**kwargs):
        settings[kwargs["check"]] = kwargs
        return object()

    def evaluate(plan, inputs, backends, output, *, task_sha256):
        assert task_sha256 == hashlib.sha256(case.read_bytes()).hexdigest()
        assert inputs["candidate"].content == (tmp_path / "synthetic-source/original.gds").read_bytes()
        assert inputs["input:netlist"].content == (tmp_path / "synthetic-source/circuit.spice").read_bytes()
        job = next(job for job in plan.jobs if job.id == "lvs")
        assert job.parameters["top_cell"] == "LAYOUT_TOP"
        assert job.parameters["subcircuit"] == "CIRCUIT_REF"
        assert all("waivers" not in job.parameters for job in plan.jobs)
        output.mkdir()
        evaluated.append(output)
        return {"outcome": "failed"}

    monkeypatch.setattr(upstream.subprocess, "check_output", lambda *args, **kwargs: data["origin"]["commit"])
    monkeypatch.setattr(upstream, "KLayoutDocker", backend)
    monkeypatch.setattr(upstream, "run_evaluation", evaluate)
    output = tmp_path / "result"
    report = upstream.evaluate(case, tmp_path, output, "declared-image", root=tmp_path)
    assert report["outcome"] == "failed"
    assert evaluated == [output]
    assert settings["lvs"]["profile"] == "compare.json"
    assert (output / "case.toml").read_bytes() == case.read_bytes()


def test_checksum_mismatch_stops_before_eda(circuit_case, tmp_path, monkeypatch):
    case = circuit_case
    data = tomllib.loads(case.read_text())
    monkeypatch.setattr(upstream.subprocess, "check_output", lambda *args, **kwargs: data["origin"]["commit"])
    (tmp_path / "synthetic-source/original.gds").write_bytes(b"corrupt")
    monkeypatch.setattr(upstream, "KLayoutDocker", lambda **kwargs: pytest.fail("EDA must not start"))
    with pytest.raises(ValueError, match="checksum mismatch"):
        upstream.evaluate(case, tmp_path, tmp_path / "result", "unused", root=tmp_path)
