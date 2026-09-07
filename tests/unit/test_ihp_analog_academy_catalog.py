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


def test_catalog_is_complete_and_points_to_named_circuit_configs():
    catalog = tomllib.loads(CATALOG.read_text())
    circuits = catalog["circuits"]
    assert catalog["schema_version"] == 2
    assert catalog["circuit_source_count"] == len(circuits) == 50
    assert catalog["artifact_count"] == len(catalog["artifacts"])
    excluded = {item["path"] for item in catalog["excluded"]}
    assert excluded == {EXCLUDED.rstrip("/"), "utils/PEX_Demo"}
    assert all(not any(item["path"].startswith(path + "/") for path in excluded)
               for item in catalog["artifacts"])

    config_paths = {item["config_path"] for item in circuits}
    assert len(config_paths) == len(circuits)
    assert all(Path(path).name != "intake.toml" for path in config_paths)
    configs = {path: tomllib.loads((CATALOG.parent / path).read_text()) for path in config_paths}
    assert all((CATALOG.parent / path).is_file() for path in config_paths)
    assert all(Path(path).stem == Path(data["source_path"]).stem
               for path, data in configs.items())

    qualified = [data for data in configs.values() if data["status"] == "qualified"]
    assert [data["id"] for data in qualified] == [
        "module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate.schematic.T_gate"
    ]
    assert qualified[0]["task_path"].endswith("/T_gate/task.toml")

    source_configs = {
        path.relative_to(CATALOG.parent).as_posix()
        for path in CATALOG.parent.rglob("*.toml")
        if "source_path" in tomllib.loads(path.read_text())
    }
    assert source_configs == config_paths
    assert not list(CATALOG.parent.rglob("intake.toml"))


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
    config_data = [tomllib.loads((CATALOG.parent / item["config_path"]).read_text())
                   for item in catalog["circuits"]]
    assert {data["source_path"] for data in config_data} == expected_circuits
    assert {item["path"] for item in catalog["artifacts"]} == expected_artifacts
    for data in config_data:
        path = academy / data["source_path"]
        assert path.is_file(), data["source_path"]
        assert not any(data["source_path"].startswith(prefix + "/") for prefix in excluded)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == data["source_sha256"]
    for item in catalog["artifacts"]:
        path = academy / item["path"]
        assert path.is_file(), item["path"]
        assert not any(item["path"].startswith(path + "/") for path in excluded)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
