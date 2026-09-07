import hashlib
import subprocess
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "tasks/IHP-AnalogAcademy/catalog.toml"
EXCLUDED = "modules/module_0_foundations/PEX_Demo/"
EXCLUDED_PREFIXES = (EXCLUDED, "utils/PEX_Demo/")
ALLOWED_PREFIXES = ("modules/", "utils/gmid_demonstration/")
ARTIFACT_EXTENSIONS = {
    ".cdl", ".cir", ".sp", ".spice", ".net", ".ext", ".gds", ".sym", ".v", ".va",
    ".s2p", ".s3p", ".s4p", ".xyce",
}


def test_catalog_is_complete_and_keeps_intake_separate_from_tasks():
    catalog = tomllib.loads(CATALOG.read_text())
    circuits = catalog["circuits"]
    assert catalog["circuit_source_count"] == len(circuits) == 50
    assert catalog["artifact_count"] == len(catalog["artifacts"])
    excluded = {item["path"] for item in catalog["excluded"]}
    assert excluded == {EXCLUDED.rstrip("/"), "utils/PEX_Demo"}
    assert all(not any(item["source_path"].startswith(path + "/") for path in excluded)
               for item in circuits)
    assert all(not any(item["path"].startswith(path + "/") for path in excluded)
               for item in catalog["artifacts"])

    qualified = [item for item in circuits if item["status"] == "qualified"]
    assert [item["id"] for item in qualified] == [
        "module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate.schematic.T_gate"
    ]
    assert qualified[0]["task_path"].endswith("/T_gate/task.toml")

    intake_paths = {item["intake_path"] for item in circuits}
    assert len(intake_paths) == len(circuits)
    assert all((CATALOG.parent / path).is_file() for path in intake_paths)
    assert all((CATALOG.parent / item["intake_path"]).read_text().startswith("schema_version = 1")
               for item in circuits)


def test_catalog_digests_match_the_pinned_submodule():
    academy = ROOT / "third_party/IHP-AnalogAcademy"
    if not (academy / ".git").exists():
        pytest.skip("IHP AnalogAcademy submodule is not initialized")
    catalog = tomllib.loads(CATALOG.read_text())
    excluded = {item["path"] for item in catalog["excluded"]}
    commit = subprocess.check_output(["git", "-C", str(academy), "rev-parse", "HEAD"], text=True).strip()
    assert catalog["source_commit"] == commit
    source_paths = subprocess.check_output(
        ["git", "-C", str(academy), "ls-tree", "-r", "--name-only", "HEAD"], text=True,
    ).splitlines()
    source_paths = {
        path for path in source_paths
        if path.startswith(ALLOWED_PREFIXES)
        and not any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES)
    }
    expected_circuits = {path for path in source_paths if path.endswith(".sch")}
    expected_artifacts = {
        path for path in source_paths if Path(path).suffix.lower() in ARTIFACT_EXTENSIONS
    }
    assert {item["source_path"] for item in catalog["circuits"]} == expected_circuits
    assert {item["path"] for item in catalog["artifacts"]} == expected_artifacts
    for item in catalog["circuits"]:
        path = academy / item["source_path"]
        assert path.is_file(), item["source_path"]
        assert not any(item["source_path"].startswith(path + "/") for path in excluded)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["source_sha256"]
    for item in catalog["artifacts"]:
        path = academy / item["path"]
        assert path.is_file(), item["path"]
        assert not any(item["path"].startswith(path + "/") for path in excluded)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
