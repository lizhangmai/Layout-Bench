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


def _configs(catalog):
    return {
        item["id"]: tomllib.loads((CATALOG.parent / item["config_path"]).read_text())
        for item in catalog["cases"]
    }


def test_catalog_has_one_unified_config_per_case():
    catalog = tomllib.loads(CATALOG.read_text())
    assert catalog["schema_version"] == 3
    assert catalog["source_count"] == 50
    assert catalog["case_count"] == len(catalog["cases"]) == 30
    assert catalog["artifact_count"] == len(catalog["artifacts"])
    excluded = {item["path"] for item in catalog["excluded"]}
    assert excluded == {EXCLUDED.rstrip("/"), "utils/PEX_Demo"}
    assert all(not any(item["path"].startswith(path + "/") for path in excluded)
               for item in catalog["artifacts"])

    config_paths = [item["config_path"] for item in catalog["cases"]]
    assert len(config_paths) == len(set(config_paths))
    assert all(Path(path).parent == Path("cases") for path in config_paths)
    assert all(Path(path).stem == item["id"] for path, item in
               zip(config_paths, catalog["cases"], strict=True))
    configs = _configs(catalog)
    assert set(configs) == {item["id"] for item in catalog["cases"]}
    assert all(data["kind"] == "layout_case" and data["schema_version"] == 2
               for data in configs.values())
    assert all(not Path(path).name in {"intake.toml", "task.toml", "source.toml"}
               for path in config_paths)

    sources = [source for data in configs.values() for source in data["sources"]]
    assert len(sources) == catalog["source_count"]
    assert len({source["id"] for source in sources}) == len(sources)
    assert len({source["path"] for source in sources}) == len(sources)
    assert all(source["path"].endswith(".sch") for source in sources)

    qualified = [data for data in configs.values() if data["status"] == "qualified"]
    assert [data["id"] for data in qualified] == [
        "module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate"
    ]
    assert "task" in qualified[0]
    assert "source_export" in qualified[0]
    assert not list(CATALOG.parent.glob("**/intake.toml"))
    assert not list(CATALOG.parent.glob("**/task.toml"))
    assert not list(CATALOG.parent.glob("**/source.toml"))
    assert not (CATALOG.parent / "qualified").exists()


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
    expected_sources = {path for path in source_paths if path.endswith(".sch")}
    expected_artifacts = {
        path for path in source_paths if Path(path).suffix.lower() in ARTIFACT_EXTENSIONS
    }
    configs = _configs(catalog)
    sources = [source for data in configs.values() for source in data["sources"]]
    assert {source["path"] for source in sources} == expected_sources
    assert {item["path"] for item in catalog["artifacts"]} == expected_artifacts
    for source in sources:
        path = academy / source["path"]
        assert path.is_file(), source["path"]
        assert not any(source["path"].startswith(prefix.rstrip("/") + "/") for prefix in excluded)
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == source["sha256"]
        assert len(content) == source["bytes"]
    for item in catalog["artifacts"]:
        path = academy / item["path"]
        assert path.is_file(), item["path"]
        assert not any(item["path"].startswith(path + "/") for path in excluded)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
