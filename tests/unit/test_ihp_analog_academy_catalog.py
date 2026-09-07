import hashlib
import subprocess
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "tasks/IHP-AnalogAcademy/catalog.toml"
EXCLUDED = "modules/module_0_foundations/PEX_Demo/"


def _configs(catalog):
    return {
        item["id"]: tomllib.loads((CATALOG.parent / item["config_path"]).read_text())
        for item in catalog["cases"]
    }


def test_catalog_has_one_unified_config_per_case():
    catalog = tomllib.loads(CATALOG.read_text())
    assert catalog["schema_version"] == 3
    assert catalog["source_count"] == 8
    assert catalog["case_count"] == len(catalog["cases"]) == 4
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
    assert {path.name for path in (CATALOG.parent / "cases").glob("*.toml")} == {
        Path(path).name for path in config_paths
    }
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
    assert qualified == []
    assert all(data.get("screening", {}).get("decision") in {"include", "defer", "exclude"}
               for data in configs.values())
    upstream_assets = [asset for data in configs.values() for asset in data.get("upstream_assets", [])]
    assert len({asset["id"] for asset in upstream_assets}) == len(upstream_assets)
    assert all("bytes" not in source for source in sources)
    assert all("bytes" not in asset for asset in upstream_assets)
    assert all("bytes" not in artifact for artifact in catalog["artifacts"])
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
    configs = _configs(catalog)
    sources = [source for data in configs.values() for source in data["sources"]]
    expected_sources = {source["path"] for source in sources}
    expected_artifacts = {
        asset["path"] for data in configs.values() for asset in data.get("upstream_assets", [])
    }
    assert {source["path"] for source in sources} == expected_sources
    assert {item["path"] for item in catalog["artifacts"]} == expected_artifacts
    for source in sources:
        path = academy / source["path"]
        assert path.is_file(), source["path"]
        assert not any(source["path"].startswith(prefix.rstrip("/") + "/") for prefix in excluded)
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == source["sha256"]
    for item in catalog["artifacts"]:
        path = academy / item["path"]
        assert path.is_file(), item["path"]
        assert not any(item["path"].startswith(path + "/") for path in excluded)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    for data in configs.values():
        checkout = ROOT / data["origin"]["checkout"]
        for asset in data.get("upstream_assets", []):
            path = checkout / asset["path"]
            assert path.is_file(), asset["path"]
            content = path.read_bytes()
            assert hashlib.sha256(content).hexdigest() == asset["sha256"]
